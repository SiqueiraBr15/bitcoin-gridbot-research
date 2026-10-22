from dataclasses import replace
from decimal import Decimal

import pytest

from gridbot.backtest.data import BacktestError
from gridbot.backtest.engine import run_backtest
from tests.backtest.test_engine import config, dataset


@pytest.mark.parametrize("high", ["100", "100.99"])
def test_benchmark_cannot_publish_adverse_fill_above_observed_high(high: str) -> None:
    settings = config()
    settings = replace(settings, policy=replace(settings.policy, spread=Decimal(".02")))
    market = dataset(("100,100,100,100,10", f"100,{high},100,100,10", "100,110,90,100,10"))
    before = market.raw
    with pytest.raises(BacktestError, match="benchmark execution price outside observed OHLC"):
        run_backtest(market, settings, code_commit="regression")
    assert market.raw == before


def test_benchmark_accepts_exact_high_boundary_without_price_clamping() -> None:
    settings = config()
    settings = replace(settings, policy=replace(settings.policy, spread=Decimal(".02")))
    market = dataset(("100,100,100,100,10", "100,101,100,100,10", "100,110,90,100,10"))
    a = run_backtest(market, settings, code_commit="regression")
    b = run_backtest(market, settings, code_commit="regression")
    assert a.benchmark_trades == b.benchmark_trades
    assert len(a.benchmark_trades) == 1
    assert a.benchmark_trades[0].price.value == Decimal("101")


def test_no_volume_does_not_become_an_impossible_benchmark_fill() -> None:
    settings = config()
    settings = replace(settings, policy=replace(settings.policy, spread=Decimal(".02")))
    market = dataset(("100,100,100,100,0", "100,100,100,100,0", "100,110,90,100,0"))
    result = run_backtest(market, settings, code_commit="regression")
    assert result.benchmark.fills == 0
    assert result.benchmark.available_quote == settings.initial_quote
