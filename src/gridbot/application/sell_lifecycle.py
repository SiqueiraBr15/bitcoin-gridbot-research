"""Contratos SELL puros da A15 (ADR-024); vínculo operacional não prova negociação."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.sell_intents import GridSellIntent
from gridbot.domain.assets import Symbol
from gridbot.domain.enums import OrderType, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Price, Qty
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy.grid_state import CellCycleRef


class SellAttemptStatus(StrEnum):
    PREPARED = "PREPARED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    EXECUTION_BOUND = "EXECUTION_BOUND"


class SellLifecycleErrorCode(StrEnum):
    INVALID_OPERATIONAL_BOOK = "INVALID_OPERATIONAL_BOOK"
    INVALID_SELL_ATTEMPT = "INVALID_SELL_ATTEMPT"
    INVALID_SELL_EXECUTION_CONTEXT = "INVALID_SELL_EXECUTION_CONTEXT"
    SELL_RESERVATION_NOT_FOUND = "SELL_RESERVATION_NOT_FOUND"
    SELL_INTENT_NOT_IN_PLAN = "SELL_INTENT_NOT_IN_PLAN"
    SELL_ATTEMPT_ALREADY_EXISTS = "SELL_ATTEMPT_ALREADY_EXISTS"
    SELL_ATTEMPT_NOT_FOUND = "SELL_ATTEMPT_NOT_FOUND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    SELL_EXECUTION_CONFLICT = "SELL_EXECUTION_CONFLICT"
    SELL_EXECUTION_REF_ALREADY_USED = "SELL_EXECUTION_REF_ALREADY_USED"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellLifecycleError(DomainError):
    def __init__(self, code: SellLifecycleErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = SellLifecycleErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _translate(exc: Exception, code: SellLifecycleErrorCode) -> SellLifecycleError:
    if getattr(exc, "code", None) == _E.FINANCIAL_PRECISION_ERROR:
        return SellLifecycleError(_E.FINANCIAL_PRECISION_ERROR, str(exc))
    return SellLifecycleError(code, str(exc))


def same_sell_authorization(first: GridSellIntent, second: GridSellIntent) -> bool:
    """Conteúdo econômico de UM ciclo; snapshots de outras células não são autoridade."""
    return (
        first.cycle_ref == second.cycle_ref
        and first.symbol == second.symbol
        and first.limit_price == second.limit_price
        and first.sell_qty == second.sell_qty
        and first.base_fee_hold == second.base_fee_hold
        and first.finalized_buy == second.finalized_buy
    )


@dataclass(frozen=True, slots=True)
class SellExecutionRef:
    """Referência SELL recebida de fora; distinta de BuyExecutionRef, nunca gerada aqui."""

    value: str

    def __post_init__(self) -> None:
        if not is_valid_external_ref(self.value):
            raise SellLifecycleError(_E.INVALID_SELL_EXECUTION_CONTEXT, "referência SELL inválida")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SellExecutionContext:
    """Associação explícita à intenção observada, sem campos financeiros redundantes.

    O adapter futuro deverá conferir lado, tipo, símbolo, preço e quantidade da ordem
    externa contra esta intenção antes de fornecê-la. Consistência não é autenticação.
    """

    intent: GridSellIntent
    execution_ref: SellExecutionRef

    def __post_init__(self) -> None:
        try:
            _expect(self.intent, GridSellIntent, "intent")
            _expect(self.execution_ref, SellExecutionRef, "execution_ref")
            replace(self.intent)
            replace(self.execution_ref)
        except (DomainError, TypeError) as exc:
            raise _translate(exc, _E.INVALID_SELL_EXECUTION_CONTEXT) from exc

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref

    @property
    def symbol(self) -> Symbol:
        return self.intent.symbol

    @property
    def side(self) -> Side:
        return self.intent.side

    @property
    def order_type(self) -> OrderType:
        return self.intent.order_type

    @property
    def limit_price(self) -> Price:
        return self.intent.limit_price

    @property
    def requested_qty(self) -> Qty:
        return self.intent.sell_qty


@dataclass(frozen=True, slots=True)
class SellAttempt:
    """Uma tentativa por ciclo; a reserva continua integral em todos os três estados."""

    intent: GridSellIntent
    status: SellAttemptStatus
    execution: SellExecutionContext | None = None

    def __post_init__(self) -> None:
        try:
            _expect(self.intent, GridSellIntent, "intent")
            _expect(self.status, SellAttemptStatus, "status")
            replace(self.intent)
            if self.status is SellAttemptStatus.EXECUTION_BOUND:
                if not isinstance(self.execution, SellExecutionContext):
                    raise TypeError("EXECUTION_BOUND exige contexto SELL")
                replace(self.execution)
                if not same_sell_authorization(self.intent, self.execution.intent):
                    raise SellLifecycleError(_E.INVALID_SELL_ATTEMPT, "contexto de outra intenção")
            elif self.execution is not None:
                raise SellLifecycleError(
                    _E.INVALID_SELL_ATTEMPT, "estado sem vínculo exige execution=None"
                )
        except (DomainError, TypeError) as exc:
            raise _translate(exc, _E.INVALID_SELL_ATTEMPT) from exc

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref
