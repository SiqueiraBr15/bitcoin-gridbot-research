"""Contabilidade pura de reservas de capital quote para compras do grid (ADR-020).

QUOTE CAPITAL -> RESERVA + PREPARE_BUY -> EXECUTION BOUND -> FINALIZED BUY -> SETTLEMENT.

``FundedBuyBook`` junta o ``BuyLifecycleBook`` (A11, autoridade sobre o ciclo econômico) ao
capital quote AUTORIZADO para o grid e às reservas das tentativas ativas (autoridade sobre
os compromissos de capital do snapshot). Invariante principal, exata:

    initial_quote_capital == spent_quote + reserved_quote + available_quote

com as três parcelas >= 0. ``spent`` e ``available`` são derivados (consumos e reservas),
nunca armazenados.

- capital autorizado != saldo da carteira; nada é lido de wallet ou exchange;
- reserva = ``preço LIMIT x qty pretendida`` + reserva explícita de fee em quote informada
  pelo chamador (nenhuma fee é inventada; zero não é política segura para execução real);
- PREPARATION_AND_QUOTE_HOLD_MUST_BE_ATOMIC: preparar e reservar é uma única transformação;
- a reserva fica bloqueada em PREPARED, SUBMISSION_UNCERTAIN e EXECUTION_BOUND;
- settlement usa o gasto OBSERVADO (``quote_debit_total``), exige notional <= hold de
  notional e fee em quote <= hold de fee, e devolve o não utilizado (não é lucro);
- fees em BTC ou terceiro ativo não são cobertas por este book.

Só em memória: não protege contra múltiplos processos nem crashes. FUTURE LIVE EXECUTION
MUST USE FUNDED ORCHESTRATION.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import DecimalException
from enum import StrEnum

from gridbot.application.buy_lifecycle import (
    BuyLifecycleBook,
    bind_buy_execution,
    consume_finalized_buy,
    mark_submission_uncertain,
    prepare_buy,
)
from gridbot.domain.assets import Asset
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Money
from gridbot.portfolio.buy_finalization import BuyExecutionContext, FinalizedBuy
from gridbot.strategy.buy_intents import BuyIntentPlan, GridBuyIntent
from gridbot.strategy.grid_state import CellCycleRef


class BuyQuoteCapitalErrorCode(StrEnum):
    QUOTE_ASSET_MISMATCH = "QUOTE_ASSET_MISMATCH"
    NEGATIVE_CAPITAL = "NEGATIVE_CAPITAL"
    NEGATIVE_FEE_RESERVE = "NEGATIVE_FEE_RESERVE"
    INSUFFICIENT_AVAILABLE_QUOTE = "INSUFFICIENT_AVAILABLE_QUOTE"
    RESERVATION_NOT_FOUND = "RESERVATION_NOT_FOUND"
    RESERVATION_MISMATCH = "RESERVATION_MISMATCH"
    NOTIONAL_EXCEEDS_HOLD = "NOTIONAL_EXCEEDS_HOLD"
    QUOTE_FEE_EXCEEDS_HOLD = "QUOTE_FEE_EXCEEDS_HOLD"
    DEBIT_EXCEEDS_HOLD = "DEBIT_EXCEEDS_HOLD"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"
    INVALID_FUNDED_BOOK = "INVALID_FUNDED_BOOK"


class BuyQuoteCapitalError(DomainError):
    """Operação de capital recusada (fail-closed); ``code`` identifica o motivo."""

    def __init__(self, code: BuyQuoteCapitalErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = BuyQuoteCapitalErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


@contextmanager
def _precision_guard(operation: str) -> Iterator[None]:
    try:
        yield
    except DecimalException as exc:
        raise BuyQuoteCapitalError(
            _E.FINANCIAL_PRECISION_ERROR,
            f"{operation} excede a precisão financeira; nenhum arredondamento feito",
        ) from exc


def _sum(values: Iterable[Money], asset: Asset, operation: str) -> Money:
    total = Money.zero(asset)
    with _precision_guard(operation):
        for value in values:
            total = total + value
    return total


def _invalid(detail: str) -> BuyQuoteCapitalError:
    return BuyQuoteCapitalError(_E.INVALID_FUNDED_BOOK, detail)


# ------------------------------------------------------------------ reserva


@dataclass(frozen=True, slots=True)
class BuyQuoteReservation:
    """Compromisso lógico de quote para UMA compra (célula/ciclo). Não é execução.

    ``notional_hold`` e ``total_hold`` são derivados da intenção e da reserva de fee.
    """

    intent: GridBuyIntent
    quote_fee_hold: Money

    def __post_init__(self) -> None:
        _expect(self.intent, GridBuyIntent, "intent")
        _expect(self.quote_fee_hold, Money, "quote_fee_hold")
        if self.quote_fee_hold.asset != self.intent.symbol.quote:
            raise BuyQuoteCapitalError(
                _E.QUOTE_ASSET_MISMATCH,
                f"fee hold em {self.quote_fee_hold.asset}; esperado {self.intent.symbol.quote}",
            )
        if self.quote_fee_hold.is_negative:
            raise BuyQuoteCapitalError(
                _E.NEGATIVE_FEE_RESERVE, f"fee hold {self.quote_fee_hold} < 0"
            )

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref

    @property
    def notional_hold(self) -> Money:
        """``preço LIMIT x quantidade pretendida`` (nunca o preço de execução futuro)."""
        with _precision_guard(f"notional hold de {self.cycle_ref}"):
            return Money(self.intent.price.notional(self.intent.qty), self.intent.symbol.quote)

    @property
    def total_hold(self) -> Money:
        with _precision_guard(f"total hold de {self.cycle_ref}"):
            return self.notional_hold + self.quote_fee_hold


# ------------------------------------------------------------------ aggregate


@dataclass(frozen=True, slots=True)
class FundedBuyBook:
    """Ciclo de vida das compras + capital quote autorizado + reservas (snapshot imutável).

    ``reservations``: uma por tentativa ativa. ``settled_reservations``: a reserva original
    de cada compra já liquidada, na ordem dos consumos (trilha de auditoria que permite
    revalidar os limites). Invariantes revalidadas em toda construção (``INVALID_FUNDED_BOOK``).
    """

    lifecycle: BuyLifecycleBook
    initial_quote_capital: Money
    reservations: tuple[BuyQuoteReservation, ...] = ()
    settled_reservations: tuple[BuyQuoteReservation, ...] = ()

    def __post_init__(self) -> None:
        _expect(self.lifecycle, BuyLifecycleBook, "lifecycle")
        _expect(self.initial_quote_capital, Money, "initial_quote_capital")
        for name in ("reservations", "settled_reservations"):
            items = getattr(self, name)
            if not isinstance(items, tuple) or not all(
                isinstance(r, BuyQuoteReservation) for r in items
            ):
                raise TypeError(f"{name} deve ser tuple[BuyQuoteReservation, ...] (imutável)")
        quote = self.quote_asset
        capital = self.initial_quote_capital
        if capital.asset != quote:
            raise BuyQuoteCapitalError(
                _E.QUOTE_ASSET_MISMATCH, f"capital em {capital.asset}; grid exige {quote}"
            )
        if capital.is_negative:
            raise BuyQuoteCapitalError(_E.NEGATIVE_CAPITAL, f"capital {capital} < 0")
        _validate_funded_book(self)

    @property
    def quote_asset(self) -> Asset:
        return self.lifecycle.grid_state.plan.spec.symbol.quote

    @property
    def spent_quote(self) -> Money:
        """Soma dos ``quote_debit_total`` observados das compras consumidas."""
        return _sum(
            (f.quote_debit_total for f in self.lifecycle.consumed), self.quote_asset, "spent"
        )

    @property
    def reserved_quote(self) -> Money:
        return _sum((r.total_hold for r in self.reservations), self.quote_asset, "reserved")

    @property
    def available_quote(self) -> Money:
        """``capital - gasto - reservado`` (nunca negativo num book válido)."""
        with _precision_guard("available"):
            return self.initial_quote_capital - self.spent_quote - self.reserved_quote

    def reservation_for(self, cycle_ref: CellCycleRef) -> BuyQuoteReservation | None:
        return next((r for r in self.reservations if r.cycle_ref == cycle_ref), None)


def _settlement_violation(reservation: BuyQuoteReservation, finalized: FinalizedBuy) -> None:
    """Limites separados do settlement: notional, fee em quote e débito total."""
    notional = finalized.ledger.gross_quote_notional
    if notional.amount > reservation.notional_hold.amount:
        raise BuyQuoteCapitalError(
            _E.NOTIONAL_EXCEEDS_HOLD,
            f"{reservation.cycle_ref}: notional {notional} > hold {reservation.notional_hold}",
        )
    fee = finalized.ledger.quote_fee_total
    if fee.amount > reservation.quote_fee_hold.amount:
        raise BuyQuoteCapitalError(
            _E.QUOTE_FEE_EXCEEDS_HOLD,
            f"{reservation.cycle_ref}: fee em quote {fee} > hold {reservation.quote_fee_hold}",
        )
    debit = finalized.quote_debit_total
    if debit.amount > reservation.total_hold.amount:  # pragma: no cover - implicado acima
        raise BuyQuoteCapitalError(
            _E.DEBIT_EXCEEDS_HOLD,
            f"{reservation.cycle_ref}: débito {debit} > hold {reservation.total_hold}",
        )


def _validate_funded_book(book: FundedBuyBook) -> None:
    lifecycle = book.lifecycle
    quote = book.quote_asset

    reserved_refs = [r.cycle_ref for r in book.reservations]
    if len(set(reserved_refs)) != len(reserved_refs):
        raise _invalid("reserva duplicada para o mesmo ciclo")
    attempts = {a.cycle_ref: a for a in lifecycle.attempts}
    if set(reserved_refs) != set(attempts):
        missing = sorted(set(attempts) - set(reserved_refs))
        orphan = sorted(set(reserved_refs) - set(attempts))
        raise _invalid(f"tentativas sem reserva {missing}; reservas sem tentativa {orphan}")
    for reservation in book.reservations:
        if reservation.intent != attempts[reservation.cycle_ref].intent:
            raise _invalid(f"{reservation.cycle_ref}: reserva de outra intenção")
        if reservation.quote_fee_hold.asset != quote:  # pragma: no cover - BuyQuoteReservation
            raise _invalid(f"{reservation.cycle_ref}: reserva fora do ativo quote")

    consumed = lifecycle.consumed
    if len(book.settled_reservations) != len(consumed):
        raise _invalid("cada compra consumida exige exatamente uma reserva liquidada")
    for reservation, finalized in zip(book.settled_reservations, consumed, strict=True):
        if reservation.intent != finalized.ledger.intent:
            raise _invalid(f"{finalized.cycle_ref}: reserva liquidada de outra intenção")
        try:
            _settlement_violation(reservation, finalized)
        except BuyQuoteCapitalError as exc:
            raise _invalid(f"liquidação acima da reserva: {exc}") from exc

    if book.spent_quote.is_negative or book.reserved_quote.is_negative:
        raise _invalid("gasto ou reservado negativo")  # pragma: no cover - Money >= 0 aqui
    if book.available_quote.is_negative:
        raise _invalid(
            f"gasto {book.spent_quote} + reservado {book.reserved_quote} excede o capital "
            f"{book.initial_quote_capital}"
        )


# ------------------------------------------------------------------ operações


def prepare_funded_buy(
    book: FundedBuyBook,
    intent_plan: BuyIntentPlan,
    cycle_ref: CellCycleRef,
    quote_fee_reserve: Money,
) -> FundedBuyBook:
    """Prepara a compra (A11) e reserva seu capital numa única transformação pura.

    Falha sem preparar nem reservar nada se o plano/ciclo forem inválidos (erros da A11),
    se a reserva de fee for inválida ou se o capital livre não cobrir
    ``preço LIMIT x qty + quote_fee_reserve`` (``INSUFFICIENT_AVAILABLE_QUOTE``).
    """
    _expect(book, FundedBuyBook, "book")
    _expect(quote_fee_reserve, Money, "quote_fee_reserve")
    new_lifecycle = prepare_buy(book.lifecycle, intent_plan, cycle_ref)
    attempt = new_lifecycle.attempt_for(cycle_ref)
    if attempt is None:  # pragma: no cover - prepare_buy acabou de registrá-la
        raise BuyQuoteCapitalError(_E.RESERVATION_NOT_FOUND, f"tentativa {cycle_ref} ausente")
    reservation = BuyQuoteReservation(attempt.intent, quote_fee_reserve)
    required, available = reservation.total_hold, book.available_quote
    if required.amount > available.amount:
        raise BuyQuoteCapitalError(
            _E.INSUFFICIENT_AVAILABLE_QUOTE,
            f"{cycle_ref} exige {required}; livre {available}",
        )
    reservations = tuple(sorted((*book.reservations, reservation), key=lambda r: r.cycle_ref))
    return replace(book, lifecycle=new_lifecycle, reservations=reservations)


def bind_funded_buy_execution(
    book: FundedBuyBook, cycle_ref: CellCycleRef, execution_context: BuyExecutionContext
) -> FundedBuyBook:
    """Vincula a execução (A11). A reserva continua exatamente a mesma."""
    _expect(book, FundedBuyBook, "book")
    new_lifecycle = bind_buy_execution(book.lifecycle, cycle_ref, execution_context)
    if new_lifecycle is book.lifecycle:
        return book
    return replace(book, lifecycle=new_lifecycle)


def mark_funded_submission_uncertain(book: FundedBuyBook, cycle_ref: CellCycleRef) -> FundedBuyBook:
    """Registra SUBMISSION_UNCERTAIN (A11). A reserva continua bloqueada."""
    _expect(book, FundedBuyBook, "book")
    return replace(book, lifecycle=mark_submission_uncertain(book.lifecycle, cycle_ref))


def settle_funded_buy(book: FundedBuyBook, finalized_buy: FinalizedBuy) -> FundedBuyBook:
    """Consome a compra finalizada (A11) e liquida sua reserva numa transformação pura.

    - mesma ``FinalizedBuy`` já liquidada: no-op (sem débito ou liberação duplos);
    - gasto = ``finalized_buy.quote_debit_total`` (fills observados), com limites separados:
      notional <= hold de notional, fee em quote <= hold de fee e débito <= hold total;
    - a reserva sai das ativas, vai para ``settled_reservations`` e o não utilizado volta a
      ``available`` (não é lucro). NO_FILL libera 100%.
    Divergência acima da reserva é erro e nada muda: no mundo real exige reconciliação,
    não significa que a execução externa não ocorreu.
    """
    _expect(book, FundedBuyBook, "book")
    _expect(finalized_buy, FinalizedBuy, "finalized_buy")
    if finalized_buy in book.lifecycle.consumed:
        return book
    new_lifecycle = consume_finalized_buy(book.lifecycle, finalized_buy)  # validações da A11
    reservation = book.reservation_for(finalized_buy.cycle_ref)
    if reservation is None:  # pragma: no cover - toda tentativa ativa tem reserva
        raise BuyQuoteCapitalError(
            _E.RESERVATION_NOT_FOUND, f"sem reserva para {finalized_buy.cycle_ref}"
        )
    if reservation.intent != finalized_buy.ledger.intent:  # pragma: no cover - A11 garante
        raise BuyQuoteCapitalError(
            _E.RESERVATION_MISMATCH, f"{finalized_buy.cycle_ref}: reserva de outra intenção"
        )
    _settlement_violation(reservation, finalized_buy)
    return FundedBuyBook(
        lifecycle=new_lifecycle,
        initial_quote_capital=book.initial_quote_capital,
        reservations=tuple(r for r in book.reservations if r.cycle_ref != reservation.cycle_ref),
        settled_reservations=(*book.settled_reservations, reservation),
    )
