from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.backtest.data import HEADER, BacktestError, Dataset
from gridbot.backtest.engine import _Runner, run_backtest
from gridbot.backtest.execution import BNB
from gridbot.backtest.interruption import (
    InterruptionWindow,
    MarketEvent,
    SuspensionGate,
    capture,
)
from gridbot.domain import BTC, USDT, Asset, Money, Price
from gridbot.domain.errors import InvalidCandleError
from gridbot.paper.simulation import PaperSimulation
from tests.backtest.test_data import spec
from tests.backtest.test_engine import config
from tests.paper.simulation_oracle import assert_source_conservation

HALT = datetime(2023, 3, 24, 11, 27, tzinfo=UTC)
RESUME = datetime(2023, 3, 24, 14, tzinfo=UTC)


def window() -> InterruptionWindow:
    return InterruptionWindow(HALT, RESUME, "Binance official 2023-03-24 incident; synthetic test")


def runner(asset: Asset = USDT) -> _Runner:
    start = HALT - timedelta(minutes=7)
    rows = []
    for i, value in enumerate(
        ("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,.01", "110,120,80,100,10")
    ):
        opened = start + timedelta(minutes=i)
        rows.append(f"{opened.isoformat()},{(opened + timedelta(minutes=1)).isoformat()},{value}\n")
    market = Dataset(
        (",".join(HEADER) + "\n" + "".join(rows)).encode(),
        replace(spec(4), start=start, end=start + timedelta(minutes=4)),
    )
    cfg = config()
    fees = replace(
        cfg.policy.fees, buy_asset=asset, sell_asset=asset, bnb_fee_price=Price.parse("100")
    )
    cfg = replace(
        cfg,
        effective_start=start,
        effective_end=RESUME + timedelta(days=1),
        policy=replace(cfg.policy, fees=fees),
        third_asset_funding=(Money.parse("1", BNB),),
        bnb_mark=Price.parse("100"),
    )
    return _Runner(market, cfg, "synthetic")


def gate_for(runtime: _Runner, at: datetime) -> SuspensionGate:
    orders = tuple((o, runtime.ages[o.ref]) for o in runtime.pending.values())
    frozen = capture(runtime.sim, orders, at, Price.parse("100"))
    return SuspensionGate(window(), frozen)


@pytest.mark.parametrize("asset", [BTC, USDT, BNB])
@pytest.mark.parametrize("stage", [0, 1, 2])
def test_halt_preserves_complete_financial_sources_and_reservations(
    asset: Asset, stage: int
) -> None:
    runtime = runner(asset)
    bars = runtime.dataset.series.candles
    runtime.schedule(bars[0])
    for bar in bars[1 : stage + 1]:
        runtime.execute(bar)
        runtime.schedule(bar)
    gate = gate_for(runtime, bars[stage].close_time)
    before = runtime.sim.snapshot()
    if stage == 0:
        assert before.active_buy_reservations.amount > 0
    if stage > 0:
        assert before.remaining_grid_base.value > 0
    if stage == 2 and asset != BTC:
        assert before.reserved_grid_base.value > 0
        assert any(d.detail == "PARTIAL_CANCELED" for d in runtime.decisions)
    paused = gate.transition(MarketEvent.MARKET_TRADING_SUSPENDED, HALT)
    resumed = paused.transition(MarketEvent.MARKET_TRADING_RESUMED, RESUME)
    assert paused.frozen == resumed.frozen == gate.frozen
    assert resumed.frozen.snapshot == before == runtime.sim.snapshot()
    assert paused.execution_state == "SUSPENDED_ORDER_EXECUTION_UNKNOWN"
    assert resumed.execution_state == "RESUMED_RECONCILIATION_REQUIRED"
    assert resumed.transition(MarketEvent.MARKET_TRADING_RESUMED, RESUME) is resumed
    assert resumed.transition(MarketEvent.MARKET_TRADING_SUSPENDED, HALT) is resumed
    replay = PaperSimulation.replay(
        resumed.frozen.sources, run_ref=runtime.sim.run_ref, max_events=runtime.sim.max_events
    )
    assert replay.snapshot() == before
    assert_source_conservation(resumed.frozen.sources, replay.snapshot())
    assert tuple(age for _, age in resumed.frozen.orders) == tuple(runtime.ages.values())


