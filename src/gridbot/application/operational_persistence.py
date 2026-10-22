"""A17.3: contratos puros de autoridade local; nenhuma prova de exchange."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from gridbot.application import operational_grid as operations
from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_intents import SellIntentPlan
from gridbot.application.sell_lifecycle import SellExecutionContext
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.domain.assets import Symbol
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Qty
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.portfolio.buy_finalization import BuyExecutionContext, FinalizedBuy
from gridbot.portfolio.sell_sizing import SellSizingAssessment
from gridbot.strategy.buy_intents import BuyIntentPlan
from gridbot.strategy.grid_state import CellCycleRef, CellPhase


class PersistenceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    EMPTY_DATABASE = "EMPTY_DATABASE"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
    CORRUPT_DATABASE = "CORRUPT_DATABASE"
    CORRUPT_JSON = "CORRUPT_JSON"
    INVALID_DECIMAL = "INVALID_DECIMAL"
    INVALID_STATE = "INVALID_STATE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    DUPLICATE_SCOPE = "DUPLICATE_SCOPE"
    BUSY = "BUSY"
    IO_ERROR = "IO_ERROR"
    PATH_UNSAFE = "PATH_UNSAFE"
    SENSITIVE_INPUT = "SENSITIVE_INPUT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    COMMIT_UNCERTAIN = "COMMIT_UNCERTAIN"


class PersistenceError(DomainError):
    """Sem payload bruto/credenciais no texto do erro."""

    def __init__(self, code: PersistenceErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def require_revision(value: int) -> None:
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise PersistenceError(
            PersistenceErrorCode.INVALID_STATE, "revisão inteira fora do contrato"
        )


@dataclass(frozen=True, slots=True)
class OperationalScope:
    """Uma autoridade por venue/conta/ambiente/símbolo dentro do banco local.

    Alias de conta é metadata não secreta fornecida, não identidade autenticada.
    Não há namespace aleatório que permita duas raízes para a mesma conta/par.
    """

    venue_ref: str
    account_ref: str
    environment_ref: str
    symbol: Symbol

    def __post_init__(self) -> None:
        for value in (self.venue_ref, self.account_ref, self.environment_ref):
            if not is_valid_external_ref(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise PersistenceError(PersistenceErrorCode.SCOPE_MISMATCH, "alias inválido")
        if type(self.symbol) is not Symbol:
            raise PersistenceError(
                PersistenceErrorCode.SCOPE_MISMATCH, "símbolo explícito requerido"
            )
        replace(self.symbol.base)
        replace(self.symbol.quote)
        replace(self.symbol)


@dataclass(frozen=True, slots=True)
class VersionedOperationalState:
    scope: OperationalScope
    revision: int
    book: GridOperationalBook

    def __post_init__(self) -> None:
        require_revision(self.revision)
        if type(self.scope) is not OperationalScope or type(self.book) is not GridOperationalBook:
            raise PersistenceError(PersistenceErrorCode.INVALID_STATE, "raiz/escopo desconhecido")
        replace(self.scope)
        replace(self.book)
        if self.book.grid_state.plan.spec.symbol != self.scope.symbol:
            raise PersistenceError(PersistenceErrorCode.SCOPE_MISMATCH, "raiz de outro símbolo")
        for binding in self.book.external_sell_bindings:
            identity = binding.identity
            if (
                identity.venue_ref,
                identity.account_ref,
                identity.environment_ref,
                identity.symbol,
            ) != (
                self.scope.venue_ref,
                self.scope.account_ref,
                self.scope.environment_ref,
                self.scope.symbol,
            ):
                raise PersistenceError(
                    PersistenceErrorCode.SCOPE_MISMATCH, "binding de outro escopo"
                )


@dataclass(frozen=True, slots=True)
class PrepareOperationalBuy:
    plan: BuyIntentPlan
    cycle_ref: CellCycleRef
    quote_fee_hold: Money


@dataclass(frozen=True, slots=True)
class BindOperationalBuy:
    cycle_ref: CellCycleRef
    context: BuyExecutionContext


@dataclass(frozen=True, slots=True)
class MarkOperationalBuyUncertain:
    cycle_ref: CellCycleRef


@dataclass(frozen=True, slots=True)
class SettleOperationalBuy:
    finalized: FinalizedBuy


@dataclass(frozen=True, slots=True)
class ReserveOperationalSell:
    assessment: SellSizingAssessment
    base_fee_hold: Qty


@dataclass(frozen=True, slots=True)
class PrepareOperationalSell:
    plan: SellIntentPlan
    cycle_ref: CellCycleRef


@dataclass(frozen=True, slots=True)
class MarkOperationalSellUncertain:
    cycle_ref: CellCycleRef


@dataclass(frozen=True, slots=True)
class BindOperationalSell:
    cycle_ref: CellCycleRef
    context: SellExecutionContext


@dataclass(frozen=True, slots=True)
class BindOperationalExternalSell:
    cycle_ref: CellCycleRef
    binding: ExternalSellOrderBinding


type OperationalTransition = (
    PrepareOperationalBuy
    | BindOperationalBuy
    | MarkOperationalBuyUncertain
    | SettleOperationalBuy
    | ReserveOperationalSell
    | PrepareOperationalSell
    | MarkOperationalSellUncertain
    | BindOperationalSell
    | BindOperationalExternalSell
)


def apply_operational_transition(
    book: GridOperationalBook, transition: OperationalTransition
) -> GridOperationalBook:
    """Dispatcher fechado; não recebe snapshot substituto nem callback do chamador.

    O codec da infraestrutura revalida todas as fontes antes desta chamada. APIs
    antigas revalidam a autoridade. Só as nove transições já autorizadas existem.
    """
    replace(book)
    match transition:
        case PrepareOperationalBuy(plan, cycle, hold) if type(transition) is PrepareOperationalBuy:
            return operations.prepare_operational_buy(book, plan, cycle, hold)
        case BindOperationalBuy(cycle, context) if type(transition) is BindOperationalBuy:
            return operations.bind_operational_buy_execution(book, cycle, context)
        case MarkOperationalBuyUncertain(cycle) if type(transition) is MarkOperationalBuyUncertain:
            return operations.mark_operational_buy_submission_uncertain(book, cycle)
        case SettleOperationalBuy(finalized) if type(transition) is SettleOperationalBuy:
            return operations.settle_operational_buy(book, finalized)
        case ReserveOperationalSell(assessment, hold) if type(transition) is ReserveOperationalSell:
            return operations.reserve_operational_sell(book, assessment, hold)
        case PrepareOperationalSell(plan, cycle) if type(transition) is PrepareOperationalSell:
            return operations.prepare_sell(book, plan, cycle)
        case MarkOperationalSellUncertain(cycle) if (
            type(transition) is MarkOperationalSellUncertain
        ):
            return operations.mark_sell_submission_uncertain(book, cycle)
        case BindOperationalSell(cycle, context) if type(transition) is BindOperationalSell:
            return operations.bind_sell_execution(book, cycle, context)
        case BindOperationalExternalSell(cycle, binding) if (
            type(transition) is BindOperationalExternalSell
        ):
            return operations.bind_external_sell_order(book, cycle, binding)
        case _:
            raise PersistenceError(PersistenceErrorCode.INVALID_STATE, "transição não autorizada")


def validate_pristine_bootstrap(book: GridOperationalBook) -> None:
    """Importação inicial restrita: capital autorizado explícito, nenhum passado inventado."""
    replace(book)
    inventory = book.inventory_book
    funded = inventory.funded_buy_book
    if (
        book.sell_attempts
        or book.external_sell_bindings
        or inventory.reservations
        or funded.reservations
        or funded.settled_reservations
        or funded.lifecycle.attempts
        or funded.lifecycle.consumed
        or any(
            c.phase is not CellPhase.WAITING_BUY or c.cycle_seq != 0 for c in book.grid_state.cells
        )
    ):
        raise PersistenceError(
            PersistenceErrorCode.INVALID_STATE, "bootstrap exige QUOTE_ONLY ciclo zero"
        )


class OperationalStatePort(Protocol):
    def load_operational_state(self, scope: OperationalScope) -> VersionedOperationalState: ...

    def commit_operational_transition(
        self, scope: OperationalScope, expected_revision: int, transition: OperationalTransition
    ) -> VersionedOperationalState: ...
