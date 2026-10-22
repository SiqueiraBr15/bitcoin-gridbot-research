"""Sondagens A14.1: fontes reais do pipeline e violações explícitas de snapshots."""

from __future__ import annotations

import dataclasses
from decimal import Decimal, Inexact, localcontext
from functools import partial
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.application import (
    GridSellIntent,
    SellIntentErrorCode,
    SellIntentFreshness,
    SellIntentPlan,
    SellIntentStaleFinding,
    SellIntentStaleReason,
    SellInventoryBook,
    SellInventoryError,
    SellInventoryErrorCode,
    build_sell_intent_for_cell,
    build_sell_intents,
    reserve_sell_inventory,
    sell_intent_plan_freshness,
    validate_sell_intent_plan_against_book,
)
from gridbot.domain import NotionalRules, Qty
from gridbot.portfolio import BuyExecutionStatus, BuyFinalizationError, finalize_buy
from gridbot.strategy import CellCycleRef
from tests.application.test_sell_intents import (
    RULES,
    acquired,
    advance_cycle_synthetically,
    assessment,
    expect_error,
    fingerprint,
    finish,
    forged,
    grid,
    held,
    prepare,
    q,
    rewrap,
)

E = SellIntentErrorCode
R = SellIntentStaleReason
D = Decimal


@pytest.mark.parametrize(
    "case", ["duplicate", "unknown", "noncanonical", "mutable_refs", "lost_source", "bad_source"]
)
def test_forged_plan_is_rejected_before_freshness_can_authorize_it(case: str) -> None:
    book = held((0, 1))
    plan = build_sell_intents(book)
    changes: dict[str, object] = {}
    if case == "duplicate":
        changes["cycle_refs"] = (CellCycleRef(0, 0),) * 2
    elif case == "unknown":
        changes["cycle_refs"] = (CellCycleRef(4, 99),)
    elif case == "noncanonical":
        changes["cycle_refs"] = tuple(reversed(plan.cycle_refs))
    elif case == "mutable_refs":
        changes["cycle_refs"] = list(plan.cycle_refs)
    elif case == "lost_source":
        changes["book"] = rewrap(book)
    else:
        changes["book"] = forged(book, funded_buy_book=prepare((0, 1)))
    bad = forged(plan, **changes)
    expect_error(E.INVALID_SELL_INTENT_PLAN, partial(sell_intent_plan_freshness, bad, book))
    expect_error(
        E.INVALID_SELL_INTENT_PLAN, partial(validate_sell_intent_plan_against_book, bad, book)
    )
    assert fingerprint(book) == fingerprint(plan.book)


@pytest.mark.parametrize("field", ["checked_cycle_refs", "findings"])
def test_freshness_rejects_mutable_internal_collections(field: str) -> None:
    kwargs: dict[str, Any] = {"checked_cycle_refs": (), "findings": ()}
    kwargs[field] = []
    with pytest.raises(TypeError):
        SellIntentFreshness(**kwargs)


@pytest.mark.parametrize(("field", "bad"), [("cycle_ref", None), ("reason", "RESERVATION_MISSING")])
def test_stale_finding_rejects_invalid_source_types(field: str, bad: object) -> None:
    kwargs: dict[str, Any] = {"cycle_ref": CellCycleRef(0, 0), "reason": R.RESERVATION_MISSING}
    kwargs[field] = bad
    with pytest.raises(TypeError):
        SellIntentStaleFinding(**kwargs)


@pytest.mark.parametrize("field", ["checked_cycle_refs", "findings"])
def test_freshness_rejects_wrong_elements(field: str) -> None:
    kwargs: dict[str, Any] = {"checked_cycle_refs": (), "findings": ()}
    kwargs[field] = (None,)
    with pytest.raises(TypeError):
        SellIntentFreshness(**kwargs)


def test_precision_error_in_original_plan_source_is_not_lost() -> None:
    book = held()
    plan = build_sell_intents(book)
    bad_reservation = forged(book.reservations[0], base_fee_hold=q("1e-100"))
    bad = forged(plan, book=forged(book, reservations=(bad_reservation,)))
    expect_error(E.FINANCIAL_PRECISION_ERROR, partial(sell_intent_plan_freshness, bad, book))


def test_direct_duplicate_reservation_cannot_borrow_global_inventory() -> None:
    book = held((0, 1, 2))
    # O total global cobre duas reservas da célula 0; a unicidade local ainda deve barrar.
    assert (
        book.reservations[0].total_reserved_base_qty + book.reservations[0].total_reserved_base_qty
        < book.confirmed_net_base_qty
    )
    with pytest.raises(SellInventoryError) as error:
        SellInventoryBook(book.funded_buy_book, (book.reservations[0], book.reservations[0]))
    assert error.value.code is SellInventoryErrorCode.INVALID_BOOK