def test_overlapping_hour_and_missing_hours_never_become_fills_or_signals() -> None:
    runtime = runner()
    bar = runtime.dataset.series.candles[0]
    gate = gate_for(runtime, bar.close_time)
    before = replace(bar, open_time=HALT - timedelta(minutes=1), close_time=HALT)
    during = replace(bar, open_time=HALT, close_time=HALT + timedelta(minutes=1))
    after = replace(bar, open_time=RESUME, close_time=RESUME + timedelta(minutes=1))
    assert gate.permits(before)
    assert not gate.permits(during)
    assert not gate.permits(after)
    resumed = gate.transition(MarketEvent.MARKET_TRADING_SUSPENDED, HALT).transition(
        MarketEvent.MARKET_TRADING_RESUMED, RESUME
    )
    assert not resumed.permits(after)
    assert resumed.frozen.mark_at == bar.close_time
    assert resumed.frozen.mark == gate.frozen.mark
    with pytest.raises(InvalidCandleError):
        replace(bar, close_time=bar.close_time - timedelta(seconds=1))
    # Even structurally valid OHLC spanning the halt is refused in its entirety.
    crossing = replace(
        bar, open_time=HALT - timedelta(seconds=30), close_time=HALT + timedelta(seconds=30)
    )
    assert not gate.permits(crossing)


def test_pending_identity_terms_age_and_future_mark_are_not_inferred() -> None:
    runtime = runner()
    bar = runtime.dataset.series.candles[0]
    runtime.schedule(bar)
    orders = tuple((o, 0) for o in runtime.pending.values())
    with pytest.raises(BacktestError, match="omitted"):
        capture(runtime.sim, (), bar.close_time, bar.close)
    with pytest.raises(BacktestError, match="duplicate"):
        capture(runtime.sim, (*orders, orders[0]), bar.close_time, bar.close)
    with pytest.raises(BacktestError, match="terms"):
        capture(
            runtime.sim,
            ((replace(orders[0][0], limit=Price.parse("1")), 0), *orders[1:]),
            bar.close_time,
            bar.close,
        )
    with pytest.raises(BacktestError, match="age"):
        capture(runtime.sim, ((orders[0][0], -1), *orders[1:]), bar.close_time, bar.close)
    gate = gate_for(runtime, bar.close_time)
    with pytest.raises(BacktestError, match="future mark"):
        replace(gate, frozen=replace(gate.frozen, mark_at=RESUME))
    with pytest.raises(BacktestError, match="requires suspension"):
        gate.transition(MarketEvent.MARKET_TRADING_RESUMED, RESUME)
    with pytest.raises(BacktestError, match="documented"):
        gate.transition(MarketEvent.MARKET_TRADING_SUSPENDED, HALT + timedelta(seconds=1))


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(min_value=1, max_value=152))
def test_every_minute_of_suspension_is_closed_and_segmentation_equivalent(minute: int) -> None:
    runtime = runner()
    bar = runtime.dataset.series.candles[0]
    gate = gate_for(runtime, bar.close_time)
    paused = gate.transition(MarketEvent.MARKET_TRADING_SUSPENDED, HALT)
    at = HALT + timedelta(minutes=minute)
    assert not paused.permits(replace(bar, open_time=at, close_time=at + timedelta(minutes=1)))
    # Segment boundary retains the same object/state; no rebootstrap or command is introduced.
    direct = paused.transition(MarketEvent.MARKET_TRADING_RESUMED, RESUME)
    segmented = replace(paused).transition(MarketEvent.MARKET_TRADING_RESUMED, RESUME)
    assert direct == segmented
    assert direct.frozen.sources.revision == 0


def test_historical_runner_still_blocks_unapproved_gap_continuity() -> None:
    runtime = runner()
    raw = runtime.dataset.raw.splitlines(keepends=True)
    missing = Dataset(b"".join([raw[0], *raw[1:3], raw[4]]), runtime.dataset.spec)
    with pytest.raises(BacktestError, match="gaps/missing"):
        run_backtest(missing, runtime.config, code_commit="v")
