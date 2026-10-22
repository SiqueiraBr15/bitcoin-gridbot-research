from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from decimal import Decimal, Inexact
from functools import partial
from itertools import permutations
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.application import (
    BuyLifecycleBook,
    FundedBuyBook,
    SellBaseInventoryReservation,
    SellInventoryBook,
    SellInventoryError,
    SellInventoryErrorCode,
    bind_funded_buy_execution,
    prepare_funded_buy,
    reserve_sell_inventory,
    settle_funded_buy,
    settle_inventory_book_buy,
)
from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    DomainError,
    FloatNotAllowedError,
    LiquidityRole,
    MarketRules,
    Money,
    NotionalRules,
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
    SellSizingAssessment,
    SellSizingStatus,
    assess_sell_sizing,
    finalize_buy,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    CellPhase,
    GridState,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

D = Decimal
E = SellInventoryErrorCode


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str | int) -> Qty:
    return Qty.parse(raw)


def rules(symbol: Symbol = BTCUSDT, step: str = "0.001") -> MarketRules:
    return MarketRules(symbol, PriceRules(p(1)), QuantityRules(q(step), q(step)))


RULES = rules()


def grid(
    symbol: Symbol = BTCUSDT,
    lower: int = 100,
    upper: int = 110,
    intervals: int = 5,
    cycle: int = 0,
) -> GridState:
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(symbol, p(lower), p(upper), intervals), rules(symbol)
    )
    state = bootstrap_grid_state(plan, p(105))
    return dataclasses.replace(
        state, cells=tuple(dataclasses.replace(c, cycle_seq=cycle) for c in state.cells)
    )


def prepare(cells: tuple[int, ...] = (0,), state: GridState | None = None) -> FundedBuyBook:
    state = state or grid()
    symbol = state.plan.spec.symbol
    funded = FundedBuyBook(BuyLifecycleBook(state), Money.parse("20", symbol.quote))
    plan = build_buy_intents(
        state, size_grid_buys(state, rules(symbol), Money.parse("10", symbol.quote))
    )
    for cell in cells:
        ref = state.cells[cell].cycle_ref
        funded = prepare_funded_buy(funded, plan, ref, Money.parse("0.01", symbol.quote))
        attempt = funded.lifecycle.attempt_for(ref)
        assert attempt is not None
        context = BuyExecutionContext(attempt.intent, BuyExecutionRef(f"buy-{cell}"))
        funded = bind_funded_buy_execution(funded, ref, context)
    return funded


def finish(
    funded: FundedBuyBook,
    cell: int = 0,
    qty: str | None = "0.032",
    fee: str = "0.000032",
    asset: Asset | None = None,
    suffix: str = "",
) -> FinalizedBuy:
    ref = funded.lifecycle.grid_state.cells[cell].cycle_ref
    attempt = funded.lifecycle.attempt_for(ref)
    assert attempt is not None
    assert attempt.execution is not None
    context = attempt.execution
    ledger = BuyFillLedger(context.intent)
    symbol = context.symbol
    if qty is not None:
        ledger = ledger.record(
            ObservedBuyFill(
                f"fill-{cell}{suffix}",
                ref,
                symbol,
                context.intent.price,
                q(qty),
                Money.parse(fee, asset or symbol.base),
                LiquidityRole.TAKER,
            )
        )
    status = BuyExecutionStatus.FILLED if ledger.is_fully_filled else BuyExecutionStatus.CANCELED
    refs = tuple(f.fill_ref for f in ledger.fills)
    gross = ledger.gross_filled_qty
    return finalize_buy(
        context,
        ledger,
        ObservedBuyTerminalReport(context.execution_ref, symbol, ref, status, gross, refs),
        BuyFillReconciliationEvidence(context.execution_ref, symbol, ref, gross, refs),
    )


def acquired(
    cells: tuple[int, ...] = (0,),
    qty: str | None = "0.032",
    fee: str = "0.000032",
    state: GridState | None = None,
    asset: Asset | None = None,
) -> SellInventoryBook:
    funded = prepare(cells, state)
    for cell in cells:
        funded = settle_funded_buy(funded, finish(funded, cell, qty, fee, asset))
    return SellInventoryBook(funded)


def assessment(
    book: SellInventoryBook, cell: int = 0, market_rules: MarketRules | None = None
) -> SellSizingAssessment:
    ref = book.grid_state.cells[cell].cycle_ref
    buy = book.funded_buy_book.lifecycle.consumed_for(ref)
    assert buy is not None
    return assess_sell_sizing(buy, book.grid_state, market_rules or rules(buy.symbol))


def expect_error(
    code: SellInventoryErrorCode, operation: Callable[[], object]
) -> SellInventoryError:
    with pytest.raises(SellInventoryError) as info:
        operation()
    assert info.value.code is code
    assert code in str(info.value)
    return info.value


def assert_identity(book: SellInventoryBook) -> None:
    assert book.total_reserved_base_qty == book.reserved_sell_qty + book.reserved_base_fee_qty
    assert book.confirmed_net_base_qty == book.total_reserved_base_qty + book.unreserved_base_qty
    assert len({r.cycle_ref for r in book.reservations}) == len(book.reservations)
    for reservation in book.reservations:
        assert reservation.reserved_sell_qty > q(0)
        assert reservation.total_reserved_base_qty <= reservation.confirmed_net_base_qty
        assert (
            reservation.total_reserved_base_qty + reservation.unreserved_base_qty
            == reservation.confirmed_net_base_qty
        )
        assert reservation.finalized_buy in book.funded_buy_book.lifecycle.consumed


def regrid(book: SellInventoryBook, lower: int = 100, upper: int = 110) -> FundedBuyBook:
    old = book.grid_state
    updated = grid(lower=lower, upper=upper)
    updated = dataclasses.replace(
        updated,
        cells=tuple(
            dataclasses.replace(c, cell=n.cell)
            for c, n in zip(old.cells, updated.cells, strict=True)
        ),
    )
    return dataclasses.replace(
        book.funded_buy_book,
        lifecycle=dataclasses.replace(book.funded_buy_book.lifecycle, grid_state=updated),
    )


def forged(source: object, **changes: object) -> Any:
    """Simula construção que ignorou __post_init__, somente nos testes de adulteração."""
    result = object.__new__(type(source))
    for field in dataclasses.fields(cast(Any, source)):
        object.__setattr__(result, field.name, changes.get(field.name, getattr(source, field.name)))
    return result


def test_empty_book_has_zero_quantities_and_no_independent_state() -> None:
    funded = FundedBuyBook(BuyLifecycleBook(grid()), Money.parse("20", USDT))
    book = SellInventoryBook(funded)
    assert book.grid_state is funded.lifecycle.grid_state
    assert book.reservation_for(CellCycleRef(0, 0)) is None
    assert book.confirmed_net_base_qty == book.unreserved_base_qty == q(0)
    assert book.total_reserved_base_qty == q(0)
    assert [f.name for f in dataclasses.fields(book)] == ["funded_buy_book", "reservations"]
    assert_identity(book)


def test_required_exact_example_preserves_residual_and_sources() -> None:
    before = acquired()
    source = assessment(before)
    after = reserve_sell_inventory(before, source, q("0.000100"))
    hold = after.reservations[0]
    assert hold.confirmed_net_base_qty == q("0.031968")
    assert hold.reserved_sell_qty == q("0.031000")
    assert hold.reserved_base_fee_qty == q("0.000100")
    assert hold.total_reserved_base_qty == q("0.031100")
    assert hold.unreserved_base_qty == q("0.000868")
    assert source.step_residual_qty == q("0.000968")
    assert source.step_residual_qty != hold.unreserved_base_qty
    assert hold.symbol == BTCUSDT
    assert hold.cycle_ref == CellCycleRef(0, 0)
    assert hold.target_sell_price == p(102)
    assert hold.finalized_buy is source.finalized_buy
    assert after.funded_buy_book is before.funded_buy_book
    assert hold.finalized_buy.ledger is source.finalized_buy.ledger
    assert before.reservations == ()
    assert after.grid_state is before.grid_state
    assert after.grid_state.cells[0].phase is CellPhase.WAITING_SELL
    assert after.grid_state.cells[0].cycle_seq == 0
    assert after.funded_buy_book.spent_quote == before.funded_buy_book.spent_quote
    assert_identity(after)


@pytest.mark.parametrize("fee", ["0", "0.0001", "0.000968"])
def test_explicit_fee_hold_including_exact_remainder(fee: str) -> None:
    b = acquired()
    after = reserve_sell_inventory(b, assessment(b), q(fee))
    assert after.reserved_base_fee_qty == q(fee)
    assert_identity(after)


