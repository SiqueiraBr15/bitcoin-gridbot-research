from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, Inexact
from typing import Any, cast

import pytest

from gridbot.backtest.data import BacktestError, Dataset
from gridbot.backtest.execution import (
    BNB,
    CausalClock,
    ExecutionPolicy,
    FeeModel,
    MixedPolicy,
    VirtualOrder,
    crossed,
    executable_quantity,
    selected_orders,
)
from gridbot.domain import BTC, USDT, Asset, FeeSchedule, LiquidityRole, Money, Price, Qty, Side
from gridbot.strategy import CellCycleRef
from tests.backtest.fixtures import rules
from tests.backtest.test_data import START, raw, spec


def policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        FeeModel(
            FeeSchedule.parse(".001", ".002"),
            LiquidityRole.MAKER,
            LiquidityRole.TAKER,
            USDT,
            USDT,
            None,
        ),
        Decimal("0"),
        Decimal("0"),
        Decimal(".5"),
        timedelta(0),
        3,
        False,
        MixedPolicy.DEFER_MIXED,
    )


def order(side: Side = Side.BUY, limit: str = "100") -> VirtualOrder:
    return VirtualOrder(
        "synthetic-order-" + side.value,
        CellCycleRef(0, 0),
        side,
        Price.parse(limit),
        Qty.parse(".1"),
        START - timedelta(minutes=1),
        START,
    )


def test_clock_and_same_bar_creation_never_look_back() -> None:
    candles = Dataset(raw(), spec()).series.candles
    clock = CausalClock()
    assert clock.now is None
    now = clock.advance(candles[0])
    created = replace(order(), created_at=now, activated_at=now)
    assert not crossed(created, candles[0], policy())
    assert crossed(created, candles[1], policy())
    late = replace(created, activated_at=now + timedelta(seconds=1))
    assert not crossed(late, candles[1], policy())
    assert crossed(late, candles[2], policy())
    with pytest.raises(BacktestError):
        clock.advance(candles[0])
    with pytest.raises(BacktestError):
        clock.advance(candles[2])


def test_touch_is_only_explicit_sensitivity_and_buffers_defer() -> None:
    candle = Dataset(raw(), spec()).series.candles[0]
    buy = order(limit="90")
    assert not crossed(buy, candle, policy())
    assert crossed(buy, candle, replace(policy(), allow_touch=True))
    assert not crossed(buy, candle, replace(policy(), allow_touch=True, spread=Decimal(".01")))
    sell = order(Side.SELL, "110")
    assert not crossed(sell, candle, policy())
    assert crossed(sell, candle, replace(policy(), allow_touch=True))
    assert not crossed(sell, candle, replace(policy(), allow_touch=True, slippage=Decimal(".01")))


@pytest.mark.parametrize(
    ("mixed", "expected"),
    [
        (MixedPolicy.DEFER_MIXED, ()),
        (MixedPolicy.BUY_PRIORITY, (Side.BUY,)),
        (MixedPolicy.SELL_PRIORITY, (Side.SELL,)),
    ],
)
def test_unknown_intrabar_sequence_does_not_execute_both(
    mixed: MixedPolicy, expected: tuple[Side, ...]
) -> None:
    candle = Dataset(raw(), spec()).series.candles[0]
    candidates, ambiguous = selected_orders(
        (order(), order(Side.SELL, "105")), candle, replace(policy(), mixed=mixed)
    )
    assert ambiguous
    assert tuple(o.side for o in candidates) == expected
    with pytest.raises(BacktestError, match="duplicate"):
        selected_orders((order(), order()), candle, policy())


@pytest.mark.parametrize("asset", [BTC, USDT, BNB])
def test_explicit_commission_asset_rate_and_role(asset: Asset) -> None:
    fees = replace(
        policy().fees, buy_asset=asset, sell_asset=asset, bnb_fee_price=Price.parse("100")
    )
    expected_buy = ".0001" if asset in (BTC, BNB) else ".01"
    expected_sell = ".0002" if asset in (BTC, BNB) else ".02"
    assert fees.commission(Side.BUY, Price.parse("100"), Qty.parse(".1")) == Money.parse(
        expected_buy, asset
    )
    assert fees.commission(Side.SELL, Price.parse("100"), Qty.parse(".1")) == Money.parse(
        expected_sell, asset
    )
    assert fees.commission(Side.BUY, Price.parse("100"), Qty.zero()).amount == 0


def test_no_silent_rounding_or_missing_bnb_price() -> None:
    with pytest.raises(BacktestError):
        replace(policy().fees, buy_asset=BNB)
    fees = replace(policy().fees, buy_asset=BNB, bnb_fee_price=Price.parse("3"))
    with pytest.raises(Inexact):
        fees.commission(Side.BUY, Price.parse("100"), Qty.parse(".1"))


def test_volume_is_explicit_step_floor_and_cannot_overfill() -> None:
    candle = Dataset(raw(), spec()).series.candles[0]
    assert policy().volume(candle, rules()) == Qty.parse("5")
    assert executable_quantity(order(), Qty.parse(".0345"), rules()) == Qty.parse(".034")
    assert executable_quantity(order(), Qty.parse("100"), rules()) == order().qty
    assert executable_quantity(order(), Qty.zero(), rules()).is_zero


@pytest.mark.parametrize(
    ("side", "values"), [(Side.BUY, "80,82,79,81,10"), (Side.SELL, "120,122,119,121,10")]
)
def test_gap_never_invents_a_limit_price_outside_the_observed_bar(side: Side, values: str) -> None:
    from tests.backtest.test_data import row

    candle = Dataset(raw(row(0, values)), spec(1)).series.candles[0]
    assert not crossed(order(side, "100"), candle, policy())
    assert not crossed(order(side, "100"), candle, replace(policy(), allow_touch=True))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ttl_bars", True),
        ("ttl_bars", 0),
        ("participation", Decimal("1.1")),
        ("spread", Decimal("-1")),
        ("slippage", Decimal("1")),
        ("latency", timedelta(seconds=-1)),
        ("allow_touch", 1),
    ],
)
def test_invalid_model_parameters(field: str, value: object) -> None:
    with pytest.raises((BacktestError, TypeError)):
        replace(policy(), **{field: cast(Any, value)})
