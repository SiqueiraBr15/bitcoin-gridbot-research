from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    ClientOrderId,
    DomainError,
    Fill,
    LiquidityRole,
    Money,
    OrderIntent,
    OrderSnapshot,
    OrderStatus,
    OrderType,
    Price,
    Qty,
    Side,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
COID = ClientOrderId("gb-1")


def make_intent(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "client_order_id": COID,
        "symbol": BTCUSDT,
        "side": Side.BUY,
        "order_type": OrderType.LIMIT_MAKER,
        "qty": Qty.parse("0.001"),
        "price": Price.parse("60000"),
        "created_at": T0,
        "grid_level": 3,
    }
    fields.update(overrides)
    return OrderIntent(**cast(Any, fields))


def make_snapshot(status: OrderStatus, executed: str, **overrides: object) -> OrderSnapshot:
    fields: dict[str, object] = {
        "client_order_id": COID,
        "symbol": BTCUSDT,
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "status": status,
        "price": Price.parse("60000"),
        "orig_qty": Qty.parse("0.002"),
        "executed_qty": Qty.parse(executed),
        "cumulative_quote_qty": Decimal(0),
        "updated_at": T0,
    }
    fields.update(overrides)
    return OrderSnapshot(**cast(Any, fields))


def make_fill(**overrides: object) -> Fill:
    fields: dict[str, object] = {
        "trade_id": "1001",
        "client_order_id": COID,
        "symbol": BTCUSDT,
        "side": Side.BUY,
        "price": Price.parse("60000.5"),
        "qty": Qty.parse("0.001"),
        "fee": Money.parse("0.000001", BTC),
        "executed_at": T0,
        "liquidity": LiquidityRole.MAKER,
    }
    fields.update(overrides)
    return Fill(**cast(Any, fields))


# ------------------------------------------------------------------ OrderIntent


def test_valid_limit_intent() -> None:
    intent = make_intent()
    assert intent.side is Side.BUY
    assert intent.price == Price.parse("60000")


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"qty": Qty.zero()}, DomainError),
        ({"price": None}, DomainError),
        ({"order_type": OrderType.MARKET}, DomainError),  # MARKET com preço
        ({"created_at": T0.replace(tzinfo=None)}, DomainError),
        ({"grid_level": -1}, DomainError),
        ({"grid_level": True}, DomainError),
        ({"side": "BUY"}, TypeError),  # string crua não substitui o enum
        ({"qty": Decimal("0.001")}, TypeError),
        ({"price": Decimal("60000")}, TypeError),
    ],
)
def test_invalid_intent_is_rejected(overrides: dict[str, object], error: type[Exception]) -> None:
    with pytest.raises(error):
        make_intent(**overrides)


def test_market_intent_without_price_is_valid() -> None:
    assert make_intent(order_type=OrderType.MARKET, price=None).price is None


# ------------------------------------------------------------------ OrderSnapshot


def test_snapshot_remaining_qty() -> None:
    snap = make_snapshot(OrderStatus.PARTIALLY_FILLED, "0.0005")
    assert snap.remaining_qty == Qty.parse("0.0015")


@pytest.mark.parametrize(
    ("status", "executed"),
    [
        (OrderStatus.FILLED, "0.001"),
        (OrderStatus.NEW, "0.001"),
        (OrderStatus.REJECTED, "0.001"),
        (OrderStatus.PARTIALLY_FILLED, "0"),
        (OrderStatus.PARTIALLY_FILLED, "0.002"),
        (OrderStatus.CANCELED, "0.003"),  # executado > original
    ],
)
def test_snapshot_status_must_match_executed_qty(status: OrderStatus, executed: str) -> None:
    with pytest.raises(DomainError):
        make_snapshot(status, executed)


@pytest.mark.parametrize(
    ("status", "executed"),
    [
        (OrderStatus.NEW, "0"),
        (OrderStatus.FILLED, "0.002"),
        (OrderStatus.CANCELED, "0.0007"),  # cancelada após fill parcial
        (OrderStatus.EXPIRED, "0"),
    ],
)
def test_snapshot_valid_states(status: OrderStatus, executed: str) -> None:
    assert make_snapshot(status, executed).status is status


def test_snapshot_rejects_negative_quote_and_naive_time() -> None:
    with pytest.raises(DomainError):
        make_snapshot(OrderStatus.NEW, "0", cumulative_quote_qty=Decimal("-1"))
    with pytest.raises(DomainError):
        make_snapshot(OrderStatus.NEW, "0", updated_at=T0.replace(tzinfo=None))


# ------------------------------------------------------------------ Fill


def test_fill_quote_qty_is_exact() -> None:
    assert make_fill().quote_qty == Decimal("60.0005")


@pytest.mark.parametrize(
    "overrides",
    [
        {"qty": Qty.zero()},
        {"fee": Money.parse("-0.01", USDT)},
        {"trade_id": ""},
        {"trade_id": "x" * 65},
        {"executed_at": T0.replace(tzinfo=None)},
    ],
)
def test_invalid_fill_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(DomainError):
        make_fill(**overrides)


def test_fill_requires_liquidity_role() -> None:
    with pytest.raises(TypeError):
        make_fill(liquidity=True)
    with pytest.raises(TypeError):
        make_fill(liquidity="MAKER")  # string crua não substitui o enum


def test_fill_fee_can_be_in_any_asset() -> None:
    fill = make_fill()
    assert replace(fill, fee=Money.parse("0.06", USDT)).fee.asset == USDT