@pytest.mark.parametrize("fee", ["0.000969", "0.001", "1"])
def test_fee_cannot_use_another_cells_inventory(fee: str) -> None:
    b = acquired((0, 1, 2))
    expect_error(
        E.INSUFFICIENT_BASE_INVENTORY, lambda: reserve_sell_inventory(b, assessment(b), q(fee))
    )
    assert b.reservations == ()


def test_required_insufficient_example_has_no_silent_resize() -> None:
    b = acquired(fee="0")
    a = assessment(b)
    assert a.eligible_sell_qty == q("0.032")
    expect_error(E.INSUFFICIENT_BASE_INVENTORY, lambda: reserve_sell_inventory(b, a, q("0.0001")))
    assert b.confirmed_net_base_qty == q("0.032")
    assert b.reservations == ()


@pytest.mark.parametrize("variant", ["identical", "fee", "rules", "equivalent_buy", "smaller_qty"])
def test_duplicate_reservation_always_fails(variant: str) -> None:
    b = acquired()
    a = assessment(b)
    held = reserve_sell_inventory(b, a, q("0.0001"))
    candidate = a
    fee = q("0.0001")
    if variant == "fee":
        fee = q(0)
    elif variant == "rules":
        candidate = dataclasses.replace(a, market_rules=rules(step="0.0001"))
    elif variant == "equivalent_buy":
        candidate = dataclasses.replace(a, finalized_buy=dataclasses.replace(a.finalized_buy))
    elif variant == "smaller_qty":
        candidate = dataclasses.replace(a, market_rules=rules(step="0.01"))
    expect_error(E.RESERVATION_ALREADY_EXISTS, lambda: reserve_sell_inventory(held, candidate, fee))
    assert held.total_reserved_base_qty == q("0.0311")
    assert len(held.reservations) == 1


def test_three_cells_and_all_orders_preserve_individual_inventory() -> None:
    b = acquired((0, 1, 2))
    assessments = tuple(assessment(b, i) for i in range(3))
    results = []
    for order in permutations(range(3)):
        current = b
        for i in order:
            previous = current.reservations
            current = reserve_sell_inventory(current, assessments[i], q("0.0001"))
            assert all(current.reservation_for(r.cycle_ref) is r for r in previous)
            assert_identity(current)
        results.append(current)
    assert all(result == results[0] for result in results)
    assert results[0].total_reserved_base_qty == q("0.0933")
    assert results[0].unreserved_base_qty == q("0.002604")
    assert tuple(r.cycle_ref.cell_index for r in results[0].reservations) == (0, 1, 2)


def test_unconsumed_buy_with_valid_waiting_sell_cell_is_not_authority() -> None:
    b = acquired()
    alternate = finish(prepare(), suffix="-other")
    a = assess_sell_sizing(alternate, b.grid_state, RULES)
    expect_error(E.FINALIZATION_NOT_CONSUMED, lambda: reserve_sell_inventory(b, a, q(0)))


def test_valid_buy_before_consumption_is_rejected() -> None:
    funded = prepare()
    buy = finish(funded)
    a = assess_sell_sizing(buy, funded.lifecycle.grid_state, RULES)
    b = SellInventoryBook(funded)
    expect_error(E.CELL_NOT_WAITING_SELL, lambda: reserve_sell_inventory(b, a, q(0)))


def test_conflicting_content_or_intent_is_not_consumed_buy() -> None:
    b = acquired()
    other = acquired(qty="0.030")
    a = dataclasses.replace(assessment(other), grid_state=b.grid_state)
    expect_error(E.FINALIZATION_NOT_CONSUMED, lambda: reserve_sell_inventory(b, a, q(0)))
    smaller_plan = prepare(state=grid(intervals=1, upper=102))
    other_buy = finish(smaller_plan, qty="0.032")
    a = assess_sell_sizing(other_buy, b.grid_state, RULES)
    expect_error(E.FINALIZATION_NOT_CONSUMED, lambda: reserve_sell_inventory(b, a, q(0)))


def test_an_equivalent_consumed_buy_is_valid_authority() -> None:
    b = acquired()
    a = assessment(b)
    equivalent = dataclasses.replace(a.finalized_buy)
    assert equivalent == a.finalized_buy
    assert equivalent is not a.finalized_buy
    after = reserve_sell_inventory(b, dataclasses.replace(a, finalized_buy=equivalent), q(0))
    assert_identity(after)


