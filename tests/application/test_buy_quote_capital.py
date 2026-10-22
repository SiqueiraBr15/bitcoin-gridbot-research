from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.application import (
    BuyLifecycleBook,
    BuyLifecycleError,
    BuyLifecycleErrorCode,
    BuyQuoteCapitalError,
    BuyQuoteCapitalErrorCode,
    BuyQuoteReservation,
    FundedBuyBook,
    bind_funded_buy_execution,
    mark_funded_submission_uncertain,
    prepare_funded_buy,
    settle_funded_buy,
)
from gridbot.application.buy_quote_capital import _settlement_violation
from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    FloatNotAllowedError,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
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

D = Decimal
E = BuyQuoteCapitalErrorCode
L = BuyLifecycleErrorCode
S = BuyExecutionStatus
BNB = Asset("BNB")


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def usdt(raw: str) -> Money:
    return Money.parse(raw, USDT)


RULES = MarketRules(BTCUSDT, PriceRules(p(1)), QuantityRules(q("0.001"), q("0.001")))


def state(reference: str = "105") -> GridState:
    plan = build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(100), p(110), 5), RULES)
    return bootstrap_grid_state(plan, p(reference))


def plan_for(s: GridState, budget: str = "10") -> BuyIntentPlan:
    return build_buy_intents(s, size_grid_buys(s, RULES, Money.parse(budget, USDT)))


STATE = state()
PLAN = plan_for(STATE)  # células 0,1,2: buy 100/102/104 x 0.032


def book(capital: str = "10") -> FundedBuyBook:
    return FundedBuyBook(BuyLifecycleBook(STATE), usdt(capital))


def ref(cell: int, cycle: int = 0) -> CellCycleRef:
    return CellCycleRef(cell, cycle)


def intent(cell: int) -> GridBuyIntent:
    return next(i for i in PLAN.intents if i.cycle_ref.cell_index == cell)


def ctx(cell: int, exec_ref: str | None = None) -> BuyExecutionContext:
    return BuyExecutionContext(intent(cell), BuyExecutionRef(exec_ref or f"exec-{cell}"))


def fill(
    cell: int,
    fill_ref: str,
    qty: str,
    fee: str = "0",
    asset: Asset = USDT,
    price: str | None = None,
) -> ObservedBuyFill:
    i = intent(cell)
    return ObservedBuyFill(
        fill_ref,
        i.cycle_ref,
        BTCUSDT,
        p(price) if price else i.price,
        q(qty),
        Money.parse(fee, asset),
        LiquidityRole.MAKER,
    )


def finalized(
    cell: int, *fills: ObservedBuyFill, status: BuyExecutionStatus | None = None
) -> FinalizedBuy:
    context = ctx(cell)
    led = BuyFillLedger(context.intent)
    for f in fills:
        led = led.record(f)
    final = status or (S.FILLED if led.is_fully_filled else S.CANCELED)
    refs = tuple(f.fill_ref for f in led.fills)
    gross = led.gross_filled_qty
    return finalize_buy(
        context,
        led,
        ObservedBuyTerminalReport(
            context.execution_ref, BTCUSDT, context.cycle_ref, final, gross, refs
        ),
        BuyFillReconciliationEvidence(
            context.execution_ref, BTCUSDT, context.cycle_ref, gross, refs
        ),
    )


def prepared(b: FundedBuyBook, cell: int, fee: str = "0.010") -> FundedBuyBook:
    return prepare_funded_buy(b, PLAN, ref(cell), usdt(fee))


def bound(b: FundedBuyBook, cell: int, fee: str = "0.010") -> FundedBuyBook:
    return bind_funded_buy_execution(prepared(b, cell, fee), ref(cell), ctx(cell))


def assert_identity(b: FundedBuyBook) -> None:
    total = b.spent_quote + b.reserved_quote + b.available_quote
    assert total == b.initial_quote_capital
    for part in (b.spent_quote, b.reserved_quote, b.available_quote):
        assert not part.is_negative


