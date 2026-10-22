from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import gridbot.application.sell_intents as sell_intents_module
from gridbot.application import (
    BuyLifecycleBook,
    FundedBuyBook,
    GridSellIntent,
    SellBaseInventoryReservation,
    SellIntentError,
    SellIntentErrorCode,
    SellIntentFreshness,
    SellIntentPlan,
    SellIntentStaleFinding,
    SellIntentStaleReason,
    SellInventoryBook,
    bind_funded_buy_execution,
    build_sell_intent_for_cell,
    build_sell_intents,
    prepare_funded_buy,
    reserve_sell_inventory,
    sell_intent_plan_freshness,
    settle_funded_buy,
    settle_inventory_book_buy,
    validate_sell_intent_plan_against_book,
)
from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    FloatNotAllowedError,
    LiquidityRole,
    MarketRules,
    Money,
    OrderType,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Side,
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
E = SellIntentErrorCode
R = SellIntentStaleReason


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str | int) -> Qty:
    return Qty.parse(raw)


def rules(symbol: Symbol = BTCUSDT, step: str = "0.001") -> MarketRules:
    return MarketRules(symbol, PriceRules(p(1)), QuantityRules(q(step), q(step)))


RULES = rules()
ETHUSDT = Symbol(Asset("ETH"), USDT)


