"""Raiz coordenada A15: transições específicas preservam compromissos A12/A13/SELL.

Snapshot puro em memória. Construção arbitrária fora das APIs não prova continuidade
histórica; persistência, autoridade transacional e reconciliação permanecem pendentes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from gridbot.application.buy_quote_capital import (
    bind_funded_buy_execution,
    mark_funded_submission_uncertain,
    prepare_funded_buy,
)
from gridbot.application.sell_intents import (
    GridSellIntent,
    SellIntentPlan,
    build_sell_intent_for_cell,
    validate_sell_intent_plan_against_book,
)
from gridbot.application.sell_inventory import (
    SellInventoryBook,
    reserve_sell_inventory,
    settle_inventory_book_buy,
)
from gridbot.application.sell_lifecycle import (
    SellAttempt,
    SellAttemptStatus,
    SellExecutionContext,
    SellLifecycleError,
    SellLifecycleErrorCode,
    _expect,
    _translate,
    same_sell_authorization,
)
from gridbot.application.sell_order_binding import (
    ExternalSellOrderBinding,
    SellOrderBindingError,
    SellOrderBindingErrorCode,
    _binding_guard,
)
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Qty
from gridbot.portfolio.buy_finalization import BuyExecutionContext, FinalizedBuy
from gridbot.portfolio.sell_sizing import SellSizingAssessment
from gridbot.strategy.buy_intents import BuyIntentPlan
from gridbot.strategy.grid_state import CellCycleRef, GridState

_E = SellLifecycleErrorCode
_S = SellAttemptStatus


def _revalidate_finalized_buy(finalized: FinalizedBuy) -> None:
    """Reexecuta os contratos de cada fonte, incluindo fills e value objects internos."""
    replace(finalized.context.intent.cycle_ref)
    replace(finalized.context.intent.symbol.base)
    replace(finalized.context.intent.symbol.quote)
    replace(finalized.context.intent.symbol)
    replace(finalized.context.intent.price)
    replace(finalized.context.intent.qty)
    replace(finalized.context.intent)
    replace(finalized.context.execution_ref)
    replace(finalized.context)
    replace(finalized.terminal_report)
    replace(finalized.reconciliation_evidence)
    for fill in finalized.ledger.fills:
        replace(fill.cycle_ref)
        replace(fill.symbol.base)
        replace(fill.symbol.quote)
        replace(fill.symbol)
        replace(fill.execution_price)
        replace(fill.executed_qty)
        replace(fill.fee.asset)
        replace(fill.fee)
        replace(fill)
    replace(finalized.ledger)
    replace(finalized)


@dataclass(frozen=True, slots=True)
class GridOperationalBook:
    """A única fonte financeira é inventory_book; tentativas não são débitos nem receitas."""

    inventory_book: SellInventoryBook
    sell_attempts: tuple[SellAttempt, ...] = ()
    external_sell_bindings: tuple[ExternalSellOrderBinding, ...] = ()

    def __post_init__(self) -> None:
        try:
            _expect(self.inventory_book, SellInventoryBook, "inventory_book")
            if not isinstance(self.sell_attempts, tuple) or not all(
                isinstance(a, SellAttempt) for a in self.sell_attempts
            ):
                raise TypeError("sell_attempts deve ser tuple[SellAttempt, ...] (imutável)")
            replace(self.inventory_book)
            # A raiz reexecuta também contratos dos consumos e tentativas BUY que podem
            # não ter reserva SELL; não basta confiar em um nested dataclass frozen.
            funded = self.inventory_book.funded_buy_book
            replace(funded.initial_quote_capital.asset)
            replace(funded.initial_quote_capital)
            for reservation in (*funded.reservations, *funded.settled_reservations):
                replace(reservation.intent.cycle_ref)
                replace(reservation.intent.symbol.base)
                replace(reservation.intent.symbol.quote)
                replace(reservation.intent.symbol)
                replace(reservation.intent.price)
                replace(reservation.intent.qty)
                replace(reservation.intent)
                replace(reservation.quote_fee_hold.asset)
                replace(reservation.quote_fee_hold)
                replace(reservation)
            for attempt in funded.lifecycle.attempts:
                replace(attempt.intent)
                replace(attempt)
                if attempt.execution is not None:
                    replace(attempt.execution.execution_ref)
                    replace(attempt.execution)
            for finalized in funded.lifecycle.consumed:
                _revalidate_finalized_buy(finalized)
            for sell_attempt in self.sell_attempts:
                replace(sell_attempt)
            refs = [a.cycle_ref for a in self.sell_attempts]
            if len(set(refs)) != len(refs):
                raise SellLifecycleError(
                    _E.SELL_ATTEMPT_ALREADY_EXISTS, "tentativa duplicada por ciclo"
                )
            executions = [a.execution.execution_ref for a in self.sell_attempts if a.execution]
            if len(set(executions)) != len(executions):
                raise SellLifecycleError(
                    _E.SELL_EXECUTION_REF_ALREADY_USED, "referência SELL repetida"
                )
            for sell_attempt in self.sell_attempts:
                sell_reservation = self.inventory_book.reservation_for(sell_attempt.cycle_ref)
                if sell_reservation is None:
                    raise SellLifecycleError(_E.SELL_RESERVATION_NOT_FOUND, "tentativa sem reserva")
                if not same_sell_authorization(
                    sell_attempt.intent, GridSellIntent(sell_reservation)
                ):
                    raise SellLifecycleError(_E.INVALID_SELL_ATTEMPT, "tentativa de outra reserva")
            if not isinstance(self.external_sell_bindings, tuple) or not all(
                isinstance(b, ExternalSellOrderBinding) for b in self.external_sell_bindings
            ):
                raise TypeError("external_sell_bindings exige tuple imutável de bindings")
            for binding in self.external_sell_bindings:
                replace(binding)
            binding_refs = tuple(b.cycle_ref for b in self.external_sell_bindings)
            if binding_refs != tuple(sorted(set(binding_refs))):
                raise DomainError("bindings duplicados ou fora da ordem canônica por ciclo")
            keys = tuple(b.external_order_key for b in self.external_sell_bindings)
            if len(set(keys)) != len(keys):
                raise DomainError("mesma ordem externa associada a mais de uma tentativa")
            for binding in self.external_sell_bindings:
                bound_attempt = self.attempt_for(binding.cycle_ref)
                if (
                    bound_attempt is None
                    or bound_attempt.status is not _S.EXECUTION_BOUND
                    or bound_attempt.execution is None
                ):
                    raise DomainError("binding externo exige tentativa BOUND na raiz")
                if not binding.matches_context(bound_attempt.execution):
                    raise DomainError("binding externo de outro contexto SELL")
        except (DomainError, TypeError, AttributeError) as exc:
            raise _translate(exc, _E.INVALID_OPERATIONAL_BOOK) from exc

    @property
    def grid_state(self) -> GridState:
        return self.inventory_book.grid_state

    def attempt_for(self, cycle_ref: CellCycleRef) -> SellAttempt | None:
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        return next((a for a in self.sell_attempts if a.cycle_ref == cycle_ref), None)

    def external_binding_for(self, cycle_ref: CellCycleRef) -> ExternalSellOrderBinding | None:
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        replace(cycle_ref)
        return next((b for b in self.external_sell_bindings if b.cycle_ref == cycle_ref), None)


def _revalidate(book: GridOperationalBook) -> None:
    _expect(book, GridOperationalBook, "book")
    replace(book)


def _attempt_or_fail(book: GridOperationalBook, cycle_ref: CellCycleRef) -> SellAttempt:
    attempt = book.attempt_for(cycle_ref)
    if attempt is None:
        raise SellLifecycleError(_E.SELL_ATTEMPT_NOT_FOUND, f"{cycle_ref}: nenhuma tentativa SELL")
    return attempt


def _replace_attempt(book: GridOperationalBook, new: SellAttempt) -> GridOperationalBook:
    return replace(
        book,
        sell_attempts=tuple(new if a.cycle_ref == new.cycle_ref else a for a in book.sell_attempts),
    )


def prepare_operational_buy(
    book: GridOperationalBook,
    intent_plan: BuyIntentPlan,
    cycle_ref: CellCycleRef,
    quote_fee_reserve: Money,
) -> GridOperationalBook:
    """Delega A12; preserva a tupla de reservas BTC e todas as tentativas SELL."""
    _revalidate(book)
    replace(intent_plan)
    updated = prepare_funded_buy(
        book.inventory_book.funded_buy_book, intent_plan, cycle_ref, quote_fee_reserve
    )
    inventory = replace(book.inventory_book, funded_buy_book=updated)
    return replace(book, inventory_book=inventory)


def bind_operational_buy_execution(
    book: GridOperationalBook, cycle_ref: CellCycleRef, execution_context: BuyExecutionContext
) -> GridOperationalBook:
    _revalidate(book)
    _expect(execution_context, BuyExecutionContext, "execution_context")
    replace(execution_context.intent)
    replace(execution_context.execution_ref)
    replace(execution_context)
    updated = bind_funded_buy_execution(
        book.inventory_book.funded_buy_book, cycle_ref, execution_context
    )
    if updated is book.inventory_book.funded_buy_book:
        return book
    return replace(book, inventory_book=replace(book.inventory_book, funded_buy_book=updated))


def mark_operational_buy_submission_uncertain(
    book: GridOperationalBook, cycle_ref: CellCycleRef
) -> GridOperationalBook:
    _revalidate(book)
    updated = mark_funded_submission_uncertain(book.inventory_book.funded_buy_book, cycle_ref)
    return replace(book, inventory_book=replace(book.inventory_book, funded_buy_book=updated))


def settle_operational_buy(
    book: GridOperationalBook, finalized_buy: FinalizedBuy
) -> GridOperationalBook:
    _revalidate(book)
    _expect(finalized_buy, FinalizedBuy, "finalized_buy")
    _revalidate_finalized_buy(finalized_buy)
    inventory = settle_inventory_book_buy(book.inventory_book, finalized_buy)
    if inventory is book.inventory_book:
        return book
    return replace(book, inventory_book=inventory)


def reserve_operational_sell(
    book: GridOperationalBook, assessment: SellSizingAssessment, base_fee_hold: Qty
) -> GridOperationalBook:
    _revalidate(book)
    inventory = reserve_sell_inventory(book.inventory_book, assessment, base_fee_hold)
    return replace(book, inventory_book=inventory)


def prepare_sell(
    book: GridOperationalBook, sell_intent_plan: SellIntentPlan, cycle_ref: CellCycleRef
) -> GridOperationalBook:
    """Autoridade A14 current + reserva A13 consumida; duplicação sempre é erro."""
    _revalidate(book)
    _expect(cycle_ref, CellCycleRef, "cycle_ref")
    validate_sell_intent_plan_against_book(sell_intent_plan, book.inventory_book)
    intent = sell_intent_plan.intent_for(cycle_ref)
    if intent is None:
        raise SellLifecycleError(
            _E.SELL_INTENT_NOT_IN_PLAN, f"{cycle_ref}: intenção não selecionada"
        )
    if book.attempt_for(cycle_ref) is not None:
        raise SellLifecycleError(
            _E.SELL_ATTEMPT_ALREADY_EXISTS, f"{cycle_ref}: tentativa já preparada"
        )
    attempt = SellAttempt(intent, _S.PREPARED)
    attempts = tuple(sorted((*book.sell_attempts, attempt), key=lambda a: a.cycle_ref))
    return replace(book, sell_attempts=attempts)


def mark_sell_submission_uncertain(
    book: GridOperationalBook, cycle_ref: CellCycleRef
) -> GridOperationalBook:
    """PREPARED -> UNCERTAIN; repetição é no-op. BOUND não regride. Nenhum hold liberado."""
    _revalidate(book)
    attempt = _attempt_or_fail(book, cycle_ref)
    if attempt.status is _S.SUBMISSION_UNCERTAIN:
        return book
    if attempt.status is not _S.PREPARED:
        raise SellLifecycleError(_E.INVALID_TRANSITION, f"{cycle_ref}: vínculo já estabelecido")
    return _replace_attempt(book, replace(attempt, status=_S.SUBMISSION_UNCERTAIN))


def bind_sell_execution(
    book: GridOperationalBook, cycle_ref: CellCycleRef, execution_context: SellExecutionContext
) -> GridOperationalBook:
    """PREPARED/UNCERTAIN -> BOUND com vínculo explícito; não reconcilia fills ou terminal."""
    _revalidate(book)
    _expect(execution_context, SellExecutionContext, "execution_context")
    replace(execution_context)
    attempt = _attempt_or_fail(book, cycle_ref)
    if not same_sell_authorization(attempt.intent, execution_context.intent):
        raise SellLifecycleError(
            _E.SELL_EXECUTION_CONFLICT, f"{cycle_ref}: contexto de outra autorização"
        )
    if attempt.status is _S.EXECUTION_BOUND:
        if attempt.execution == execution_context:
            return book
        raise SellLifecycleError(
            _E.SELL_EXECUTION_CONFLICT, f"{cycle_ref}: execução não substituída"
        )
    if any(
        a.execution and a.execution.execution_ref == execution_context.execution_ref
        for a in book.sell_attempts
    ):
        raise SellLifecycleError(_E.SELL_EXECUTION_REF_ALREADY_USED, "referência SELL já utilizada")
    bound = SellAttempt(attempt.intent, _S.EXECUTION_BOUND, execution_context)
    return _replace_attempt(book, bound)


def validate_operational_sell(book: GridOperationalBook, cycle_ref: CellCycleRef) -> None:
    """Revalida raiz e tentativa existente; consulta não concede nova submissão."""
    _revalidate(book)
    attempt = _attempt_or_fail(book, cycle_ref)
    plan = build_sell_intent_for_cell(book.inventory_book, cycle_ref)
    if not same_sell_authorization(attempt.intent, plan.intents[0]):
        raise SellLifecycleError(_E.INVALID_SELL_ATTEMPT, "autorização SELL incompatível")


def bind_external_sell_order(
    book: GridOperationalBook, cycle_ref: CellCycleRef, binding: ExternalSellOrderBinding
) -> GridOperationalBook:
    """Anexa identidade declarada após BOUND; não resolve autenticidade ou timeout."""
    code = SellOrderBindingErrorCode
    with _binding_guard(code.INVALID_OPERATIONAL_BOOK):
        _revalidate(book)
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        replace(cycle_ref)
        _expect(binding, ExternalSellOrderBinding, "binding")
        replace(binding)
        attempt = book.attempt_for(cycle_ref)
        if attempt is None or attempt.status is not _S.EXECUTION_BOUND or attempt.execution is None:
            raise SellOrderBindingError(code.ATTEMPT_NOT_BOUND, "binding requer tentativa BOUND")
        if binding.cycle_ref != cycle_ref or not binding.matches_context(attempt.execution):
            raise SellOrderBindingError(code.AUTHORIZATION_MISMATCH, "outra identidade interna")
        existing = book.external_binding_for(cycle_ref)
        if existing is not None:
            if existing == binding:
                return book
            raise SellOrderBindingError(code.BINDING_CONFLICT, "binding original não substituído")
        if any(
            b.external_order_key == binding.external_order_key for b in book.external_sell_bindings
        ):
            raise SellOrderBindingError(
                code.EXTERNAL_ORDER_ALREADY_BOUND, "ordem externa já vinculada"
            )
        bindings = tuple(sorted((*book.external_sell_bindings, binding), key=lambda b: b.cycle_ref))
        return replace(book, external_sell_bindings=bindings)