def expect_error(code: BuyQuoteCapitalErrorCode, fn: Callable[[], object]) -> BuyQuoteCapitalError:
    with pytest.raises(BuyQuoteCapitalError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


def expect_lifecycle_error(code: BuyLifecycleErrorCode, fn: Callable[[], object]) -> None:
    with pytest.raises(BuyLifecycleError) as excinfo:
        fn()
    assert excinfo.value.code is code


# ------------------------------------------------------------------ capital inicial


@pytest.mark.parametrize("capital", ["0", "10"])
def test_empty_books(capital: str) -> None:
    b = book(capital)
    assert b.available_quote == usdt(capital)
    assert b.reserved_quote == usdt("0")
    assert b.spent_quote == usdt("0")
    assert_identity(b)


def test_capital_validation() -> None:
    lifecycle = BuyLifecycleBook(STATE)
    expect_error(E.QUOTE_ASSET_MISMATCH, lambda: FundedBuyBook(lifecycle, Money.parse("1", BTC)))
    expect_error(E.NEGATIVE_CAPITAL, lambda: FundedBuyBook(lifecycle, usdt("-0.01")))
    with pytest.raises(FloatNotAllowedError):
        FundedBuyBook(lifecycle, cast(Any, 10.0))


# ------------------------------------------------------------------ reservas


def test_reserve_one_buy() -> None:
    b = prepared(book(), 0)
    r = b.reservation_for(ref(0))
    assert r is not None
    assert (r.notional_hold, r.quote_fee_hold, r.total_hold) == (
        usdt("3.2"),
        usdt("0.010"),
        usdt("3.210"),
    )
    assert b.available_quote == usdt("6.790")
    assert b.lifecycle.attempt_for(ref(0)) is not None
    assert b.lifecycle.grid_state is STATE  # nenhuma compra executada
    assert_identity(b)


def test_mandatory_9_822_reserved_0_178_available() -> None:
    b = book("10")
    for cell in (0, 1, 2):
        b = prepared(b, cell, "0.010")
    holds = [b.reservation_for(ref(c)) for c in (0, 1, 2)]
    assert [h.notional_hold for h in holds if h] == [usdt("3.200"), usdt("3.264"), usdt("3.328")]
    notional = sum((h.notional_hold.amount for h in holds if h), D(0))
    fees = sum((h.quote_fee_hold.amount for h in holds if h), D(0))
    assert (notional, fees) == (D("9.792"), D("0.030"))
    assert b.reserved_quote == usdt("9.822")
    assert b.available_quote == usdt("0.178")
    assert b.reserved_quote.amount + b.available_quote.amount == D("10")
    assert b.spent_quote == usdt("0")
    assert_identity(b)


def test_double_spend_is_blocked() -> None:
    b = prepared(book("10"), 0, "2.8")  # 3.2 + 2.8 = 6.0 reservado; livre 4.0
    assert b.available_quote == usdt("4.0")
    err = expect_error(E.INSUFFICIENT_AVAILABLE_QUOTE, lambda: prepared(b, 1, "1.736"))  # pede 5.0
    assert "5.000" in str(err)
    reserved = b.reservation_for(ref(0))
    assert reserved is not None
    assert reserved.total_hold == usdt("6.0")  # primeira intacta


def test_fee_hold_can_make_full_plan_infeasible() -> None:
    b = prepared(prepared(book("9.792"), 0), 1)  # notional exato do sizing, sem folga p/ fee
    expect_error(E.INSUFFICIENT_AVAILABLE_QUOTE, lambda: prepared(b, 2))
    assert b.lifecycle.attempt_for(ref(2)) is None  # nada preparado nem reservado


def test_failed_preparation_is_atomic() -> None:
    b = book("3")  # não cobre 3.21
    before = dataclasses.astuple(b)
    expect_error(E.INSUFFICIENT_AVAILABLE_QUOTE, lambda: prepared(b, 0))
    assert dataclasses.astuple(b) == before
    assert b.lifecycle.attempts == ()


def test_preparation_validations_come_from_the_lifecycle() -> None:
    b = prepared(book(), 0)
    expect_lifecycle_error(L.ATTEMPT_ALREADY_ACTIVE, lambda: prepared(b, 0))
    expect_lifecycle_error(
        L.CYCLE_MISMATCH, lambda: prepare_funded_buy(b, PLAN, ref(1, 1), usdt("0"))
    )
    stale = plan_for(state("110"))
    expect_lifecycle_error(
        L.STALE_INTENT_PLAN, lambda: prepare_funded_buy(b, stale, ref(1), usdt("0"))
    )


def test_fee_reserve_validation() -> None:
    expect_error(
        E.QUOTE_ASSET_MISMATCH,
        lambda: prepare_funded_buy(book(), PLAN, ref(0), Money.parse("0", BTC)),
    )
    expect_error(
        E.NEGATIVE_FEE_RESERVE, lambda: prepare_funded_buy(book(), PLAN, ref(0), usdt("-0.01"))
    )
    with pytest.raises(FloatNotAllowedError):
        prepare_funded_buy(book(), PLAN, ref(0), cast(Any, 0.01))


def test_zero_fee_reserve_is_allowed_for_controlled_simulation() -> None:
    b = prepared(book(), 0, "0")
    assert b.reserved_quote == usdt("3.2")


def test_precision_overflow_is_an_error_not_a_rounding() -> None:
    b = book("1" + "0" * 31)  # available exigiria mais de 34 dígitos significativos
    expect_error(E.FINANCIAL_PRECISION_ERROR, lambda: prepared(b, 0, "0.0001"))
    assert b.reservations == ()


# ------------------------------------------------------------------ vínculo e incerteza


def test_binding_preserves_reservation() -> None:
    b = prepared(book(), 0)
    reservation = b.reservation_for(ref(0))
    after = bind_funded_buy_execution(b, ref(0), ctx(0))
    assert after.reservation_for(ref(0)) is reservation
    assert after.available_quote == b.available_quote
    assert bind_funded_buy_execution(after, ref(0), ctx(0)) is after  # vínculo repetido: no-op


def test_submission_uncertain_keeps_reservation_blocked() -> None:
    b = mark_funded_submission_uncertain(prepared(book(), 1), ref(1))
    assert b.reserved_quote == usdt("3.274")
    reconciled = bind_funded_buy_execution(b, ref(1), ctx(1))
    assert reconciled.reserved_quote == usdt("3.274")


# ------------------------------------------------------------------ settlement


def test_settle_full_buy() -> None:
    b = settle_funded_buy(bound(book(), 0), finalized(0, fill(0, "t1", "0.032", "0.0032")))
    assert b.spent_quote == usdt("3.2032")  # 3.2 notional + 0.0032 fee observada
    assert b.reserved_quote == usdt("0")
    assert b.available_quote == usdt("6.7968")
    assert b.lifecycle.grid_state.cell(0).phase is CellPhase.WAITING_SELL
    assert b.settled_reservations[0].cycle_ref == ref(0)
    assert_identity(b)


def test_settle_better_price_releases_unused_hold() -> None:
    b = bound(book(), 0)  # hold 3.200 + 0.010 = 3.210
    fin = finalized(0, fill(0, "t1", "0.032", "0.005", price="93.75"), status=S.FILLED)
    after = settle_funded_buy(b, fin)
    assert fin.ledger.gross_quote_notional == usdt("3.000")
    assert after.spent_quote == usdt("3.005")
    assert after.available_quote == usdt("6.995")  # 10 - 3.005: os 0.205 não usados voltaram
    assert after.available_quote.amount - b.available_quote.amount == D("0.205")


def test_settle_partial_canceled_buy() -> None:
    fin = finalized(0, fill(0, "t1", "0.010", "0.00001", BTC))
    after = settle_funded_buy(bound(book(), 0), fin)
    assert after.spent_quote == usdt("1.000")
    assert after.available_quote == usdt("9.000")
    cell = after.lifecycle.grid_state.cell(0)
    assert (cell.phase, cell.cycle_seq) == (CellPhase.WAITING_SELL, 0)
    assert after.lifecycle.consumed[0].net_acquired_base_qty == q("0.00999")


def test_no_fill_releases_everything() -> None:
    after = settle_funded_buy(bound(book(), 1), finalized(1, status=S.CANCELED))
    assert after.spent_quote == usdt("0")
    assert after.reserved_quote == usdt("0")
    assert after.available_quote == usdt("10")
    cell = after.lifecycle.grid_state.cell(1)
    assert (cell.phase, cell.buy_armed, cell.cycle_seq) == (CellPhase.WAITING_BUY, False, 0)
    assert after.lifecycle.attempts == ()  # nenhuma compra nova


@pytest.mark.parametrize(
    ("fee", "asset", "spent"),
    [("0.000032", BTC, "3.2"), ("0.00002", BNB, "3.2"), ("0.008", USDT, "3.208")],
)
def test_fee_assets_in_settlement(fee: str, asset: Asset, spent: str) -> None:
    after = settle_funded_buy(bound(book(), 0), finalized(0, fill(0, "t1", "0.032", fee, asset)))
    assert after.spent_quote == usdt(spent)  # BTC e BNB não viram custo em USDT


def test_quote_fee_above_hold_is_rejected_and_nothing_changes() -> None:
    b = bound(book(), 0, fee="0.010")
    before = dataclasses.astuple(b)
    fin = finalized(0, fill(0, "t1", "0.010", "0.011", USDT), status=S.CANCELED)
    # Notional 1.0 muito abaixo do hold de 3.2, mas a fee ultrapassa seu limite explícito.
    expect_error(E.QUOTE_FEE_EXCEEDS_HOLD, lambda: settle_funded_buy(b, fin))
    assert dataclasses.astuple(b) == before
    assert b.reservation_for(ref(0)) is not None


def test_notional_above_hold_guard() -> None:
    # Pelas invariantes da A8 (preço <= limite, qty <= pretendida) isso não ocorre com uma
    # FinalizedBuy válida; o guarda é verificado diretamente contra uma reserva menor.
    small = BuyQuoteReservation(GridBuyIntent(ref(0), BTCUSDT, p(100), q("0.010")), usdt("1"))
    expect_error(
        E.NOTIONAL_EXCEEDS_HOLD,
        lambda: _settlement_violation(small, finalized(0, fill(0, "t1", "0.032"))),
    )


def test_identical_settlement_is_noop() -> None:
    fin = finalized(0, fill(0, "t1", "0.032"))
    once = settle_funded_buy(bound(book(), 0), fin)
    assert settle_funded_buy(once, fin) is once
    assert once.spent_quote == usdt("3.2")  # debitado uma única vez


def test_conflicting_settlement_is_rejected() -> None:
    once = settle_funded_buy(bound(book(), 0), finalized(0, fill(0, "t1", "0.032")))
    other = finalized(0, fill(0, "t9", "0.010"))
    expect_lifecycle_error(L.FINALIZATION_CONFLICT, lambda: settle_funded_buy(once, other))


def test_settlement_requires_bound_attempt() -> None:
    b = prepared(book(), 0)
    expect_lifecycle_error(
        L.EXECUTION_NOT_BOUND, lambda: settle_funded_buy(b, finalized(0, fill(0, "t1", "0.032")))
    )


def test_cells_finalizing_out_of_order() -> None:
    b = book("10")
    for cell in (0, 1, 2):
        b = bound(b, cell)
    b = settle_funded_buy(b, finalized(2, fill(2, "c", "0.032", "0.003")))
    assert_identity(b)
    b = settle_funded_buy(b, finalized(0, status=S.EXPIRED))
    assert_identity(b)
    b = settle_funded_buy(b, finalized(1, fill(1, "a", "0.010")))
    assert_identity(b)
    assert b.reservations == ()
    assert b.spent_quote == usdt("4.351")  # 3.328 + 0.003 + 1.020
    assert b.available_quote == usdt("5.649")


# ------------------------------------------------------------------ construção direta / pureza


def test_tampered_funded_books_are_rejected() -> None:
    b = prepared(prepared(book(), 0), 1)
    r0, r1 = b.reservations
    other_intent = GridBuyIntent(ref(0), BTCUSDT, p(100), q("0.031"))
    settled = settle_funded_buy(bound(book(), 0), finalized(0, fill(0, "t1", "0.032")))
    cases: list[tuple[FundedBuyBook, dict[str, object]]] = [
        (b, {"reservations": (r0, r0, r1)}),  # duplicada
        (b, {"reservations": (r0,)}),  # tentativa sem reserva
        (book(), {"reservations": (r0,)}),  # reserva sem tentativa
        (
            b,
            {"reservations": (BuyQuoteReservation(other_intent, usdt("0.010")), r1)},
        ),  # notional adulterado
        (b, {"initial_quote_capital": usdt("6")}),  # reservado > capital
        (settled, {"settled_reservations": ()}),  # consumo sem reserva liquidada
        (settled, {"initial_quote_capital": usdt("3")}),  # gasto > capital
    ]
    for base, changes in cases:
        with pytest.raises(BuyQuoteCapitalError) as excinfo:
            dataclasses.replace(base, **cast(Any, changes))
        assert excinfo.value.code is E.INVALID_FUNDED_BOOK


def test_settled_reservation_must_match_and_respect_limits() -> None:
    settled = settle_funded_buy(
        bound(book(), 0, fee="0.010"), finalized(0, fill(0, "t1", "0.032", "0.005"))
    )
    tight = BuyQuoteReservation(intent(0), usdt("0.001"))  # fee observada 0.005 > 0.001
    wrong = BuyQuoteReservation(intent(1), usdt("0.010"))
    for res in (tight, wrong):
        with pytest.raises(BuyQuoteCapitalError) as excinfo:
            dataclasses.replace(settled, settled_reservations=(res,))
        assert excinfo.value.code is E.INVALID_FUNDED_BOOK


def test_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        FundedBuyBook(BuyLifecycleBook(STATE), usdt("10"), cast(Any, [1]))
    with pytest.raises(TypeError):
        BuyQuoteReservation(cast(Any, "intent"), usdt("0"))
    with pytest.raises(TypeError):
        settle_funded_buy(book(), cast(Any, "fin"))


def test_errors_never_change_the_book() -> None:
    b = bound(book(), 0)
    before = dataclasses.astuple(b)
    attempts: tuple[Callable[[], object], ...] = (
        lambda: prepared(b, 0),
        lambda: bind_funded_buy_execution(b, ref(0), ctx(0, "x")),
        lambda: settle_funded_buy(b, finalized(0, fill(0, "t1", "0.010", "1", USDT))),
    )
    for fn in attempts:
        with pytest.raises((BuyLifecycleError, BuyQuoteCapitalError)):
            fn()
    assert dataclasses.astuple(b) == before


def test_determinism() -> None:
    def run() -> FundedBuyBook:
        b = bound(bound(book(), 0), 2)
        return settle_funded_buy(b, finalized(0, fill(0, "t1", "0.032", "0.003")))

    assert run() == run()
    assert hash(run()) == hash(run())


def test_no_external_balance_orders_or_sell() -> None:
    for fn in (
        prepare_funded_buy,
        bind_funded_buy_execution,
        mark_funded_submission_uncertain,
        settle_funded_buy,
    ):
        params = set(inspect.signature(fn).parameters)
        assert not {"balance", "wallet", "exchange", "core"} & params
    public = {n for n in dir(book()) if not n.startswith("_")}
    assert not {
        n for n in public if any(w in n.lower() for w in ("sell", "order", "deposit", "withdraw"))
    }


# ------------------------------------------------------------------ propriedades

FEES = st.sampled_from(["0", "0.001", "0.010", "0.5"])
OUTCOMES = st.sampled_from(["full", "partial", "none", "better"])


@given(
    st.sampled_from(["3", "6.5", "9.822", "10", "20"]),
    st.permutations([0, 1, 2]),
    st.lists(FEES, min_size=3, max_size=3),
    st.lists(OUTCOMES, min_size=3, max_size=3),
)
def test_capital_identity_holds_through_any_sequence(
    capital: str, order: list[int], fees: list[str], outcomes: list[str]
) -> None:
    b = book(capital)
    prepared_cells = []
    for cell, fee in zip(order, fees, strict=True):
        need = intent(cell).price.notional(intent(cell).qty) + D(fee)
        if need > b.available_quote.amount:
            with pytest.raises(BuyQuoteCapitalError) as excinfo:
                bound(b, cell, fee)
            assert excinfo.value.code is E.INSUFFICIENT_AVAILABLE_QUOTE
            continue
        b = bound(b, cell, fee)
        prepared_cells.append(cell)
        assert_identity(b)
        assert len(b.reservations) == len(b.lifecycle.attempts)
    spent_before = b.spent_quote.amount
    for cell, outcome in zip(order, outcomes, strict=True):
        if cell not in prepared_cells:
            continue
        hold = b.reservation_for(ref(cell))
        assert hold is not None
        fee_cap = str(hold.quote_fee_hold.amount)
        if outcome == "none":
            fin = finalized(cell, status=S.CANCELED)
        elif outcome == "partial":
            fin = finalized(cell, fill(cell, f"f{cell}", "0.010", fee_cap))
        elif outcome == "better":
            fin = finalized(
                cell, fill(cell, f"f{cell}", "0.032", fee_cap, price="90"), status=S.FILLED
            )
        else:
            fin = finalized(cell, fill(cell, f"f{cell}", "0.032", fee_cap))
        b = settle_funded_buy(b, fin)
        assert settle_funded_buy(b, fin) is b  # liquidar de novo é no-op
        assert b.reservation_for(ref(cell)) is None
        assert b.spent_quote.amount == spent_before + fin.quote_debit_total.amount
        spent_before = b.spent_quote.amount
        assert_identity(b)
    assert b.reservations == ()
