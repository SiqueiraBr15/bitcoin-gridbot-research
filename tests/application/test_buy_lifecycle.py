from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.application import (
    BuyAttempt,
    BuyAttemptStatus,
    BuyLifecycleBook,
    BuyLifecycleError,
    BuyLifecycleErrorCode,
    bind_buy_execution,
    consume_finalized_buy,
    mark_submission_uncertain,
    prepare_buy,
)
from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Symbol,
)
from gridbot.portfolio import (
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    SellSizingStatus,
    assess_sell_sizing,
    finalize_buy,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    BuyIntentPlan,
    CellCycleRef,
    CellPhase,
    GridBuyIntent,
    GridState,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

E = BuyLifecycleErrorCode
S = BuyExecutionStatus
BNB = Asset("BNB")
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


RULES = MarketRules(BTCUSDT, PriceRules(p(1)), QuantityRules(q("0.001"), q("0.001")))


def state(reference: str = "105") -> GridState:
    plan = build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(100), p(110), 5), RULES)
    return bootstrap_grid_state(plan, p(reference))


def plan_for(s: GridState, budget: str = "10") -> BuyIntentPlan:
    return build_buy_intents(s, size_grid_buys(s, RULES, Money.parse(budget, USDT)))


STATE = state()  # células 0, 1, 2 armadas (buy 100, 102, 104)
PLAN = plan_for(STATE)  # qty 0.032 por célula
BOOK = BuyLifecycleBook(STATE)


def intent(cell: int, plan: BuyIntentPlan = PLAN) -> GridBuyIntent:
    return next(i for i in plan.intents if i.cycle_ref.cell_index == cell)


def ref(cell: int, cycle: int = 0) -> CellCycleRef:
    return CellCycleRef(cell, cycle)


def ctx(cell: int, exec_ref: str | None = None, plan: BuyIntentPlan = PLAN) -> BuyExecutionContext:
    return BuyExecutionContext(intent(cell, plan), BuyExecutionRef(exec_ref or f"exec-{cell}"))


def fill(
    cell: int, fill_ref: str, qty: str, fee: str = "0", asset: Asset = USDT
) -> ObservedBuyFill:
    i = intent(cell)
    return ObservedBuyFill(
        fill_ref,
        i.cycle_ref,
        BTCUSDT,
        i.price,
        q(qty),
        Money.parse(fee, asset),
        LiquidityRole.MAKER,
    )


def finalized(
    context: BuyExecutionContext, *fills: ObservedBuyFill, status: BuyExecutionStatus | None = None
) -> FinalizedBuy:
    led = BuyFillLedger(context.intent)
    for f in fills:
        led = led.record(f)
    final = status or (S.FILLED if led.is_fully_filled else S.CANCELED)
    refs = tuple(f.fill_ref for f in led.fills)
    gross = led.gross_filled_qty
    report = ObservedBuyTerminalReport(
        context.execution_ref, BTCUSDT, context.cycle_ref, final, gross, refs
    )
    evidence = BuyFillReconciliationEvidence(
        context.execution_ref, BTCUSDT, context.cycle_ref, gross, refs
    )
    return finalize_buy(context, led, report, evidence)


def bound(book: BuyLifecycleBook, cell: int) -> BuyLifecycleBook:
    return bind_buy_execution(prepare_buy(book, PLAN, ref(cell)), ref(cell), ctx(cell))


