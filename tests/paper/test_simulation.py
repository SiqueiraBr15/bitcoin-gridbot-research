"""Incremental ownership, atomicity, identity and resource contracts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus, Qty
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperBook,
    PaperCommand,
    PaperError,
    PaperErrorCode,
    PaperInitialState,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperReleaseNoFill,
    PaperSettleBuy,
    _apply,
    _Frame,
    paper_transition,
)
from gridbot.paper.simulation import (
    PaperSimulation,
    SimulationError,
    SimulationErrorCode,
    SimulationEvent,
    SimulationLog,
)
from gridbot.storage.financial_codec import encode_contract
from tests.paper.fixtures import initial
from tests.paper.simulation_fixtures import buy_command, buy_fill_result, sell_command, sell_source
from tests.paper.simulation_oracle import assert_source_conservation


def runtime(limit: int = 1000) -> PaperSimulation:
    return PaperSimulation(initial().initial, run_ref="SIM:test", max_events=limit)


def ready(limit: int = 1000) -> tuple[PaperSimulation, SellExecutionRef]:
    sim = runtime(limit)
    sim.apply(sim.revision, buy_command(sim))
    sim.apply(sim.revision, PaperSettleBuy(buy_fill_result(sim)))
    command = sell_command(sim)
    sim.apply(sim.revision, command)
    return sim, command.execution_ref


def apply_full(sim: PaperSimulation, execution: SellExecutionRef) -> PaperApplySell:
    sim.apply(sim.revision, PaperObserveSell(sell_source(sim, execution)))
    command = PaperApplySell(execution, sim.revision)
    sim.apply(sim.revision, command)
    return command


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 10001])
def test_capacity_budget_is_explicit_bounded_native_integer(limit: object) -> None:
    with pytest.raises(SimulationError) as error:
        runtime(cast(int, limit))
    assert error.value.code is SimulationErrorCode.INVALID_INPUT


@pytest.mark.parametrize("run_ref", ["LIVE:test", "PAPER:test", "SIM:", "SIM:x\n", 1])
def test_declared_run_namespace_is_not_a_mode_switch(run_ref: object) -> None:
    with pytest.raises(SimulationError):
        PaperSimulation(initial().initial, run_ref=cast(str, run_ref), max_events=10)


def test_constructor_and_ingress_have_no_alias_to_caller() -> None:
    source = initial().initial
    sim = PaperSimulation(source, run_ref="SIM:owned", max_events=20)
    object.__setattr__(source.initial_quote, "amount", Money.parse("999", USDT).amount)
    assert sim.available_quote == Money.parse("20", USDT)
    command = buy_command(sim)
    sim.apply(0, command)
    before = sim.snapshot()
    object.__setattr__(command.quote_fee_hold, "amount", Money.parse("999", USDT).amount)
    object.__setattr__(command.execution_ref, "value", "LIVE:changed")
    assert sim.snapshot() == before
    assert (
        PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=20).snapshot()
        == before
    )


def test_all_detached_views_cannot_mutate_internal_sources() -> None:
    sim, execution = ready()
    command = apply_full(sim, execution)
    before = sim.snapshot()
    for money in [sim.available_quote, sim.buy_spending, sim.settled_sell_proceeds]:
        object.__setattr__(money, "amount", Money.parse("999", USDT).amount)
    object.__setattr__(sim.remaining_grid_base, "value", Qty.parse("999").value)
    object.__setattr__(sim.initial.initial_quote, "amount", Money.parse("999", USDT).amount)
    object.__setattr__(sim.grid_state.cells[0], "cycle_seq", 999)
    auth = sim.sell_authorization(execution)
    object.__setattr__(auth.identity, "account_ref", "LIVE:changed")
    log = sim.source_log()
    first = log.events[0].command
    assert isinstance(first, PaperPrepareBuy)
    object.__setattr__(first.execution_ref, "value", "LIVE:changed")
    assert sim.snapshot() == before
    assert sim.apply(sim.revision, command) == sim.revision


def test_buy_context_is_detached() -> None:
    sim = runtime()
    command = buy_command(sim)
    sim.apply(0, command)
    context = sim.buy_context(command.cycle_ref)
    object.__setattr__(context.execution_ref, "value", "LIVE:changed")
    assert sim.buy_context(command.cycle_ref).execution_ref == command.execution_ref


@pytest.mark.parametrize("failure", [RuntimeError, MemoryError])
def test_late_failure_does_not_publish_any_part_of_next_head(
    monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    sim, execution = ready()
    sim.apply(sim.revision, PaperObserveSell(sell_source(sim, execution)))
    before, log = sim.snapshot(), sim.source_log()

    def fail_after_native(
        initial: PaperInitialState, frame: _Frame, command: PaperCommand, revision: int
    ) -> None:
        _apply(initial, frame, command, revision)
        raise failure("controlled failure after native financial transition")

    monkeypatch.setattr("gridbot.paper.simulation._apply", fail_after_native)
    with pytest.raises(failure):
        sim.apply(sim.revision, PaperApplySell(execution, sim.revision))
    assert sim.snapshot() == before
    assert sim.source_log() == log


def test_pending_exception_observation_does_not_leak_owned_history() -> None:
    sim, execution = ready()
    sim.apply(sim.revision, PaperObserveSell(sell_source(sim, execution, status=None)))
    before = sim.source_log()
    with pytest.raises(PaperError) as error:
        sim.apply(sim.revision, PaperApplySell(execution, sim.revision))
    assert error.value.code is PaperErrorCode.EVIDENCE_PENDING
    assert error.value.observation is not None
    object.__setattr__(error.value.observation, "source_revision", 999)
    assert sim.source_log() == before
    assert sim.settled_sell_proceeds == Money.zero(USDT)


def test_local_concurrent_stale_decisions_have_one_winner() -> None:
    sim = runtime()
    command = buy_command(sim)

    def invoke() -> int | PaperErrorCode:
        try:
            return sim.apply(0, command)
        except PaperError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert sorted(map(str, results)) == ["1", "STALE_REVISION"]
    assert sim.revision == 1


def test_full_budget_preserves_noop_and_rejects_new_event_without_mutation() -> None:
    sim, execution = ready(5)
    apply = apply_full(sim, execution)
    before = sim.snapshot(), sim.source_log()
    assert sim.apply(5, apply) == 5
    with pytest.raises(SimulationError) as error:
        sim.apply(5, buy_command(sim))
    assert error.value.code is SimulationErrorCode.CAPACITY_EXCEEDED
    assert (sim.snapshot(), sim.source_log()) == before


def test_late_conflict_survives_replay_and_blocks_repeated_application() -> None:
    sim, execution = ready()
    apply = apply_full(sim, execution)
    before = sim.available_quote
    source = sell_source(sim, execution, fees=(Money.parse(".02", USDT),))
    sim.apply(sim.revision, PaperObserveSell(source))
    assert sim.incident_blocked
    restored = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=1000)
    assert restored.source_log() == sim.source_log()
    for instance in (sim, restored):
        with pytest.raises(PaperError) as error:
            instance.apply(instance.revision, apply)
        assert error.value.code is PaperErrorCode.INCIDENT_BLOCKED
        assert instance.available_quote == before


@pytest.mark.parametrize(
    "damage",
    ["gap", "run", "version", "version-bool", "truncated", "duplicate", "noop-event", "capacity"],
)
def test_replay_rejects_incomplete_foreign_or_reordered_sources(damage: str) -> None:
    sim, execution = ready()
    apply = apply_full(sim, execution)
    original = sim.source_log()
    log = original
    capacity = 100
    if damage == "gap":
        log = replace(log, events=(replace(log.events[0], revision=2), *log.events[1:]))
    elif damage == "run":
        log = replace(log, events=(replace(log.events[0], run_ref="SIM:foreign"), *log.events[1:]))
    elif damage == "version":
        log = replace(log, version=2)
    elif damage == "version-bool":
        log = replace(log, version=True)
    elif damage == "truncated":
        log = replace(log, events=log.events[:-1])
    elif damage == "duplicate":
        log = replace(log, events=(*log.events, log.events[-1]), revision=6)
    elif damage == "noop-event":
        log = replace(log, events=(*log.events, SimulationEvent(log.run_ref, 6, apply)), revision=6)
    else:
        capacity = 4
    with pytest.raises(SimulationError):
        PaperSimulation.replay(log, run_ref=sim.run_ref, max_events=capacity)
    assert sim.source_log() == original


def test_unknown_and_missing_sources_do_not_become_zero_fee_or_credit() -> None:
    sim, execution = ready()
    source = sell_source(sim, execution)
    absent = replace(source, reconciliation=replace(source.reconciliation, collection=None))
    sim.apply(sim.revision, PaperObserveSell(absent))
    with pytest.raises(PaperError):
        sim.apply(sim.revision, PaperApplySell(execution, sim.revision))
    assert sim.settled_sell_proceeds == Money.zero(USDT)


def test_partial_and_no_fill_do_not_rearm_and_release_is_unique() -> None:
    sim, execution = ready()
    source = sell_source(sim, execution, status=OrderStatus.CANCELED, qty=Qty.zero())
    sim.apply(sim.revision, PaperObserveSell(source))
    apply = PaperApplySell(execution, sim.revision)
    sim.apply(sim.revision, apply)
    assert sim.reserved_grid_base > Qty.zero()
    release = PaperReleaseNoFill(execution)
    sim.apply(sim.revision, release)
    revision = sim.revision
    assert sim.apply(revision, release) == revision
    assert sim.reserved_grid_base == Qty.zero()
    assert sim.grid_state.cells[0].cycle_seq == 0


def test_simulation_cannot_be_encoded_or_used_as_durable_or_operational_book() -> None:
    sim = runtime()
    with pytest.raises(DomainError):
        encode_contract(sim)
    with pytest.raises(PaperError):
        paper_transition(cast(PaperBook, sim), 0, buy_command(sim))
    with pytest.raises(PaperError):
        sim.apply(0, cast(PaperCommand, sim.snapshot()))


def test_real_insufficient_capital_refuses_without_changing_sources() -> None:
    source = replace(initial().initial, initial_quote=Money.parse("1", USDT))
    sim = PaperSimulation(source, run_ref="SIM:poor", max_events=20)
    before = sim.source_log()
    with pytest.raises(PaperError) as error:
        sim.apply(0, buy_command(sim))
    assert error.value.code is PaperErrorCode.INSUFFICIENT_QUOTE
    assert sim.source_log() == before


@pytest.mark.parametrize("invalid", [True, 0.0, -1])
def test_bad_revision_is_refused_before_idempotent_lookup(invalid: object) -> None:
    sim, execution = ready()
    apply = apply_full(sim, execution)
    before = sim.source_log()
    with pytest.raises(DomainError):
        sim.apply(cast(int, invalid), apply)
    assert sim.source_log() == before


@pytest.mark.parametrize("damage", ["overfill", "quote-fee", "identity"])
def test_invalid_buy_cannot_partially_consume_hold_or_create_inventory(damage: str) -> None:
    sim = runtime()
    sim.apply(0, buy_command(sim))
    finalized = buy_fill_result(sim)
    if damage == "overfill":
        finalized = deepcopy(finalized)
        object.__setattr__(finalized.ledger.fills[0], "executed_qty", Qty.parse(".033"))
    elif damage == "quote-fee":
        finalized = buy_fill_result(sim, fee=Money.parse(".02", USDT))
    else:
        object.__setattr__(finalized.context.execution_ref, "value", "LIVE:BUY:foreign")
    before = sim.snapshot(), sim.source_log()
    with pytest.raises(DomainError):
        sim.apply(sim.revision, PaperSettleBuy(finalized))
    assert (sim.snapshot(), sim.source_log()) == before


@pytest.mark.parametrize("damage", ["overfill", "fee-hold", "foreign-account"])
def test_revalidation_of_supplied_sell_sources_rejects_tampering_without_mutation(
    damage: str,
) -> None:
    sim, execution = ready()
    source = sell_source(sim, execution)
    ledger = source.reconciliation.ledger
    assert ledger is not None
    if damage == "overfill":
        object.__setattr__(ledger.fills[0], "executed_qty", Qty.parse(".032"))
    elif damage == "fee-hold":
        object.__setattr__(ledger.fills[0], "fee", Money.parse(".0002", BTC))
    else:
        object.__setattr__(source.account, "ref", "PAPER:foreign")
    before = sim.snapshot(), sim.source_log()
    with pytest.raises(DomainError):
        sim.apply(sim.revision, PaperObserveSell(source))
    assert (sim.snapshot(), sim.source_log()) == before


def test_missing_fee_is_distinct_from_explicit_zero_and_cannot_settle() -> None:
    sim, execution = ready()
    source = sell_source(sim, execution, fees=(Money.zero(USDT),))
    collection = source.reconciliation.collection
    assert collection is not None
    page = collection.pages[0]
    missing = replace(page.trades[0], fee=None)
    changed = replace(collection, pages=(replace(page, trades=(missing,)), *collection.pages[1:]))
    source = replace(source, reconciliation=replace(source.reconciliation, collection=changed))
    sim.apply(sim.revision, PaperObserveSell(source))
    before = sim.snapshot()
    with pytest.raises(PaperError) as error:
        sim.apply(sim.revision, PaperApplySell(execution, sim.revision))
    assert error.value.code is PaperErrorCode.EVIDENCE_PENDING
    assert sim.snapshot() == before


def test_old_cycle_cannot_reuse_buy_or_sell_identity_after_rearm() -> None:
    sim, execution = ready()
    old_buy = sim.source_log().events[0].command
    old_sell = sim.source_log().events[2].command
    apply_full(sim, execution)
    before = sim.source_log()
    for command in (old_buy, old_sell):
        with pytest.raises(DomainError):
            sim.apply(sim.revision, command)
        assert sim.source_log() == before


@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB")])
def test_buy_fees_preserve_their_asset_and_do_not_invent_virtual_funding(asset: Asset) -> None:
    sim = runtime()
    sim.apply(0, buy_command(sim))
    sim.apply(1, PaperSettleBuy(buy_fill_result(sim, fee=Money.parse(".00001", asset))))
    assert_source_conservation(sim.source_log(), sim.snapshot())
    expected = (Money.parse(".00001", asset),) if asset.code == "BNB" else ()
    assert sim.third_asset_obligations() == expected


def test_reordered_commands_require_valid_economic_predecessors() -> None:
    sim, _ = ready()
    log = sim.source_log()
    first, second = log.events[:2]
    reordered = replace(
        log,
        events=(
            replace(first, command=second.command),
            replace(second, command=first.command),
            *log.events[2:],
        ),
    )
    with pytest.raises(DomainError):
        PaperSimulation.replay(reordered, run_ref=sim.run_ref, max_events=1000)
    assert sim.source_log() == log


def test_replay_accepts_neither_foreign_authority_nor_an_untyped_event() -> None:
    sim, _ = ready()
    with pytest.raises(SimulationError):
        PaperSimulation.replay(cast(SimulationLog, initial()), run_ref=sim.run_ref, max_events=1000)
    log = sim.source_log()
    invalid = replace(log, events=cast(tuple[SimulationEvent, ...], (object(), *log.events[1:])))
    with pytest.raises(SimulationError):
        PaperSimulation.replay(invalid, run_ref=sim.run_ref, max_events=1000)


def test_exported_source_alias_cannot_change_retained_identifiers() -> None:
    sim, execution = ready()
    apply_full(sim, execution)
    original = deepcopy(sim.source_log())
    exported = sim.source_log()
    first = exported.events[0].command
    assert isinstance(first, PaperPrepareBuy)
    object.__setattr__(first.execution_ref, "value", "LIVE:changed-after-export")
    assert sim.source_log() == original
    restored = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=1000)
    assert restored.snapshot() == sim.snapshot()
