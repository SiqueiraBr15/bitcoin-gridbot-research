"""Planejamento puro de intenções SELL LIMIT a partir de reservas do book (ADR-022).

INTENT != ORDER != FILL != SETTLEMENT. Uma intenção diz "o grid deseja ter esta ordem". Não
é ordem enviada, aceita ou executada; não é fill, receita, lucro nem encerramento de ciclo.

GRID CANNOT SELL CORE BTC: a única autoridade é uma ``SellBaseInventoryReservation`` que
pertence a um ``SellInventoryBook`` válido (A13), vinculada a uma ``FinalizedBuy`` já
consumida pelo lifecycle. Nenhuma API daqui recebe saldo, wallet, preço ou quantidade do
chamador: preço, quantidade, símbolo, ciclo e fee hold são derivados da reserva.

Uma ``GridSellIntent`` ISOLADA não prova autorização; a legitimidade se verifica contra um
``SellInventoryBook`` (``SellIntentPlan`` na construção, ``validate_sell_intent_plan_against_book``
depois). Um plano vazio nunca é autorização. Construir o mesmo plano duas vezes dá objetos
equivalentes e NÃO autoriza transmitir duas ordens: idempotência persistente e reservas
transacionais continuam bloqueadores das fases operacionais. Tudo é em memória: o plano
mantém uma cópia lógica do book de origem, e a ausência de uma reserva num book novo
(rewrap) torna a intenção antiga stale, nunca válida.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.sell_inventory import SellBaseInventoryReservation, SellInventoryBook
from gridbot.domain.assets import Symbol
from gridbot.domain.enums import OrderType, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Price, Qty
from gridbot.portfolio.buy_finalization import FinalizedBuy
from gridbot.strategy.grid_state import CellCycleRef, CellPhase


class SellIntentErrorCode(StrEnum):
    INVALID_SELL_INTENT = "INVALID_SELL_INTENT"
    INVALID_SELL_INTENT_PLAN = "INVALID_SELL_INTENT_PLAN"
    INVALID_BOOK = "INVALID_BOOK"
    RESERVATION_NOT_FOUND = "RESERVATION_NOT_FOUND"
    DUPLICATE_SELL_INTENT = "DUPLICATE_SELL_INTENT"
    STALE_SELL_INTENT = "STALE_SELL_INTENT"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellIntentStaleReason(StrEnum):
    SYMBOL_CHANGED = "SYMBOL_CHANGED"
    CELL_UNKNOWN = "CELL_UNKNOWN"
    CYCLE_ADVANCED = "CYCLE_ADVANCED"
    CELL_NOT_WAITING_SELL = "CELL_NOT_WAITING_SELL"
    RESERVATION_MISSING = "RESERVATION_MISSING"
    ORIGIN_CHANGED = "ORIGIN_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    QUANTITY_CHANGED = "QUANTITY_CHANGED"
    FEE_HOLD_CHANGED = "FEE_HOLD_CHANGED"


@dataclass(frozen=True, slots=True)
class SellIntentStaleFinding:
    cycle_ref: CellCycleRef
    reason: SellIntentStaleReason

    def __post_init__(self) -> None:
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.reason, SellIntentStaleReason, "reason")


class SellIntentError(DomainError):
    """Intenção/plano recusado sem alterar a entrada; ``code`` identifica o motivo.

    ``findings`` só é preenchido em ``STALE_SELL_INTENT`` (um achado por intenção/motivo).
    """

    def __init__(
        self,
        code: SellIntentErrorCode,
        detail: str,
        findings: tuple[SellIntentStaleFinding, ...] = (),
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.findings = findings


_E = SellIntentErrorCode
_R = SellIntentStaleReason


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _translate(exc: Exception, code: SellIntentErrorCode) -> SellIntentError:
    """Erro de precisão da A13 é preservado; qualquer outro vira ``code`` (causa encadeada).

    Esta camada não faz aritmética própria: somas e diferenças ficam na A13 (contexto
    financeiro, ``Inexact`` fatal), então um ``FINANCIAL_PRECISION_ERROR`` só chega daqui.
    """
    if getattr(exc, "code", None) == _E.FINANCIAL_PRECISION_ERROR:
        return SellIntentError(_E.FINANCIAL_PRECISION_ERROR, str(exc))
    return SellIntentError(code, str(exc))


def _revalidated_book(book: SellInventoryBook) -> None:
    """Reexecuta as invariantes da A13 (também para objetos montados fora do construtor)."""
    try:
        replace(book)
    except (DomainError, TypeError) as exc:
        raise _translate(exc, _E.INVALID_BOOK) from exc


# ------------------------------------------------------------------ intenção


@dataclass(frozen=True, slots=True)
class GridSellIntent:
    """Desejo de uma venda LIMIT de UM ciclo. A única fonte é a reserva; o resto é derivado.

    Preço, quantidade, fee hold, símbolo e ciclo não são campos: não existe como ter valores
    divergentes da reserva. ``sell_qty`` é só a candidata reservada; o ``base_fee_hold`` NÃO é
    quantidade da ordem e o inventário não comprometido NÃO é oferecido. Sem client order id,
    id de exchange, timestamp, status, fill ou fee realizada.
    """

    reservation: SellBaseInventoryReservation

    def __post_init__(self) -> None:
        _expect(self.reservation, SellBaseInventoryReservation, "reservation")
        try:
            replace(self.reservation)
        except (DomainError, TypeError) as exc:
            raise _translate(exc, _E.INVALID_SELL_INTENT) from exc

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.reservation.cycle_ref

    @property
    def symbol(self) -> Symbol:
        return self.reservation.symbol

    @property
    def side(self) -> Side:
        return Side.SELL

    @property
    def order_type(self) -> OrderType:
        return OrderType.LIMIT

    @property
    def limit_price(self) -> Price:
        """Exatamente o preço SELL da célula (``sell_level``); nunca recalculado."""
        return self.reservation.target_sell_price

    @property
    def sell_qty(self) -> Qty:
        """Candidata reservada da A10/A13: sem hold de fee e sem residual."""
        return self.reservation.reserved_sell_qty

    @property
    def base_fee_hold(self) -> Qty:
        return self.reservation.reserved_base_fee_qty

    @property
    def total_base_commitment(self) -> Qty:
        """``sell_qty + base_fee_hold``: compromisso de inventário, não quantidade da ordem."""
        return self.reservation.total_reserved_base_qty

    @property
    def confirmed_net_base_qty(self) -> Qty:
        return self.reservation.confirmed_net_base_qty

    @property
    def unreserved_base_qty(self) -> Qty:
        return self.reservation.unreserved_base_qty

    @property
    def finalized_buy(self) -> FinalizedBuy:
        return self.reservation.finalized_buy


# ------------------------------------------------------------------ plano


@dataclass(frozen=True, slots=True)
class SellIntentPlan:
    """Book de origem + ciclos escolhidos; as intenções são DERIVADAS das reservas do book.

    Armazenar só ``cycle_refs`` evita qualquer coleção externa de intenções, preço ou
    quantidade independentes: o plano não consegue representar valores que a reserva não
    tenha. Um subconjunto de ciclos é um plano parcial válido. Invariantes (revalidadas em
    toda construção): book válido segundo a A13; ciclos únicos e em ordem canônica
    (crescente); cada ciclo com reserva no próprio book. Um ciclo, no máximo uma intenção.
    """

    book: SellInventoryBook
    cycle_refs: tuple[CellCycleRef, ...] = ()

    def __post_init__(self) -> None:
        _expect(self.book, SellInventoryBook, "book")
        if not isinstance(self.cycle_refs, tuple) or not all(
            isinstance(ref, CellCycleRef) for ref in self.cycle_refs
        ):
            raise TypeError("cycle_refs deve ser tuple[CellCycleRef, ...] (imutável)")
        _revalidated_book(self.book)
        if len(set(self.cycle_refs)) != len(self.cycle_refs):
            raise SellIntentError(_E.DUPLICATE_SELL_INTENT, "mais de uma intenção por ciclo")
        if list(self.cycle_refs) != sorted(self.cycle_refs):
            raise SellIntentError(
                _E.INVALID_SELL_INTENT_PLAN, "ciclos fora da ordem canônica (crescente)"
            )
        for ref in self.cycle_refs:
            if self.book.reservation_for(ref) is None:
                raise SellIntentError(_E.RESERVATION_NOT_FOUND, f"{ref}: sem reserva no book")

    @property
    def symbol(self) -> Symbol:
        return self.book.grid_state.plan.spec.symbol

    @property
    def is_empty(self) -> bool:
        return not self.cycle_refs

    @property
    def intents(self) -> tuple[GridSellIntent, ...]:
        chosen = set(self.cycle_refs)
        reservations = sorted(self.book.reservations, key=lambda r: r.cycle_ref)
        return tuple(GridSellIntent(r) for r in reservations if r.cycle_ref in chosen)

    def intent_for(self, cycle_ref: CellCycleRef) -> GridSellIntent | None:
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        return next((i for i in self.intents if i.cycle_ref == cycle_ref), None)


def build_sell_intents(book: SellInventoryBook) -> SellIntentPlan:
    """Uma intenção por reserva do book, em ordem canônica. Book sem reservas: plano vazio.

    Função pura: não altera o book, não cria reservas, não recebe preço nem quantidade.
    """
    _expect(book, SellInventoryBook, "book")
    return SellIntentPlan(book, tuple(sorted(r.cycle_ref for r in book.reservations)))


def build_sell_intent_for_cell(book: SellInventoryBook, cycle_ref: CellCycleRef) -> SellIntentPlan:
    """Plano parcial de UM ciclo; a reserva é conferida dentro do próprio book."""
    _expect(book, SellInventoryBook, "book")
    _expect(cycle_ref, CellCycleRef, "cycle_ref")
    return SellIntentPlan(book, (cycle_ref,))


# ------------------------------------------------------------------ freshness


@dataclass(frozen=True, slots=True)
class SellIntentFreshness:
    checked_cycle_refs: tuple[CellCycleRef, ...]
    findings: tuple[SellIntentStaleFinding, ...]

    def __post_init__(self) -> None:
        for name, item_type in (
            ("checked_cycle_refs", CellCycleRef),
            ("findings", SellIntentStaleFinding),
        ):
            items = getattr(self, name)
            if not isinstance(items, tuple) or not all(isinstance(i, item_type) for i in items):
                raise TypeError(f"{name} deve ser tuple[{item_type.__name__}, ...] (imutável)")

    @property
    def is_current(self) -> bool:
        return not self.findings


def sell_intent_plan_freshness(
    plan: SellIntentPlan, current_book: SellInventoryBook
) -> SellIntentFreshness:
    """Confere cada intenção do plano contra o book ATUAL, sem alterar nenhum dos dois.

    Compara só o vínculo econômico de cada ciclo (célula, fase, compra de origem, preço,
    quantidade e fee hold); NÃO exige igualdade de snapshots globais, então mudanças
    independentes em outras células não invalidam o plano. A reserva ausente (inclusive num
    book reconstruído sem histórico) é achado ``RESERVATION_MISSING``. Uma reserva trocada por
    outra IDÊNTICA em conteúdo é indistinguível: isso só persistência transacional resolve.
    """
    _expect(plan, SellIntentPlan, "plan")
    _expect(current_book, SellInventoryBook, "current_book")
    # A origem também precisa continuar válida: refs adulterados poderiam desaparecer
    # de plan.intents e transformar um plano inválido em uma aprovação vazia.
    try:
        replace(plan)
    except (DomainError, TypeError) as exc:
        raise _translate(exc, _E.INVALID_SELL_INTENT_PLAN) from exc
    _revalidated_book(current_book)
    state = current_book.grid_state
    symbol = state.plan.spec.symbol
    findings: list[SellIntentStaleFinding] = []

    def add(ref: CellCycleRef, reason: SellIntentStaleReason) -> None:
        findings.append(SellIntentStaleFinding(ref, reason))

    for intent in plan.intents:
        ref = intent.cycle_ref
        if intent.symbol != symbol:
            add(ref, _R.SYMBOL_CHANGED)
            continue
        if ref.cell_index >= len(state.cells):
            add(ref, _R.CELL_UNKNOWN)
            continue
        cell = state.cells[ref.cell_index]
        if cell.cycle_ref != ref:
            add(ref, _R.CYCLE_ADVANCED)
            continue
        if cell.phase is not CellPhase.WAITING_SELL:
            add(ref, _R.CELL_NOT_WAITING_SELL)
            continue
        reservation = current_book.reservation_for(ref)
        if reservation is None:
            add(ref, _R.RESERVATION_MISSING)
            continue
        consumed = current_book.funded_buy_book.lifecycle.consumed_for(ref)
        if reservation.finalized_buy != intent.finalized_buy or consumed != intent.finalized_buy:
            add(ref, _R.ORIGIN_CHANGED)
        if (
            reservation.target_sell_price != intent.limit_price
            or cell.cell.sell_price != intent.limit_price
        ):
            add(ref, _R.PRICE_CHANGED)
        if reservation.reserved_sell_qty != intent.sell_qty:
            add(ref, _R.QUANTITY_CHANGED)
        if reservation.reserved_base_fee_qty != intent.base_fee_hold:
            add(ref, _R.FEE_HOLD_CHANGED)
    return SellIntentFreshness(plan.cycle_refs, tuple(findings))


def validate_sell_intent_plan_against_book(
    plan: SellIntentPlan, current_book: SellInventoryBook
) -> None:
    """Levanta ``STALE_SELL_INTENT`` (com ``findings``) se qualquer intenção não se sustenta.

    Não restaura reservas, não cria ordens e não modifica o book. Plano parcial continua
    válido enquanto todas as suas intenções forem válidas; reservas extras em outras
    células não importam.
    """
    freshness = sell_intent_plan_freshness(plan, current_book)
    if not freshness.is_current:
        summary = ", ".join(f"{f.cycle_ref}: {f.reason}" for f in freshness.findings)
        raise SellIntentError(_E.STALE_SELL_INTENT, summary, freshness.findings)
