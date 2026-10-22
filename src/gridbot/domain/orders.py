"""Ordens: intenção, snapshot de estado e fill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from gridbot.domain.assets import Symbol
from gridbot.domain.decimals import financial, require_finite
from gridbot.domain.enums import LiquidityRole, OrderStatus, OrderType, Side
from gridbot.domain.errors import DomainError
from gridbot.domain.ids import ClientOrderId
from gridbot.domain.time import require_utc
from gridbot.domain.values import Money, Price, Qty

_MAX_TRADE_ID_LEN = 64


def _expect(value: object, expected: type, field: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _check_price_for_type(order_type: OrderType, price: Price | None) -> None:
    if order_type.requires_price:
        if price is None:
            raise DomainError(f"ordem {order_type} exige preço")
        _expect(price, Price, "price")
    elif price is not None:
        raise DomainError(f"ordem {order_type} não aceita preço")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Decisão de colocar uma ordem, antes de qualquer envio a uma exchange."""

    client_order_id: ClientOrderId
    symbol: Symbol
    side: Side
    order_type: OrderType
    qty: Qty
    price: Price | None
    created_at: datetime
    grid_level: int | None = None

    def __post_init__(self) -> None:
        _expect(self.client_order_id, ClientOrderId, "client_order_id")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.side, Side, "side")
        _expect(self.order_type, OrderType, "order_type")
        _expect(self.qty, Qty, "qty")
        if self.qty.is_zero:
            raise DomainError("OrderIntent.qty deve ser > 0")
        _check_price_for_type(self.order_type, self.price)
        require_utc(self.created_at, field="created_at")
        if self.grid_level is not None and (
            isinstance(self.grid_level, bool)
            or not isinstance(self.grid_level, int)
            or self.grid_level < 0
        ):
            raise DomainError(f"grid_level inválido: {self.grid_level!r}")


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """Estado conhecido de uma ordem num instante (local ou reportado pela exchange)."""

    client_order_id: ClientOrderId
    symbol: Symbol
    side: Side
    order_type: OrderType
    status: OrderStatus
    price: Price | None
    orig_qty: Qty
    executed_qty: Qty
    cumulative_quote_qty: Decimal
    updated_at: datetime
    exchange_order_id: str | None = None

    def __post_init__(self) -> None:
        _expect(self.client_order_id, ClientOrderId, "client_order_id")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.side, Side, "side")
        _expect(self.order_type, OrderType, "order_type")
        _expect(self.status, OrderStatus, "status")
        _expect(self.orig_qty, Qty, "orig_qty")
        _expect(self.executed_qty, Qty, "executed_qty")
        _check_price_for_type(self.order_type, self.price)
        if self.orig_qty.is_zero:
            raise DomainError("orig_qty deve ser > 0")
        if self.executed_qty > self.orig_qty:
            raise DomainError("executed_qty não pode exceder orig_qty")
        if require_finite(self.cumulative_quote_qty, field="cumulative_quote_qty") < 0:
            raise DomainError("cumulative_quote_qty não pode ser negativo")
        if self.executed_qty.is_zero and self.cumulative_quote_qty != 0:
            raise DomainError("executed_qty zero exige cumulative_quote_qty zero")
        require_utc(self.updated_at, field="updated_at")
        self._check_status_consistency()

    def _check_status_consistency(self) -> None:
        executed, orig = self.executed_qty, self.orig_qty
        if self.status is OrderStatus.FILLED and executed != orig:
            raise DomainError("status FILLED exige executed_qty == orig_qty")
        if self.status in (OrderStatus.NEW, OrderStatus.REJECTED) and not executed.is_zero:
            raise DomainError(f"status {self.status} exige executed_qty == 0")
        if self.status is OrderStatus.PARTIALLY_FILLED and (executed.is_zero or executed == orig):
            raise DomainError("status PARTIALLY_FILLED exige 0 < executed_qty < orig_qty")

    @property
    def remaining_qty(self) -> Qty:
        return self.orig_qty - self.executed_qty


@dataclass(frozen=True, slots=True)
class Fill:
    """Execução (total ou parcial) de uma ordem. ``trade_id`` é único por símbolo."""

    trade_id: str
    client_order_id: ClientOrderId
    symbol: Symbol
    side: Side
    price: Price
    qty: Qty
    fee: Money
    executed_at: datetime
    liquidity: LiquidityRole

    def __post_init__(self) -> None:
        if not isinstance(self.trade_id, str) or not (0 < len(self.trade_id) <= _MAX_TRADE_ID_LEN):
            raise DomainError(f"trade_id inválido: {self.trade_id!r}")
        _expect(self.client_order_id, ClientOrderId, "client_order_id")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.side, Side, "side")
        _expect(self.price, Price, "price")
        _expect(self.qty, Qty, "qty")
        _expect(self.fee, Money, "fee")
        _expect(self.liquidity, LiquidityRole, "liquidity")
        if self.qty.is_zero:
            raise DomainError("Fill.qty deve ser > 0")
        if self.fee.is_negative:
            raise DomainError("Fill.fee não pode ser negativa")
        require_utc(self.executed_at, field="executed_at")

    @property
    def quote_qty(self) -> Decimal:
        """Valor bruto em moeda de cotação (preço x quantidade), antes de taxas."""
        with financial():
            return self.price.notional(self.qty)
