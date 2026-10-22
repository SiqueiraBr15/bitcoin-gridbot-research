"""P2 must preserve real native residual/partial origins; copied into final test cohort."""

from dataclasses import replace
from typing import cast

import pytest

from gridbot.backtest.data import Dataset
from gridbot.backtest.engine import _Runner
from gridbot.backtest.execution import BNB
from gridbot.backtest.lifecycle import RangeCandidate, plan_recenter
from gridbot.domain import BTC, USDT, Asset, FeeSchedule, Price
from gridbot.paper.accounting import PaperCommand, PaperError
from gridbot.paper.simulation import PaperSimulation
from gridbot.strategy import build_arithmetic_grid
from tests.backtest.test_interruption import runner
from tests.paper.simulation_oracle import assert_source_conservation


@pytest.mark.parametrize("asset", [BTC, USDT, BNB])
@pytest.mark.parametrize("partial", ["BUY", "SELL"])
def test_blocked_recenter_keeps_partial_origins_cost_residual_reservations_and_identity(
    asset: Asset, partial: str
) -> None:
    initial = runner(asset)
    market = initial.dataset
    if partial == "BUY":
        market = Dataset(
            market.raw.replace(b"100,106,89,100,10", b"100,106,89,100,.01"), market.spec
        )
    cfg = replace(
        initial.config,
        policy=replace(
            initial.config.policy,
            fees=replace(initial.config.policy.fees, schedule=FeeSchedule.parse(".001", ".001")),
        ),
    )
    runtime = _Runner(market, cfg, "partial-recenter-regression")
    bars = market.series.candles
    runtime.schedule(bars[0])
    runtime.execute(bars[1])
    runtime.schedule(bars[1])
    if partial == "SELL":
        runtime.execute(bars[2])
        runtime.schedule(bars[2])
    before = runtime.sim.snapshot()
    sources = runtime.sim.source_log()
    pending = tuple(runtime.pending.items())
    assert before.remaining_grid_base.value > 0
    if partial == "SELL":
        assert before.reserved_grid_base.value > 0
    else:
        assert before.active_buy_reservations.amount > 0
        # This tiny partial BUY cannot admit a new SELL below minNotional.
        assert any(d.kind == "SELL_SIZING_INELIGIBLE" for d in runtime.decisions)
    assert any(d.detail == "PARTIAL_CANCELED" for d in runtime.decisions)
    known_bar = replace(
        bars[3],
        open=Price.parse("120"),
        high=Price.parse("120"),
        low=Price.parse("120"),
        close=Price.parse("120"),
    )
    candidate = RangeCandidate(known_bar, build_arithmetic_grid(cfg.grid, cfg.rules), 168)
    plan = plan_recenter(candidate, cfg.rules)
    assert not plan.executable
    assert plan == plan_recenter(candidate, cfg.rules)
    with pytest.raises(PaperError, match="closed PAPER command set"):
        runtime.sim.apply(runtime.sim.revision, cast(PaperCommand, plan))
    assert runtime.sim.snapshot() == before
    assert runtime.sim.source_log() == sources
    assert tuple(runtime.pending.items()) == pending
    assert runtime.sim.buy_spending == before.buy_spending
    replay = PaperSimulation.replay(sources, run_ref=runtime.sim.run_ref, max_events=4000)
    assert replay.snapshot() == before
    assert_source_conservation(sources, before)
