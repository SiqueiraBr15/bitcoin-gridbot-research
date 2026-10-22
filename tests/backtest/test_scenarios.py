from dataclasses import replace
from datetime import timedelta

import pytest

from gridbot.backtest.engine import compare_scenarios, run_backtest
from gridbot.backtest.execution import MixedPolicy
from gridbot.domain import Side
from tests.backtest.scenarios import MARKETS, market_case
from tests.backtest.test_engine import config, dataset
from tests.paper.simulation_oracle import assert_source_conservation


@pytest.mark.parametrize("name", tuple(MARKETS))
def test_market_behaviors_are_financially_conserved_not_profitability_claims(name: str) -> None:
    market, settings = market_case(name)
    result = run_backtest(market, settings, code_commit="synthetic-fixture")
    assert_source_conservation(result.sources, result.points[-1].state)
    for trade in result.trades:
        candle = next(c for c in market.series if c.open_time == trade.bar_open)
        assert candle.low <= trade.price <= candle.high
        assert trade.observed_at == candle.close_time
    if name in ("no_fill", "low_volatility", "strong_rise", "insufficient_capital"):
        assert not result.trades
    if name == "strong_rise":
        assert result.benchmark.final_equity is not None
        assert result.metrics.final_equity is not None
        assert result.benchmark.final_equity.amount > result.metrics.final_equity.amount
    if name == "strong_fall":
        assert result.metrics.return_pct is not None
        assert result.metrics.return_pct < 0
    if name == "partial":
        assert result.metrics.reserved_btc.value > 0
    if name == "multiple_levels":
        for candle in market.series:
            assert len({t.side for t in result.trades if t.observed_at == candle.close_time}) <= 1


def test_actual_intrabar_sensitivity_changes_fills_without_inventing_a_path() -> None:
    market = dataset(("100,110,90,105,10", "100,106,95,100,10", "100,111,89,105,10"))
    settings = config()
    variants = tuple(
        replace(settings, run_ref=f"SIM:MIXED_{i}", policy=replace(settings.policy, mixed=choice))
        for i, choice in enumerate(MixedPolicy)
    )
    results = compare_scenarios(market, variants, code_commit="hypotheses")
    assert [len(r.trades) for r in results] == [1, 2, 2]
    assert {t.side for t in results[1].trades} == {Side.BUY}
    assert {t.side for t in results[2].trades} == {Side.BUY, Side.SELL}
    assert len({r.metrics.final_grid_btc for r in results}) == 3
    assert all(any(d.kind == "OHLC_INTRABAR_PATH_UNKNOWN" for d in r.decisions) for r in results)


def test_latency_skips_ineligible_candle_and_benchmark_uses_eligible_open() -> None:
    market = dataset(("100,110,90,105,10", "100,106,89,95,10", "120,121,119,120,10"))
    settings = replace(config(), policy=replace(config().policy, latency=timedelta(seconds=1)))
    result = run_backtest(market, settings, code_commit="v")
    assert not result.trades
    assert result.benchmark_trades[0].price == market.series.candles[2].open
    assert result.benchmark_trades[0].bar_open == market.series.candles[2].open_time
    immediate = run_backtest(market, config(), code_commit="v")
    assert immediate.benchmark_trades[0].price == market.series.candles[1].open
    assert immediate.benchmark_trades[0].price != market.series.candles[1].close


def test_changing_future_close_cannot_change_initial_bootstrap_or_earlier_orders() -> None:
    prefix = ("100,110,90,95,10", "100,106,89,100,10")
    a = run_backtest(dataset((*prefix, "100,120,70,105,10")), config(), code_commit="v")
    b = run_backtest(dataset((*prefix, "100,120,70,80,10")), config(), code_commit="v")
    assert a.points[:2] == b.points[:2]
    assert a.sources.events[:3] == b.sources.events[:3]
    assert not a.sources.initial.grid_state.cells[1].buy_armed
    assert a.points[-1].price != b.points[-1].price
    assert a.benchmark.final_equity != b.benchmark.final_equity


def test_benchmark_filter_boundary_is_explicitly_unavailable_not_a_grid_win() -> None:
    from gridbot.backtest.export import comparison
    from gridbot.domain import Price

    market, settings = market_case("strong_rise")
    bounded = replace(
        settings,
        rules=replace(
            settings.rules, price=replace(settings.rules.price, max_price=Price.parse("110"))
        ),
    )
    result = run_backtest(market, bounded, code_commit="v")
    assert any(d.kind == "BENCHMARK_NATIVE_WITNESS_GEOMETRY_UNAVAILABLE" for d in result.decisions)
    assert comparison(result.metrics, result.benchmark)["status"] == "BENCHMARK_NOT_EXECUTED"
