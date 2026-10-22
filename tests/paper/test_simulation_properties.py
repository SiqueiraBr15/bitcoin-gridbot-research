from collections import Counter
from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus, Qty
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperCommand,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
    paper_transition,
)
from gridbot.paper.simulation import PaperSimulation
from tests.paper.fixtures import initial
from tests.paper.simulation_fixtures import buy_command, buy_fill_result, sell_command, sell_source
from tests.paper.simulation_oracle import assert_source_conservation
from tests.paper.test_simulation import ready

COUNTS: Counter[str] = Counter()


@settings(max_examples=6, derandomize=True, deadline=None)
@given(asset=st.sampled_from([BTC, USDT, Asset("BNB")]), full=st.booleans())
def test_generated_commands_have_exact_equivalence_with_full_reconstruction(
    asset: Asset, full: bool
) -> None:
    COUNTS["differential"] += 1
    book = initial()
    sim = PaperSimulation(book.initial, run_ref="SIM:generated", max_events=30)

    def drive(command: PaperCommand) -> None:
        nonlocal book
        revision = book.revision
        book = paper_transition(book, revision, command)
        sim.apply(revision, command)
        assert sim.grid_state == book.grid_state
        assert sim.available_quote == book.available_quote
        assert sim.buy_spending == book.buy_spending
        assert sim.settled_sell_proceeds == book.settled_sell_proceeds
        assert sim.remaining_grid_base == book.remaining_grid_base
        assert sim.reserved_grid_base == book.reserved_grid_base

    drive(buy_command(book))
    drive(PaperSettleBuy(buy_fill_result(book)))
    prepare = sell_command(book)
    drive(prepare)
    source = sell_source(
        book,
        prepare.execution_ref,
        status=OrderStatus.FILLED if full else OrderStatus.CANCELED,
        qty=None if full else Qty.parse(".015"),
        fees=(Money.parse(".00004", asset),),
    )
    drive(PaperObserveSell(source))
    drive(PaperApplySell(prepare.execution_ref, sim.revision))
    assert_source_conservation(sim.source_log(), sim.snapshot())


@settings(max_examples=12, derandomize=True, deadline=None)
@given(
    asset=st.sampled_from([BTC, USDT, Asset("BNB")]),
    qty=st.sampled_from([".015", ".030", ".031"]),
    zero=st.booleans(),
)
def test_exact_conservation_multifee_duplicate_and_replay(
    asset: Asset, qty: str, zero: bool
) -> None:
    COUNTS["fees_conservation"] += 1
    sim, execution = ready()
    status = OrderStatus.FILLED if qty == ".031" else OrderStatus.CANCELED
    fee = Money.zero(asset) if zero else Money.parse(".00004", asset)
    sim.apply(
        sim.revision,
        PaperObserveSell(
            sell_source(sim, execution, qty=Qty.parse(qty), status=status, fees=(fee,))
        ),
    )
    apply = PaperApplySell(execution, sim.revision)
    sim.apply(sim.revision, apply)
    before = sim.snapshot()
    assert sim.apply(sim.revision, apply) == before.revision
    log = sim.source_log()
    assert_source_conservation(log, before)
    restored = PaperSimulation.replay(log, run_ref=sim.run_ref, max_events=1000)
    assert restored.snapshot() == before
    assert restored.source_log() == log


@settings(max_examples=6, derandomize=True, deadline=None)
@given(count=st.integers(min_value=1, max_value=4), boundary=st.integers(min_value=0, max_value=20))
def test_prefix_replay_and_continuation_preserve_sources_and_result(
    count: int, boundary: int
) -> None:
    COUNTS["segments"] += 1
    sim, execution = ready()
    for cycle in range(count):
        if cycle:
            sim.apply(sim.revision, buy_command(sim))
            sim.apply(sim.revision, PaperSettleBuy(buy_fill_result(sim)))
            prepare = sell_command(sim)
            execution = prepare.execution_ref
            sim.apply(sim.revision, prepare)
        sim.apply(sim.revision, PaperObserveSell(sell_source(sim, execution)))
        sim.apply(sim.revision, PaperApplySell(execution, sim.revision))
    log = sim.source_log()
    cut = min(boundary, log.revision)
    prefix = replace(log, events=log.events[:cut], revision=cut)
    resumed = PaperSimulation.replay(prefix, run_ref=sim.run_ref, max_events=1000)
    for event in log.events[cut:]:
        resumed.apply(event.revision - 1, event.command)
    assert resumed.snapshot() == sim.snapshot()
    assert resumed.source_log() == log
    assert_source_conservation(log, sim.snapshot())


class IncrementalPaperMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        COUNTS["sequences"] += 1
        self.sim, self.execution = ready()
        self.source = sell_source(
            self.sim, self.execution, status=OrderStatus.CANCELED, qty=Qty.zero()
        )
        self.sim.apply(self.sim.revision, PaperObserveSell(self.source))
        self.apply = PaperApplySell(self.execution, self.sim.revision)
        self.sim.apply(self.sim.revision, self.apply)

    @rule()
    def duplicate(self) -> None:
        COUNTS["duplicate"] += 1
        before = self.sim.snapshot()
        self.sim.apply(self.sim.revision, self.apply)
        assert self.sim.snapshot() == before

    @rule()
    def restart_from_retained_sources(self) -> None:
        COUNTS["restart"] += 1
        self.sim = PaperSimulation.replay(
            self.sim.source_log(), run_ref=self.sim.run_ref, max_events=1000
        )

    @rule()
    def observe(self) -> None:
        COUNTS["observe"] += 1
        self.sim.apply(self.sim.revision, PaperObserveSell(self.source))

    @rule()
    def release(self) -> None:
        COUNTS["release"] += 1
        self.sim.apply(self.sim.revision, PaperReleaseNoFill(self.execution))

    @invariant()
    def conserve(self) -> None:
        COUNTS["invariants"] += 1
        assert_source_conservation(self.sim.source_log(), self.sim.snapshot())
        assert self.sim.grid_state.cells[0].cycle_seq == 0


TestIncrementalPaperMachine = IncrementalPaperMachine.TestCase
TestIncrementalPaperMachine.settings = settings(
    max_examples=4, stateful_step_count=6, derandomize=True, deadline=None
)