def grid(
    symbol: Symbol = BTCUSDT, lower: int = 100, upper: int = 110, intervals: int = 5
) -> GridState:
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(symbol, p(lower), p(upper), intervals), rules(symbol)
    )
    return bootstrap_grid_state(plan, p(105))


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
    qty: str = "0.032",
    fee: str = "0.000032",
    suffix: str = "",
) -> FinalizedBuy:
    ref = funded.lifecycle.grid_state.cells[cell].cycle_ref
    attempt = funded.lifecycle.attempt_for(ref)
    assert attempt is not None
    assert attempt.execution is not None
    context = attempt.execution
    symbol = context.symbol
    ledger = BuyFillLedger(context.intent).record(
        ObservedBuyFill(
            f"fill-{cell}{suffix}",
            ref,
            symbol,
            context.intent.price,
            q(qty),
            Money.parse(fee, symbol.base),
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
    qty: str = "0.032",
    fee: str = "0.000032",
    state: GridState | None = None,
) -> SellInventoryBook:
    funded = prepare(cells, state)
    for cell in cells:
        funded = settle_funded_buy(funded, finish(funded, cell, qty, fee))
    return SellInventoryBook(funded)


def assessment(
    book: SellInventoryBook, cell: int = 0, market_rules: MarketRules | None = None
) -> SellSizingAssessment:
    ref = book.grid_state.cells[cell].cycle_ref
    buy = book.funded_buy_book.lifecycle.consumed_for(ref)
    assert buy is not None
    return assess_sell_sizing(buy, book.grid_state, market_rules or rules(buy.symbol))


def held(
    cells: tuple[int, ...] = (0,),
    hold: str = "0.0001",
    qty: str = "0.032",
    fee: str = "0.000032",
    state: GridState | None = None,
) -> SellInventoryBook:
    book = acquired(cells, qty, fee, state)
    for cell in cells:
        book = reserve_sell_inventory(book, assessment(book, cell), q(hold))
    return book


def rewrap(book: SellInventoryBook) -> SellInventoryBook:
    """Reconstrói o snapshot a partir do funded book: perde as reservas (limitação da A13)."""
    return SellInventoryBook(book.funded_buy_book)


def forged(source: object, **changes: object) -> Any:
    """Simula construção que ignorou __post_init__, somente nos testes de adulteração."""
    result = object.__new__(type(source))
    for field in dataclasses.fields(cast(Any, source)):
        object.__setattr__(result, field.name, changes.get(field.name, getattr(source, field.name)))
    return result


def advance_cycle_synthetically(funded: FundedBuyBook, cell: int) -> FundedBuyBook:
    """SOMENTE TESTE: não existe liquidação SELL; ``confirm_sell`` monta a fixture."""
    state = funded.lifecycle.grid_state.confirm_sell(cell)
    lifecycle = dataclasses.replace(funded.lifecycle, grid_state=state)
    return dataclasses.replace(funded, lifecycle=lifecycle)


def expect_error(code: SellIntentErrorCode, operation: Any) -> SellIntentError:
    with pytest.raises(SellIntentError) as info:
        operation()
    assert info.value.code is code
    assert code in str(info.value)
    return info.value


def fingerprint(book: SellInventoryBook) -> tuple[object, ...]:
    funded = book.funded_buy_book
    return (
        funded.initial_quote_capital,
        funded.spent_quote,
        funded.reserved_quote,
        funded.available_quote,
        book.confirmed_net_base_qty,
        book.reserved_sell_qty,
        book.reserved_base_fee_qty,
        book.unreserved_base_qty,
        tuple((c.phase, c.buy_armed, c.cycle_seq) for c in book.grid_state.cells),
        book.reservations,
        funded.lifecycle.consumed,
        funded.lifecycle.attempts,
    )


def reasons(freshness: SellIntentFreshness) -> list[SellIntentStaleReason]:
    return [f.reason for f in freshness.findings]


# ------------------------------------------------------------------ planos vazios


def test_book_without_reservations_yields_an_empty_plan() -> None:
    book = acquired()
    plan = build_sell_intents(book)
    assert plan.is_empty
    assert plan.cycle_refs == ()
    assert plan.intents == ()
    assert plan.book is book
    assert plan.symbol == BTCUSDT


def test_empty_book_without_any_purchase_yields_an_empty_plan() -> None:
    funded = FundedBuyBook(BuyLifecycleBook(grid()), Money.parse("20", USDT))
    assert build_sell_intents(SellInventoryBook(funded)).is_empty


def test_empty_plan_is_never_an_authorization() -> None:
    book = acquired()
    plan = build_sell_intents(book)
    ref = book.grid_state.cells[0].cycle_ref
    assert plan.intent_for(ref) is None
    expect_error(E.RESERVATION_NOT_FOUND, partial(build_sell_intent_for_cell, book, ref))
    # Inventário líquido existe, mas sem reserva não há intenção nem quantidade vendável.
    assert book.confirmed_net_base_qty == q("0.031968")
    assert book.reserved_sell_qty == q(0)


# ------------------------------------------------------------------ uma intenção válida


def test_single_intent_has_the_exact_audited_amounts() -> None:
    book = held()
    plan = build_sell_intents(book)
    (intent,) = plan.intents
    assert intent.side is Side.SELL
    assert intent.order_type is OrderType.LIMIT
    assert intent.cycle_ref == CellCycleRef(0, 0)
    assert intent.symbol == BTCUSDT
    assert intent.limit_price == p(102)
    assert intent.sell_qty == q("0.031000")
    assert intent.base_fee_hold == q("0.000100")
    assert intent.total_base_commitment == q("0.031100")
    assert intent.confirmed_net_base_qty == q("0.031968")
    assert intent.unreserved_base_qty == q("0.000868")


def test_order_quantity_is_neither_the_commitment_nor_the_net_nor_the_gross() -> None:
    (intent,) = build_sell_intents(held()).intents
    for forbidden in ("0.031100", "0.031968", "0.032000", "0.000868"):
        assert intent.sell_qty != q(forbidden)
    assert intent.sell_qty == intent.reservation.assessment.quantized_candidate_qty


def test_commitment_is_conserved_exactly() -> None:
    (intent,) = build_sell_intents(held()).intents
    assert intent.total_base_commitment == intent.sell_qty + intent.base_fee_hold
    assert intent.total_base_commitment <= intent.confirmed_net_base_qty
    assert (
        intent.total_base_commitment + intent.unreserved_base_qty == intent.confirmed_net_base_qty
    )


@pytest.mark.parametrize("hold", ["0", "0.0001", "0.000968"])
def test_fee_hold_never_changes_the_order_quantity(hold: str) -> None:
    (intent,) = build_sell_intents(held(hold=hold)).intents
    assert intent.sell_qty == q("0.031")
    assert intent.base_fee_hold == q(hold)
    assert intent.total_base_commitment == q("0.031") + q(hold)


def test_residual_is_not_offered_for_sale() -> None:
    (intent,) = build_sell_intents(held(hold="0")).intents
    residual = intent.reservation.assessment.step_residual_qty
    assert residual == q("0.000968")
    assert intent.sell_qty + residual == intent.confirmed_net_base_qty
    assert intent.sell_qty < intent.confirmed_net_base_qty


def test_insufficient_inventory_is_not_bypassed() -> None:
    book = acquired()
    with pytest.raises(Exception, match="INSUFFICIENT_BASE_INVENTORY"):
        reserve_sell_inventory(book, assessment(book), q("0.000969"))
    assert build_sell_intents(book).is_empty


def test_origin_is_the_consumed_finalized_buy() -> None:
    book = held()
    (intent,) = build_sell_intents(book).intents
    consumed = book.funded_buy_book.lifecycle.consumed_for(intent.cycle_ref)
    assert consumed is not None
    assert intent.finalized_buy == consumed
    assert intent.finalized_buy.net_acquired_base_qty == q("0.031968")


@pytest.mark.parametrize("cell", [0, 1, 2])
def test_limit_price_always_comes_from_the_cell(cell: int) -> None:
    book = held((0, 1, 2))
    intent = build_sell_intents(book).intent_for(book.grid_state.cells[cell].cycle_ref)
    assert intent is not None
    assert intent.limit_price == book.grid_state.cells[cell].cell.sell_price == p(102 + 2 * cell)


# ------------------------------------------------------------------ várias células


def test_three_cells_yield_three_independent_intents_in_canonical_order() -> None:
    book = held((0, 1, 2))
    plan = build_sell_intents(book)
    intents = plan.intents
    assert [i.cycle_ref for i in intents] == [CellCycleRef(i, 0) for i in range(3)]
    assert plan.cycle_refs == tuple(i.cycle_ref for i in intents)
    assert [i.limit_price for i in intents] == [p(102), p(104), p(106)]
    assert {i.sell_qty for i in intents} == {q("0.031")}
    # Cada célula só compromete o próprio inventário: nada é somado nem emprestado.
    assert all(i.total_base_commitment == q("0.0311") for i in intents)
    assert all(i.unreserved_base_qty == q("0.000868") for i in intents)
    assert len({i.finalized_buy.execution_ref for i in intents}) == 3
    assert book.reserved_sell_qty == q("0.093")


def test_canonical_order_does_not_depend_on_reservation_order() -> None:
    book = held((0, 1, 2))
    shuffled = SellInventoryBook(book.funded_buy_book, tuple(reversed(book.reservations)))
    assert [r.cycle_ref.cell_index for r in shuffled.reservations] == [2, 1, 0]
    plan = build_sell_intents(shuffled)
    assert [i.cycle_ref.cell_index for i in plan.intents] == [0, 1, 2]
    assert plan.cycle_refs == build_sell_intents(book).cycle_refs


def test_each_cycle_has_at_most_one_intent() -> None:
    plan = build_sell_intents(held((0, 1, 2)))
    assert len(set(plan.cycle_refs)) == len(plan.intents) == 3
    assert plan.intent_for(CellCycleRef(1, 0)) == plan.intents[1]
    assert plan.intent_for(CellCycleRef(1, 5)) is None


def test_single_cell_plan_is_partial_and_checked_inside_the_book() -> None:
    book = held((0, 1, 2))
    ref = CellCycleRef(1, 0)
    plan = build_sell_intent_for_cell(book, ref)
    assert plan.cycle_refs == (ref,)
    assert [i.cycle_ref for i in plan.intents] == [ref]
    assert plan.intents[0] == build_sell_intents(book).intent_for(ref)
    expect_error(
        E.RESERVATION_NOT_FOUND, partial(build_sell_intent_for_cell, book, CellCycleRef(1, 1))
    )
    expect_error(
        E.RESERVATION_NOT_FOUND, partial(build_sell_intent_for_cell, book, CellCycleRef(4, 0))
    )


def test_cell_without_reservation_is_left_out_of_the_plan() -> None:
    book = acquired((0, 1))
    book = reserve_sell_inventory(book, assessment(book, 1), q("0.0001"))
    plan = build_sell_intents(book)
    assert plan.cycle_refs == (CellCycleRef(1, 0),)
    assert plan.intent_for(CellCycleRef(0, 0)) is None


# ------------------------------------------------------------------ determinismo e imutabilidade


def test_planning_is_deterministic_and_regenerable() -> None:
    book = held((0, 1, 2))
    first, second = build_sell_intents(book), build_sell_intents(book)
    assert first == second
    assert first.intents == second.intents
    # Equivalência econômica NÃO é autorização para transmitir duas ordens.
    assert first is not second


def test_planning_leaves_every_financial_fact_untouched() -> None:
    book = held((0, 1, 2))
    before = fingerprint(book)
    state = book.grid_state
    reservations = book.reservations
    plan = build_sell_intents(book)
    _ = plan.intents
    validate_sell_intent_plan_against_book(plan, book)
    assert fingerprint(book) == before
    assert book.grid_state is state
    assert book.reservations is reservations
    assert plan.book is book
    # Nenhum USDT movimentado, nenhum ciclo avançado, nenhuma venda confirmada.
    assert [c.cycle_seq for c in book.grid_state.cells] == [0] * 5
    assert [c.phase for c in book.grid_state.cells[:3]] == [CellPhase.WAITING_SELL] * 3
    assert book.funded_buy_book.reserved_quote == Money.parse("0", USDT)


def test_value_objects_are_frozen_with_slots() -> None:
    plan = build_sell_intents(held())
    finding = SellIntentStaleFinding(CellCycleRef(0, 0), R.RESERVATION_MISSING)
    freshness = sell_intent_plan_freshness(plan, held())
    for instance in (plan.intents[0], plan, finding, freshness):
        assert not hasattr(instance, "__dict__")
        field = dataclasses.fields(instance)[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field.name, getattr(instance, field.name))
    assert isinstance(plan.cycle_refs, tuple)
    assert isinstance(plan.intents, tuple)


def test_models_store_only_sources_and_no_independent_financial_fields() -> None:
    assert [f.name for f in dataclasses.fields(GridSellIntent)] == ["reservation"]
    assert [f.name for f in dataclasses.fields(SellIntentPlan)] == ["book", "cycle_refs"]


def test_intent_has_no_exchange_identity_status_or_timestamp() -> None:
    (intent,) = build_sell_intents(held()).intents
    names = {n for n in dir(intent) if not n.startswith("_")}
    banned = {"client_order_id", "exchange_order_id", "order_id", "created_at", "timestamp"}
    banned |= {"status", "fill_ref", "fills", "executed_qty", "fee", "revenue", "pnl", "profit"}
    assert not names & banned


def test_public_functions_take_no_wallet_price_or_quantity() -> None:
    functions = (
        build_sell_intents,
        build_sell_intent_for_cell,
        sell_intent_plan_freshness,
        validate_sell_intent_plan_against_book,
    )
    for function in functions:
        params = set(inspect.signature(function).parameters)
        assert not params & {"price", "qty", "quantity", "balance", "wallet", "core", "limit_price"}
    assert not hasattr(sell_intents_module, "Balance")
    assert not hasattr(sell_intents_module, "ClientOrderId")
    assert not hasattr(sell_intents_module, "OrderIntent")


# ------------------------------------------------------------------ tipos e origem exclusiva


@pytest.mark.parametrize("bad", [None, "book", [], 3, object()])
def test_builders_reject_non_books(bad: object) -> None:
    with pytest.raises(TypeError):
        build_sell_intents(cast(Any, bad))
    with pytest.raises(TypeError):
        build_sell_intent_for_cell(cast(Any, bad), CellCycleRef(0, 0))


def test_a_bare_reservation_is_not_an_authorizing_source() -> None:
    book = held()
    reservation = book.reservations[0]
    with pytest.raises(TypeError):
        build_sell_intents(cast(Any, reservation))
    with pytest.raises(TypeError):
        build_sell_intent_for_cell(cast(Any, reservation), CellCycleRef(0, 0))
    with pytest.raises(TypeError):
        SellIntentPlan(cast(Any, reservation))


def test_float_and_bad_cycle_refs_are_rejected() -> None:
    book = held()
    with pytest.raises(FloatNotAllowedError):
        build_sell_intent_for_cell(book, cast(Any, 0.5))
    with pytest.raises(TypeError):
        build_sell_intent_for_cell(book, cast(Any, (0, 0)))
    with pytest.raises(FloatNotAllowedError):
        build_sell_intents(cast(Any, 1.5))
    with pytest.raises(TypeError):
        build_sell_intents(book).intent_for(cast(Any, 0))


@pytest.mark.parametrize("bad", [None, "reservation", 3, [], object()])
def test_intent_requires_a_reservation(bad: object) -> None:
    with pytest.raises(TypeError):
        GridSellIntent(cast(Any, bad))
    with pytest.raises(FloatNotAllowedError):
        GridSellIntent(cast(Any, 0.5))


def test_isolated_intent_does_not_prove_authorization() -> None:
    book = held()
    isolated = GridSellIntent(book.reservations[0])
    assert isolated.sell_qty == q("0.031")
    # Contra um snapshot sem a reserva (rewrap) a mesma intenção não se sustenta.
    plan = build_sell_intents(book)
    stale = sell_intent_plan_freshness(plan, rewrap(book))
    assert reasons(stale) == [R.RESERVATION_MISSING]
    assert plan.intents == (isolated,)


def test_reservation_from_another_book_cannot_enter_a_plan() -> None:
    other = held((0, 1))
    mine = held((0,))
    expect_error(E.RESERVATION_NOT_FOUND, partial(SellIntentPlan, mine, (CellCycleRef(1, 0),)))
    # E uma reserva alheia não entra no book (verificação da A13, preservada).
    with pytest.raises(Exception, match="INVALID_BOOK"):
        SellInventoryBook(mine.funded_buy_book, (*mine.reservations, other.reservations[1]))


def test_reservation_of_an_unconsumed_purchase_never_reaches_a_plan() -> None:
    funded = prepare((2,))
    fin = finish(funded, 2)
    state = funded.lifecycle.grid_state.confirm_buy(2)
    loose = SellBaseInventoryReservation(assess_sell_sizing(fin, state, RULES), q("0.0001"))
    book = SellInventoryBook(funded)
    with pytest.raises(Exception, match="INVALID_BOOK"):
        SellInventoryBook(funded, (loose,))
    expect_error(E.RESERVATION_NOT_FOUND, partial(SellIntentPlan, book, (loose.cycle_ref,)))
    assert build_sell_intents(book).is_empty


# ------------------------------------------------------------------ construção direta


def test_direct_plan_with_valid_refs_equals_the_built_plan() -> None:
    book = held((0, 1))
    assert SellIntentPlan(book, (CellCycleRef(0, 0), CellCycleRef(1, 0))) == build_sell_intents(
        book
    )
    assert SellIntentPlan(book).is_empty


def test_direct_plan_rejects_duplicate_cycle_refs() -> None:
    book = held((0, 1))
    ref = CellCycleRef(0, 0)
    expect_error(E.DUPLICATE_SELL_INTENT, partial(SellIntentPlan, book, (ref, ref)))
    expect_error(
        E.DUPLICATE_SELL_INTENT, partial(SellIntentPlan, book, (ref, CellCycleRef(1, 0), ref))
    )


def test_direct_plan_requires_canonical_order() -> None:
    book = held((0, 1, 2))
    refs = (CellCycleRef(2, 0), CellCycleRef(0, 0))
    expect_error(E.INVALID_SELL_INTENT_PLAN, partial(SellIntentPlan, book, refs))


@pytest.mark.parametrize("bad", [[], [CellCycleRef(0, 0)], (None,), (0,), ((0, 0),), "ref"])
def test_direct_plan_requires_an_immutable_tuple_of_refs(bad: object) -> None:
    with pytest.raises(TypeError):
        SellIntentPlan(held(), cast(Any, bad))


def test_direct_plan_requires_a_book() -> None:
    with pytest.raises(TypeError):
        SellIntentPlan(cast(Any, None), ())


def test_forged_book_in_a_plan_is_rejected() -> None:
    book = held()
    bad_reservation = forged(book.reservations[0], base_fee_hold=q(1))
    bad_book = forged(book, reservations=(bad_reservation,))
    expect_error(E.INVALID_BOOK, partial(SellIntentPlan, bad_book, ()))
    expect_error(E.INVALID_BOOK, partial(build_sell_intents, bad_book))
    duplicated = forged(book, reservations=(*book.reservations, *book.reservations))
    expect_error(E.INVALID_BOOK, partial(build_sell_intents, duplicated))


@pytest.mark.parametrize("case", ["cycle", "rules_symbol", "buy_price", "ledger", "state_shape"])
def test_forged_assessment_is_rejected_at_the_intent(case: str) -> None:
    book = held()
    a = book.reservations[0].assessment
    if case == "cycle":
        other = acquired(
            state=dataclasses.replace(
                grid(), cells=tuple(dataclasses.replace(c, cycle_seq=1) for c in grid().cells)
            )
        )
        bad = forged(a, finalized_buy=assessment(other).finalized_buy)
    elif case == "rules_symbol":
        bad = forged(a, market_rules=rules(ETHUSDT))
    elif case == "buy_price":
        bad = forged(a, grid_state=grid(lower=99, upper=109))
    elif case == "ledger":
        bad_ledger = forged(
            a.finalized_buy.ledger,
            fills=(*a.finalized_buy.ledger.fills, *a.finalized_buy.ledger.fills),
        )
        bad = forged(a, finalized_buy=forged(a.finalized_buy, ledger=bad_ledger))
    else:
        bad = forged(a, grid_state=forged(a.grid_state, cells=()))
    reservation = forged(book.reservations[0], assessment=bad)
    expect_error(E.INVALID_SELL_INTENT, partial(GridSellIntent, reservation))
    bad_book = forged(book, reservations=(reservation,))
    expect_error(E.INVALID_BOOK, partial(build_sell_intents, bad_book))


def test_forged_hold_above_the_net_is_rejected_at_the_intent() -> None:
    reservation = forged(held().reservations[0], base_fee_hold=q(1))
    error = expect_error(E.INVALID_SELL_INTENT, partial(GridSellIntent, reservation))
    assert isinstance(error.__cause__, Exception)


def test_precision_errors_of_the_sources_are_preserved() -> None:
    book = held()
    reservation = forged(
        book.reservations[0], base_fee_hold=q("0.0001000000000000000000000000000000001")
    )
    expect_error(E.FINANCIAL_PRECISION_ERROR, partial(GridSellIntent, reservation))
    bad_book = forged(book, reservations=(reservation,))
    expect_error(E.FINANCIAL_PRECISION_ERROR, partial(SellIntentPlan, bad_book, ()))
    expect_error(
        E.FINANCIAL_PRECISION_ERROR,
        partial(sell_intent_plan_freshness, build_sell_intents(book), bad_book),
    )


def test_errors_do_not_modify_their_inputs() -> None:
    book = held((0, 1))
    before = fingerprint(book)
    plan = build_sell_intents(book)
    expect_error(
        E.RESERVATION_NOT_FOUND, partial(build_sell_intent_for_cell, book, CellCycleRef(3, 0))
    )
    expect_error(E.DUPLICATE_SELL_INTENT, partial(SellIntentPlan, book, (CellCycleRef(0, 0),) * 2))
    expect_error(
        E.STALE_SELL_INTENT, partial(validate_sell_intent_plan_against_book, plan, rewrap(book))
    )
    assert fingerprint(book) == before
    assert plan == build_sell_intents(book)


def test_error_carries_code_message_and_default_findings() -> None:
    error = SellIntentError(E.INVALID_SELL_INTENT, "detalhe")
    assert error.code is E.INVALID_SELL_INTENT
    assert str(error) == "INVALID_SELL_INTENT: detalhe"
    assert error.findings == ()


# ------------------------------------------------------------------ freshness


def test_plan_is_current_against_its_own_book_and_an_equivalent_one() -> None:
    book = held((0, 1))
    plan = build_sell_intents(book)
    freshness = sell_intent_plan_freshness(plan, book)
    assert freshness.is_current
    assert freshness.checked_cycle_refs == plan.cycle_refs
    validate_sell_intent_plan_against_book(plan, book)  # não levanta
    assert sell_intent_plan_freshness(plan, held((0, 1))).is_current


def test_empty_plan_is_trivially_current_but_still_not_an_authorization() -> None:
    plan = build_sell_intents(acquired())
    assert sell_intent_plan_freshness(plan, acquired()).is_current
    assert plan.intents == ()


def test_lost_reservation_makes_the_old_intent_stale() -> None:
    book = held()
    plan = build_sell_intents(book)
    lost = rewrap(book)
    assert lost.reservations == ()
    error = expect_error(
        E.STALE_SELL_INTENT, partial(validate_sell_intent_plan_against_book, plan, lost)
    )
    assert error.findings == (SellIntentStaleFinding(CellCycleRef(0, 0), R.RESERVATION_MISSING),)
    assert lost.reservations == ()  # a revalidação não restaura reservas


def test_lost_reservation_stays_stale_even_if_the_rest_of_the_book_looks_valid() -> None:
    book = held((0, 1))
    plan = build_sell_intents(book)
    other_only = SellInventoryBook(book.funded_buy_book, (book.reservations[1],))
    freshness = sell_intent_plan_freshness(plan, other_only)
    assert freshness.findings == (
        SellIntentStaleFinding(CellCycleRef(0, 0), R.RESERVATION_MISSING),
    )


def test_extra_reservations_in_other_cells_keep_a_partial_plan_current() -> None:
    funded = prepare((0, 1, 2))
    book = SellInventoryBook(settle_funded_buy(funded, finish(funded, 0)))
    book = reserve_sell_inventory(book, assessment(book, 0), q("0.0001"))
    plan = build_sell_intents(book)
    updated = settle_inventory_book_buy(book, finish(book.funded_buy_book, 1))
    updated = reserve_sell_inventory(updated, assessment(updated, 1), q("0.0001"))
    assert updated.grid_state != book.grid_state
    assert sell_intent_plan_freshness(plan, updated).is_current
    assert plan.cycle_refs == (CellCycleRef(0, 0),)
    assert build_sell_intents(updated).cycle_refs == (CellCycleRef(0, 0), CellCycleRef(1, 0))


def test_independent_purchase_in_another_cell_keeps_the_plan_current() -> None:
    funded = prepare((0, 1))
    book = SellInventoryBook(settle_funded_buy(funded, finish(funded, 0)))
    book = reserve_sell_inventory(book, assessment(book, 0), q("0.0001"))
    plan = build_sell_intents(book)
    updated = settle_inventory_book_buy(book, finish(book.funded_buy_book, 1))
    assert updated.reservations is book.reservations
    validate_sell_intent_plan_against_book(plan, updated)


def test_old_cycle_after_a_cycle_change_is_stale() -> None:
    book = held()
    plan = build_sell_intents(book)
    advanced = SellInventoryBook(advance_cycle_synthetically(book.funded_buy_book, 0))
    assert advanced.reservations == ()
    freshness = sell_intent_plan_freshness(plan, advanced)
    assert reasons(freshness) == [R.CYCLE_ADVANCED]


def test_cell_not_waiting_sell_is_stale() -> None:
    plan = build_sell_intents(held())
    empty = SellInventoryBook(FundedBuyBook(BuyLifecycleBook(grid()), Money.parse("20", USDT)))
    assert reasons(sell_intent_plan_freshness(plan, empty)) == [R.CELL_NOT_WAITING_SELL]


def test_other_symbol_is_stale() -> None:
    plan = build_sell_intents(held())
    eth = SellInventoryBook(
        FundedBuyBook(BuyLifecycleBook(grid(ETHUSDT)), Money.parse("20", ETHUSDT.quote))
    )
    assert reasons(sell_intent_plan_freshness(plan, eth)) == [R.SYMBOL_CHANGED]


@pytest.mark.parametrize("intervals", [1, 2])
def test_unknown_cell_is_stale(intervals: int) -> None:
    # intervals=2: o índice 2 é exatamente o tamanho da grade (fronteira); 1: bem além.
    plan = build_sell_intent_for_cell(held((0, 1, 2)), CellCycleRef(2, 0))
    small = SellInventoryBook(
        FundedBuyBook(BuyLifecycleBook(grid(intervals=intervals)), Money.parse("20", USDT))
    )
    assert len(small.grid_state.cells) == intervals
    assert reasons(sell_intent_plan_freshness(plan, small)) == [R.CELL_UNKNOWN]


def test_changed_origin_purchase_is_stale() -> None:
    plan = build_sell_intents(held())
    other_origin = held(qty="0.030", fee="0.00003")
    freshness = sell_intent_plan_freshness(plan, other_origin)
    assert R.ORIGIN_CHANGED in reasons(freshness)
    assert all(f.cycle_ref == CellCycleRef(0, 0) for f in freshness.findings)


def test_changed_price_is_stale() -> None:
    plan = build_sell_intents(held())
    repriced = held(state=grid(upper=120))
    assert repriced.grid_state.cells[0].cell.sell_price == p(104)
    # A grade diferente também muda o sizing e, portanto, a compra de origem do ciclo.
    assert reasons(sell_intent_plan_freshness(plan, repriced)) == [
        R.ORIGIN_CHANGED,
        R.PRICE_CHANGED,
    ]


def test_changed_quantity_is_stale() -> None:
    plan = build_sell_intents(held())
    book = acquired()
    coarser = reserve_sell_inventory(book, assessment(book, 0, rules(step="0.01")), q("0.0001"))
    assert coarser.reservations[0].reserved_sell_qty == q("0.03")
    assert reasons(sell_intent_plan_freshness(plan, coarser)) == [R.QUANTITY_CHANGED]


def test_changed_fee_hold_is_stale() -> None:
    plan = build_sell_intents(held(hold="0.0001"))
    assert reasons(sell_intent_plan_freshness(plan, held(hold="0.0002"))) == [R.FEE_HOLD_CHANGED]
    assert sell_intent_plan_freshness(plan, held(hold="0.0001")).is_current


def test_stale_error_summarises_all_findings() -> None:
    plan = build_sell_intents(held((0, 1)))
    error = expect_error(
        E.STALE_SELL_INTENT,
        partial(validate_sell_intent_plan_against_book, plan, rewrap(held((0, 1)))),
    )
    assert [f.cycle_ref for f in error.findings] == [CellCycleRef(0, 0), CellCycleRef(1, 0)]
    assert all(f.reason is R.RESERVATION_MISSING for f in error.findings)
    assert "RESERVATION_MISSING" in str(error)


def test_freshness_requires_valid_types_and_a_valid_current_book() -> None:
    book = held()
    plan = build_sell_intents(book)
    with pytest.raises(TypeError):
        sell_intent_plan_freshness(cast(Any, book), book)
    with pytest.raises(TypeError):
        sell_intent_plan_freshness(plan, cast(Any, plan))
    with pytest.raises(FloatNotAllowedError):
        validate_sell_intent_plan_against_book(plan, cast(Any, 0.5))
    bad = forged(book, reservations=(forged(book.reservations[0], base_fee_hold=q(1)),))
    expect_error(E.INVALID_BOOK, partial(sell_intent_plan_freshness, plan, bad))


def test_revalidation_neither_restores_nor_creates_anything() -> None:
    book = held()
    plan = build_sell_intents(book)
    lost = rewrap(book)
    before = fingerprint(lost)
    expect_error(E.STALE_SELL_INTENT, partial(validate_sell_intent_plan_against_book, plan, lost))
    assert fingerprint(lost) == before
    assert lost.reservations == ()
    assert plan.book is book


def test_rewrapped_and_rereserved_book_gives_an_equivalent_but_unauthorized_plan() -> None:
    book = held()
    plan = build_sell_intents(book)
    again = rewrap(book)
    again = reserve_sell_inventory(again, assessment(again), q("0.0001"))
    # Conteúdo idêntico é indistinguível (limite da memória); não autoriza ordem nova.
    assert sell_intent_plan_freshness(plan, again).is_current
    assert build_sell_intents(again).intents[0].sell_qty == plan.intents[0].sell_qty


# ------------------------------------------------------------------ propriedades


@settings(max_examples=60, deadline=None)
@given(
    steps=st.integers(min_value=2, max_value=32),
    buy_fee_units=st.integers(min_value=1, max_value=999),
    fee_fraction=st.integers(min_value=0, max_value=1000),
    order=st.permutations((0, 1, 2)),
)
def test_generated_intents_derive_exactly_from_their_reservations(
    steps: int, buy_fee_units: int, fee_fraction: int, order: list[int]
) -> None:
    gross = D(steps).scaleb(-3)
    buy_fee = D(buy_fee_units).scaleb(-6)
    book = acquired((0, 1, 2), str(gross), str(buy_fee))
    fee_units = (1000 - buy_fee_units) * fee_fraction // 1000
    hold = q(str(D(fee_units).scaleb(-6)))
    for cell in order:
        book = reserve_sell_inventory(book, assessment(book, cell), hold)
    plan = build_sell_intents(book)
    assert plan == build_sell_intents(book)
    assert plan.cycle_refs == tuple(sorted(plan.cycle_refs))
    assert len(set(plan.cycle_refs)) == len(plan.intents) == 3
    net = gross - buy_fee
    for intent in plan.intents:
        cell = intent.cycle_ref.cell_index
        assert intent.side is Side.SELL
        assert intent.order_type is OrderType.LIMIT
        assert intent.limit_price == book.grid_state.cells[cell].cell.sell_price
        assert intent.sell_qty.value == (net // D("0.001")) * D("0.001")
        assert intent.base_fee_hold == hold
        assert intent.total_base_commitment == intent.sell_qty + intent.base_fee_hold
        assert intent.total_base_commitment <= intent.confirmed_net_base_qty
        assert (
            intent.total_base_commitment + intent.unreserved_base_qty
            == intent.confirmed_net_base_qty
        )
        assert intent.sell_qty <= intent.confirmed_net_base_qty
        assert intent.finalized_buy == book.funded_buy_book.lifecycle.consumed_for(intent.cycle_ref)
    assert sell_intent_plan_freshness(plan, book).is_current


@settings(max_examples=40, deadline=None)
@given(
    chosen=st.sets(st.sampled_from((0, 1, 2)), min_size=1, max_size=3),
    dropped=st.sets(st.sampled_from((0, 1, 2)), max_size=3),
)
def test_generated_cells_are_independent_and_only_lost_reservations_go_stale(
    chosen: set[int], dropped: set[int]
) -> None:
    book = held((0, 1, 2))
    refs = tuple(CellCycleRef(c, 0) for c in sorted(chosen))
    plan = SellIntentPlan(book, refs)
    kept = tuple(r for r in book.reservations if r.cycle_ref.cell_index not in dropped)
    current = SellInventoryBook(book.funded_buy_book, kept)
    freshness = sell_intent_plan_freshness(plan, current)
    expected = [CellCycleRef(c, 0) for c in sorted(chosen & dropped)]
    assert [f.cycle_ref for f in freshness.findings] == expected
    assert all(f.reason is R.RESERVATION_MISSING for f in freshness.findings)
    assert freshness.is_current == (not expected)


@settings(max_examples=40, deadline=None)
@given(
    extra_units=st.integers(min_value=1, max_value=5000),
    cell=st.integers(min_value=0, max_value=2),
    cycle=st.integers(min_value=1, max_value=4),
)
def test_generated_invalid_inputs_fail_closed(extra_units: int, cell: int, cycle: int) -> None:
    book = acquired((0, 1, 2))
    too_big = q(str(D(968 + extra_units).scaleb(-6)))
    before = fingerprint(book)
    with pytest.raises(Exception, match="INSUFFICIENT_BASE_INVENTORY"):
        reserve_sell_inventory(book, assessment(book, cell), too_big)
    assert build_sell_intents(book).is_empty
    expect_error(
        E.RESERVATION_NOT_FOUND,
        partial(build_sell_intent_for_cell, book, CellCycleRef(cell, cycle)),
    )
    assert fingerprint(book) == before