def test_other_symbol_is_rejected() -> None:
    other = acquired(state=grid(Symbol(Asset("ETH"), USDT)))
    b = acquired()
    expect_error(E.SYMBOL_MISMATCH, lambda: reserve_sell_inventory(b, assessment(other), q(0)))


def test_other_cycle_is_rejected() -> None:
    b = acquired()
    other = acquired(state=grid(cycle=1))
    expect_error(E.CYCLE_MISMATCH, lambda: reserve_sell_inventory(b, assessment(other), q(0)))


def test_unknown_cell_is_rejected() -> None:
    b = SellInventoryBook(
        FundedBuyBook(BuyLifecycleBook(grid(intervals=1, upper=102)), Money.parse("20", USDT))
    )
    other = acquired((1,))
    expect_error(E.UNKNOWN_CELL, lambda: reserve_sell_inventory(b, assessment(other, 1), q(0)))


def test_no_fill_does_not_offer_inventory() -> None:
    b = acquired(qty=None)
    a = assessment(b)
    assert a.eligibility_status is SellSizingStatus.NO_INVENTORY
    expect_error(E.CELL_NOT_WAITING_SELL, lambda: reserve_sell_inventory(b, a, q(0)))
    expect_error(E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(a, q(0)))
    assert b.confirmed_net_base_qty == q(0)


@pytest.mark.parametrize("case", ["below_step", "min_notional", "max_qty", "changed_tick"])
def test_ineligible_assessments_cannot_reserve(case: str) -> None:
    b = acquired(qty="0.0009", fee="0") if case == "below_step" else acquired()
    r = RULES
    if case == "min_notional":
        r = dataclasses.replace(r, notional=NotionalRules.parse("5"))
    elif case == "max_qty":
        r = dataclasses.replace(r, quantity=QuantityRules(q("0.001"), q("0.001"), q("0.01")))
    elif case == "changed_tick":
        r = dataclasses.replace(r, price=PriceRules(p(5)))
    a = assessment(b, market_rules=r)
    expect_error(E.SIZING_NOT_ELIGIBLE, lambda: reserve_sell_inventory(b, a, q(0)))
    assert b.reservations == ()


@pytest.mark.parametrize(
    ("lower", "upper", "code"), [(99, 109, E.BUY_PRICE_MISMATCH), (100, 115, E.SELL_PRICE_MISMATCH)]
)
def test_changed_prices_of_current_cell_are_rejected(
    lower: int, upper: int, code: SellInventoryErrorCode
) -> None:
    b = acquired()
    a = assessment(b)
    changed = SellInventoryBook(regrid(b, lower, upper))
    expect_error(code, lambda: reserve_sell_inventory(changed, a, q(0)))
    held = reserve_sell_inventory(b, a, q(0))
    expect_error(
        E.INVALID_BOOK, lambda: dataclasses.replace(held, funded_buy_book=regrid(b, lower, upper))
    )


def test_old_assessment_after_own_cycle_advances_is_rejected() -> None:
    b = acquired()
    c = dataclasses.replace(
        b.grid_state.cells[0], cycle_seq=1, phase=CellPhase.WAITING_BUY, buy_armed=True
    )
    state = dataclasses.replace(b.grid_state, cells=(c, *b.grid_state.cells[1:]))
    funded = dataclasses.replace(
        b.funded_buy_book,
        lifecycle=dataclasses.replace(b.funded_buy_book.lifecycle, grid_state=state),
    )
    advanced = SellInventoryBook(funded)
    assert advanced.confirmed_net_base_qty == q(0)  # histórico não volta a estar disponível
    expect_error(E.CYCLE_MISMATCH, lambda: reserve_sell_inventory(advanced, assessment(b), q(0)))
    held = reserve_sell_inventory(b, assessment(b), q(0))
    expect_error(E.INVALID_BOOK, lambda: dataclasses.replace(held, funded_buy_book=funded))


def test_assessment_before_own_buy_transition_is_rejected() -> None:
    funded = prepare()
    finalized = finish(funded)
    a = assess_sell_sizing(finalized, funded.lifecycle.grid_state, RULES)
    b = SellInventoryBook(settle_funded_buy(funded, finalized))
    expect_error(E.CELL_NOT_WAITING_SELL, lambda: reserve_sell_inventory(b, a, q(0)))


