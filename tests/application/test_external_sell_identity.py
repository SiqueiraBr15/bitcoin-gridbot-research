"""A17.1: identidades sintéticas, coleta declarada e conservação sem autorização."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from typing import Any, cast

import pytest

from gridbot.application import (
    BuyLifecycleBook,
    ExternalSellOrderBinding,
    FundedBuyBook,
    GridOperationalBook,
    SellAttemptStatus,
    SellBindingVerification,
    SellCollectionStopReason,
    SellCollectionVerification,
    SellEvidenceError,
    SellInventoryBook,
    SellOrderBindingError,
    SellOrderBindingErrorCode,
    SellReconciliationCode,
    SellReconciliationState,
    SellTradeCollection,
    SellTradePage,
    SellTradePagination,
    SellTradeQueryScope,
    assess_sell_finalization,
    bind_external_sell_order,
    bind_operational_buy_execution,
    bind_sell_execution,
    build_sell_fill_ledger,
    mark_operational_buy_submission_uncertain,
    mark_sell_submission_uncertain,
    prepare_sell,
    record_sell_fill,
    reserve_operational_sell,
    settle_operational_buy,
)
from gridbot.application.sell_lifecycle import SellLifecycleError
from gridbot.domain import BTC, USDT, Asset, Money, Side, Symbol
from tests.application.test_operational_grid import (
    buy_context,
    context,
    prepare_other_buy,
    prepared_root,
    ref,
    with_status,
)
from tests.application.test_sell_fills import fill
from tests.application.test_sell_intents import acquired, assessment, finish, forged, grid, q
from tests.application.test_sell_reconciliation import codes, identity, report, scenario, trade

C = SellReconciliationCode
E = SellOrderBindingErrorCode


def binding(root: GridOperationalBook, cell: int = 0, **changes: Any) -> ExternalSellOrderBinding:
    ledger = build_sell_fill_ledger(root, ref(cell))
    return ExternalSellOrderBinding(identity(ledger, **changes), Side.SELL)


def bound_cells(cells: tuple[int, ...] = (0,)) -> GridOperationalBook:
    root = prepared_root(cells)
    for cell in cells:
        root = with_status(root, SellAttemptStatus.EXECUTION_BOUND, cell)
    return root


def native_scenario(n: int = 1) -> tuple[Any, Any, Any, Any]:
    root, _ = scenario(None)
    ledger = build_sell_fill_ledger(root, ref())
    qty = ledger.context.requested_qty.value / Decimal(n)
    for index in range(n):
        ledger = record_sell_fill(
            ledger,
            fill(
                ledger,
                fill_ref=str(101 + 3 * index),
                executed_qty=q(str(qty)),
                observed_quote=Money(qty * Decimal(105), USDT),
            ),
        )
    root = bind_external_sell_order(root, ref(), binding(root))
    r = report(ledger, collection_ref="capture-1")
    ident = identity(ledger)
    pages = []
    cursor = "0"
    for start in range(0, n, 10):
        ts = tuple(trade(ledger, i) for i in range(start, min(start + 10, n)))
        next_cursor = str(int(ts[-1].trade_ref) + 1)
        pages.append(
            SellTradePage(f"page-{start}", cursor, next_cursor, ts, ident, "capture-1", 10)
        )
        cursor = next_cursor
    pages.append(SellTradePage("page-empty", cursor, None, (), ident, "capture-1", 10))
    query = SellTradeQueryScope(ident, "capture-1", SellTradePagination.BINANCE_FROM_ID, "0", 10)
    col = SellTradeCollection(
        ident, tuple(pages), SellCollectionStopReason.NO_MORE_RESULTS, r, r, query
    )
    return root, ledger, r, col


def evaluate_change(**changes: Any) -> Any:
    root, ledger, r, col = native_scenario()
    return assess_sell_finalization(root, ledger, r, replace(col, **changes))


def test_binding_preserves_finances_and_ref_and_identical_is_same_object() -> None:
    root = bound_cells()
    b = binding(root)
    updated = bind_external_sell_order(root, ref(), b)
    assert updated.inventory_book is root.inventory_book
    assert updated.sell_attempts is root.sell_attempts
    assert updated.external_binding_for(ref()) is b
    attempt = updated.attempt_for(ref())
    assert attempt is not None
    assert attempt.execution is not None
    assert attempt.execution.execution_ref == b.identity.execution_ref
    assert b.identity.order_ref != b.identity.execution_ref.value
    assert bind_external_sell_order(updated, ref(), replace(b)) is updated
    with pytest.raises(FrozenInstanceError):
        cast(Any, b).side = Side.BUY


@pytest.mark.parametrize(
    "field", ["venue_ref", "environment_ref", "account_ref", "order_ref", "client_order_ref"]
)
def test_original_identity_cannot_be_rebound(field: str) -> None:
    root = bound_cells()
    original = binding(root)
    root = bind_external_sell_order(root, ref(), original)
    changes: dict[str, Any] = {field: "other"}
    conflict = replace(original, identity=replace(original.identity, **changes))
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(root, ref(), conflict)
    assert error.value.code is E.BINDING_CONFLICT
    assert root.external_binding_for(ref()) is original


@pytest.mark.parametrize("client", [None, "client-123", "another-client"])
def test_duplicate_order_not_hidden_by_client_alias(client: str | None) -> None:
    root = bound_cells((0, 1))
    root = bind_external_sell_order(root, ref(), binding(root))
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(root, ref(1), binding(root, 1, client_order_ref=client))
    assert error.value.code is E.EXTERNAL_ORDER_ALREADY_BOUND
    assert root.external_binding_for(ref(1)) is None


@pytest.mark.parametrize("field", ["venue_ref", "environment_ref", "account_ref", "order_ref"])
def test_order_id_unicity_is_scoped(field: str) -> None:
    root = bound_cells((0, 1))
    root = bind_external_sell_order(root, ref(), binding(root))
    root = bind_external_sell_order(root, ref(1), binding(root, 1, **{field: "other"}))
    assert len(root.external_sell_bindings) == 2


@pytest.mark.parametrize(
    "status", [SellAttemptStatus.PREPARED, SellAttemptStatus.SUBMISSION_UNCERTAIN]
)
def test_binding_requires_bound_attempt(status: SellAttemptStatus) -> None:
    root = with_status(prepared_root(), status)
    b = binding(bound_cells())
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(root, ref(), b)
    assert error.value.code is E.ATTEMPT_NOT_BOUND


def test_wrong_cycle_and_context_rejected_without_mutation() -> None:
    root = bound_cells((0, 1))
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(root, ref(), binding(root, 1))
    assert error.value.code is E.AUTHORIZATION_MISMATCH
    assert not root.external_sell_bindings


@pytest.mark.parametrize("bad", [None, [], "SELL", Side.BUY])
def test_binding_side_must_be_explicit_sell(bad: Any) -> None:
    b = binding(bound_cells())
    with pytest.raises(SellOrderBindingError):
        ExternalSellOrderBinding(b.identity, bad)


@pytest.mark.parametrize(
    "field", ["venue_ref", "account_ref", "environment_ref", "order_ref", "client_order_ref"]
)
@pytest.mark.parametrize("bad", ["", " spaced", "new\nline", 3, 1.0])
def test_binding_revalidates_forged_nested_identity(field: str, bad: Any) -> None:
    b = binding(bound_cells())
    with pytest.raises(SellOrderBindingError):
        ExternalSellOrderBinding(forged(b.identity, **{field: bad}), Side.SELL)


@pytest.mark.parametrize(
    "shape", ["list", "duplicate", "reversed", "wrong-context", "unbound", "duplicate-order"]
)
def test_root_rejects_direct_binding_tampering(shape: str) -> None:
    root = bound_cells((0, 1))
    b0, b1 = binding(root), binding(root, 1, order_ref="124")
    values: Any = {
        "list": [b0],
        "duplicate": (b0, b0),
        "reversed": (b1, b0),
        "wrong-context": (
            replace(b0, identity=replace(b0.identity, execution_ref=b1.identity.execution_ref)),
        ),
        "unbound": (b0,),
        "duplicate-order": (b0, binding(root, 1)),
    }[shape]
    source = GridOperationalBook(root.inventory_book) if shape == "unbound" else root
    with pytest.raises(SellLifecycleError):
        replace(source, external_sell_bindings=values)


def test_identical_binding_revalidates_entire_root_first() -> None:
    root = bound_cells()
    b = binding(root)
    root = bind_external_sell_order(root, ref(), b)
    bad = forged(root, external_sell_bindings=(b, b))
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(bad, ref(), b)
    assert error.value.code is E.INVALID_OPERATIONAL_BOOK


@pytest.mark.parametrize(
    "asset_location", ["fee", "context-base", "context-quote", "fill-base", "fill-quote", "capital"]
)
def test_root_rejects_forged_nested_buy_asset(asset_location: str) -> None:
    inv = acquired()
    funded = inv.funded_buy_book
    consumed = funded.lifecycle.consumed[0]
    f = consumed.ledger.fills[0]
    if asset_location == "fee":
        bad_asset = forged(f.fee.asset, code="btc")
        consumed = forged(
            consumed,
            ledger=forged(consumed.ledger, fills=(forged(f, fee=forged(f.fee, asset=bad_asset)),)),
        )
    elif asset_location.startswith("context"):
        name = asset_location.split("-")[1]
        sym = consumed.context.intent.symbol
        bad_sym = forged(sym, **{name: forged(getattr(sym, name), code="btc")})
        consumed = forged(
            consumed,
            context=forged(
                consumed.context, intent=forged(consumed.context.intent, symbol=bad_sym)
            ),
        )
    elif asset_location.startswith("fill"):
        name = asset_location.split("-")[1]
        bad_sym = forged(f.symbol, **{name: forged(getattr(f.symbol, name), code="btc")})
        consumed = forged(
            consumed, ledger=forged(consumed.ledger, fills=(forged(f, symbol=bad_sym),))
        )
    else:
        funded = forged(
            funded,
            initial_quote_capital=forged(
                funded.initial_quote_capital, asset=forged(USDT, code="usdt")
            ),
        )
    funded = forged(funded, lifecycle=forged(funded.lifecycle, consumed=(consumed,)))
    with pytest.raises(SellLifecycleError):
        GridOperationalBook(forged(inv, funded_buy_book=funded))


def test_all_other_cell_updates_preserve_binding_and_old_reservation() -> None:
    root = bound_cells()
    root = bind_external_sell_order(root, ref(), binding(root))
    original = root
    root = prepare_other_buy(root)
    root = mark_operational_buy_submission_uncertain(root, ref(1))
    root = bind_operational_buy_execution(root, ref(1), buy_context(root))
    funded = root.inventory_book.funded_buy_book
    root = settle_operational_buy(root, finish(funded, 1, qty="0.02", suffix="preservation"))
    root = reserve_operational_sell(root, assessment(root.inventory_book, 1), q("0.0001"))
    from gridbot.application import build_sell_intent_for_cell

    root = prepare_sell(root, build_sell_intent_for_cell(root.inventory_book, ref(1)), ref(1))
    root = mark_sell_submission_uncertain(root, ref(1))
    root = bind_sell_execution(root, ref(1), context(root, 1))
    assert root.external_sell_bindings is original.external_sell_bindings
    assert root.inventory_book.reservation_for(ref()) is original.inventory_book.reservation_for(
        ref()
    )
    assert root.attempt_for(ref()) is original.attempt_for(ref())
    assert bind_sell_execution(root, ref(), context(root)) is root
    assert settle_operational_buy(root, funded.lifecycle.consumed[0]) is root


@pytest.mark.parametrize("n", [1, 10, 50, 100])
def test_structural_binding_and_collection_never_authenticate_or_finalize(n: int) -> None:
    root, ledger, r, col = native_scenario(n)
    a = assess_sell_finalization(root, ledger, r, col)
    assert a.binding_verification is SellBindingVerification.STRUCTURALLY_MATCHED
    assert a.collection_verification is SellCollectionVerification.STRUCTURALLY_COHERENT
    assert a.state is SellReconciliationState.PENDING_EVIDENCE
    assert C.EXTERNAL_IDENTITY_UNAUTHENTICATED in codes(a)
    assert C.EXTERNAL_COMPLETENESS_UNCONFIRMED in codes(a)
    assert C.ORDER_BINDING_UNCONFIRMED not in codes(a)
    assert C.ORDER_BINDING_STRUCTURALLY_VERIFIED in codes(a)


@pytest.mark.parametrize(
    "field", ["venue_ref", "account_ref", "environment_ref", "order_ref", "client_order_ref"]
)
def test_matching_numbers_from_other_order_are_conflicting(field: str) -> None:
    root, ledger, r, col = native_scenario()
    other = replace(r, identity=replace(r.identity, **{field: "other"}))
    a = assess_sell_finalization(root, ledger, other, col)
    assert a.binding_verification is SellBindingVerification.CONFLICTING
    assert C.ORDER_IDENTITY_MISMATCH in codes(a)


def test_missing_binding_and_legacy_collection_are_distinct() -> None:
    root, ledger, r, col = native_scenario()
    legacy = GridOperationalBook(root.inventory_book, root.sell_attempts)
    a = assess_sell_finalization(legacy, ledger, r, replace(col, query=None))
    assert a.binding_verification is SellBindingVerification.MISSING
    assert a.collection_verification is SellCollectionVerification.INSUFFICIENT_METADATA
    assert C.COLLECTION_QUERY_MISSING in codes(a)
    assert (
        assess_sell_finalization(root, ledger, r).collection_verification
        is SellCollectionVerification.NOT_PROVIDED
    )
    stale = GridOperationalBook(root.inventory_book)
    assert (
        assess_sell_finalization(stale, ledger, r, col).binding_verification
        is SellBindingVerification.ROOT_UNVERIFIED
    )


@pytest.mark.parametrize("reason", list(SellCollectionStopReason))
def test_collection_stop_claim_is_not_proof(reason: SellCollectionStopReason) -> None:
    a = evaluate_change(stop_reason=reason)
    assert C.EXTERNAL_COMPLETENESS_UNCONFIRMED in codes(a)
    assert (C.COLLECTION_NOT_EXHAUSTED in codes(a)) == (
        reason is not SellCollectionStopReason.NO_MORE_RESULTS
    )


@pytest.mark.parametrize("cursor", ["-1", "01", "\uff11\uff12", "x", "9" * 21, None])
def test_native_cursor_invalid(cursor: str | None) -> None:
    _, _, _, col = native_scenario()
    page = replace(col.pages[0], cursor_from=cursor)
    assert C.NATIVE_CURSOR_INVALID in codes(evaluate_change(pages=(page, *col.pages[1:])))


@pytest.mark.parametrize("next_cursor", ["0", "100", "101", "103", "999"])
def test_native_cursor_must_advance_to_max_plus_one(next_cursor: str) -> None:
    _, _, _, col = native_scenario()
    page = replace(col.pages[0], next_cursor=next_cursor)
    assert C.CURSOR_ADVANCE_INVALID in codes(evaluate_change(pages=(page, *col.pages[1:])))


@pytest.mark.parametrize(
    "target",
    [
        "page-identity",
        "page-capture",
        "page-limit",
        "query-identity",
        "report-capture",
        "before-capture",
        "after-capture",
        "empty-identity",
    ],
)
def test_request_scope_and_capture_mismatch(target: str) -> None:
    root, ledger, r, col = native_scenario()
    expected = C.CAPTURE_MISMATCH
    if target.endswith("identity"):
        expected = C.COLLECTION_SCOPE_MISMATCH
        wrong = replace(col.identity, account_ref="other")
        if target == "query-identity":
            col = replace(col, query=replace(col.query, identity=wrong))
        else:
            idx = 1 if target == "empty-identity" else 0
            pages = list(col.pages)
            pages[idx] = replace(pages[idx], query_identity=wrong)
            col = replace(col, pages=tuple(pages))
    elif target == "page-limit":
        expected = C.QUERY_LIMIT_INVALID
        col = replace(col, pages=(replace(col.pages[0], requested_limit=2), col.pages[1]))
    elif target == "page-capture":
        col = replace(
            col, pages=(replace(col.pages[0], collection_ref="old-capture"), col.pages[1])
        )
    elif target == "report-capture":
        r = replace(r, collection_ref="old-capture")
    else:
        field = "order_before" if target == "before-capture" else "order_after"
        col = replace(col, **{field: replace(getattr(col, field), collection_ref="old-capture")})
    a = assess_sell_finalization(root, ledger, r, col)
    assert expected in codes(a)
    assert a.collection_verification is SellCollectionVerification.INCONSISTENT


@pytest.mark.parametrize("field", ["query_identity", "collection_ref", "requested_limit"])
def test_missing_page_metadata_including_empty_page(field: str) -> None:
    _, _, _, col = native_scenario()
    col = replace(col, pages=(col.pages[0], replace(col.pages[1], **{field: None})))
    assert C.FIELD_MISSING in codes(evaluate_change(pages=col.pages))


@pytest.mark.parametrize("bad", [0, -1, True, 1.0, "10"])
def test_limits_type_and_sign(bad: Any) -> None:
    _, _, _, col = native_scenario()
    with pytest.raises(SellEvidenceError):
        replace(col.query, limit=bad)
    with pytest.raises(SellEvidenceError):
        replace(col.pages[0], requested_limit=bad)


def test_inclusive_boundary_gaps_truncation_and_empty_page_rules() -> None:
    _, _, _, col = native_scenario(10)
    # IDs 101,104,...: actual gaps are valid; inclusive cursor rejects IDs below it.
    bad = replace(col.pages[0], cursor_from="102")
    assert C.CURSOR_ADVANCE_INVALID in codes(evaluate_change(pages=(bad,)))
    full_without_next = replace(col.pages[0], next_cursor=None)
    assert C.COLLECTION_POSSIBLY_TRUNCATED in codes(evaluate_change(pages=(full_without_next,)))
    empty_with_next = replace(col.pages[-1], next_cursor="200")
    assert C.CURSOR_ADVANCE_INVALID in codes(evaluate_change(pages=(empty_with_next,)))
    assert C.QUERY_LIMIT_INVALID in codes(evaluate_change(query=replace(col.query, limit=1001)))
    assert C.PAGE_CHAIN_INCOMPLETE in codes(
        evaluate_change(query=replace(col.query, initial_cursor="10"))
    )


@pytest.mark.parametrize(
    ("asset", "fee"), [(USDT, "0"), (USDT, "0.01"), (BTC, "0.00001"), (Asset("BNB"), "0.0002")]
)
def test_exact_independent_fraction_oracle_and_no_financial_effect(asset: Asset, fee: str) -> None:
    root, ledger = scenario(fee=fee, asset=asset)
    before = root.inventory_book
    b = binding(root)
    root = bind_external_sell_order(root, ref(), b)
    a = assess_sell_finalization(root, ledger, report(ledger))
    x = sum((Fraction(f.executed_qty.value) for f in ledger.fills), Fraction(0))
    base_fee = sum(
        (Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == BTC), Fraction(0)
    )
    quote = sum((Fraction(f.observed_quote.amount) for f in ledger.fills), Fraction(0))
    quote_fee = sum(
        (Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == USDT), Fraction(0)
    )
    assert Fraction((ledger.gross_executed_qty + ledger.base_fee_qty).value) == x + base_fee
    assert Fraction(ledger.net_observed_quote.amount) == quote - quote_fee
    assert x + base_fee <= Fraction(
        ledger.context.requested_qty.value + ledger.context.intent.base_fee_hold.value
    )
    assert root.inventory_book is before
    assert a.state is SellReconciliationState.PENDING_EVIDENCE


def test_small_callers_context_is_preserved_and_finance_stays_exact() -> None:
    root, ledger, r, col = native_scenario()
    with localcontext() as ctx:
        ctx.prec = 2
        a = assess_sell_finalization(root, ledger, r, col)
        assert a.state is SellReconciliationState.PENDING_EVIDENCE
        assert ctx.prec == 2
        assert not ctx.flags[Inexact]


@pytest.mark.parametrize(
    "case",
    [
        "missing-query-limit",
        "missing-before",
        "missing-after",
        "missing-report-capture",
        "missing-before-capture",
        "missing-after-capture",
        "native-other-venue",
        "bad-pagination",
        "forged-query",
        "forged-page-identity",
    ],
)
def test_query_and_snapshot_boundary_cases(case: str) -> None:
    root, ledger, r, col = native_scenario()
    expected = C.FIELD_MISSING
    if case == "missing-query-limit":
        col = replace(col, query=replace(col.query, limit=None))
    elif case in ("missing-before", "missing-after"):
        col = replace(col, **{"order_before" if case.endswith("before") else "order_after": None})
    elif case == "missing-report-capture":
        r = replace(r, collection_ref=None)
    elif case.endswith("capture"):
        field = "order_before" if "before" in case else "order_after"
        col = replace(col, **{field: replace(getattr(col, field), collection_ref=None)})
    elif case == "native-other-venue":
        expected = C.COLLECTION_SCOPE_MISMATCH
        col = replace(
            col, query=replace(col.query, identity=replace(col.identity, venue_ref="OTHER"))
        )
    elif case == "bad-pagination":
        with pytest.raises(SellEvidenceError):
            replace(col.query, pagination="BINANCE_FROM_ID")
        return
    elif case == "forged-query":
        with pytest.raises(SellEvidenceError):
            replace(col, query=forged(col.query, collection_ref=""))
        return
    else:
        with pytest.raises(SellEvidenceError):
            replace(col.pages[0], query_identity=forged(col.identity, account_ref=""))
        return
    assert expected in codes(assess_sell_finalization(root, ledger, r, col))


@pytest.mark.parametrize("target", ["report", "page", "query"])
def test_capture_ref_rejected_without_normalization(target: str) -> None:
    _, _, r, col = native_scenario()
    source = r if target == "report" else col.pages[0] if target == "page" else col.query
    with pytest.raises(SellEvidenceError):
        replace(source, collection_ref="")


def test_symbol_components_remain_unambiguous_in_diagnostics() -> None:
    root, ledger, r, col = native_scenario()
    symbol = Symbol(Asset("BT"), Asset("CUSDT"))
    assert str(symbol) == str(r.identity.symbol)
    other = replace(r, identity=replace(r.identity, symbol=symbol), cumulative_quote=None)
    a = assess_sell_finalization(root, ledger, other, col)
    mismatch = next(f for f in a.findings if f.code is C.ORDER_IDENTITY_MISMATCH)
    assert mismatch.expected != mismatch.observed


@pytest.mark.parametrize("case", ["query-identity", "query-venue", "query-limit"])
def test_query_findings_identify_the_failing_request_boundary(case: str) -> None:
    root, ledger, r, col = native_scenario()
    if case == "query-limit":
        query = replace(col.query, limit=1001)
        pages = tuple(replace(p, requested_limit=1001) for p in col.pages)
        col = replace(col, query=query, pages=pages)
        expected, source = C.QUERY_LIMIT_INVALID, "collection.query.limit"
    else:
        field = "account_ref" if case == "query-identity" else "venue_ref"
        changes: dict[str, Any] = {field: "OTHER"}
        col = replace(col, query=replace(col.query, identity=replace(col.identity, **changes)))
        expected = C.COLLECTION_SCOPE_MISMATCH
        source = (
            "collection.query.identity" if case == "query-identity" else "collection.query.venue"
        )
    a = assess_sell_finalization(root, ledger, r, col)
    assert any(f.code is expected and f.source == source for f in a.findings)


def test_empty_book_revalidates_capital_asset_even_with_matching_forged_symbol() -> None:
    state = grid()
    funded = FundedBuyBook(BuyLifecycleBook(state), Money.parse("20", USDT))
    bad_asset = forged(USDT, code="usdt")
    bad_symbol = forged(state.plan.spec.symbol, quote=bad_asset)
    bad_state = forged(
        state, plan=forged(state.plan, spec=forged(state.plan.spec, symbol=bad_symbol))
    )
    bad_funded = forged(
        funded,
        lifecycle=forged(funded.lifecycle, grid_state=bad_state),
        initial_quote_capital=forged(funded.initial_quote_capital, asset=bad_asset),
    )
    with pytest.raises(SellLifecycleError):
        GridOperationalBook(forged(SellInventoryBook(funded), funded_buy_book=bad_funded))


def test_binding_precision_error_preserves_financial_code() -> None:
    root = bound_cells()
    b = binding(root)
    reserve = forged(root.inventory_book.reservations[0], base_fee_hold=q("1e-100"))
    bad = forged(root, inventory_book=forged(root.inventory_book, reservations=(reserve,)))
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(bad, ref(), b)
    assert error.value.code is E.FINANCIAL_PRECISION_ERROR
    assert error.value.__cause__ is not None


def test_binding_without_attempt_fails_typed() -> None:
    root = bound_cells()
    with pytest.raises(SellOrderBindingError) as error:
        bind_external_sell_order(GridOperationalBook(root.inventory_book), ref(), binding(root))
    assert error.value.code is E.ATTEMPT_NOT_BOUND


def test_declared_opaque_chain_and_unknown_native_start_are_distinct() -> None:
    root, ledger, r, col = native_scenario()
    query = replace(col.query, pagination=SellTradePagination.DECLARED_CHAIN, initial_cursor=None)
    page = replace(col.pages[0], cursor_from=None, next_cursor="opaque")
    end = replace(col.pages[-1], cursor_from="opaque")
    a = assess_sell_finalization(root, ledger, r, replace(col, query=query, pages=(page, end)))
    assert a.collection_verification is SellCollectionVerification.STRUCTURALLY_COHERENT
    assert C.EXTERNAL_IDENTITY_UNAUTHENTICATED in codes(a)
    native = replace(col.query, initial_cursor=None)
    other = assess_sell_finalization(root, ledger, r, replace(col, query=native))
    assert C.PAGE_CHAIN_INCOMPLETE in codes(other)
