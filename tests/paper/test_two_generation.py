"""Two-generation financial publication, routing, replay and failure boundaries."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest

from gridbot.domain import BTC, USDT, Money, Price, Qty
from gridbot.domain.errors import DomainError
from gridbot.paper import two_generation
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperCommand,
    PaperInitialState,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperSettleBuy,
    _apply,
    _Frame,
)
from gridbot.paper.partial_allocation import PartialCosts
from gridbot.paper.two_generation import PartialPublishPlan, TwoGenerationPaper
from tests.backtest.test_safe_recenter import runtime, signal
from tests.paper.simulation_fixtures import (
    buy_command,
    buy_fill_result,
    sell_command,
    sell_source,
)


def prepared(*, active_sell: bool = False, active_buy: bool = False) -> TwoGenerationPaper:
    native = runtime(armed=True)
    command = buy_command(native)
    native.apply(native.revision, command)
    if not active_buy:
        native.apply(
            native.revision, PaperSettleBuy(buy_fill_result(native, fee=Money.parse(".001", USDT)))
        )
    if active_sell:
        native.apply(native.revision, sell_command(native, hold="0"))
    return TwoGenerationPaper(native.source_log(), max_events=1000)


def plan(sim: TwoGenerationPaper, *, transition: bool = True) -> PartialPublishPlan:
    return sim.plan(
        mark=Price.parse("80"),
        costs=PartialCosts(Decimal(".001"), USDT),
        notional_ceiling=Money.parse("90", USDT),
        configuration_ref="CFG:A19_6_UNIT",
        signal=signal() if transition else (),
    )


def authority(sim: TwoGenerationPaper) -> tuple[object, ...]:
    return deepcopy((sim.snapshot(), sim.source_log(), sim.generations, sim.base_by_generation()))


def conserved(sim: TwoGenerationPaper) -> None:
    snap = sim.snapshot()
    assert Fraction(sim.initial.initial_quote.amount) + Fraction(
        snap.settled_sell_proceeds.amount
    ) == (
        Fraction(snap.buy_spending.amount)
        + Fraction(snap.active_buy_reservations.amount)
        + Fraction(snap.available_quote.amount)
    )
    assert sum((q for _, q in sim.base_by_generation()), Qty.zero()) == snap.remaining_grid_base
    assert snap.reserved_grid_base <= snap.remaining_grid_base
    assert snap.available_quote.amount >= 0


def test_atomic_transition_reserves_real_orders_and_preserves_legacy() -> None:
    sim = prepared()
    before = sim.snapshot()
    old = sim.generations[0]
    request = plan(sim)
    assert request.allocation.admissible
    sim.publish(sim.revision, request)
    snap = sim.snapshot()
    assert len(sim.generations) == 2
    assert sim.generations[1].predecessor == old.ref
    assert sim.generations[0] == old
    assert snap.remaining_grid_base == before.remaining_grid_base
    assert snap.buy_spending == before.buy_spending
    assert snap.settled_sell_proceeds == before.settled_sell_proceeds
    assert snap.active_buy_reservations == request.allocation.required_quote
    assert snap.available_quote + snap.active_buy_reservations == before.available_quote
    assert request.allocation.plan is not None
    for intent in request.allocation.plan.intents:
        assert sim.buy_context(intent.cycle_ref).intent == intent
        assert sim.owner(intent.cycle_ref) == sim.main_ref
    conserved(sim)


def test_legacy_sell_observation_cannot_fund_new_buy_but_apply_can() -> None:
    sim = prepared(active_sell=True)
    old = sim.generations[0]
    legacy_ref = sim.source_log().prefix.events[-1].command
    from gridbot.paper.accounting import PaperPrepareSell

    assert isinstance(legacy_ref, PaperPrepareSell)
    legacy_execution = legacy_ref.execution_ref
    sim.publish(sim.revision, plan(sim))
    old_btc = dict(sim.base_by_generation())[old.ref]
    evidence = sell_source(sim, legacy_execution, price="105")
    before = sim.snapshot()
    revision = sim.apply(sim.revision, old.ref, PaperObserveSell(evidence))
    assert sim.snapshot().available_quote == before.available_quote
    assert sim.snapshot().remaining_grid_base == before.remaining_grid_base
    sim.apply(sim.revision, old.ref, PaperApplySell(legacy_execution, revision))
    projection = evidence.assessment.projection
    assert projection is not None
    assert sim.snapshot().available_quote == before.available_quote + projection.net_observed_quote
    assert (
        dict(sim.base_by_generation())[old.ref] == old_btc - projection.projected_base_consumption
    )
    assert dict(sim.base_by_generation())[sim.main_ref].is_zero
    state = authority(sim)
    sim.apply(sim.revision, old.ref, PaperApplySell(legacy_execution, revision))
    assert authority(sim) == state
    conserved(sim)
    rebuilt = TwoGenerationPaper.replay(sim.source_log(), max_events=1000)
    assert authority(rebuilt) == authority(sim)


def test_main_buy_preserves_origin_then_replay_rebuilds_every_source() -> None:
    sim = prepared()
    legacy = sim.base_by_generation()
    request = plan(sim)
    sim.publish(sim.revision, request)
    assert request.allocation.plan is not None
    cell = request.allocation.plan.intents[0].cycle_ref.cell_index
    context = sim.buy_context(request.allocation.plan.intents[0].cycle_ref)
    fee = request.costs.fee(context.intent.price, context.intent.qty)
    final = buy_fill_result(sim, cell, fee=fee)
    sim.apply(sim.revision, sim.main_ref, PaperSettleBuy(final))
    assert sim.base_by_generation()[0] == legacy[0]
    assert dict(sim.base_by_generation())[sim.main_ref] == final.net_acquired_base_qty
    conserved(sim)
    before = authority(sim)
    sim.apply(sim.revision, sim.main_ref, PaperSettleBuy(final))
    assert authority(sim) == before
    assert authority(TwoGenerationPaper.replay(sim.source_log(), max_events=1000)) == before


def test_active_or_uncertain_old_buy_blocks_transition_without_release() -> None:
    sim = prepared(active_buy=True)
    before = authority(sim)
    with pytest.raises(DomainError, match="OLD_BUY_ACTIVE"):
        plan(sim)
    assert authority(sim) == before


@pytest.mark.parametrize(
    "damage", ["revision", "generation", "allocation", "fees", "quantity", "empty", "configuration"]
)
def test_forged_plan_rejected_atomically(damage: str) -> None:
    sim = prepared()
    request = plan(sim)
    if damage == "revision":
        request = replace(request, revision=request.revision + 1)
    elif damage == "generation":
        request = replace(request, generation_ref="PAPER:FOREIGN:GEN:0")
    elif damage == "configuration":
        request = replace(request, configuration_ref="")
    elif damage == "empty":
        request = replace(request, allocation=replace(request.allocation, plan=None))
    elif damage == "fees":
        request = replace(request, allocation=replace(request.allocation, fees=()))
    elif damage == "quantity":
        request = replace(
            request, allocation=replace(request.allocation, projected_gross_base=Qty.parse("9999"))
        )
    else:
        request = replace(
            request, allocation=replace(request.allocation, required_quote=Money.zero(USDT))
        )
    before = authority(sim)
    with pytest.raises(DomainError):
        sim.publish(sim.revision, request)
    assert authority(sim) == before


def test_duplicate_candidate_is_noop_and_third_generation_is_forbidden() -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    before = authority(sim)
    assert sim.publish(sim.revision, request) == sim.revision
    with pytest.raises(DomainError, match="THIRD_GENERATION"):
        plan(sim)
    with pytest.raises(DomainError, match="stale"):
        sim.publish(sim.revision, replace(request, configuration_ref="CFG:OTHER"))
    assert authority(sim) == before


def test_new_settlement_between_assessment_and_publish_invalidates_plan() -> None:
    sim = prepared(active_sell=True)
    request = plan(sim)
    from gridbot.paper.accounting import PaperPrepareSell

    source = sim.source_log().prefix.events[-1].command
    assert isinstance(source, PaperPrepareSell)
    evidence = sell_source(sim, source.execution_ref, price="105")
    old = sim.generations[0].ref
    revision = sim.apply(sim.revision, old, PaperObserveSell(evidence))
    sim.apply(sim.revision, old, PaperApplySell(source.execution_ref, revision))
    before = authority(sim)
    with pytest.raises(DomainError, match="stale"):
        sim.publish(sim.revision, request)
    assert authority(sim) == before


def test_failure_during_reservation_loop_never_publishes_partial_finance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = prepared()
    request = plan(sim)
    before = authority(sim)
    native = _apply
    calls = 0

    def interrupted(
        initial: PaperInitialState,
        frame: _Frame,
        command: PaperCommand,
        revision: int,
    ) -> None:
        nonlocal calls
        calls += 1
        native(initial, frame, command, revision)
        if calls == 1:
            raise RuntimeError("injected after native reservation")

    monkeypatch.setattr(two_generation, "_apply", interrupted)
    with pytest.raises(RuntimeError, match="native reservation"):
        sim.publish(sim.revision, request)
    assert calls == 1
    assert authority(sim) == before


def test_cross_generation_settlement_cannot_consume_another_lot() -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    assert request.allocation.plan is not None
    ref = request.allocation.plan.intents[0].cycle_ref
    intent = sim.buy_context(ref).intent
    final = buy_fill_result(sim, ref.cell_index, fee=request.costs.fee(intent.price, intent.qty))
    before = authority(sim)
    with pytest.raises(DomainError, match="GENERATION_ORIGIN_MISMATCH"):
        sim.apply(sim.revision, sim.generations[0].ref, PaperSettleBuy(final))
    assert authority(sim) == before


def test_external_prepare_cannot_bypass_risk_and_legacy_cannot_open_buy() -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    assert request.allocation.plan is not None
    intent = request.allocation.plan.intents[0]
    from gridbot.portfolio import BuyExecutionRef

    command = PaperPrepareBuy(
        request.allocation.plan,
        intent.cycle_ref,
        Money.zero(USDT),
        BuyExecutionRef("PAPER:A19_4_UNIT:BUY:rogue"),
    )
    before = authority(sim)
    with pytest.raises(DomainError, match="admitted batch"):
        sim.apply(sim.revision, sim.generations[0].ref, command)
    assert authority(sim) == before


@pytest.mark.parametrize(
    "damage", ["version", "revision", "omit", "duplicate", "reorder", "generation"]
)
def test_replay_corruption_is_rejected_entirely(damage: str) -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    assert request.allocation.plan is not None
    intent = request.allocation.plan.intents[0]
    sim.apply(
        sim.revision,
        sim.main_ref,
        PaperSettleBuy(
            buy_fill_result(
                sim, intent.cycle_ref.cell_index, fee=request.costs.fee(intent.price, intent.qty)
            )
        ),
    )
    log = sim.source_log()
    if damage == "version":
        log = replace(log, version=2)
    elif damage == "revision":
        log = replace(log, revision=log.revision + 1)
    elif damage == "omit":
        log = replace(log, events=log.events[1:])
    elif damage == "duplicate":
        log = replace(log, events=(*log.events, log.events[-1]), revision=log.revision + 1)
    elif damage == "reorder":
        log = replace(log, events=tuple(reversed(log.events)))
    else:
        log = replace(
            log,
            events=(replace(log.events[0], generation_ref="PAPER:FOREIGN:GEN:1"), *log.events[1:]),
        )
    before = authority(sim)
    with pytest.raises(DomainError):
        TwoGenerationPaper.replay(log, max_events=1000)
    assert authority(sim) == before


def test_unexpected_base_fee_after_quote_admission_is_rejected() -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    assert request.allocation.plan is not None
    ref = request.allocation.plan.intents[0].cycle_ref
    final = buy_fill_result(sim, ref.cell_index, fee=Money.parse(".00001", BTC))
    before = authority(sim)
    with pytest.raises(DomainError, match="unexpected BUY commission"):
        sim.apply(sim.revision, sim.main_ref, PaperSettleBuy(final))
    assert authority(sim) == before


def test_partial_legacy_sell_keeps_its_own_reserved_remainder() -> None:
    from gridbot.domain import OrderStatus
    from gridbot.paper.accounting import PaperPrepareSell

    sim = prepared(active_sell=True)
    source = sim.source_log().prefix.events[-1].command
    assert isinstance(source, PaperPrepareSell)
    legacy = sim.generations[0].ref
    sim.publish(sim.revision, plan(sim))
    context = sim.sell_authorization(source.execution_ref).context
    evidence = sell_source(
        sim,
        source.execution_ref,
        qty=Qty(context.requested_qty.value / Decimal(2)),
        status=OrderStatus.CANCELED,
        price="105",
    )
    revision = sim.apply(sim.revision, legacy, PaperObserveSell(evidence))
    sim.apply(sim.revision, legacy, PaperApplySell(source.execution_ref, revision))
    projection = evidence.assessment.projection
    assert projection is not None
    assert sim.snapshot().reserved_grid_base == projection.projected_reserved_remainder
    assert sim.snapshot().reserved_grid_base.value > 0
    assert dict(sim.base_by_generation())[sim.main_ref].is_zero
    conserved(sim)


def test_new_reservation_invalidates_previous_plan_even_without_spending() -> None:
    sim = prepared()
    first = plan(sim)
    sim.publish(sim.revision, first)
    before = authority(sim)
    # A byte-identical candidate is a noop, a changed proposal is stale.
    with pytest.raises(DomainError, match="stale"):
        sim.publish(sim.revision, replace(first, mark=Price.parse("79")))
    assert authority(sim) == before


def test_public_aliases_cannot_rewrite_funding_or_legacy_state() -> None:
    sim = prepared()
    request = plan(sim)
    sim.publish(sim.revision, request)
    before = authority(sim)
    detached = sim.generations
    object.__setattr__(detached[0].state.cells[0], "cycle_seq", 9999)
    detached_source = sim.source_log()
    object.__setattr__(detached_source.prefix.initial.initial_quote, "amount", Decimal("999999"))
    assert authority(sim) == before


@pytest.mark.parametrize("value", [True, False, -1, "1"])
@pytest.mark.parametrize("field", ["log", "event", "plan"])
def test_source_revisions_require_exact_nonnegative_integers(value: object, field: str) -> None:
    from typing import Any, cast

    from gridbot.paper.two_generation import PartialSourceLog
    from tests.backtest.test_safe_recenter import runtime

    # With an empty native prefix and one publication, True used to equal1.
    sim = TwoGenerationPaper(runtime().source_log(), max_events=1000)
    request = plan(sim)
    before = authority(sim)
    if field == "plan":
        invalid = replace(request, revision=cast(Any, value))
        with pytest.raises(DomainError):
            sim.publish(sim.revision, invalid)
    else:
        sim.publish(sim.revision, request)
        before = authority(sim)
        log = sim.source_log()
        if field == "log":
            log = replace(log, revision=cast(Any, value))
        else:
            log = replace(log, events=(replace(log.events[0], revision=cast(Any, value)),))
        assert isinstance(log, PartialSourceLog)
        with pytest.raises(DomainError):
            TwoGenerationPaper.replay(log, max_events=1000)
    assert authority(sim) == before