def test_other_cell_completion_accepts_old_snapshot_and_keeps_prior_reservation() -> None:
    funded = prepare((0, 1, 2))
    b = SellInventoryBook(settle_funded_buy(funded, finish(funded, 0)))
    a0 = assessment(b)
    held = reserve_sell_inventory(b, a0, q("0.0001"))
    buy1 = finish(held.funded_buy_book, 1)
    updated = settle_inventory_book_buy(held, buy1)
    assert updated.grid_state != a0.grid_state
    assert updated.reservations is held.reservations
    assert updated.reservations[0] is held.reservations[0]
    after = reserve_sell_inventory(updated, assessment(updated, 1), q("0.0001"))
    assert_identity(after)
    unheld_updated = settle_inventory_book_buy(b, buy1)
    assert_identity(reserve_sell_inventory(unheld_updated, a0, q("0.0001")))
    assert settle_inventory_book_buy(after, buy1) is after


def test_coordinated_update_cannot_erase_or_replace_sources() -> None:
    b = acquired()
    held = reserve_sell_inventory(b, assessment(b), q(0))
    assert "funded_buy_book" not in inspect.signature(settle_inventory_book_buy).parameters
    alternative = finish(prepare(), suffix="-other")
    with pytest.raises(DomainError):
        settle_inventory_book_buy(held, alternative)
    expect_error(
        E.INVALID_BOOK,
        lambda: dataclasses.replace(held, funded_buy_book=acquired(qty="0.030").funded_buy_book),
    )
    expect_error(
        E.INVALID_BOOK,
        lambda: dataclasses.replace(
            held, funded_buy_book=SellInventoryBook(prepare()).funded_buy_book
        ),
    )
    assert len(held.reservations) == 1


@pytest.mark.parametrize("asset", [USDT, Asset("BNB")])
def test_buy_fees_in_other_assets_do_not_create_sell_fee_conversion(asset: Asset) -> None:
    b = acquired(fee="0.000032", asset=asset)
    held = reserve_sell_inventory(b, assessment(b), q(0))
    assert held.confirmed_net_base_qty == q("0.032")
    assert held.reserved_base_fee_qty == q(0)
    assert held.funded_buy_book is b.funded_buy_book


def test_qty_negative_rejected_at_boundary_and_if_validation_was_bypassed() -> None:
    b = acquired()
    with pytest.raises(DomainError):
        q("-0.0001")
    negative = forged(q(0), value=D("-0.0001"))
    expect_error(
        E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(assessment(b), negative)
    )
    expect_error(
        E.INVALID_BOOK,
        lambda: SellInventoryBook(
            b.funded_buy_book,
            (forged(SellBaseInventoryReservation(assessment(b), q(0)), base_fee_hold=negative),),
        ),
    )


@pytest.mark.parametrize("bad", [None, "0.001", D("0.001"), Money.parse("0.001", BTC), []])
def test_invalid_fee_types(bad: object) -> None:
    b = acquired()
    with pytest.raises(TypeError):
        reserve_sell_inventory(b, assessment(b), cast(Any, bad))
    expect_error(
        E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(assessment(b), cast(Any, bad))
    )


def test_float_is_rejected() -> None:
    b = acquired()
    with pytest.raises(FloatNotAllowedError):
        reserve_sell_inventory(b, assessment(b), cast(Any, 0.001))


@pytest.mark.parametrize("bad", [None, [], (), 3, "book"])
def test_invalid_book_types(bad: object) -> None:
    expect_error(E.INVALID_BOOK, lambda: SellInventoryBook(cast(Any, bad)))
    with pytest.raises(TypeError):
        reserve_sell_inventory(cast(Any, bad), assessment(acquired()), q(0))
    with pytest.raises(TypeError):
        settle_inventory_book_buy(cast(Any, bad), assessment(acquired()).finalized_buy)


@pytest.mark.parametrize(
    "bad", [None, (), [], "assessment", assessment(acquired()).finalized_buy.inventory]
)
def test_isolated_inventory_or_invalid_assessment_is_rejected(bad: object) -> None:
    b = acquired()
    with pytest.raises(TypeError):
        reserve_sell_inventory(b, cast(Any, bad), q(0))
    expect_error(E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(cast(Any, bad), q(0)))


@pytest.mark.parametrize("bad", [[], [None], (None,), (q(1),)])
def test_mutable_or_invalid_reservation_collections(bad: object) -> None:
    expect_error(
        E.INVALID_BOOK, lambda: SellInventoryBook(acquired().funded_buy_book, cast(Any, bad))
    )