def test_partial_open_buy_cannot_be_finalized_or_planned() -> None:
    funded = prepare()
    terminal = finish(funded, qty="0.02")
    report = dataclasses.replace(
        terminal.terminal_report, final_status=BuyExecutionStatus.PARTIALLY_FILLED_OPEN
    )
    with pytest.raises(BuyFinalizationError, match="NOT_TERMINAL"):
        finalize_buy(terminal.context, terminal.ledger, report, terminal.reconciliation_evidence)
    assert build_sell_intents(SellInventoryBook(funded)).intents == ()


def test_changed_origin_with_equal_amounts_is_still_stale() -> None:
    book = held()
    alternate = acquired()
    original = alternate.funded_buy_book.lifecycle.consumed[0]
    fill = dataclasses.replace(original.ledger.fills[0], fill_ref="another-observed-trade")
    ledger = dataclasses.replace(original.ledger, fills=(fill,))
    report = dataclasses.replace(original.terminal_report, fill_refs=(fill.fill_ref,))
    evidence = dataclasses.replace(original.reconciliation_evidence, fill_refs=(fill.fill_ref,))
    buy = finalize_buy(original.context, ledger, report, evidence)
    lifecycle = dataclasses.replace(alternate.funded_buy_book.lifecycle, consumed=(buy,))
    funded = dataclasses.replace(alternate.funded_buy_book, lifecycle=lifecycle)
    other = SellInventoryBook(funded)
    other = reserve_sell_inventory(other, assessment(other), q("0.0001"))
    assert book.confirmed_net_base_qty == other.confirmed_net_base_qty
    assert sell_intent_plan_freshness(build_sell_intents(book), other).findings == (
        SellIntentStaleFinding(CellCycleRef(0, 0), R.ORIGIN_CHANGED),
    )


def test_equal_prices_and_quantities_do_not_replace_cycle_identity() -> None:
    first = held(qty="0.02")
    second = held((1,), qty="0.02", state=grid(lower=98, upper=108))
    a = build_sell_intents(first).intents[0]
    b = build_sell_intents(second).intents[0]
    assert a.limit_price == b.limit_price
    assert a.sell_qty == b.sell_qty
    assert a.cycle_ref != b.cycle_ref
    expect_error(
        E.STALE_SELL_INTENT,
        partial(validate_sell_intent_plan_against_book, build_sell_intents(first), second),
    )


@pytest.mark.parametrize(
    ("qty", "eligible"), [("0.000999999", False), ("0.001", True), ("0.001000001", True)]
)
def test_quantities_next_to_step_fail_or_preserve_the_exact_residual(
    qty: str, eligible: bool
) -> None:
    book = acquired(qty=qty, fee="0")
    a = assessment(book)
    if not eligible:
        with pytest.raises(SellInventoryError):
            reserve_sell_inventory(book, a, q(0))
        assert build_sell_intents(book).is_empty
    else:
        book = reserve_sell_inventory(book, a, q(0))
        intent = build_sell_intents(book).intents[0]
        assert intent.sell_qty == q("0.001")
        assert intent.sell_qty + intent.unreserved_base_qty == q(qty)


@pytest.mark.parametrize(
    ("offset", "eligible"), [("-0.000000001", True), ("0", True), ("0.000000001", False)]
)
def test_min_notional_boundary_is_exact(offset: str, eligible: bool) -> None:
    book = acquired()
    minimum = D("3.162") + D(offset)
    market_rules = dataclasses.replace(RULES, notional=NotionalRules(min_notional=minimum))
    a = assessment(book, market_rules=market_rules)
    if eligible:
        plan = build_sell_intents(reserve_sell_inventory(book, a, q("0.0001")))
        assert plan.intents[0].sell_qty == q("0.031")
    else:
        with pytest.raises(SellInventoryError, match="SIZING_NOT_ELIGIBLE"):
            reserve_sell_inventory(book, a, q(0))


def test_low_ambient_decimal_precision_does_not_round_financial_values() -> None:
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        book = held()
        plan = build_sell_intents(book)
        validate_sell_intent_plan_against_book(plan, book)
        intent = plan.intents[0]
        assert intent.sell_qty == q("0.031")
        assert intent.total_base_commitment == q("0.0311")
        assert intent.unreserved_base_qty == q("0.000868")
        assert context.prec == 2


@pytest.mark.parametrize("hold", ["1e-100", "1e1000000"])
def test_inexact_and_overflow_holds_fail_closed(hold: str) -> None:
    book = held()
    bad = forged(book.reservations[0], base_fee_hold=q(hold))
    expect_error(E.FINANCIAL_PRECISION_ERROR, partial(GridSellIntent, bad))


