"""A17.1: vínculo estrutural declarado; não autentica origem nem completa coleta."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import DecimalException
from enum import StrEnum

from gridbot.application.sell_evidence import SellOrderIdentity, _nested, _typed
from gridbot.application.sell_lifecycle import SellExecutionContext
from gridbot.domain.assets import Symbol
from gridbot.domain.enums import Side
from gridbot.domain.errors import DomainError
from gridbot.strategy.grid_state import CellCycleRef


class SellOrderBindingErrorCode(StrEnum):
    INVALID_BINDING = "INVALID_BINDING"
    INVALID_OPERATIONAL_BOOK = "INVALID_OPERATIONAL_BOOK"
    ATTEMPT_NOT_BOUND = "ATTEMPT_NOT_BOUND"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    BINDING_CONFLICT = "BINDING_CONFLICT"
    EXTERNAL_ORDER_ALREADY_BOUND = "EXTERNAL_ORDER_ALREADY_BOUND"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellOrderBindingError(DomainError):
    def __init__(self, code: SellOrderBindingErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@contextmanager
def _binding_guard(code: SellOrderBindingErrorCode) -> Iterator[None]:
    try:
        yield
    except SellOrderBindingError:
        raise
    except (DomainError, TypeError, AttributeError, DecimalException) as exc:
        if isinstance(exc, DecimalException) or getattr(exc, "code", None) == (
            SellOrderBindingErrorCode.FINANCIAL_PRECISION_ERROR
        ):
            code = SellOrderBindingErrorCode.FINANCIAL_PRECISION_ERROR
        raise SellOrderBindingError(code, str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ExternalSellOrderBinding:
    """Sem finanças duplicadas. Escopo de conta deve ser alias não secreto fornecido.

    client_order_ref é confrontável, não chave global nem alias mutável nesta fase.
    A revalidação na raiz acrescenta reserva/origem/tentativa legítimas a este DTO.
    """

    identity: SellOrderIdentity
    side: Side

    def __post_init__(self) -> None:
        with _binding_guard(SellOrderBindingErrorCode.INVALID_BINDING):
            _nested(self.identity, SellOrderIdentity)
            _typed(self.side, Side)
            if self.side is not Side.SELL:
                raise DomainError("binding exige observação SELL explícita")

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.identity.cycle_ref

    @property
    def external_order_key(self) -> tuple[str, str, str, Symbol, str]:
        return (
            self.identity.venue_ref,
            self.identity.environment_ref,
            self.identity.account_ref,
            self.identity.symbol,
            self.identity.order_ref,
        )

    def matches_context(self, context: SellExecutionContext) -> bool:
        with _binding_guard(SellOrderBindingErrorCode.INVALID_BINDING):
            replace(self)
            _typed(context, SellExecutionContext)
            replace(context)
            return (
                self.identity.cycle_ref == context.cycle_ref
                and self.identity.execution_ref == context.execution_ref
                and self.identity.symbol == context.symbol
                and self.side is context.side
            )