def test_direct_duplicate_book_is_rejected_even_with_different_fee() -> None:
    b = acquired()
    a = assessment(b)
    r1 = SellBaseInventoryReservation(a, q(0))
    r2 = SellBaseInventoryReservation(a, q("0.0001"))
    for pair in ((r1, r1), (r1, r2)):
        expect_error(E.INVALID_BOOK, partial(SellInventoryBook, b.funded_buy_book, pair))


def test_direct_reservation_without_consumed_source_is_rejected() -> None:
    b = acquired()
    other = acquired(qty="0.030")
    r = SellBaseInventoryReservation(assessment(other), q(0))
    expect_error(E.INVALID_BOOK, lambda: SellInventoryBook(b.funded_buy_book, (r,)))


@pytest.mark.parametrize(
    "case", ["cycle", "rules_symbol", "buy_price", "finalization", "ledger", "state_shape"]
)
def test_direct_forged_assessment_sources_are_revalidated(case: str) -> None:
    b = acquired()
    a = assessment(b)
    if case == "cycle":
        other = acquired(state=grid(cycle=1))
        bad = forged(a, finalized_buy=assessment(other).finalized_buy)
    elif case == "rules_symbol":
        bad = forged(a, market_rules=rules(Symbol(Asset("ETH"), USDT)))
    elif case == "buy_price":
        bad = forged(a, grid_state=regrid(b, 99, 109).lifecycle.grid_state)
    elif case == "finalization":
        bad_buy = forged(
            a.finalized_buy,
            terminal_report=dataclasses.replace(
                a.finalized_buy.terminal_report, cumulative_executed_qty=q("0.01")
            ),
        )
        bad = forged(a, finalized_buy=bad_buy)
    elif case == "ledger":
        bad_ledger = forged(
            a.finalized_buy.ledger,
            fills=(*a.finalized_buy.ledger.fills, *a.finalized_buy.ledger.fills),
        )
        bad = forged(a, finalized_buy=forged(a.finalized_buy, ledger=bad_ledger))
    else:
        bad = forged(a, grid_state=forged(a.grid_state, cells=()))
    expect_error(E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(bad, q(0)))
    r = forged(SellBaseInventoryReservation(a, q(0)), assessment=bad)
    expect_error(E.INVALID_BOOK, lambda: SellInventoryBook(b.funded_buy_book, (r,)))


def test_direct_forged_hold_cannot_exceed_confirmed_inventory() -> None:
    b = acquired()
    a = assessment(b)
    expect_error(E.INVALID_RESERVATION, lambda: SellBaseInventoryReservation(a, q(1)))
    r = forged(SellBaseInventoryReservation(a, q(0)), base_fee_hold=q(1))
    expect_error(E.INVALID_BOOK, lambda: SellInventoryBook(b.funded_buy_book, (r,)))


def test_books_and_reservations_are_frozen_with_slots() -> None:
    b = acquired()
    held = reserve_sell_inventory(b, assessment(b), q(0))
    r = held.reservations[0]
    for instance in (b, held, r):
        assert not hasattr(instance, "__dict__")
        field = dataclasses.fields(instance)[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field.name, getattr(instance, field.name))


def test_precision_failure_in_hold_and_subtraction_is_typed_and_atomic() -> None:
    b = acquired()
    a = assessment(b)
    for fee in ("1e-100", "0.0001000000000000000000000000000000001"):
        error = expect_error(
            E.FINANCIAL_PRECISION_ERROR, partial(reserve_sell_inventory, b, a, q(fee))
        )
        assert isinstance(error.__cause__, Inexact)
        expect_error(
            E.FINANCIAL_PRECISION_ERROR,
            partial(SellBaseInventoryReservation, a, q(fee)),
        )
    assert b.reservations == ()


def test_very_small_unreserved_difference_is_preserved_exactly() -> None:
    # Cancelamento decimal exato preserva até o residual muito menor que o step.
    funded = dataclasses.replace(prepare(), initial_quote_capital=Money.parse("10", USDT))
    buy = finish(funded, qty="0.03100000000000000000000000000000001", fee="0")
    b = SellInventoryBook(settle_funded_buy(funded, buy))
    a = assessment(b)
    after = reserve_sell_inventory(b, a, q(0))
    assert after.unreserved_base_qty == q("1e-35")
    assert_identity(after)


