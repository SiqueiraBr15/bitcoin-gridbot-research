"""A15: pipeline econômico real, coordenação, lifecycle e snapshots adversariais."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from decimal import Inexact, localcontext
from functools import partial
from typing import Any, cast

import pytest

from gridbot.application import (
    BuyLifecycleBook,
    BuyLifecycleError,
    BuyLifecycleErrorCode,
    FundedBuyBook,
    GridOperationalBook,
    SellAttempt,
    SellAttemptStatus,
    SellExecutionContext,
    SellExecutionRef,
    SellIntentError,
    SellIntentErrorCode,
    SellInventoryBook,
    SellInventoryError,
    SellLifecycleError,
    SellLifecycleErrorCode,
    bind_operational_buy_execution,
    bind_sell_execution,
    build_sell_intent_for_cell,
    build_sell_intents,
    mark_operational_buy_submission_uncertain,
    mark_sell_submission_uncertain,
    prepare_operational_buy,
    prepare_sell,
    reserve_operational_sell,
    settle_operational_buy,
    validate_operational_sell,
)
from gridbot.domain import (
    BTCUSDT,
    USDT,
    DomainError,
    FloatNotAllowedError,
    Money,
    OrderType,
    Side,
)
from gridbot.portfolio import (
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFinalizationError,
    finalize_buy,
)
from gridbot.strategy import CellCycleRef, build_buy_intents, size_grid_buys
from tests.application.test_sell_intents import (
    ETHUSDT,
    RULES,
    acquired,
    assessment,
    fingerprint,
    finish,
    forged,
    grid,
    held,
    p,
    prepare,
    q,
    rules,
)
from tests.application.test_sell_inventory import advance_cycle_synthetically, rebuy_in_new_cycle

E = SellLifecycleErrorCode
S = SellAttemptStatus


def ref(cell: int = 0, cycle: int = 0) -> CellCycleRef:
    return CellCycleRef(cell, cycle)


def prepared_root(cells: tuple[int, ...] = (0,)) -> GridOperationalBook:
    root = GridOperationalBook(held(cells))
    plan = build_sell_intents(root.inventory_book)
    for cell in cells:
        root = prepare_sell(root, plan, ref(cell))
    return root


def context(
    root: GridOperationalBook, cell: int = 0, value: str | None = None
) -> SellExecutionContext:
    attempt = root.attempt_for(root.grid_state.cells[cell].cycle_ref)
    assert attempt is not None
    return SellExecutionContext(attempt.intent, SellExecutionRef(value or f"sell-{cell}"))


def with_status(
    root: GridOperationalBook, status: SellAttemptStatus, cell: int = 0
) -> GridOperationalBook:
    if status is S.SUBMISSION_UNCERTAIN:
        return mark_sell_submission_uncertain(root, root.grid_state.cells[cell].cycle_ref)
    if status is S.EXECUTION_BOUND:
        return bind_sell_execution(root, root.grid_state.cells[cell].cycle_ref, context(root, cell))
    return root


def expect(code: SellLifecycleErrorCode, operation: Callable[[], object]) -> SellLifecycleError:
    with pytest.raises(SellLifecycleError) as info:
        operation()
    assert info.value.code is code
    assert code in str(info.value)
    return info.value


def buy_plan(root: GridOperationalBook) -> Any:
    state = root.grid_state
    return build_buy_intents(
        state, size_grid_buys(state, rules(state.plan.spec.symbol), Money.parse("5", USDT))
    )


def prepare_other_buy(root: GridOperationalBook, cell: int = 1) -> GridOperationalBook:
    return prepare_operational_buy(
        root, buy_plan(root), root.grid_state.cells[cell].cycle_ref, Money.parse("0.01", USDT)
    )


def buy_context(root: GridOperationalBook, cell: int = 1) -> BuyExecutionContext:
    attempt = root.inventory_book.funded_buy_book.lifecycle.attempt_for(
        root.grid_state.cells[cell].cycle_ref
    )
    assert attempt is not None
    return BuyExecutionContext(attempt.intent, BuyExecutionRef(f"new-buy-{cell}"))


def assert_preserved(old: GridOperationalBook, new: GridOperationalBook) -> None:
    for reservation in old.inventory_book.reservations:
        assert new.inventory_book.reservation_for(reservation.cycle_ref) is reservation
    for attempt in old.sell_attempts:
        assert new.attempt_for(attempt.cycle_ref) is attempt
    assert new.grid_state.cells[0] == old.grid_state.cells[0]
    funded = new.inventory_book.funded_buy_book
    assert (
        funded.initial_quote_capital
        == funded.spent_quote + funded.reserved_quote + funded.available_quote
    )
    validate_operational_sell(new, ref())


def test_empty_root_derives_state_from_one_source() -> None:
    inventory = SellInventoryBook(FundedBuyBook(BuyLifecycleBook(grid()), Money.parse("20", USDT)))
    root = GridOperationalBook(inventory)
    assert root.grid_state is inventory.grid_state
    assert root.sell_attempts == ()
    assert root.attempt_for(ref()) is None
    assert [f.name for f in dataclasses.fields(root)] == [
        "inventory_book",
        "sell_attempts",
        "external_sell_bindings",
    ]


def test_root_with_reservation_needs_no_sell_attempt_yet() -> None:
    root = GridOperationalBook(held())
    assert root.inventory_book.total_reserved_base_qty == q("0.0311")
    assert root.sell_attempts == ()


@pytest.mark.parametrize("status", list(S))
def test_direct_valid_root_in_each_lifecycle_state(status: SellAttemptStatus) -> None:
    root = with_status(prepared_root(), status)
    assert dataclasses.replace(root) == root
    attempt = root.attempt_for(ref())
    assert attempt is not None
    assert attempt.status is status
    validate_operational_sell(root, ref())


@pytest.mark.parametrize("bad", [None, "book", [], (), 42])
def test_root_rejects_wrong_inventory_type(bad: object) -> None:
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, cast(Any, bad)))


@pytest.mark.parametrize("bad", [[], [None], (None,), (q(1),), "attempts"])
def test_root_rejects_mutable_or_wrong_attempts(bad: object) -> None:
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, held(), cast(Any, bad)))


@pytest.mark.parametrize("bad", [None, "intent", q(1), BuyExecutionRef("buy"), 1.5])
def test_attempt_rejects_wrong_intent(bad: object) -> None:
    expect(E.INVALID_SELL_ATTEMPT, partial(SellAttempt, cast(Any, bad), S.PREPARED))


@pytest.mark.parametrize("bad", ["PREPARED", "CANCELED", "SETTLED", None, 1])
def test_attempt_rejects_unapproved_states(bad: object) -> None:
    intent = build_sell_intents(held()).intents[0]
    expect(E.INVALID_SELL_ATTEMPT, partial(SellAttempt, intent, cast(Any, bad)))


@pytest.mark.parametrize("state", [S.PREPARED, S.SUBMISSION_UNCERTAIN])
def test_unbound_state_cannot_carry_execution(state: SellAttemptStatus) -> None:
    root = prepared_root()
    ctx = context(root)
    expect(E.INVALID_SELL_ATTEMPT, partial(SellAttempt, ctx.intent, state, ctx))


def test_bound_state_requires_explicit_sell_context() -> None:
    expect(
        E.INVALID_SELL_ATTEMPT,
        partial(SellAttempt, build_sell_intents(held()).intents[0], S.EXECUTION_BOUND),
    )


def test_bound_attempt_rejects_context_of_another_cell() -> None:
    root = prepared_root((0, 1))
    expect(
        E.INVALID_SELL_ATTEMPT,
        partial(SellAttempt, context(root).intent, S.EXECUTION_BOUND, context(root, 1)),
    )


@pytest.mark.parametrize("bad", ["", " ", " x", "x ", "x" * 129, None, 1, BuyExecutionRef("buy")])
def test_external_sell_reference_is_structurally_checked(bad: object) -> None:
    expect(E.INVALID_SELL_EXECUTION_CONTEXT, partial(SellExecutionRef, cast(Any, bad)))


def test_sell_reference_is_opaque_and_distinct_from_buy() -> None:
    sell = SellExecutionRef("provider-account/123")
    assert str(sell) == "provider-account/123"
    assert sell != cast(object, BuyExecutionRef(sell.value))
    assert SellExecutionRef("x" * 128).value == "x" * 128


@pytest.mark.parametrize("field", ["intent", "execution_ref"])
def test_context_rejects_buy_objects(field: str) -> None:
    root = prepared_root()
    ctx = context(root)
    values: dict[str, Any] = {"intent": ctx.intent, "execution_ref": ctx.execution_ref}
    buy = prepare()
    attempt = buy.lifecycle.attempt_for(ref())
    assert attempt is not None
    assert attempt.execution is not None
    values[field] = attempt.intent if field == "intent" else attempt.execution.execution_ref
    expect(E.INVALID_SELL_EXECUTION_CONTEXT, partial(SellExecutionContext, **values))


def test_context_derives_exact_sell_order_fields() -> None:
    ctx = context(prepared_root())
    assert ctx.cycle_ref == ref()
    assert ctx.symbol == BTCUSDT
    assert ctx.side is Side.SELL
    assert ctx.order_type is OrderType.LIMIT
    assert ctx.limit_price == p(102)
    assert ctx.requested_qty == q("0.031")
    assert ctx.requested_qty != ctx.intent.total_base_commitment


@pytest.mark.parametrize("status", list(S))
def test_required_btc_and_quote_numbers_remain_unchanged(status: SellAttemptStatus) -> None:
    inventory = held()
    before = fingerprint(inventory)
    root = prepare_sell(GridOperationalBook(inventory), build_sell_intents(inventory), ref())
    after = with_status(root, status)
    assert fingerprint(after.inventory_book) == before
    assert after.inventory_book is inventory
    intent = after.sell_attempts[0].intent
    assert (
        intent.confirmed_net_base_qty,
        intent.sell_qty,
        intent.base_fee_hold,
        intent.total_base_commitment,
        intent.unreserved_base_qty,
    ) == tuple(q(v) for v in ("0.031968", "0.031", "0.0001", "0.0311", "0.000868"))
    assert after.grid_state is inventory.grid_state
    assert all(c.cycle_seq == 0 for c in after.grid_state.cells)


@pytest.mark.parametrize("status", list(S))
def test_second_preparation_always_fails(status: SellAttemptStatus) -> None:
    root = with_status(prepared_root(), status)
    before = hash(root)
    expect(
        E.SELL_ATTEMPT_ALREADY_EXISTS,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), ref()),
    )
    assert hash(root) == before


def test_partial_plan_does_not_authorize_an_unselected_reservation() -> None:
    root = GridOperationalBook(held((0, 1)))
    expect(
        E.SELL_INTENT_NOT_IN_PLAN,
        partial(prepare_sell, root, build_sell_intent_for_cell(root.inventory_book, ref(1)), ref()),
    )


def test_empty_plan_does_not_authorize_inventory() -> None:
    root = GridOperationalBook(acquired())
    expect(
        E.SELL_INTENT_NOT_IN_PLAN,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), ref()),
    )


@pytest.mark.parametrize("cycle_ref", [ref(0, 1), ref(0, 99), ref(4), ref(10)])
def test_future_or_unknown_identity_cannot_be_prepared(cycle_ref: CellCycleRef) -> None:
    root = GridOperationalBook(held())
    expect(
        E.SELL_INTENT_NOT_IN_PLAN,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), cycle_ref),
    )


@pytest.mark.parametrize("case", ["fee", "quantity", "price", "symbol", "origin", "missing"])
def test_stale_sell_plan_fails_without_regeneration(case: str) -> None:
    source = held()
    current = source
    if case == "fee":
        current = held(hold="0.0002")
    elif case == "quantity":
        current = acquired()
        from gridbot.application import reserve_sell_inventory

        current = reserve_sell_inventory(
            current, assessment(current, market_rules=rules(step="0.01")), q("0.0001")
        )
    elif case == "price":
        current = held(state=grid(upper=120))
    elif case == "symbol":
        current = held(state=grid(ETHUSDT))
    elif case == "origin":
        current = held(qty="0.03")
    else:
        current = SellInventoryBook(source.funded_buy_book)
    root = GridOperationalBook(current)
    before = fingerprint(current)
    with pytest.raises(SellIntentError) as info:
        prepare_sell(root, build_sell_intents(source), ref())
    assert info.value.code is SellIntentErrorCode.STALE_SELL_INTENT
    assert root.sell_attempts == ()
    assert fingerprint(current) == before


@pytest.mark.parametrize("case", ["duplicate", "mutable", "missing_source"])
def test_original_plan_is_revalidated(case: str) -> None:
    root = GridOperationalBook(held())
    plan = build_sell_intents(root.inventory_book)
    changes: dict[str, Any] = {"cycle_refs": (ref(), ref())}
    if case == "mutable":
        changes = {"cycle_refs": [ref()]}
    elif case == "missing_source":
        changes = {"book": SellInventoryBook(root.inventory_book.funded_buy_book)}
    with pytest.raises(SellIntentError, match="INVALID_SELL_INTENT_PLAN"):
        prepare_sell(root, forged(plan, **changes), ref())


@pytest.mark.parametrize("status", [S.PREPARED, S.SUBMISSION_UNCERTAIN])
def test_explicit_bind_is_operational_only(status: SellAttemptStatus) -> None:
    root = with_status(prepared_root(), status)
    before = fingerprint(root.inventory_book)
    ctx = context(root)
    after = bind_sell_execution(root, ref(), ctx)
    assert after.sell_attempts[0].status is S.EXECUTION_BOUND
    assert after.sell_attempts[0].execution is ctx
    assert fingerprint(after.inventory_book) == before
    assert bind_sell_execution(after, ref(), dataclasses.replace(ctx)) is after


def test_uncertainty_is_idempotent_and_blocks_reprepare() -> None:
    root = mark_sell_submission_uncertain(prepared_root(), ref())
    assert mark_sell_submission_uncertain(root, ref()) is root
    assert root.sell_attempts[0].execution is None
    expect(
        E.SELL_ATTEMPT_ALREADY_EXISTS,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), ref()),
    )


def test_bound_state_cannot_regress_to_uncertain() -> None:
    root = with_status(prepared_root(), S.EXECUTION_BOUND)
    expect(E.INVALID_TRANSITION, partial(mark_sell_submission_uncertain, root, ref()))


def test_bound_execution_cannot_be_replaced() -> None:
    root = with_status(prepared_root(), S.EXECUTION_BOUND)
    expect(
        E.SELL_EXECUTION_CONFLICT,
        partial(bind_sell_execution, root, ref(), context(root, value="different")),
    )


@pytest.mark.parametrize("operation", [mark_sell_submission_uncertain, validate_operational_sell])
def test_lifecycle_requires_existing_attempt(operation: Any) -> None:
    expect(E.SELL_ATTEMPT_NOT_FOUND, partial(operation, GridOperationalBook(held()), ref()))


def test_bind_requires_existing_attempt() -> None:
    root = prepared_root()
    expect(
        E.SELL_ATTEMPT_NOT_FOUND,
        partial(
            bind_sell_execution, GridOperationalBook(root.inventory_book), ref(), context(root)
        ),
    )


def test_execution_reference_cannot_be_shared_by_sell_cells() -> None:
    root = prepared_root((0, 1))
    root = bind_sell_execution(root, ref(), context(root, value="shared"))
    expect(
        E.SELL_EXECUTION_REF_ALREADY_USED,
        partial(bind_sell_execution, root, ref(1), context(root, 1, "shared")),
    )


@pytest.mark.parametrize(
    "variant", ["cell", "cycle", "symbol", "price", "quantity", "fee", "origin"]
)
def test_bind_requires_original_economic_authorization(variant: str) -> None:
    root = prepared_root((0, 1))
    if variant == "cell":
        ctx = context(root, 1)
    else:
        kw: dict[str, Any] = {}
        if variant == "cycle":
            state = grid()
            kw["state"] = dataclasses.replace(
                state, cells=tuple(dataclasses.replace(c, cycle_seq=1) for c in state.cells)
            )
        elif variant == "symbol":
            kw["state"] = grid(ETHUSDT)
        elif variant == "price":
            kw["state"] = grid(upper=120)
        elif variant == "fee":
            kw["hold"] = "0.0002"
        elif variant in {"quantity", "origin"}:
            kw["qty"] = "0.029" if variant == "quantity" else "0.0315"
        ctx = SellExecutionContext(
            build_sell_intents(held(**kw)).intents[0], SellExecutionRef("other")
        )
    expect(E.SELL_EXECUTION_CONFLICT, partial(bind_sell_execution, root, ref(), ctx))


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "fee",
        "quantity",
        "price",
        "symbol",
        "origin",
        "duplicate",
        "wrong_status",
        "bad_execution_ref",
    ],
)
def test_direct_root_revalidates_attempt_and_current_reservation(case: str) -> None:
    root = prepared_root()
    inventory = root.inventory_book
    attempts = root.sell_attempts
    if case == "missing":
        inventory = SellInventoryBook(inventory.funded_buy_book)
    elif case == "fee":
        inventory = held(hold="0.0002")
    elif case == "quantity":
        inventory = held(qty="0.029")
    elif case == "price":
        inventory = held(state=grid(upper=120))
    elif case == "symbol":
        inventory = held(state=grid(ETHUSDT))
    elif case == "origin":
        inventory = held(qty="0.0315")
    elif case == "duplicate":
        attempts = (*attempts, *attempts)
    elif case == "wrong_status":
        attempts = (forged(attempts[0], status="PREPARED"),)
    else:
        bound = with_status(root, S.EXECUTION_BOUND).sell_attempts[0]
        assert bound.execution is not None
        attempts = (
            forged(
                bound,
                execution=forged(
                    bound.execution, execution_ref=forged(bound.execution.execution_ref, value=" ")
                ),
            ),
        )
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, inventory, attempts))


def test_direct_root_rejects_duplicate_external_execution_refs() -> None:
    root = prepared_root((0, 1))
    attempts = tuple(
        SellAttempt(context(root, c).intent, S.EXECUTION_BOUND, context(root, c, "shared"))
        for c in (0, 1)
    )
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, root.inventory_book, attempts))


@pytest.mark.parametrize(
    "case", ["unconsumed", "phase", "historical", "forged_ledger", "forged_hold"]
)
def test_root_rejects_invalid_economic_sources(case: str) -> None:
    root = prepared_root()
    inventory = root.inventory_book
    if case == "unconsumed":
        inventory = forged(inventory, funded_buy_book=prepare())
    elif case == "phase":
        state = forged(inventory.grid_state, cells=grid().cells)
        funded = forged(
            inventory.funded_buy_book,
            lifecycle=forged(inventory.funded_buy_book.lifecycle, grid_state=state),
        )
        inventory = forged(inventory, funded_buy_book=funded)
    elif case == "historical":
        inventory = forged(
            inventory, funded_buy_book=advance_cycle_synthetically(inventory.funded_buy_book, 0)
        )
    elif case == "forged_ledger":
        source = inventory.reservations[0]
        buy = source.finalized_buy
        bad = forged(buy, ledger=forged(buy.ledger, fills=(*buy.ledger.fills, *buy.ledger.fills)))
        reservation = forged(source, assessment=forged(source.assessment, finalized_buy=bad))
        inventory = forged(inventory, reservations=(reservation,))
    else:
        inventory = forged(
            inventory, reservations=(forged(inventory.reservations[0], base_fee_hold=q(1)),)
        )
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, inventory, root.sell_attempts))


@pytest.mark.parametrize("status", list(S))
def test_full_other_cell_buy_to_sell_pipeline_preserves_prior_sell(
    status: SellAttemptStatus,
) -> None:
    root = with_status(prepared_root(), status)
    original = root
    old_plan = build_sell_intent_for_cell(root.inventory_book, ref())
    root = prepare_other_buy(root)
    assert_preserved(original, root)
    ctx = buy_context(root)
    root = bind_operational_buy_execution(root, ref(1), ctx)
    assert bind_operational_buy_execution(root, ref(1), ctx) is root
    assert_preserved(original, root)
    attempt = root.inventory_book.funded_buy_book.lifecycle.attempt_for(ref(1))
    assert attempt is not None
    qty = str(attempt.intent.qty.value)
    finalized = finish(root.inventory_book.funded_buy_book, 1, qty, "0.000032")
    root = settle_operational_buy(root, finalized)
    assert settle_operational_buy(root, finalized) is root
    assert_preserved(original, root)
    root = reserve_operational_sell(root, assessment(root.inventory_book, 1), q("0.0001"))
    assert_preserved(original, root)
    root = prepare_sell(root, build_sell_intent_for_cell(root.inventory_book, ref(1)), ref(1))
    root = bind_sell_execution(root, ref(1), context(root, 1))
    assert_preserved(original, root)
    from gridbot.application import validate_sell_intent_plan_against_book

    validate_sell_intent_plan_against_book(old_plan, root.inventory_book)
    assert root.sell_attempts[0] is original.sell_attempts[0]


def test_old_plan_after_independent_buy_is_still_preparable() -> None:
    root = GridOperationalBook(held())
    plan = build_sell_intents(root.inventory_book)
    root = prepare_other_buy(root)
    root = bind_operational_buy_execution(root, ref(1), buy_context(root))
    root = settle_operational_buy(root, finish(root.inventory_book.funded_buy_book, 1, "0.01", "0"))
    root = prepare_sell(root, plan, ref())
    assert root.sell_attempts[0].intent == plan.intents[0]


def test_buy_uncertainty_preserves_sell_commitment_and_requires_binding() -> None:
    original = prepared_root()
    root = prepare_other_buy(original)
    root = mark_operational_buy_submission_uncertain(root, ref(1))
    assert_preserved(original, root)
    root = bind_operational_buy_execution(root, ref(1), buy_context(root))
    assert_preserved(original, root)


def test_stale_buy_plan_is_refused_without_resizing() -> None:
    root = prepared_root()
    old = build_buy_intents(grid(), size_grid_buys(grid(), RULES, Money.parse("10", USDT)))
    with pytest.raises(BuyLifecycleError) as info:
        prepare_operational_buy(root, old, ref(1), Money.parse("0", USDT))
    assert info.value.code is BuyLifecycleErrorCode.STALE_INTENT_PLAN
    assert root.inventory_book.reserved_sell_qty == q("0.031")


def test_three_independent_sell_states_coexist_without_financial_effects() -> None:
    root = prepared_root((0, 1, 2))
    root = mark_sell_submission_uncertain(root, ref(1))
    root = bind_sell_execution(root, ref(2), context(root, 2))
    assert [a.status for a in root.sell_attempts] == [
        S.PREPARED,
        S.SUBMISSION_UNCERTAIN,
        S.EXECUTION_BOUND,
    ]
    assert root.inventory_book.total_reserved_base_qty == q("0.0933")
    assert root.inventory_book.unreserved_base_qty == q("0.002604")
    for c in range(3):
        validate_operational_sell(root, ref(c))


def test_coordinated_reservation_cannot_replace_or_duplicate_old_hold() -> None:
    root = prepared_root()
    with pytest.raises(SellInventoryError, match="RESERVATION_ALREADY_EXISTS"):
        reserve_operational_sell(root, assessment(root.inventory_book), q(0))
    assert root.inventory_book.reserved_base_fee_qty == q("0.0001")


@pytest.mark.parametrize("status", list(S))
def test_api_entry_revalidates_tampered_root(status: SellAttemptStatus) -> None:
    root = with_status(prepared_root(), status)
    bad = forged(root, inventory_book=SellInventoryBook(root.inventory_book.funded_buy_book))
    expect(E.INVALID_OPERATIONAL_BOOK, partial(mark_sell_submission_uncertain, bad, ref()))
    expect(E.INVALID_OPERATIONAL_BOOK, partial(bind_sell_execution, bad, ref(), context(root)))


@pytest.mark.parametrize("bad", [None, "root", [], 42])
def test_operation_refuses_raw_root_types(bad: object) -> None:
    with pytest.raises(TypeError):
        mark_sell_submission_uncertain(cast(Any, bad), ref())


def test_operation_refuses_float_and_raw_cycle_refs() -> None:
    root = prepared_root()
    with pytest.raises(FloatNotAllowedError):
        mark_sell_submission_uncertain(root, cast(Any, 1.5))
    with pytest.raises(TypeError):
        bind_sell_execution(root, cast(Any, (0, 0)), context(root))


@pytest.mark.parametrize("hold", ["0", "0.0001", "0.000968"])
def test_explicit_hold_is_preserved_without_affecting_order_qty(hold: str) -> None:
    inventory = held(hold=hold)
    root = prepare_sell(GridOperationalBook(inventory), build_sell_intents(inventory), ref())
    assert context(root).requested_qty == q("0.031")
    assert root.inventory_book.reserved_base_fee_qty == q(hold)


@pytest.mark.parametrize("hold", ["0.000969", "1"])
def test_no_core_or_other_cell_inventory_can_cover_insufficient_hold(hold: str) -> None:
    root = GridOperationalBook(acquired((0, 1, 2)))
    with pytest.raises(SellInventoryError, match="INSUFFICIENT_BASE_INVENTORY"):
        reserve_operational_sell(root, assessment(root.inventory_book), q(hold))
    assert root.inventory_book.reservations == ()


@pytest.mark.parametrize("hold", ["1e-100", "1e1000000"])
def test_precision_error_is_preserved_through_root_and_attempt(hold: str) -> None:
    root = prepared_root()
    reservation = forged(root.inventory_book.reservations[0], base_fee_hold=q(hold))
    inventory = forged(root.inventory_book, reservations=(reservation,))
    expect(E.FINANCIAL_PRECISION_ERROR, partial(GridOperationalBook, inventory))
    intent = forged(root.sell_attempts[0].intent, reservation=reservation)
    expect(E.FINANCIAL_PRECISION_ERROR, partial(SellAttempt, intent, S.PREPARED))
    expect(
        E.FINANCIAL_PRECISION_ERROR,
        partial(SellExecutionContext, intent, SellExecutionRef("observed")),
    )


def test_low_ambient_precision_never_rounds_operational_finances() -> None:
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        root = with_status(prepared_root(), S.SUBMISSION_UNCERTAIN)
        root = bind_sell_execution(root, ref(), context(root))
        assert root.inventory_book.unreserved_base_qty == q("0.000868")
        assert ctx.prec == 2


@pytest.mark.parametrize(
    "quantity", ["0.001", "0.001000001", "0.03100000000000000000000000000000001"]
)
def test_step_boundaries_preserve_exact_residual(quantity: str) -> None:
    from gridbot.application import reserve_sell_inventory, settle_funded_buy

    funded = dataclasses.replace(prepare(), initial_quote_capital=Money.parse("10", USDT))
    funded = settle_funded_buy(funded, finish(funded, qty=quantity, fee="0"))
    inventory = SellInventoryBook(funded)
    inventory = reserve_sell_inventory(inventory, assessment(inventory), q(0))
    root = prepare_sell(GridOperationalBook(inventory), build_sell_intents(inventory), ref())
    intent = root.sell_attempts[0].intent
    assert intent.sell_qty + intent.unreserved_base_qty == q(quantity)


def test_open_partial_buy_does_not_authorize_sell() -> None:
    funded = prepare()
    buy = finish(funded, qty="0.02")
    report = dataclasses.replace(
        buy.terminal_report, final_status=BuyExecutionStatus.PARTIALLY_FILLED_OPEN
    )
    with pytest.raises(BuyFinalizationError, match="NOT_TERMINAL"):
        finalize_buy(buy.context, buy.ledger, report, buy.reconciliation_evidence)
    root = GridOperationalBook(SellInventoryBook(funded))
    expect(
        E.SELL_INTENT_NOT_IN_PLAN,
        partial(prepare_sell, root, build_sell_intents(root.inventory_book), ref()),
    )


def test_old_inventory_and_old_plan_cannot_authorize_current_cycle() -> None:
    first = held()
    funded = rebuy_in_new_cycle(advance_cycle_synthetically(first.funded_buy_book, 0))
    current = SellInventoryBook(funded)
    root = reserve_operational_sell(GridOperationalBook(current), assessment(current), q("0.0001"))
    with pytest.raises(SellIntentError, match="STALE_SELL_INTENT"):
        prepare_sell(root, build_sell_intents(first), ref())
    root = prepare_sell(root, build_sell_intents(root.inventory_book), ref(0, 1))
    assert root.inventory_book.confirmed_net_base_qty == q("0.031968")
    assert len(root.sell_attempts) == 1


def test_snapshot_outside_api_can_still_drop_obligations_known_limit() -> None:
    root = prepared_root()
    outside = GridOperationalBook(SellInventoryBook(root.inventory_book.funded_buy_book))
    assert outside.sell_attempts == ()
    assert outside.inventory_book.reservations == ()
    assert root.inventory_book.total_reserved_base_qty == q("0.0311")
    expect(
        E.INVALID_OPERATIONAL_BOOK,
        partial(GridOperationalBook, outside.inventory_book, root.sell_attempts),
    )


def test_all_a15_values_are_frozen_slotted_and_hashable() -> None:
    root = prepared_root()
    ctx = context(root)
    for value in (root, root.sell_attempts[0], ctx, ctx.execution_ref):
        assert not hasattr(value, "__dict__")
        assert isinstance(hash(value), int)
        field = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field, getattr(value, field))


def test_failure_does_not_change_root_or_original_plan() -> None:
    root = prepared_root((0, 1))
    before = dataclasses.astuple(root)
    plan = build_sell_intents(root.inventory_book)
    for operation in (
        partial(prepare_sell, root, plan, ref()),
        partial(bind_sell_execution, root, ref(), context(root, 1)),
    ):
        with pytest.raises(DomainError):
            operation()
        assert dataclasses.astuple(root) == before
    assert plan == build_sell_intents(root.inventory_book)


def test_no_generic_release_settlement_or_cycle_advancement_api() -> None:
    import inspect

    import gridbot.application.operational_grid as module

    for name, fn in vars(module).items():
        if inspect.isfunction(fn) and fn.__module__ == module.__name__ and not name.startswith("_"):
            assert not {
                "new_funded_buy_book",
                "new_sell_inventory_book",
                "qty",
                "price",
                "wallet",
            } & set(inspect.signature(fn).parameters)
    assert not hasattr(module, "confirm_sell")
    assert not hasattr(module, "settle_sell")
    assert not hasattr(module, "release_sell")


def test_deep_revalidation_covers_buy_sources_without_sell_reservation() -> None:
    inventory = acquired()
    finalized = inventory.funded_buy_book.lifecycle.consumed[0]
    bad = forged(
        finalized,
        terminal_report=dataclasses.replace(
            finalized.terminal_report, final_status=BuyExecutionStatus.OPEN
        ),
    )
    lifecycle = forged(inventory.funded_buy_book.lifecycle, consumed=(bad,))
    funded = forged(inventory.funded_buy_book, lifecycle=lifecycle)
    expect(
        E.INVALID_OPERATIONAL_BOOK,
        partial(GridOperationalBook, forged(inventory, funded_buy_book=funded)),
    )


def test_deep_revalidation_covers_unsettled_buy_attempts() -> None:
    funded = prepare()
    attempt = funded.lifecycle.attempts[0]
    bad = forged(attempt, status="EXECUTION_BOUND")
    funded = forged(funded, lifecycle=forged(funded.lifecycle, attempts=(bad,)))
    expect(
        E.INVALID_OPERATIONAL_BOOK,
        partial(GridOperationalBook, forged(SellInventoryBook(prepare()), funded_buy_book=funded)),
    )


@pytest.mark.parametrize("case", ["fill_side", "fill_ref", "liquidity", "cycle_type"])
def test_nested_buy_sources_are_revalidated_even_without_sell_hold(case: str) -> None:
    inventory = acquired()
    original = inventory.funded_buy_book.lifecycle.consumed[0]
    fill = original.ledger.fills[0]
    if case == "fill_side":
        fill = forged(fill, side=Side.SELL)
    elif case == "fill_ref":
        fill = forged(fill, fill_ref=" ")
    elif case == "liquidity":
        fill = forged(fill, liquidity="MAKER")
    else:
        cycle = forged(fill.cycle_ref, cycle_seq=True)
        fill = forged(fill, cycle_ref=cycle)
    ledger = forged(original.ledger, fills=(fill,))
    bad = forged(original, ledger=ledger)
    lifecycle = forged(inventory.funded_buy_book.lifecycle, consumed=(bad,))
    funded = forged(inventory.funded_buy_book, lifecycle=lifecycle)
    expect(
        E.INVALID_OPERATIONAL_BOOK,
        partial(GridOperationalBook, forged(inventory, funded_buy_book=funded)),
    )


@pytest.mark.parametrize("case", ["price", "quantity"])
def test_equal_buy_origin_does_not_authorize_altered_sell_terms(case: str) -> None:
    from gridbot.application import reserve_sell_inventory
    from tests.application.test_sell_inventory import regrid

    root = prepared_root()
    if case == "price":
        # A BUY da célula 0 continua 100; só SELL muda de 102 para 103.
        inventory = SellInventoryBook(regrid(root.inventory_book, upper=115))
        candidate = assessment(inventory)
    else:
        inventory = SellInventoryBook(root.inventory_book.funded_buy_book)
        candidate = assessment(inventory, market_rules=rules(step="0.01"))
    inventory = reserve_sell_inventory(inventory, candidate, q("0.0001"))
    intent = build_sell_intents(inventory).intents[0]
    assert intent.finalized_buy == root.sell_attempts[0].intent.finalized_buy
    ctx = SellExecutionContext(intent, SellExecutionRef("same-origin-other-terms"))
    expect(E.SELL_EXECUTION_CONFLICT, partial(bind_sell_execution, root, ref(), ctx))
    expect(E.INVALID_OPERATIONAL_BOOK, partial(GridOperationalBook, inventory, root.sell_attempts))


def test_full_plan_with_another_stale_cell_cannot_authorize_selected_cell() -> None:
    source = held((0, 1))
    current = dataclasses.replace(source, reservations=(source.reservations[0],))
    root = GridOperationalBook(current)
    with pytest.raises(SellIntentError, match="STALE_SELL_INTENT"):
        prepare_sell(root, build_sell_intents(source), ref())
    root = prepare_sell(root, build_sell_intent_for_cell(source, ref()), ref())
    assert root.sell_attempts[0].cycle_ref == ref()
