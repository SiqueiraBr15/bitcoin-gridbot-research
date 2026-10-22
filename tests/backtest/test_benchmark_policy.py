from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from gridbot.backtest.engine import run_backtest
from gridbot.backtest.execution import BNB
from gridbot.domain import BTC, USDT, Asset, LiquidityRole, Money, Price
from tests.backtest.test_engine import config, dataset


@pytest.mark.parametrize("asset", [BTC, USDT, BNB])
def test_market_benchmark_uses_taker_while_grid_keeps_maker(asset: Asset) -> None:
    cfg = config()
    cfg = replace(
        cfg,
        policy=replace(
            cfg.policy,
            fees=replace(cfg.policy.fees, buy_asset=asset, bnb_fee_price=Price.parse("100")),
        ),
        third_asset_funding=(Money.parse("1", BNB),),
        bnb_mark=Price.parse("100"),
    )
    result = run_backtest(dataset(), cfg, code_commit="v")
    trade = result.benchmark_trades[0]
    assert trade.liquidity is LiquidityRole.TAKER
    base = Fraction(trade.qty.value)
    expected = base * Fraction(cfg.policy.fees.schedule.taker_rate)
    if asset == USDT:
        expected *= Fraction(trade.price.value)
    if asset == BNB:
        expected *= Fraction(trade.price.value) / 100
    assert Fraction(trade.fee.amount) == expected
    assert all(t.liquidity is LiquidityRole.MAKER for t in result.trades if t.side.value == "BUY")


def test_open_after_latency_slippage_and_future_extrema_do_not_select_execution() -> None:
    cfg = config()
    cfg = replace(
        cfg,
        policy=replace(
            cfg.policy,
            latency=timedelta(seconds=1),
            spread=Decimal(".01"),
            slippage=Decimal(".005"),
        ),
    )
    market = dataset(("100,110,90,105,10", "120,200,80,130,10", "100,110,90,101,10"))
    result = run_backtest(market, cfg, code_commit="v")
    trade = result.benchmark_trades[0]
    assert trade.bar_open == market.series.candles[2].open_time
    assert trade.price == Price.parse("101")
    alternate = dataset(("100,110,90,105,10", "120,200,80,130,10", "100,300,1,250,10"))
    other = run_backtest(alternate, cfg, code_commit="v")
    assert other.benchmark_trades == result.benchmark_trades


@pytest.mark.parametrize(
    ("opened", "high", "expected"),
    [
        ("42613.57", "42638.41", "42656.19"),
        ("16551.47", "16559.77", "16568.03"),
    ],
)
def test_two_historical_b_counterexamples_remain_refused(
    opened: str, high: str, expected: str
) -> None:
    from gridbot.backtest.data import BacktestError

    cfg = config()
    cfg = replace(
        cfg, policy=replace(cfg.policy, spread=Decimal(".001"), slippage=Decimal(".0005"))
    )
    market = dataset(
        ("100,110,90,105,10", f"{opened},{high},{opened},{opened},10", "100,110,90,105,10")
    )
    with pytest.raises(BacktestError, match="outside observed OHLC"):
        run_backtest(market, cfg, code_commit="v")
    assert cfg.rules.price.ceil(Price(Decimal(opened) * Decimal("1.001"))) == Price.parse(expected)