@pytest.mark.parametrize("api", [build_sell_intents, sell_intent_plan_freshness])
def test_adversarial_float_sources_are_rejected(api: Any) -> None:
    operation = partial(api, cast(Any, 1.5))
    if api is sell_intent_plan_freshness:
        operation = partial(api, cast(Any, 1.5), held())
    with pytest.raises(TypeError):
        operation()


def test_repeated_stale_validation_never_restores_reservations() -> None:
    book = held((0, 1, 2))
    plan = build_sell_intents(book)
    current = rewrap(book)
    before = fingerprint(current)
    for _ in range(5):
        expect_error(
            E.STALE_SELL_INTENT, partial(validate_sell_intent_plan_against_book, plan, current)
        )
    assert fingerprint(current) == before


def test_no_proceeds_are_invented_by_synthetic_cycle_advance() -> None:
    book = held()
    before = book.funded_buy_book
    advanced = advance_cycle_synthetically(before, 0)
    assert advanced.available_quote == before.available_quote
    assert advanced.spent_quote == before.spent_quote
    assert SellInventoryBook(advanced).confirmed_net_base_qty == q(0)
    # Reproduz F1/F2 apenas como fixture; NÃO é uma venda reconciliada ou operacional.


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    fills=st.lists(st.integers(min_value=1100, max_value=31999), min_size=3, max_size=3),
    fees=st.lists(st.integers(min_value=0, max_value=99), min_size=3, max_size=3),
    order=st.permutations((0, 1, 2)),
    chosen=st.sets(st.integers(min_value=0, max_value=2), min_size=1, max_size=3),
)
def test_generated_heterogeneous_cells_preserve_identity_conservation_and_partial_plans(
    fills: list[int], fees: list[int], order: list[int], chosen: set[int]
) -> None:
    from gridbot.application import settle_funded_buy

    funded = prepare((0, 1, 2))
    for cell in order:
        funded = settle_funded_buy(
            funded,
            finish(funded, cell, str(D(fills[cell]).scaleb(-6)), str(D(fees[cell]).scaleb(-6))),
        )
    book = SellInventoryBook(funded)
    expected: dict[CellCycleRef, Qty] = {}
    for cell in order:
        a = assessment(book, cell)
        assert a.eligible_sell_qty is not None
        expected[a.cycle_ref] = a.eligible_sell_qty
        hold = a.step_residual_qty
        book = reserve_sell_inventory(book, a, hold)
    refs = tuple(CellCycleRef(i, 0) for i in sorted(chosen))
    plan = SellIntentPlan(book, refs)
    assert plan == SellIntentPlan(book, refs)
    assert len(plan.intents) == len(chosen)
    for intent in plan.intents:
        assert intent.sell_qty == expected[intent.cycle_ref]
        assert intent.total_base_commitment == intent.confirmed_net_base_qty
        assert intent.unreserved_base_qty == q(0)
    validate_sell_intent_plan_against_book(plan, book)
    for cell in chosen:
        changed = dataclasses.replace(
            book, reservations=tuple(r for r in book.reservations if r.cycle_ref.cell_index != cell)
        )
        result = sell_intent_plan_freshness(plan, changed)
        assert result.findings == (
            SellIntentStaleFinding(CellCycleRef(cell, 0), R.RESERVATION_MISSING),
        )


@settings(max_examples=80, deadline=None, derandomize=True)
@given(cell=st.integers(min_value=0, max_value=2), cycles=st.integers(min_value=1, max_value=12))
def test_generated_historical_refs_are_never_authorized(cell: int, cycles: int) -> None:
    book = held((0, 1, 2))
    plan = build_sell_intent_for_cell(book, CellCycleRef(cell, 0))
    funded = advance_cycle_synthetically(book.funded_buy_book, cell)
    state = funded.lifecycle.grid_state
    target = dataclasses.replace(state.cells[cell], cycle_seq=cycles)
    cells = (*state.cells[:cell], target, *state.cells[cell + 1 :])
    funded = dataclasses.replace(
        funded,
        lifecycle=dataclasses.replace(
            funded.lifecycle, grid_state=dataclasses.replace(state, cells=cells)
        ),
    )
    kept = tuple(r for r in book.reservations if r.cycle_ref.cell_index != cell)
    current = SellInventoryBook(funded, kept)
    assert sell_intent_plan_freshness(plan, current).findings == (
        SellIntentStaleFinding(CellCycleRef(cell, 0), R.CYCLE_ADVANCED),
    )
