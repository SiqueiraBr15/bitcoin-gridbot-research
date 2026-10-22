"""A17: observações fornecidas pela ingestão futura, sem promessa de completude.

Identidades são declarações; A17.1 permite vínculo estrutural na raiz A15.
None preserva ausência; zeros são literais. A camada externa deve guardar o
evento bruto antes destes DTOs, inclusive sentinelas e observações recusadas.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import DecimalException
from enum import StrEnum

from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.domain.assets import Symbol
from gridbot.domain.enums import LiquidityRole, OrderStatus, OrderType, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Money, Price, Qty
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy.grid_state import CellCycleRef


class SellEvidenceErrorCode(StrEnum):
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellEvidenceError(DomainError):
    def __init__(self, code: SellEvidenceErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@contextmanager
def _guard() -> Iterator[None]:
    try:
        yield
    except SellEvidenceError:
        raise
    except (DomainError, TypeError, AttributeError, DecimalException) as exc:
        code = SellEvidenceErrorCode.INVALID_EVIDENCE
        if isinstance(exc, DecimalException) or getattr(exc, "code", None) == (
            SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR
        ):
            code = SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR
        raise SellEvidenceError(code, str(exc)) from exc


def _typed(value: object, expected: type) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(expected.__name__)
    if not isinstance(value, expected):
        raise TypeError(f"esperado {expected.__name__}")


def _ref(value: object) -> None:
    if not is_valid_external_ref(value):
        raise DomainError("referência externa inválida")
    if isinstance(value, str) and any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise DomainError("referência externa contém caractere de controle")


def _nested[T](value: T, expected: type[T]) -> None:
    _typed(value, expected)
    # Estes tipos são dataclasses; replace reexecuta suas validações.
    if isinstance(
        value,
        (
            SellOrderIdentity,
            SellTradeQueryScope,
            ObservedSellOrderReport,
            CollectedSellTrade,
            SellTradePage,
            SellTradeCollection,
            SellExecutionRef,
            CellCycleRef,
            Symbol,
            Money,
            Price,
            Qty,
        ),
    ):
        replace(value)
    if isinstance(value, Symbol):
        replace(value.base)
        replace(value.quote)
    if isinstance(value, Money):
        replace(value.asset)


def _optional_finance(value: Qty | Price | Money | None, expected: type) -> None:
    if value is not None:
        _nested(value, expected)
        if isinstance(value, Money) and value.is_negative:
            raise DomainError("observação monetária negativa; preservar sentinela fora do DTO")


@dataclass(frozen=True, slots=True)
class SellOrderIdentity:
    venue_ref: str
    account_ref: str
    environment_ref: str
    order_ref: str
    execution_ref: SellExecutionRef
    cycle_ref: CellCycleRef
    symbol: Symbol
    client_order_ref: str | None = None

    def __post_init__(self) -> None:
        with _guard():
            for value in (self.venue_ref, self.account_ref, self.environment_ref, self.order_ref):
                _ref(value)
            if self.client_order_ref is not None:
                _ref(self.client_order_ref)
            _nested(self.execution_ref, SellExecutionRef)
            _nested(self.cycle_ref, CellCycleRef)
            _nested(self.symbol, Symbol)


@dataclass(frozen=True, slots=True)
class ObservedSellOrderReport:
    """Terminal ou não terminal; status desconhecido é None, nunca FILLED inferido."""

    identity: SellOrderIdentity
    status: OrderStatus | None
    original_qty: Qty | None
    cumulative_executed_qty: Qty | None
    cumulative_quote: Money | None
    limit_price: Price | None
    side: Side
    order_type: OrderType
    source_ref: str | None = None
    collection_ref: str | None = None

    def __post_init__(self) -> None:
        with _guard():
            _nested(self.identity, SellOrderIdentity)
            if self.status is not None:
                _typed(self.status, OrderStatus)
            _typed(self.side, Side)
            _typed(self.order_type, OrderType)
            for value, expected in (
                (self.original_qty, Qty),
                (self.cumulative_executed_qty, Qty),
                (self.cumulative_quote, Money),
                (self.limit_price, Price),
            ):
                _optional_finance(value, expected)
            if self.cumulative_quote is not None and (
                self.cumulative_quote.asset != self.identity.symbol.quote
            ):
                raise DomainError("cumulative_quote deve usar ativo quote")
            if self.source_ref is not None:
                _ref(self.source_ref)
            if self.collection_ref is not None:
                _ref(self.collection_ref)


class SellTradeIdentityCoverage(StrEnum):
    FULL_DECLARED_IDENTITY = "FULL_DECLARED_IDENTITY"
    ORDER_ID_WITHOUT_CLIENT_ID = "ORDER_ID_WITHOUT_CLIENT_ID"


@dataclass(frozen=True, slots=True)
class CollectedSellTrade:
    """Permite fee ausente e acima do hold sem adulterar o ledger A16."""

    identity: SellOrderIdentity
    trade_ref: str
    execution_price: Price | None
    executed_qty: Qty | None
    observed_quote: Money | None
    fee: Money | None
    side: Side
    liquidity: LiquidityRole | None = None
    identity_coverage: SellTradeIdentityCoverage = SellTradeIdentityCoverage.FULL_DECLARED_IDENTITY

    def __post_init__(self) -> None:
        with _guard():
            _nested(self.identity, SellOrderIdentity)
            _ref(self.trade_ref)
            _typed(self.side, Side)
            if self.liquidity is not None:
                _typed(self.liquidity, LiquidityRole)
            _typed(self.identity_coverage, SellTradeIdentityCoverage)
            if (
                self.identity_coverage is SellTradeIdentityCoverage.ORDER_ID_WITHOUT_CLIENT_ID
                and self.identity.client_order_ref is not None
            ):
                raise DomainError("cobertura sem client ID não pode declarar client ID")
            for value, expected in (
                (self.execution_price, Price),
                (self.executed_qty, Qty),
                (self.observed_quote, Money),
                (self.fee, Money),
            ):
                _optional_finance(value, expected)
            if self.observed_quote is not None and (
                self.observed_quote.asset != self.identity.symbol.quote
            ):
                raise DomainError("observed_quote deve usar ativo quote")


@dataclass(frozen=True, slots=True)
class SellTradePage:
    source_ref: str
    cursor_from: str | None
    next_cursor: str | None
    trades: tuple[CollectedSellTrade, ...]
    query_identity: SellOrderIdentity | None = None
    collection_ref: str | None = None
    requested_limit: int | None = None

    def __post_init__(self) -> None:
        with _guard():
            _ref(self.source_ref)
            for value in (self.cursor_from, self.next_cursor):
                if value is not None:
                    _ref(value)
            _typed(self.trades, tuple)
            for trade in self.trades:
                _nested(trade, CollectedSellTrade)
            if self.query_identity is not None:
                _nested(self.query_identity, SellOrderIdentity)
            if self.collection_ref is not None:
                _ref(self.collection_ref)
            _limit(self.requested_limit)


def _limit(value: int | None) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise DomainError("limit exige inteiro positivo, sem bool")


class SellTradePagination(StrEnum):
    DECLARED_CHAIN = "DECLARED_CHAIN"
    BINANCE_FROM_ID = "BINANCE_FROM_ID"


@dataclass(frozen=True, slots=True)
class SellTradeQueryScope:
    """Metadados declarados pelo futuro coletor, não campos da resposta Binance.

    initial_cursor registra a requisição inicial, inclusive começo intermediário.
    collection_ref identifica uma captura; não prova idade, confiança ou completude.
    """

    identity: SellOrderIdentity
    collection_ref: str
    pagination: SellTradePagination
    initial_cursor: str | None
    limit: int | None

    def __post_init__(self) -> None:
        with _guard():
            _nested(self.identity, SellOrderIdentity)
            _ref(self.collection_ref)
            _typed(self.pagination, SellTradePagination)
            if self.initial_cursor is not None:
                _ref(self.initial_cursor)
            _limit(self.limit)


class SellCollectionStopReason(StrEnum):
    UNKNOWN = "UNKNOWN"
    IN_PROGRESS = "IN_PROGRESS"
    PAGE_LIMIT_REACHED = "PAGE_LIMIT_REACHED"
    HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"
    NO_MORE_RESULTS = "NO_MORE_RESULTS"
    SOURCE_ERROR = "SOURCE_ERROR"
    TRUNCATED = "TRUNCATED"


@dataclass(frozen=True, slots=True)
class SellTradeCollection:
    identity: SellOrderIdentity
    pages: tuple[SellTradePage, ...]
    stop_reason: SellCollectionStopReason
    order_before: ObservedSellOrderReport | None = None
    order_after: ObservedSellOrderReport | None = None
    query: SellTradeQueryScope | None = None

    def __post_init__(self) -> None:
        with _guard():
            _nested(self.identity, SellOrderIdentity)
            _typed(self.pages, tuple)
            _typed(self.stop_reason, SellCollectionStopReason)
            for page in self.pages:
                _nested(page, SellTradePage)
            for report in (self.order_before, self.order_after):
                if report is not None:
                    _nested(report, ObservedSellOrderReport)
            if self.query is not None:
                _nested(self.query, SellTradeQueryScope)
