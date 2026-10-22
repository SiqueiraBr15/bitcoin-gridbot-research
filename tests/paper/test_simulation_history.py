from dataclasses import replace

import pytest

from gridbot.domain import USDT, Money
from gridbot.paper.accounting import PaperApplySell, PaperError, PaperObserveSell, PaperSettleBuy
from gridbot.paper.simulation import PaperSimulation, SimulationError, SimulationErrorCode
from tests.paper.simulation_fixtures import buy_command, buy_fill_result, sell_source
from tests.paper.simulation_oracle import assert_source_conservation
from tests.paper.test_simulation import ready


def test_thousand_real_memory_transitions_preserve_all_prefix_boundaries_and_identities() -> None:
    sim, execution = ready(1000)
    observation = PaperObserveSell(sell_source(sim, execution, status=None))
    checkpoints = {255, 256, 257, 500, 1000}
    for expected in range(3, 1000):
        assert sim.apply(expected, observation) == expected + 1
        if sim.revision in checkpoints:
            assert sim.settled_sell_proceeds == Money.zero(USDT)
            assert sim.grid_state.cells[0].cycle_seq == 0
            assert sim.sell_authorization(execution).revision == 3
    log = sim.source_log()
    assert len(log.events) == 1000
    assert [e.revision for e in log.events] == list(range(1, 1001))
    assert_source_conservation(log, sim.snapshot())
    prefix = replace(log, events=log.events[:257], revision=257)
    continued = PaperSimulation.replay(prefix, run_ref=sim.run_ref, max_events=1000)
    for event in log.events[257:]:
        continued.apply(event.revision - 1, event.command)
    assert continued.source_log() == log
    assert continued.snapshot() == sim.snapshot()
    before = continued.snapshot()
    with pytest.raises(SimulationError) as error:
        continued.apply(1000, observation)
    assert error.value.code is SimulationErrorCode.CAPACITY_EXCEEDED
    assert continued.snapshot() == before
    with pytest.raises(PaperError):
        sim.apply(999, PaperApplySell(execution, 1000))


def test_settlement_after_long_pending_prefix_can_fund_next_buy_without_reset() -> None:
    sim, execution = ready(300)
    unknown = PaperObserveSell(sell_source(sim, execution, status=None))
    for revision in range(3, 260):
        sim.apply(revision, unknown)
    before = sim.available_quote
    sim.apply(260, PaperObserveSell(sell_source(sim, execution)))
    assert sim.available_quote == before
    sim.apply(261, PaperApplySell(execution, 261))
    assert sim.grid_state.cells[0].cycle_seq == 1
    assert sim.settled_sell_proceeds.amount > 0
    sim.apply(262, buy_command(sim))
    sim.apply(263, PaperSettleBuy(buy_fill_result(sim)))
    assert sim.revision == 264
    assert_source_conservation(sim.source_log(), sim.snapshot())
