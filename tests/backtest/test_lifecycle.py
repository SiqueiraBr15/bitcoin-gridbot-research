from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.backtest.data import BacktestError
from gridbot.backtest.engine import run_backtest
from gridbot.backtest.export import json_value
from gridbot.backtest.lifecycle import RangeCandidate, RangeObserver, plan_recenter
from gridbot.domain import BTCUSDT, Price
from gridbot.strategy import ArithmeticGridSpec, build_arithmetic_grid
from tests.backtest.test_engine import config, dataset


def observer(threshold: int = 2) -> RangeObserver:
    cfg = config()
    return RangeObserver(build_arithmetic_grid(cfg.grid, cfg.rules), threshold)


def test_candidate_exact_threshold_once_duplicate_and_reentry() -> None:
    candles = dataset(("120,120,120,120,10",) * 7).series.candles
    state = observer()
    state, event = state.observe(candles[0])
    assert event is None
    state, event = state.observe(candles[1])
    assert event is not None
    assert event.candle.close == Price.parse("120")
    assert state.observe(candles[1]) == (state, None)
    state, event = state.observe(candles[2])
    assert event is None
    inside = replace(
        candles[3],
        open=Price.parse("110"),
        low=Price.parse("110"),
        high=Price.parse("110"),
        close=Price.parse("110"),
    )
    state, event = state.observe(inside)
    assert state.consecutive == 0
    assert event is None
    state, event = state.observe(candles[4])
    assert event is None
    state, event = state.observe(candles[5])
    assert event is not None


def test_missing_bar_resets_streak_and_conflicting_duplicate_refused() -> None:
    candles = dataset(("120,120,120,120,10",) * 4).series.candles
    state, _ = observer().observe(candles[0])
    state, event = state.observe(candles[2])
    assert state.consecutive == 1
    assert event is None
    with pytest.raises(BacktestError, match="duplicate/conflicting"):
        state.observe(replace(candles[2], volume=candles[0].volume + candles[0].volume))
    with pytest.raises(BacktestError):
        state.observe(candles[0])


@pytest.mark.parametrize("threshold", [0, True, 100001])
def test_invalid_threshold(threshold: int) -> None:
    with pytest.raises(BacktestError):
        observer(threshold)


def test_recenter_never_executes_or_erases_inventory_or_changes_cost() -> None:
    market, cfg = dataset(), config()
    result = run_backtest(market, cfg, code_commit="v")
    before = result.sources
    candle = dataset(("120,120,120,120,10",)).series.candles[0]
    state, candidate = observer(1).observe(candle)
    assert candidate is not None
    plan = plan_recenter(candidate, cfg.rules)
    assert not plan.executable
    assert plan.proposed is not None
    assert plan.proposed.spec.lower_price == Price.parse("110")
    assert plan.proposed.spec.upper_price == Price.parse("130")
    assert plan.blockers == ("NO_ATOMIC_GEOMETRY_AND_SOURCE_MIGRATION_COMMAND",)
    assert plan == plan_recenter(candidate, cfg.rules)
    assert result.sources == before
    assert state.grid == observer().grid


def test_invalid_proposed_geometry_blocks_without_selling_residual() -> None:
    candle = dataset(("1,1,1,1,10",)).series.candles[0]
    candidate = RangeCandidate(candle, observer().grid, 168)
    result = plan_recenter(candidate, config().rules)
    assert not result.executable
    assert result.proposed is None
    assert "PROPOSED_GEOMETRY_INVALID" in result.blockers


def test_candidate_inside_range_and_wrong_rules_refused() -> None:
    with pytest.raises(BacktestError, match="outside"):
        RangeCandidate(dataset().series.candles[0], observer().grid, 1)
    candle = dataset(("120,120,120,120,10",)).series.candles[0]
    candidate = RangeCandidate(candle, observer().grid, 1)
    rules = config().rules
    with pytest.raises(BacktestError, match="mismatch"):
        plan_recenter(
            candidate, replace(rules, price=replace(rules.price, tick_size=Price.parse(".02")))
        )


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.lists(st.booleans(), min_size=1, max_size=40), st.integers(min_value=1, max_value=10))
def test_prefix_causality_segment_equivalence_and_independent_streak(
    flags: list[bool], threshold: int
) -> None:
    values = tuple("120,120,120,120,0" if f else "100,100,100,100,0" for f in flags)
    bars = dataset(values).series.candles
    state = observer(threshold)
    streak = 0
    emitted = []
    for i, bar in enumerate(bars):
        streak = streak + 1 if flags[i] else 0
        state, event = state.observe(bar)
        assert state.consecutive == streak
        assert (event is not None) == (streak == threshold)
        emitted.append(event)
        prefix = observer(threshold)
        prefix_events = []
        for known in bars[: i + 1]:
            prefix, found = prefix.observe(known)
            prefix_events.append(found)
        assert prefix == state
        assert prefix_events == emitted


def test_observation_has_no_financial_effect_even_with_partial_sale_and_fees() -> None:
    market = dataset(("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,.01"))
    a = run_backtest(market, config(), code_commit="v")
    state = observer(1)
    for bar in market.series:
        state, _ = state.observe(bar)
    b = run_backtest(market, config(), code_commit="v")
    assert a == b
    assert a.metrics.reserved_btc.value > 0
    assert all(c.cycle_seq == 0 for c in b.points[-1].state.grid_state.cells)


def test_geometry_preserves_width_and_interval_count_for_odd_count() -> None:
    cfg = config()
    grid = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse("90"), Price.parse("120"), 3), cfg.rules
    )
    bar = dataset(("150,150,150,150,0",)).series.candles[0]
    candidate = RangeCandidate(bar, grid, 1)
    plan = plan_recenter(candidate, cfg.rules)
    assert plan.proposed is not None
    assert plan.proposed.spec.lower_price.value == Decimal("140")
    assert plan.proposed.spec.upper_price.value == Decimal("170")
    assert plan.proposed.spec.interval_count == 3
    with pytest.raises(BacktestError, match="past"):
        RangeObserver(grid, 1, 1, bar).observe(
            replace(
                bar,
                open_time=bar.open_time - timedelta(minutes=1),
                close_time=bar.close_time - timedelta(minutes=1),
            )
        )


def test_p1_candidate_diagnostic_exports_without_serializing_timeframe_duration() -> None:
    import json

    from scripts.a19_3_study import lifecycle_diagnostics

    market = dataset(("120,120,120,120,10",) * 169)
    result = run_backtest(market, config(), code_commit="diagnostic-regression")
    diagnostic = lifecycle_diagnostics(market, result, "P1")
    encoded = json_value(diagnostic)
    parsed = json.loads(json.dumps(encoded))
    assert len(parsed["candidates"]) == 1
    assert parsed["candidates"][0]["consecutive"] == 168
    assert parsed["p2_plans"][0]["executable"] is False
    fractions = [
        Fraction(parsed[key]["numerator"], parsed[key]["denominator"])
        for key in ("cash_time_fraction", "buy_hold_time_fraction", "btc_time_fraction")
    ]
    assert sum(fractions) == 1
    assert 0 < fractions[0] < 1  # Pending BUY holds occupy cash before TTL, even without fills.
    assert fractions[2] == 0
