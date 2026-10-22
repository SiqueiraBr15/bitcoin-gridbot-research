"""Dez propriedades A15; Hypothesis reporta exemplos efetivos com --hypothesis-show-statistics."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from functools import partial

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.application import (
    GridOperationalBook,
    SellAttemptStatus,
    SellExecutionContext,
    SellExecutionRef,
    SellIntentError,
    SellInventoryBook,
    SellInventoryError,
    bind_operational_buy_execution,
    bind_sell_execution,
    build_sell_intents,
    mark_sell_submission_uncertain,
    prepare_sell,
    reserve_operational_sell,
    settle_funded_buy,
    settle_operational_buy,
)
from tests.application.test_operational_grid import (
    E,
    assert_preserved,
    buy_context,
    context,
    expect,
    prepare_other_buy,
    prepared_root,
    ref,
    with_status,
)
from tests.application.test_sell_intents import (
    assessment,
    fingerprint,
    finish,
    grid,
    held,
    prepare,
    q,
)

PROPERTY_SETTINGS = settings(max_examples=40, deadline=None, derandomize=True)


@st.composite
def scenarios(
    draw: st.DrawFn,
) -> tuple[int, int, int, int, int, list[int], list[SellAttemptStatus]]:
    count = draw(st.integers(1, 3))
    steps = draw(st.integers(2, 32))
    fee_units = draw(st.integers(1, 999))
    hold_units = draw(st.integers(0, 1000 - fee_units))
    cycle = draw(st.integers(0, 9))
    order = draw(st.permutations(tuple(range(count))))
    statuses = draw(
        st.lists(st.sampled_from(list(SellAttemptStatus)), min_size=count, max_size=count)
    )
    return count, steps, fee_units, hold_units, cycle, order, statuses


Scenario = tuple[int, int, int, int, int, list[int], list[SellAttemptStatus]]


def inventory_for(scenario: Scenario) -> SellInventoryBook:
    count, steps, fee_units, hold_units, cycle, order, _ = scenario
    state = grid()
    state = dataclasses.replace(
        state, cells=tuple(dataclasses.replace(c, cycle_seq=cycle) for c in state.cells)
    )
    funded = prepare(tuple(range(count)), state)
    for cell in order:
        funded = settle_funded_buy(
            funded,
            finish(
                funded, cell, str(Decimal(steps).scaleb(-3)), str(Decimal(fee_units).scaleb(-6))
            ),
        )
    root = GridOperationalBook(SellInventoryBook(funded))
    for cell in order:
        root = reserve_operational_sell(
            root, assessment(root.inventory_book, cell), q(str(Decimal(hold_units).scaleb(-6)))
        )
    return root.inventory_book


def run(scenario: Scenario) -> GridOperationalBook:
    _, _, _, _, cycle, order, statuses = scenario
    inventory = inventory_for(scenario)
    root = GridOperationalBook(inventory)
    plan = build_sell_intents(inventory)
    for cell in order:
        root = prepare_sell(root, plan, ref(cell, cycle))
        root = with_status(root, statuses[cell], cell)
    return root


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_btc_holds_survive_each_sell_transition(scenario: Scenario) -> None:
    root = GridOperationalBook(inventory_for(scenario))
    before = fingerprint(root.inventory_book)
    plan = build_sell_intents(root.inventory_book)
    _, _, _, _, cycle, order, statuses = scenario
    for cell in order:
        root = prepare_sell(root, plan, ref(cell, cycle))
        root = with_status(root, statuses[cell], cell)
        assert fingerprint(root.inventory_book) == before
        assert all(
            root.inventory_book.reservation_for(r.cycle_ref) is r for r in plan.book.reservations
        )


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_quote_identity_remains_exact_without_proceeds(scenario: Scenario) -> None:
    inventory = inventory_for(scenario)
    initial = inventory.funded_buy_book
    root = run(scenario)
    funded = root.inventory_book.funded_buy_book
    assert (funded.spent_quote, funded.available_quote, funded.reserved_quote) == (
        initial.spent_quote,
        initial.available_quote,
        initial.reserved_quote,
    )
    assert (
        funded.initial_quote_capital
        == funded.spent_quote + funded.reserved_quote + funded.available_quote
    )


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_one_attempt_per_cycle_in_all_states(scenario: Scenario) -> None:
    root = run(scenario)
    refs = tuple(a.cycle_ref for a in root.sell_attempts)
    assert len(set(refs)) == len(refs) == scenario[0]
    for cycle_ref in refs:
        expect(
            E.SELL_ATTEMPT_ALREADY_EXISTS,
            partial(prepare_sell, root, build_sell_intents(root.inventory_book), cycle_ref),
        )


@PROPERTY_SETTINGS
@given(st.text(alphabet="abcdef0123456789", min_size=1, max_size=30))
def test_generated_sell_execution_ref_is_exclusive(value: str) -> None:
    root = prepared_root((0, 1))
    root = bind_sell_execution(root, ref(), context(root, value=value))
    expect(
        E.SELL_EXECUTION_REF_ALREADY_USED,
        partial(bind_sell_execution, root, ref(1), context(root, 1, value)),
    )
    assert root.sell_attempts[1].execution is None


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_replay_is_deterministic(scenario: Scenario) -> None:
    a, b = run(scenario), run(scenario)
    assert a == b
    assert hash(a) == hash(b)


@PROPERTY_SETTINGS
@given(st.sampled_from(list(SellAttemptStatus)), st.integers(1, 100))
def test_generated_failure_is_pure(status: SellAttemptStatus, other_cycle: int) -> None:
    root = with_status(prepared_root(), status)
    before = dataclasses.astuple(root)
    expect(
        E.SELL_ATTEMPT_NOT_FOUND, partial(mark_sell_submission_uncertain, root, ref(0, other_cycle))
    )
    expect(
        E.SELL_ATTEMPT_ALREADY_EXISTS,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), ref()),
    )
    assert dataclasses.astuple(root) == before


@PROPERTY_SETTINGS
@given(st.sampled_from(list(SellAttemptStatus)), st.integers(1, 24), st.integers(0, 99))
def test_generated_independent_buy_updates_preserve_sell(
    status: SellAttemptStatus, units: int, fee: int
) -> None:
    original = with_status(prepared_root(), status)
    root = prepare_other_buy(original)
    root = bind_operational_buy_execution(root, ref(1), buy_context(root))
    assert_preserved(original, root)
    root = settle_operational_buy(
        root,
        finish(
            root.inventory_book.funded_buy_book,
            1,
            str(Decimal(units).scaleb(-3)),
            str(Decimal(fee).scaleb(-6)),
        ),
    )
    assert_preserved(original, root)
    candidate = assessment(root.inventory_book, 1)
    if candidate.eligible_sell_qty is None:
        with pytest.raises(SellInventoryError, match="SIZING_NOT_ELIGIBLE"):
            reserve_operational_sell(root, candidate, q(0))
    else:
        root = reserve_operational_sell(root, candidate, q(0))
    assert_preserved(original, root)


@PROPERTY_SETTINGS
@given(st.integers(2, 32), st.integers(1, 999), st.integers(1, 20))
def test_generated_missing_origin_or_reservation_never_authorizes_sell(
    steps: int, fee: int, cycle: int
) -> None:
    inventory = held(qty=str(Decimal(steps).scaleb(-3)), fee=str(Decimal(fee).scaleb(-6)))
    plan = build_sell_intents(inventory)
    lost = GridOperationalBook(SellInventoryBook(inventory.funded_buy_book))
    with pytest.raises(SellIntentError):
        prepare_sell(lost, plan, ref())
    expect(
        E.SELL_INTENT_NOT_IN_PLAN,
        partial(prepare_sell, GridOperationalBook(inventory), plan, ref(0, cycle)),
    )
    assert lost.sell_attempts == ()


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_order_never_contains_hold_or_unreserved_btc(scenario: Scenario) -> None:
    root = run(scenario)
    for attempt in root.sell_attempts:
        intent = attempt.intent
        reservation = root.inventory_book.reservation_for(attempt.cycle_ref)
        assert reservation is not None
        assert intent.sell_qty == reservation.reserved_sell_qty
        assert (
            intent.sell_qty
            <= reservation.total_reserved_base_qty
            <= reservation.confirmed_net_base_qty
        )
        assert (
            intent.total_base_commitment + intent.unreserved_base_qty
            == intent.confirmed_net_base_qty
        )
        assert (
            SellExecutionContext(intent, SellExecutionRef("observed")).requested_qty
            == intent.sell_qty
        )


@PROPERTY_SETTINGS
@given(scenarios())
def test_generated_lifecycle_never_advances_or_rearms_cell(scenario: Scenario) -> None:
    root = run(scenario)
    cycle = scenario[4]
    assert all(c.cycle_seq == cycle for c in root.grid_state.cells)
    for attempt in root.sell_attempts:
        cell = root.grid_state.cells[attempt.cycle_ref.cell_index]
        assert not cell.buy_armed
        assert (
            root.inventory_book.funded_buy_book.lifecycle.consumed_for(attempt.cycle_ref)
            == attempt.intent.finalized_buy
        )