def test_precision_failure_in_aggregate_of_valid_consumed_buys_is_typed() -> None:
    funded = prepare((0, 1))
    tiny = finish(funded, 0, qty="0.0032", fee="0.003199999999999999999999999999999999")
    assert tiny.net_acquired_base_qty == q("1e-36")
    funded = settle_funded_buy(funded, tiny)
    funded = settle_funded_buy(funded, finish(funded, 1))
    error = expect_error(E.FINANCIAL_PRECISION_ERROR, partial(SellInventoryBook, funded))
    assert isinstance(error.__cause__, Inexact)


def test_precision_error_from_funded_source_is_preserved_when_revalidated() -> None:
    funded = dataclasses.replace(prepare(), initial_quote_capital=Money.parse("10", USDT))
    buy = finish(funded, qty="0.03100000000000000000000000000000001", fee="0")
    funded = settle_funded_buy(funded, buy)
    bad = forged(funded, initial_quote_capital=Money.parse("20", USDT))
    error = expect_error(E.FINANCIAL_PRECISION_ERROR, partial(SellInventoryBook, bad))
    assert getattr(error.__cause__, "code", None) == E.FINANCIAL_PRECISION_ERROR


@given(
    steps=st.integers(min_value=2, max_value=32),
    buy_fee_units=st.integers(min_value=1, max_value=999),
    fee_fraction=st.integers(min_value=0, max_value=1000),
    order=st.permutations((0, 1, 2)),
)
def test_generated_inventory_is_conserved_and_exclusive(
    steps: int, buy_fee_units: int, fee_fraction: int, order: list[int]
) -> None:
    gross = D(steps).scaleb(-3)
    buy_fee = D(buy_fee_units).scaleb(-6)
    b = acquired((0, 1, 2), str(gross), str(buy_fee))
    assessments = tuple(assessment(b, i) for i in range(3))
    # Inteiros constroem o hold dentro do residual, sem filtros/rejeições silenciosas.
    remainder_units = 1000 - buy_fee_units
    fee_units = remainder_units * fee_fraction // 1000
    hold = q(str(D(fee_units).scaleb(-6)))
    current = b
    replay = b
    for cell in order:
        a = assessments[cell]
        current = reserve_sell_inventory(current, a, hold)
        replay = reserve_sell_inventory(replay, a, hold)
        assert current == replay
        total = current.total_reserved_base_qty
        expect_error(
            E.RESERVATION_ALREADY_EXISTS,
            partial(reserve_sell_inventory, current, a, q(0)),
        )
        assert current.total_reserved_base_qty == total
        assert_identity(current)
    canonical = b
    for a in assessments:
        canonical = reserve_sell_inventory(canonical, a, hold)
    assert current == canonical


@given(extra_units=st.integers(min_value=1, max_value=10000))
def test_generated_insufficient_hold_never_borrows_other_inventory(extra_units: int) -> None:
    b = acquired((0, 1, 2))
    fee = q(str(D(968 + extra_units).scaleb(-6)))
    before = dataclasses.replace(b)
    expect_error(
        E.INSUFFICIENT_BASE_INVENTORY, lambda: reserve_sell_inventory(b, assessment(b), fee)
    )
    assert b == before
    assert b.reservations == ()


# ---------------------------------------------------------------- regressão A14 sobre a A13
# Auditoria geral: o mutante M4 (remover o filtro de ciclo atual de ``confirmed_net_base_qty``)
# sobrevivia. Ainda não existe liquidação SELL legítima; por isso a transição abaixo é
# SINTÉTICA e vive exclusivamente aqui, no código de teste (nenhuma operação de venda em
# produção e nenhuma ampliação das permissões de ``confirm_sell``).


def advance_cycle_synthetically(funded: FundedBuyBook, cell: int) -> FundedBuyBook:
    state = funded.lifecycle.grid_state.confirm_sell(cell)
    lifecycle = dataclasses.replace(funded.lifecycle, grid_state=state)
    return dataclasses.replace(funded, lifecycle=lifecycle)