def expect_error(code: BuyLifecycleErrorCode, fn: Any) -> BuyLifecycleError:
    with pytest.raises(BuyLifecycleError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ preparação


def test_initial_book_is_valid() -> None:
    assert BOOK.attempts == ()
    assert BOOK.consumed == ()
    assert BOOK.grid_state is STATE


def test_prepare_current_buy() -> None:
    book = prepare_buy(BOOK, PLAN, ref(1))
    attempt = book.attempt_for(ref(1))
    assert attempt is not None
    assert attempt.status is BuyAttemptStatus.PREPARED
    assert attempt.intent == intent(1)
    assert attempt.execution is None
    assert book.grid_state == STATE  # PREPARED não altera GridState
    assert book.grid_state is STATE


def test_stale_plan_is_rejected() -> None:
    stale = plan_for(state("110"))  # plano de outro estado (5 células armadas)
    expect_error(E.STALE_INTENT_PLAN, lambda: prepare_buy(BOOK, stale, ref(0)))


@pytest.mark.parametrize(
    ("cycle_ref", "code"),
    [
        (ref(3), E.CELL_NOT_BUYABLE),  # buy 106 >= referência 105: não armada
        (ref(9), E.UNKNOWN_CELL),
        (ref(0, 1), E.CYCLE_MISMATCH),
    ],
)
def test_prepare_rejects_invalid_cells(
    cycle_ref: CellCycleRef, code: BuyLifecycleErrorCode
) -> None:
    expect_error(code, lambda: prepare_buy(BOOK, PLAN, cycle_ref))


def test_double_preparation_is_blocked() -> None:
    book = prepare_buy(BOOK, PLAN, ref(0))
    expect_error(E.ATTEMPT_ALREADY_ACTIVE, lambda: prepare_buy(book, PLAN, ref(0)))


def test_concurrent_preparation_from_another_plan_is_blocked() -> None:
    other = plan_for(STATE, "20")  # mesmo ciclo, quantidade diferente (0.065)
    assert intent(0, other).qty != intent(0).qty
    book = prepare_buy(BOOK, PLAN, ref(0))
    expect_error(E.ATTEMPT_ALREADY_ACTIVE, lambda: prepare_buy(book, other, ref(0)))


# ------------------------------------------------------------------ vínculo


def test_bind_execution_context() -> None:
    book = bound(BOOK, 1)
    attempt = book.attempt_for(ref(1))
    assert attempt is not None
    assert attempt.status is BuyAttemptStatus.EXECUTION_BOUND
    assert attempt.execution == ctx(1)
    assert book.grid_state is STATE


def test_bind_rejects_context_of_another_intent() -> None:
    book = prepare_buy(BOOK, PLAN, ref(0))
    other_plan = plan_for(STATE, "20")
    expect_error(
        E.INTENT_MISMATCH, lambda: bind_buy_execution(book, ref(0), ctx(0, plan=other_plan))
    )
    expect_error(E.CYCLE_MISMATCH, lambda: bind_buy_execution(book, ref(0), ctx(1)))


def test_bind_rejects_reused_execution_ref() -> None:
    book = bound(prepare_buy(BOOK, PLAN, ref(1)), 0)
    expect_error(E.EXECUTION_REF_IN_USE, lambda: bind_buy_execution(book, ref(1), ctx(1, "exec-0")))


def test_bind_never_silently_replaces_and_repeat_is_noop() -> None:
    book = bound(BOOK, 0)
    assert bind_buy_execution(book, ref(0), ctx(0)) is book
    expect_error(
        E.EXECUTION_ALREADY_BOUND, lambda: bind_buy_execution(book, ref(0), ctx(0, "exec-x"))
    )


def test_bind_without_attempt_is_rejected() -> None:
    expect_error(E.ATTEMPT_NOT_FOUND, lambda: bind_buy_execution(BOOK, ref(0), ctx(0)))


# ------------------------------------------------------------------ SUBMISSION_UNCERTAIN


def test_submission_uncertain_blocks_preparation_and_has_no_retry() -> None:
    book = mark_submission_uncertain(prepare_buy(BOOK, PLAN, ref(2)), ref(2))
    attempt = book.attempt_for(ref(2))
    assert attempt is not None
    assert attempt.status is BuyAttemptStatus.SUBMISSION_UNCERTAIN
    expect_error(E.ATTEMPT_ALREADY_ACTIVE, lambda: prepare_buy(book, PLAN, ref(2)))
    expect_error(E.INVALID_TRANSITION, lambda: mark_submission_uncertain(book, ref(2)))
    public = {n for n in dir(book) if not n.startswith("_")}
    assert not {n for n in public if "retry" in n.lower() or "release" in n.lower()}


def test_uncertain_can_be_bound_only_with_explicit_context() -> None:
    book = mark_submission_uncertain(prepare_buy(BOOK, PLAN, ref(2)), ref(2))
    reconciled = bind_buy_execution(book, ref(2), ctx(2))
    attempt = reconciled.attempt_for(ref(2))
    assert attempt is not None
    assert attempt.status is BuyAttemptStatus.EXECUTION_BOUND


def test_bound_attempt_cannot_become_uncertain() -> None:
    book = bound(BOOK, 0)
    expect_error(E.INVALID_TRANSITION, lambda: mark_submission_uncertain(book, ref(0)))


# ------------------------------------------------------------------ consumo


@pytest.mark.parametrize(
    ("fills", "status", "net"),
    [
        ((("t1", "0.032", "0.000032", BTC),), S.FILLED, "0.031968"),
        ((("t1", "0.010", "0.00001", BTC),), S.CANCELED, "0.00999"),
        ((("t1", "0.005", "0", USDT),), S.EXPIRED, "0.005"),
    ],
)
def test_positive_finalization_moves_cell_to_waiting_sell(
    fills: tuple[tuple[str, str, str, Asset], ...], status: BuyExecutionStatus, net: str
) -> None:
    book = bound(BOOK, 2)
    fin = finalized(ctx(2), *(fill(2, r, qty, fee, a) for r, qty, fee, a in fills), status=status)
    after = consume_finalized_buy(book, fin)
    cell = after.grid_state.cell(2)
    assert (cell.phase, cell.cycle_seq, cell.buy_armed) == (CellPhase.WAITING_SELL, 0, False)
    assert after.attempt_for(ref(2)) is None
    assert after.consumed == (fin,)
    assert after.consumed_for(ref(2)) is fin
    assert after.consumed[0].net_acquired_base_qty == q(net)  # inventário, não a qty pretendida


def test_no_fill_disarms_without_cycle_change_or_retry() -> None:
    book = bound(BOOK, 1)
    fin = finalized(ctx(1), status=S.CANCELED)
    after = consume_finalized_buy(book, fin)
    cell = after.grid_state.cell(1)
    assert (cell.phase, cell.buy_armed, cell.cycle_seq) == (CellPhase.WAITING_BUY, False, 0)
    assert after.attempts == ()
    assert after.consumed == (fin,)
    # Sem retry: a célula não pode ser preparada de novo com um plano novo.
    expect_error(E.CELL_NOT_BUYABLE, lambda: prepare_buy(after, plan_for(after.grid_state), ref(1)))


@pytest.mark.parametrize("status", [S.EXPIRED, S.REJECTED])
def test_no_fill_from_other_terminal_statuses(status: BuyExecutionStatus) -> None:
    after = consume_finalized_buy(bound(BOOK, 0), finalized(ctx(0), status=status))
    assert not after.grid_state.cell(0).can_buy


def test_ledger_and_fees_stay_with_the_cycle() -> None:
    fin = finalized(
        ctx(0), fill(0, "t1", "0.020", "0.001", USDT), fill(0, "t2", "0.012", "0.00002", BNB)
    )
    after = consume_finalized_buy(bound(BOOK, 0), fin)
    kept = after.consumed_for(ref(0))
    assert kept is not None
    assert kept.ledger.fills == fin.ledger.fills
    assert kept.fees_by_asset == (Money.parse("0.00002", BNB), Money.parse("0.001", USDT))
    assert kept.has_unvalued_fees


def test_identical_finalization_is_noop() -> None:
    fin = finalized(ctx(0), fill(0, "t1", "0.032"))
    once = consume_finalized_buy(bound(BOOK, 0), fin)
    assert consume_finalized_buy(once, fin) is once
    assert once.grid_state.cell(0).cycle_seq == 0  # confirm_buy não aplicado duas vezes


def test_conflicting_finalization_is_rejected() -> None:
    once = consume_finalized_buy(bound(BOOK, 0), finalized(ctx(0), fill(0, "t1", "0.032")))
    other = finalized(ctx(0), fill(0, "t9", "0.010"))  # mesmo ciclo, conteúdo diferente
    expect_error(E.FINALIZATION_CONFLICT, lambda: consume_finalized_buy(once, other))


def test_finalization_without_attempt_is_rejected() -> None:
    expect_error(
        E.ATTEMPT_NOT_FOUND,
        lambda: consume_finalized_buy(BOOK, finalized(ctx(0), fill(0, "t1", "0.032"))),
    )


def test_finalization_of_unbound_attempt_is_rejected() -> None:
    book = prepare_buy(BOOK, PLAN, ref(0))
    expect_error(
        E.EXECUTION_NOT_BOUND,
        lambda: consume_finalized_buy(book, finalized(ctx(0), fill(0, "t1", "0.032"))),
    )


def test_finalization_with_wrong_execution_ref_is_rejected() -> None:
    book = bound(BOOK, 0)
    fin = finalized(ctx(0, "exec-other"), fill(0, "t1", "0.032"))
    expect_error(E.EXECUTION_REF_MISMATCH, lambda: consume_finalized_buy(book, fin))


def test_finalization_of_another_intent_is_rejected() -> None:
    book = bound(BOOK, 0)
    other_ctx = ctx(0, "exec-0", plan=plan_for(STATE, "20"))
    led_fill = ObservedBuyFill(
        "t1", ref(0), BTCUSDT, p(100), q("0.010"), Money.parse("0", USDT), LiquidityRole.MAKER
    )
    expect_error(
        E.INTENT_MISMATCH, lambda: consume_finalized_buy(book, finalized(other_ctx, led_fill))
    )


def test_finalization_of_another_cycle_is_rejected() -> None:
    # Tentativa do ciclo 0; a célula avança (estado externo) e nada combina mais.
    book = bound(BOOK, 0)
    fin = finalized(ctx(1), fill(1, "t1", "0.032"))  # finalização de outra célula
    expect_error(E.ATTEMPT_NOT_FOUND, lambda: consume_finalized_buy(book, fin))


def test_same_fill_ref_across_consumptions_is_rejected() -> None:
    book = bound(bound(BOOK, 0), 1)
    book = consume_finalized_buy(book, finalized(ctx(0), fill(0, "shared", "0.032")))
    err = expect_error(
        E.FILL_REF_ALREADY_CONSUMED,
        lambda: consume_finalized_buy(book, finalized(ctx(1), fill(1, "shared", "0.032"))),
    )
    assert "shared" in str(err)


# ------------------------------------------------------------------ várias células


def test_three_cells_coexist_and_finalize_independently() -> None:
    book = BOOK
    for cell in (0, 1, 2):
        book = prepare_buy(book, PLAN, ref(cell))
    assert book.active_cycle_refs == (ref(0), ref(1), ref(2))
    for cell in (0, 1, 2):
        book = bind_buy_execution(book, ref(cell), ctx(cell))

    book = consume_finalized_buy(book, finalized(ctx(1), fill(1, "t1", "0.032")))
    assert book.grid_state.cell(1).phase is CellPhase.WAITING_SELL
    assert book.active_cycle_refs == (ref(0), ref(2))  # nada apagado
    assert not PLAN.is_current_for(book.grid_state, PLAN.sizing)  # plano ficou stale...

    # ...mas as tentativas legitimamente preparadas antes continuam finalizáveis.
    book = consume_finalized_buy(book, finalized(ctx(0), fill(0, "t2", "0.010")))
    book = consume_finalized_buy(book, finalized(ctx(2), status=S.EXPIRED))
    assert book.attempts == ()
    assert [c.phase for c in book.grid_state.cells[:3]] == [
        CellPhase.WAITING_SELL,
        CellPhase.WAITING_SELL,
        CellPhase.WAITING_BUY,
    ]
    assert not book.grid_state.cell(2).can_buy
    assert [c.cycle_seq for c in book.grid_state.cells] == [0, 0, 0, 0, 0]


def test_positive_but_below_step_keeps_inventory_and_waiting_sell() -> None:
    fin = finalized(ctx(0), fill(0, "t1", "0.0008"))
    book = consume_finalized_buy(bound(BOOK, 0), fin)
    assert book.grid_state.cell(0).phase is CellPhase.WAITING_SELL
    assessment = assess_sell_sizing(fin, book.grid_state, RULES)
    assert assessment.eligibility_status is SellSizingStatus.BELOW_STEP
    assert assessment.step_residual_qty == q("0.0008")
    assert book.consumed[0].net_acquired_base_qty == q("0.0008")


# ------------------------------------------------------------------ invariantes do book


def test_tampered_books_are_rejected() -> None:
    fin = finalized(ctx(0), fill(0, "t1", "0.032"))
    consumed_book = consume_finalized_buy(bound(BOOK, 0), fin)
    eth_intent = GridBuyIntent(ref(0), ETHUSDT, p(100), q("0.032"))
    cases: list[dict[str, object]] = [
        {"attempts": (BuyAttempt(intent(0), BuyAttemptStatus.PREPARED),) * 2},
        {
            "attempts": (BuyAttempt(intent(0), BuyAttemptStatus.PREPARED),),
            "grid_state": STATE.disarm_buy(0),
        },
        {"attempts": (BuyAttempt(eth_intent, BuyAttemptStatus.PREPARED),)},
        {"grid_state": STATE.confirm_buy(1)},  # WAITING_SELL sem compra consumida
        {"consumed": (fin,)},  # consumo do ciclo atual com célula ainda WAITING_BUY armada
    ]
    for changes in cases:
        with pytest.raises(BuyLifecycleError) as excinfo:
            dataclasses.replace(BOOK, **cast(Any, changes))
        assert excinfo.value.code is E.INVALID_BOOK
    with pytest.raises(BuyLifecycleError) as excinfo:  # tentativa em ciclo já consumido
        dataclasses.replace(
            consumed_book, attempts=(BuyAttempt(intent(0), BuyAttemptStatus.PREPARED),)
        )
    assert excinfo.value.code is E.INVALID_BOOK
    with pytest.raises(BuyLifecycleError):  # mesmo execution_ref em dois registros
        dataclasses.replace(
            BOOK,
            attempts=(
                BuyAttempt(intent(0), BuyAttemptStatus.EXECUTION_BOUND, ctx(0, "dup")),
                BuyAttempt(intent(1), BuyAttemptStatus.EXECUTION_BOUND, ctx(1, "dup")),
            ),
        )


def test_attempt_status_and_execution_must_agree() -> None:
    with pytest.raises(BuyLifecycleError):
        BuyAttempt(intent(0), BuyAttemptStatus.EXECUTION_BOUND)
    with pytest.raises(BuyLifecycleError):
        BuyAttempt(intent(0), BuyAttemptStatus.PREPARED, ctx(0))
    with pytest.raises(BuyLifecycleError):
        BuyAttempt(intent(0), BuyAttemptStatus.EXECUTION_BOUND, ctx(1))
    with pytest.raises(TypeError):
        BuyLifecycleBook(STATE, cast(Any, [BuyAttempt(intent(0), BuyAttemptStatus.PREPARED)]))


def test_failed_operations_leave_book_unchanged() -> None:
    book = bound(BOOK, 0)
    snapshot = dataclasses.astuple(book)
    attempts: tuple[Callable[[], object], ...] = (
        lambda: prepare_buy(book, PLAN, ref(0)),
        lambda: bind_buy_execution(book, ref(0), ctx(0, "x")),
        lambda: consume_finalized_buy(book, finalized(ctx(0, "wrong"), fill(0, "t1", "0.032"))),
    )
    for fn in attempts:
        with pytest.raises(BuyLifecycleError):
            fn()
    assert dataclasses.astuple(book) == snapshot


def test_operations_are_deterministic() -> None:
    def run() -> BuyLifecycleBook:
        book = bound(bound(BOOK, 2), 0)
        return consume_finalized_buy(book, finalized(ctx(0), fill(0, "t1", "0.032")))

    assert run() == run()
    assert hash(run()) == hash(run())


def test_no_orders_sell_core_balance_or_persistence_in_api() -> None:
    for fn in (prepare_buy, bind_buy_execution, mark_submission_uncertain, consume_finalized_buy):
        params = set(inspect.signature(fn).parameters)
        assert not {"balance", "wallet", "core", "exchange", "port"} & params
    book = consume_finalized_buy(bound(BOOK, 0), finalized(ctx(0), fill(0, "t1", "0.032")))
    public = {n for n in dir(book) if not n.startswith("_")}
    assert not {n for n in public if any(w in n.lower() for w in ("sell", "order", "core", "save"))}


def test_buy_consumption_never_advances_cycle() -> None:
    book = BOOK
    for cell in (0, 1, 2):
        book = bound(book, cell)
    book = consume_finalized_buy(book, finalized(ctx(0), fill(0, "a", "0.032")))
    book = consume_finalized_buy(book, finalized(ctx(1), status=S.REJECTED))
    book = consume_finalized_buy(book, finalized(ctx(2), fill(2, "b", "0.001")))
    assert all(c.cycle_seq == 0 for c in book.grid_state.cells)


# ------------------------------------------------------------------ propriedades

OUTCOMES = st.sampled_from(["full", "partial", "none", "uncertain_then_full"])


@given(st.permutations([0, 1, 2]), st.lists(OUTCOMES, min_size=3, max_size=3))
def test_any_order_of_independent_cycles_keeps_invariants(
    order: list[int], outcomes: list[str]
) -> None:
    book = BOOK
    for cell in (0, 1, 2):
        book = prepare_buy(book, PLAN, ref(cell))
    for cell, outcome in zip(order, outcomes, strict=True):
        if outcome == "uncertain_then_full":
            book = mark_submission_uncertain(book, ref(cell))
        book = bind_buy_execution(book, ref(cell), ctx(cell))
    for cell, outcome in zip(order, outcomes, strict=True):
        if outcome == "none":
            fin = finalized(ctx(cell), status=S.CANCELED)
        elif outcome == "partial":
            fin = finalized(ctx(cell), fill(cell, f"f{cell}", "0.010"))
        else:
            fin = finalized(ctx(cell), fill(cell, f"f{cell}", "0.032"))
        book = consume_finalized_buy(book, fin)
        assert consume_finalized_buy(book, fin) is book  # repetir é no-op
    assert book.attempts == ()
    assert len(book.consumed) == 3
    for cell, outcome in zip(order, outcomes, strict=True):
        state_cell = book.grid_state.cell(cell)
        assert state_cell.cycle_seq == 0
        expected = CellPhase.WAITING_BUY if outcome == "none" else CellPhase.WAITING_SELL
        assert state_cell.phase is expected
        assert not state_cell.buy_armed


# ------------------------------------------------------------------ invariantes (construção direta)


def _finalized_for(i: GridBuyIntent, exec_ref: str, *fills: ObservedBuyFill) -> FinalizedBuy:
    return finalized(BuyExecutionContext(i, BuyExecutionRef(exec_ref)), *fills)


def _raw_fill(i: GridBuyIntent, fill_ref: str, qty: str = "0.032") -> ObservedBuyFill:
    return ObservedBuyFill(
        fill_ref,
        i.cycle_ref,
        i.symbol,
        i.price,
        q(qty),
        Money.parse("0", USDT),
        LiquidityRole.MAKER,
    )


def _expect_invalid_book(**fields: object) -> None:
    with pytest.raises(BuyLifecycleError) as excinfo:
        BuyLifecycleBook(**cast(Any, fields))
    assert excinfo.value.code is E.INVALID_BOOK


def test_book_rejects_two_consumptions_of_the_same_cycle() -> None:
    a = _finalized_for(intent(0), "exec-a", _raw_fill(intent(0), "a"))
    b = _finalized_for(intent(0), "exec-b", _raw_fill(intent(0), "b"))
    _expect_invalid_book(grid_state=STATE.confirm_buy(0), consumed=(a, b))


def test_book_rejects_fill_ref_shared_by_two_consumptions() -> None:
    a = _finalized_for(intent(0), "exec-a", _raw_fill(intent(0), "same"))
    b = _finalized_for(intent(1), "exec-b", _raw_fill(intent(1), "same"))
    _expect_invalid_book(grid_state=STATE.confirm_buy(0).confirm_buy(1), consumed=(a, b))


def test_book_rejects_attempt_for_missing_cell_or_wrong_price() -> None:
    missing = GridBuyIntent(ref(9), BTCUSDT, p(100), q("0.032"))
    wrong_price = GridBuyIntent(ref(0), BTCUSDT, p(101), q("0.032"))
    for i in (missing, wrong_price):
        _expect_invalid_book(grid_state=STATE, attempts=(BuyAttempt(i, BuyAttemptStatus.PREPARED),))


def test_book_rejects_consumption_of_other_symbol_missing_cell_or_future_cycle() -> None:
    eth = GridBuyIntent(ref(0), ETHUSDT, p(100), q("0.032"))
    missing = GridBuyIntent(ref(9), BTCUSDT, p(100), q("0.032"))
    future = GridBuyIntent(ref(0, 1), BTCUSDT, p(100), q("0.032"))
    eth_fin = finalize_buy(
        BuyExecutionContext(eth, BuyExecutionRef("exec-eth")),
        BuyFillLedger(eth),
        ObservedBuyTerminalReport(
            BuyExecutionRef("exec-eth"), ETHUSDT, ref(0), S.CANCELED, Qty.zero(), ()
        ),
        BuyFillReconciliationEvidence(BuyExecutionRef("exec-eth"), ETHUSDT, ref(0), Qty.zero(), ()),
    )
    for fin in (eth_fin, _finalized_for(missing, "exec-m"), _finalized_for(future, "exec-f")):
        _expect_invalid_book(grid_state=STATE, consumed=(fin,))


def test_operations_reject_raw_types() -> None:
    with pytest.raises(TypeError):
        prepare_buy(cast(Any, "book"), PLAN, ref(0))
    with pytest.raises(TypeError):
        prepare_buy(BOOK, PLAN, cast(Any, (0, 0)))
    with pytest.raises(TypeError):
        consume_finalized_buy(BOOK, cast(Any, 1.5))