def rebuy_in_new_cycle(funded: FundedBuyBook, cell: int = 0) -> FundedBuyBook:
    state = funded.lifecycle.grid_state
    sizing = size_grid_buys(state, RULES, Money.parse("10", USDT))
    plan = build_buy_intents(state, sizing)
    ref = state.cells[cell].cycle_ref
    funded = prepare_funded_buy(funded, plan, ref, Money.parse("0.01", USDT))
    attempt = funded.lifecycle.attempt_for(ref)
    assert attempt is not None
    context = BuyExecutionContext(attempt.intent, BuyExecutionRef(f"buy-{cell}-c{ref.cycle_seq}"))
    funded = bind_funded_buy_execution(funded, ref, context)
    return settle_funded_buy(funded, finish(funded, cell, suffix=f"-c{ref.cycle_seq}"))


def test_global_inventory_excludes_historical_consumption_of_the_same_cell() -> None:
    funded = prepare((0,))
    funded = settle_funded_buy(funded, finish(funded))
    first_cycle = SellInventoryBook(funded)
    assert first_cycle.confirmed_net_base_qty == q("0.031968")

    advanced = advance_cycle_synthetically(funded, 0)
    between = SellInventoryBook(advanced)
    # Célula de volta a WAITING_BUY no ciclo 1: o consumo do ciclo 0 é só histórico.
    assert between.grid_state.cells[0].phase is CellPhase.WAITING_BUY
    assert between.grid_state.cells[0].cycle_seq == 1
    assert len(between.funded_buy_book.lifecycle.consumed) == 1
    assert between.confirmed_net_base_qty == q(0)
    assert between.unreserved_base_qty == q(0)

    second = rebuy_in_new_cycle(advanced)
    book = SellInventoryBook(second)
    refs = [f.cycle_ref for f in book.funded_buy_book.lifecycle.consumed]
    assert refs == [CellCycleRef(0, 0), CellCycleRef(0, 1)]
    assert book.grid_state.cells[0].phase is CellPhase.WAITING_SELL
    # Só o ciclo 1 (atualmente elegível) integra o total ativo: 0.031968, nunca 0.063936.
    assert book.confirmed_net_base_qty == q("0.031968")
    assert book.unreserved_base_qty == q("0.031968")


def test_historical_cycle_inventory_never_reappears_after_a_reservation() -> None:
    funded = prepare((0,))
    funded = settle_funded_buy(funded, finish(funded))
    second = rebuy_in_new_cycle(advance_cycle_synthetically(funded, 0))
    book = SellInventoryBook(second)
    held = reserve_sell_inventory(book, assessment(book), q("0.0001"))
    assert held.reservations[0].cycle_ref == CellCycleRef(0, 1)
    assert held.confirmed_net_base_qty == q("0.031968")
    assert held.total_reserved_base_qty == q("0.0311")
    assert held.unreserved_base_qty == q("0.000868")
    assert_identity(held)
    # O consumo do ciclo 0 não financia nem completa um hold maior do ciclo 1.
    expect_error(
        E.INSUFFICIENT_BASE_INVENTORY,
        lambda: reserve_sell_inventory(book, assessment(book), q("0.000969")),
    )


def test_known_limitation_rewrapping_a_book_silently_drops_reservations() -> None:
    """LIMITAÇÃO CONHECIDA (auditoria F3): documentada, NÃO corrigida na A14.

    Um ``SellInventoryBook`` é um snapshot e não carrega a história do aggregate anterior.
    Reconstruí-lo a partir do ``funded_buy_book`` é aceito e descarta as reservas sem erro.
    Ausência de reservas num snapshot novo NÃO prova que nunca houve compromissos; só uma
    decisão de coordenação de estado (antes da A15) e persistência transacional resolvem isso.
    """
    b = acquired()
    held = reserve_sell_inventory(b, assessment(b), q("0.0001"))
    assert held.total_reserved_base_qty == q("0.0311")

    rewrapped = SellInventoryBook(held.funded_buy_book)
    assert rewrapped.reservations == ()
    assert rewrapped.total_reserved_base_qty == q(0)
    assert rewrapped.unreserved_base_qty == held.confirmed_net_base_qty
    assert rewrapped != held

    # O original permanece intacto: o risco é o novo snapshot, não uma mutação do antigo.
    assert len(held.reservations) == 1
    assert held.total_reserved_base_qty == q("0.0311")
    # E o inventário "liberado" no snapshot novo pode ser reservado de novo: dois snapshots
    # concorrentes comprometeriam o mesmo BTC (ver PERSISTENT_ATOMIC_INVENTORY_RESERVATION...).
    again = reserve_sell_inventory(rewrapped, assessment(rewrapped), q("0.0001"))
    assert again.reservations[0].base_fee_hold == held.reservations[0].base_fee_hold
