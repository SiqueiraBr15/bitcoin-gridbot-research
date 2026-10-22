"""A17: evidências sintéticas, fixtures econômicas A8-A16 reais e oráculos explícitos."""

from __future__ import annotations

import dataclasses
from decimal import Decimal, Inexact, localcontext
from typing import Any, cast

import pytest

from gridbot.application import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellEvidenceError,
    SellEvidenceErrorCode,
    SellExecutionRef,
    SellFindingKind,
    SellObservedOutcome,
    SellOrderIdentity,
    SellReconciliationAssessment,
    SellReconciliationCode,
    SellReconciliationFinding,
    SellReconciliationState,
    SellTradeCollection,
    SellTradePage,
    assess_sell_finalization,
    bind_operational_buy_execution,
    build_sell_fill_ledger,
    record_sell_fill,
    settle_operational_buy,
)
from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_fills import SellFillLedger
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus, OrderType, Side
from gridbot.strategy import CellCycleRef
from tests.application.test_operational_grid import (
    buy_context,
    prepare_other_buy,
    prepared_root,
    ref,
)
from tests.application.test_sell_fills import bound_root, fill
from tests.application.test_sell_intents import ETHUSDT, fingerprint, finish, forged, p, q

C = SellReconciliationCode
K = SellFindingKind
S = OrderStatus
PENDING = SellReconciliationState.PENDING_EVIDENCE
BAD = SellReconciliationState.CONTRADICTORY_EVIDENCE


def identity(ledger: SellFillLedger, **changes: Any) -> SellOrderIdentity:
    values: dict[str, Any] = dict(
        venue_ref="BINANCE_SPOT",
        account_ref="synthetic-account",
        environment_ref="synthetic",
        order_ref="123",
        execution_ref=ledger.context.execution_ref,
        cycle_ref=ledger.context.cycle_ref,
        symbol=ledger.context.symbol,
        client_order_ref="client-123",
    )
    values.update(changes)
    return SellOrderIdentity(**values)


def report(ledger: SellFillLedger, **changes: Any) -> ObservedSellOrderReport:
    values: dict[str, Any] = dict(
        identity=identity(ledger),
        status=S.FILLED,
        original_qty=ledger.context.requested_qty,
        cumulative_executed_qty=ledger.gross_executed_qty,
        cumulative_quote=ledger.gross_observed_quote,
        limit_price=ledger.context.limit_price,
        source_ref="synthetic-terminal",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
    )
    values.update(changes)
    return ObservedSellOrderReport(**values)


def trade(ledger: SellFillLedger, index: int = 0, /, **changes: Any) -> CollectedSellTrade:
    f = ledger.fills[index]
    values: dict[str, Any] = dict(
        identity=identity(ledger),
        trade_ref=f.fill_ref,
        execution_price=f.execution_price,
        executed_qty=f.executed_qty,
        observed_quote=f.observed_quote,
        fee=f.fee,
        side=Side.SELL,
    )
    values.update(changes)
    return CollectedSellTrade(**values)


def collection(
    ledger: SellFillLedger, r: ObservedSellOrderReport | None = None, **changes: Any
) -> SellTradeCollection:
    snapshot = r if r is not None else report(ledger)
    values: dict[str, Any] = dict(
        identity=identity(ledger),
        pages=(
            SellTradePage(
                "synthetic-page",
                None,
                None,
                tuple(trade(ledger, i) for i in range(len(ledger.fills))),
            ),
        ),
        stop_reason=SellCollectionStopReason.NO_MORE_RESULTS,
        order_before=snapshot,
        order_after=snapshot,
    )
    values.update(changes)
    return SellTradeCollection(**values)


def scenario(
    qty: str | None = "0.031", fee: str = "0", asset: Asset = USDT, quote: str | None = None
) -> tuple[GridOperationalBook, SellFillLedger]:
    root = bound_root()
    ledger = build_sell_fill_ledger(root, ref())
    if qty is not None:
        gross = str(p(105).notional(q(qty))) if quote is None else quote
        ledger = record_sell_fill(
            ledger,
            fill(
                ledger,
                executed_qty=q(qty),
                observed_quote=Money.parse(gross, USDT),
                fee=Money.parse(fee, asset),
            ),
        )
    return root, ledger


def assess(
    root: GridOperationalBook, ledger: SellFillLedger, **changes: Any
) -> SellReconciliationAssessment:
    r = changes.pop("report", report(ledger))
    col = changes.pop("collection", collection(ledger, r))
    return assess_sell_finalization(root, ledger, r, col)


def codes(a: SellReconciliationAssessment) -> set[SellReconciliationCode]:
    return {f.code for f in a.findings}


def has(
    a: SellReconciliationAssessment,
    code: SellReconciliationCode,
    kind: SellFindingKind | None = None,
) -> None:
    assert any(f.code is code and (kind is None or f.kind is kind) for f in a.findings)


@pytest.mark.parametrize("status", [*OrderStatus, None])
@pytest.mark.parametrize("quantity", [None, "0.01", "0.031"])
def test_status_matrix_does_not_finalize_or_settle(
    status: OrderStatus | None, quantity: str | None
) -> None:
    root, ledger = scenario(quantity)
    before = fingerprint(root.inventory_book), hash(root), hash(ledger)
    r = report(ledger, status=status)
    a = assess(root, ledger, report=r)
    assert (fingerprint(root.inventory_book), hash(root), hash(ledger)) == before
    has(a, C.ORDER_BINDING_UNCONFIRMED, K.UNCONFIRMED)
    has(a, C.EXTERNAL_COMPLETENESS_UNCONFIRMED, K.UNCONFIRMED)
    assert a.state in (PENDING, BAD)
    if status is None:
        has(a, C.UNKNOWN_EXECUTION_STATUS)
    elif not status.is_terminal:
        has(a, C.NON_TERMINAL_ORDER)
    elif (status is S.FILLED and quantity != "0.031") or (status is S.REJECTED and quantity):
        has(a, C.TERMINAL_STATUS_CONFLICT, K.CONTRADICTORY)
        assert a.observed_outcome is SellObservedOutcome.UNDETERMINED
    elif quantity is None:
        assert a.observed_outcome is SellObservedOutcome.TERMINAL_NO_FILL_OBSERVED
    elif quantity == "0.01":
        assert a.observed_outcome is SellObservedOutcome.PARTIAL_TERMINAL_EXECUTION_OBSERVED
    elif status is S.FILLED:
        assert a.observed_outcome is SellObservedOutcome.FULL_TERMINAL_EXECUTION_OBSERVED
    else:
        has(a, C.TERMINAL_STATUS_POLICY_UNCONFIRMED)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("side", Side.BUY, C.SIDE_MISMATCH),
        ("order_type", OrderType.MARKET, C.ORDER_TYPE_MISMATCH),
        ("order_type", OrderType.LIMIT_MAKER, C.ORDER_TYPE_MISMATCH),
        ("original_qty", q("0.0311"), C.ORIGINAL_QUANTITY_MISMATCH),
        ("original_qty", q("0.032"), C.ORIGINAL_QUANTITY_MISMATCH),
        ("limit_price", p(104), C.LIMIT_PRICE_MISMATCH),
        ("cumulative_executed_qty", q(0), C.EXECUTED_QUANTITY_MISMATCH),
        ("cumulative_executed_qty", q("0.032"), C.EXECUTED_QUANTITY_MISMATCH),
        ("cumulative_quote", Money.parse("0", USDT), C.CUMULATIVE_QUOTE_MISMATCH),
        ("cumulative_quote", Money.parse("3.256", USDT), C.CUMULATIVE_QUOTE_MISMATCH),
    ],
)
def test_terminal_contradictions_have_values(
    field: str, value: object, code: SellReconciliationCode
) -> None:
    root, ledger = scenario()
    a = assess(root, ledger, report=report(ledger, **{field: value}))
    has(a, code, K.CONTRADICTORY)
    assert a.state is BAD
    assert a.observed_outcome is SellObservedOutcome.UNDETERMINED
    assert any(f.code is code and f.observed == value for f in a.findings)


@pytest.mark.parametrize(
    "field", ["original_qty", "limit_price", "cumulative_executed_qty", "cumulative_quote"]
)
def test_missing_report_fields_are_not_zero(field: str) -> None:
    root, ledger = scenario()
    a = assess(root, ledger, report=report(ledger, **{field: None}))
    has(a, C.FIELD_MISSING, K.MISSING)
    assert a.state is PENDING


IDENTITY_CHANGES = [
    ("venue_ref", "other-venue"),
    ("account_ref", "other-account"),
    ("environment_ref", "other-env"),
    ("order_ref", "456"),
    ("client_order_ref", "client-456"),
    ("client_order_ref", None),
    ("execution_ref", SellExecutionRef("other-execution")),
    ("cycle_ref", CellCycleRef(0, 1)),
    ("cycle_ref", CellCycleRef(1, 0)),
    ("symbol", ETHUSDT),
]


@pytest.mark.parametrize(("field", "value"), IDENTITY_CHANGES)
@pytest.mark.parametrize("source", ["report", "collection", "trade"])
def test_same_numbers_do_not_erase_different_identity(
    field: str, value: object, source: str
) -> None:
    root, ledger = scenario()
    r = report(ledger)
    col = collection(ledger, r)
    ident = identity(ledger, **{field: value})
    if source == "report":
        r = dataclasses.replace(r, identity=ident)
    elif source == "collection":
        col = dataclasses.replace(col, identity=ident)
    else:
        t = dataclasses.replace(trade(ledger), identity=ident)
        col = dataclasses.replace(col, pages=(SellTradePage("p", None, None, (t,)),))
    a = assess_sell_finalization(root, ledger, r, col)
    has(a, C.ORDER_IDENTITY_MISMATCH, K.CONTRADICTORY)
    if field == "symbol":
        has(a, C.SYMBOL_MISMATCH, K.CONTRADICTORY)
    elif field == "cycle_ref":
        has(a, C.CYCLE_MISMATCH, K.CONTRADICTORY)
    elif field == "execution_ref":
        has(a, C.EXECUTION_REF_MISMATCH, K.CONTRADICTORY)
    assert a.state is BAD


@pytest.mark.parametrize("field", ["execution_price", "executed_qty", "observed_quote", "fee"])
def test_missing_trade_fields_remain_missing(field: str) -> None:
    root, ledger = scenario()
    t = trade(ledger, **{field: None})
    col = collection(ledger, pages=(SellTradePage("p", None, None, (t,)),))
    a = assess(root, ledger, collection=col)
    has(a, C.FEE_EVIDENCE_INCOMPLETE if field == "fee" else C.FIELD_MISSING, K.MISSING)
    assert a.state is PENDING
    assert t.fee is None if field == "fee" else True


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("side", Side.BUY, C.SIDE_MISMATCH),
        ("execution_price", p(104), C.TRADE_FIELD_MISMATCH),
        ("executed_qty", q("0.030"), C.TRADE_FIELD_MISMATCH),
        ("executed_qty", q(0), C.NON_TRADE_OBSERVATION),
        ("executed_qty", q("0.032"), C.OVERFILL),
        ("observed_quote", Money.parse("0", USDT), C.QUOTE_DISCREPANCY),
        ("observed_quote", Money.parse("3.255000001", USDT), C.QUOTE_DISCREPANCY),
        ("fee", Money.parse("0.01", USDT), C.FEE_MISMATCH),
        ("fee", Money.parse("0.000101", BTC), C.BASE_FEE_EXCEEDS_HOLD),
        ("fee", Money.parse("4", USDT), C.QUOTE_FEE_EXCEEDS_PROCEEDS),
        ("fee", Money.parse("0.01", Asset("BNB")), C.FEE_MISMATCH),
        ("trade_ref", "-1", C.NON_TRADE_OBSERVATION),
    ],
)
def test_external_trade_contradictions_keep_original_observation(
    field: str, value: object, code: SellReconciliationCode
) -> None:
    root, ledger = scenario()
    t = trade(ledger, **{field: value})
    col = collection(ledger, pages=(SellTradePage("p", None, None, (t,)),))
    a = assess(root, ledger, collection=col)
    has(a, code, K.CONTRADICTORY)
    assert a.state is BAD
    assert getattr(a.collection.pages[0].trades[0], field) == value if a.collection else False
    assert ledger.fills[0].fee == Money.zero(USDT)


@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB"), Asset("XYZ")])
@pytest.mark.parametrize("amount", ["0", "0.00001"])
def test_observed_fee_exact_asset_and_zero(asset: Asset, amount: str) -> None:
    root, ledger = scenario(fee=amount, asset=asset)
    a = assess(root, ledger)
    assert a.state is PENDING
    assert C.FEE_MISMATCH not in codes(a)
    assert ledger.fees_by_asset == (Money.parse(amount, asset),)
    assert ledger.net_observed_quote == Money.parse("3.255", USDT) - (
        Money.parse(amount if asset == USDT else "0", USDT)
    )
    if asset not in (BTC, USDT) and amount != "0":
        has(a, C.THIRD_ASSET_FEE_UNVALUED, K.INFORMATION)


@pytest.mark.parametrize("quote", ["0", "3.25", "3.25500000000000000001"])
def test_ledger_discrepancy_not_repaired_by_matching_report(quote: str) -> None:
    root, ledger = scenario(quote=quote)
    a = assess(root, ledger)
    has(a, C.QUOTE_DISCREPANCY, K.CONTRADICTORY)
    assert any(
        f.code is C.QUOTE_DISCREPANCY
        and f.source == "ledger:trade-1"
        and f.expected == Money.parse("3.255", USDT)
        and f.observed == Money.parse(quote, USDT)
        for f in a.findings
    )
    assert a.state is BAD
    assert ledger.gross_observed_quote == Money.parse(quote, USDT)
    assert ledger.gross_derived_quote == Money.parse("3.255", USDT)


@pytest.mark.parametrize("reason", list(SellCollectionStopReason))
def test_collection_stop_never_proves_complete(reason: SellCollectionStopReason) -> None:
    root, ledger = scenario()
    a = assess(root, ledger, collection=collection(ledger, stop_reason=reason))
    assert a.state is PENDING
    has(a, C.EXTERNAL_COMPLETENESS_UNCONFIRMED)
    assert (C.COLLECTION_NOT_EXHAUSTED in codes(a)) == (
        reason is not SellCollectionStopReason.NO_MORE_RESULTS
    )


@pytest.mark.parametrize(
    "case",
    [
        "no_pages",
        "missing_trade",
        "extra_trade",
        "duplicate_same",
        "duplicate_conflict",
        "start_cursor",
        "end_cursor",
        "gap",
        "stopped_middle",
        "loop",
        "repeat_source",
        "missing_before",
        "missing_after",
        "changed_before",
        "changed_after",
    ],
)
def test_collection_structure(case: str) -> None:
    root, ledger = scenario()
    t = trade(ledger)
    r = report(ledger)
    col = collection(ledger, r)
    expected = C.PAGE_CHAIN_INCOMPLETE
    if case == "no_pages":
        col = dataclasses.replace(col, pages=())
    elif case == "missing_trade":
        col = collection(ledger, pages=(SellTradePage("p", None, None, ()),))
        expected = C.FILL_SET_INCOMPLETE
    elif case == "extra_trade":
        col = collection(
            ledger,
            pages=(SellTradePage("p", None, None, (t, dataclasses.replace(t, trade_ref="extra"))),),
        )
        expected = C.TRADE_SET_MISMATCH
    elif case.startswith("duplicate"):
        other = (
            t if case == "duplicate_same" else dataclasses.replace(t, fee=Money.parse("1", USDT))
        )
        col = collection(ledger, pages=(SellTradePage("p", None, None, (t, other)),))
        expected = C.TRADE_ID_CONFLICT
    elif case == "start_cursor":
        col = collection(ledger, pages=(SellTradePage("p", "100", None, (t,)),))
    elif case == "end_cursor":
        col = collection(ledger, pages=(SellTradePage("p", None, "200", (t,)),))
    elif case in {"gap", "stopped_middle", "loop", "repeat_source"}:
        col = collection(
            ledger,
            pages=(
                SellTradePage("p", None, None if case == "stopped_middle" else "200", (t,)),
                SellTradePage(
                    "p" if case == "repeat_source" else "p2",
                    "300" if case == "gap" else "200",
                    "200" if case == "loop" else None,
                    (),
                ),
            ),
        )
        if case == "repeat_source":
            expected = C.PAGE_SOURCE_CONFLICT
    elif case.startswith("missing"):
        col = dataclasses.replace(col, **cast(Any, {"order_" + case.split("_")[1]: None}))
        expected = C.FIELD_MISSING
    else:
        col = dataclasses.replace(
            col,
            **cast(
                Any,
                {
                    "order_" + case.split("_")[1]: dataclasses.replace(
                        r, cumulative_quote=Money.parse("3.256", USDT)
                    )
                },
            ),
        )
        expected = C.COLLECTION_CHANGED
    a = assess(root, ledger, collection=col)
    has(a, expected)
    if case == "loop":
        has(a, C.PAGE_CHAIN_INCOMPLETE, K.CONTRADICTORY)
        assert a.state is BAD


def test_coherent_multiple_pages_are_still_pending() -> None:
    root, ledger = scenario("0.01")
    ledger = record_sell_fill(
        ledger,
        fill(
            ledger,
            fill_ref="trade-2",
            executed_qty=q("0.021"),
            observed_quote=Money.parse("2.205", USDT),
            fee=Money.parse("0.00005", BTC),
        ),
    )
    col = collection(
        ledger,
        pages=(
            SellTradePage("p1", None, "t2", (trade(ledger, 0),)),
            SellTradePage("p2", "t2", None, (trade(ledger, 1),)),
        ),
    )
    a = assess(root, ledger, collection=col)
    assert a.state is PENDING
    assert C.PAGE_CHAIN_INCOMPLETE not in codes(a)
    assert ledger.gross_executed_qty == q("0.031")
    assert ledger.base_fee_qty == q("0.00005")
    assert ledger.net_observed_quote == Money.parse("3.255", USDT)


@pytest.mark.parametrize(
    "case",
    [
        "unbound",
        "uncertain",
        "lost_reservation",
        "other_execution",
        "origin_not_consumed",
        "changed_fee_hold",
    ],
)
def test_current_root_is_revalidated_and_stale_is_explicit(case: str) -> None:
    root, ledger = scenario()
    current = root
    if case in {"unbound", "uncertain"}:
        current = prepared_root()
        if case == "uncertain":
            from gridbot.application import mark_sell_submission_uncertain

            current = mark_sell_submission_uncertain(current, ref())
    elif case == "lost_reservation":
        current = forged(root, inventory_book=forged(root.inventory_book, reservations=()))
    elif case == "other_execution":
        attempt = root.sell_attempts[0]
        assert attempt.execution is not None
        changed = dataclasses.replace(attempt.execution, execution_ref=SellExecutionRef("another"))
        current = dataclasses.replace(
            root, sell_attempts=(dataclasses.replace(attempt, execution=changed),)
        )
    elif case == "origin_not_consumed":
        funded = root.inventory_book.funded_buy_book
        current = forged(
            root,
            inventory_book=forged(
                root.inventory_book,
                funded_buy_book=forged(funded, lifecycle=forged(funded.lifecycle, consumed=())),
            ),
        )
    else:
        reservation = forged(root.inventory_book.reservations[0], base_fee_hold=q("0.0002"))
        current = forged(
            root, inventory_book=forged(root.inventory_book, reservations=(reservation,))
        )
    a = assess(current, ledger)
    has(a, C.STALE_OPERATIONAL_BOOK, K.UNCONFIRMED)
    assert a.observed_outcome is SellObservedOutcome.UNDETERMINED
    assert root.inventory_book.reserved_base_fee_qty == q("0.0001")


def test_other_cell_buy_settlement_preserves_valid_sell_authority() -> None:
    root, ledger = scenario()
    current = prepare_other_buy(root)
    current = bind_operational_buy_execution(current, ref(1), buy_context(current))
    current = settle_operational_buy(
        current, finish(current.inventory_book.funded_buy_book, 1, "0.01", "0")
    )
    a = assess(current, ledger)
    assert C.STALE_OPERATIONAL_BOOK not in codes(a)
    assert a.state is PENDING
    assert current.inventory_book.reservations is root.inventory_book.reservations


def test_absent_report_collection_and_repeat_leave_every_source_unchanged() -> None:
    root, ledger = scenario()
    before = hash(root), hash(ledger), fingerprint(root.inventory_book)
    a = assess_sell_finalization(root, ledger, None)
    has(a, C.ORDER_REPORT_MISSING, K.MISSING)
    has(a, C.COLLECTION_MISSING, K.MISSING)
    assert a.observed_outcome is SellObservedOutcome.UNDETERMINED
    assert a == dataclasses.replace(a)
    assert before == (hash(root), hash(ledger), fingerprint(root.inventory_book))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("venue_ref", ""),
        ("account_ref", " x"),
        ("environment_ref", "x "),
        ("order_ref", "x" * 129),
        ("client_order_ref", ""),
        ("execution_ref", "sell-0"),
        ("cycle_ref", (0, 0)),
        ("symbol", "BTCUSDT"),
        ("order_ref", 123),
    ],
)
def test_identity_invalid_types_and_refs(field: str, bad: object) -> None:
    _, ledger = scenario()
    with pytest.raises(SellEvidenceError) as error:
        identity(ledger, **{field: bad})
    assert error.value.code is SellEvidenceErrorCode.INVALID_EVIDENCE


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("status", "FILLED"),
        ("status", "UNKNOWN"),
        ("side", "SELL"),
        ("order_type", "LIMIT"),
        ("original_qty", Decimal("0.031")),
        ("cumulative_quote", Money.parse("-1", USDT)),
        ("cumulative_quote", Money.parse("1", BTC)),
        ("limit_price", 105.0),
        ("source_ref", " "),
        ("identity", None),
    ],
)
def test_report_boundary_rejects_invalid_types_not_repair(field: str, bad: object) -> None:
    _, ledger = scenario()
    with pytest.raises(SellEvidenceError):
        report(ledger, **{field: bad})


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("trade_ref", ""),
        ("fee", Money.parse("-1", BTC)),
        ("fee", 0.0),
        ("observed_quote", Money.parse("1", BTC)),
        ("executed_qty", "0.031"),
        ("execution_price", 105),
        ("side", "SELL"),
        ("identity", None),
    ],
)
def test_trade_boundary_rejects_invalid_types(field: str, bad: object) -> None:
    _, ledger = scenario()
    with pytest.raises(SellEvidenceError):
        trade(ledger, **{field: bad})


@pytest.mark.parametrize(
    "case",
    [
        "pages_list",
        "trades_list",
        "bad_page",
        "bad_trade",
        "stop_string",
        "bad_before",
        "bad_after",
    ],
)
def test_nested_collections_require_immutable_valid_sources(case: str) -> None:
    _, ledger = scenario()

    def construct() -> None:
        if case == "trades_list":
            SellTradePage("p", None, None, cast(Any, []))
        elif case == "bad_trade":
            SellTradePage("p", None, None, cast(Any, (None,)))
        else:
            changes: dict[str, Any] = {"pages": []}
            if case == "bad_page":
                changes = {"pages": (None,)}
            elif case == "stop_string":
                changes = {"stop_reason": "NO_MORE_RESULTS"}
            elif case in {"bad_before", "bad_after"}:
                changes = {"order_" + case.split("_")[1]: "report"}
            collection(ledger, **changes)

    with pytest.raises(SellEvidenceError):
        construct()


@pytest.mark.parametrize("case", ["report", "trade_fee", "symbol", "cycle", "ledger", "buy_origin"])
def test_forged_nested_inputs_fail_deep_revalidation(case: str) -> None:
    root, ledger = scenario()
    r = report(ledger)
    col = collection(ledger, r)
    if case == "report":
        r = forged(r, original_qty=forged(q(1), value=Decimal("-1")))
    elif case == "trade_fee":
        t = forged(trade(ledger), fee=forged(Money.zero(USDT), asset=forged(USDT, code="bad")))
        col = forged(col, pages=(forged(col.pages[0], trades=(t,)),))
    elif case == "symbol":
        r = forged(
            r,
            identity=forged(
                r.identity, symbol=forged(r.identity.symbol, base=forged(BTC, code="bad"))
            ),
        )
    elif case == "cycle":
        r = forged(r, identity=forged(r.identity, cycle_ref=forged(ref(), cycle_seq=True)))
    elif case == "ledger":
        ledger = forged(ledger, fills=(*ledger.fills, *ledger.fills))
    else:
        context = ledger.context
        buy = context.intent.finalized_buy
        bad_buy = forged(
            buy, ledger=forged(buy.ledger, fills=(*buy.ledger.fills, *buy.ledger.fills))
        )
        reservation = context.intent.reservation
        bad_reservation = forged(
            reservation, assessment=forged(reservation.assessment, finalized_buy=bad_buy)
        )
        ledger = forged(
            ledger,
            context=forged(context, intent=forged(context.intent, reservation=bad_reservation)),
        )
    with pytest.raises(SellEvidenceError):
        assess_sell_finalization(root, ledger, r, col)


def test_decimal_small_context_and_exact_conservation() -> None:
    root, ledger = scenario(fee="0.00005", asset=BTC)
    before = fingerprint(root.inventory_book)
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        a = assess(root, ledger)
        assert a.state is PENDING
        assert ledger.gross_executed_qty + ledger.base_fee_qty == q("0.03105")
        assert ledger.context.intent.total_base_commitment == q("0.0311")
        assert ledger.context.intent.confirmed_net_base_qty == q("0.031968")
        assert ctx.prec == 2
    assert before == fingerprint(root.inventory_book)


def test_inexact_external_product_fails_typed_and_preserves_observation() -> None:
    root, ledger = scenario()
    t = trade(ledger, execution_price=p("1.0000000000000000000000000000000001"))
    col = collection(ledger, pages=(SellTradePage("p", None, None, (t,)),))
    with pytest.raises(SellEvidenceError) as error:
        assess(root, ledger, collection=col)
    assert error.value.code is SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR
    assert isinstance(error.value.__cause__, Inexact)
    assert col.pages[0].trades[0] is t


def test_precision_error_in_current_root_is_not_pending() -> None:
    root, ledger = scenario()
    bad_reservation = forged(root.inventory_book.reservations[0], base_fee_hold=q("1e-100"))
    bad = forged(root, inventory_book=forged(root.inventory_book, reservations=(bad_reservation,)))
    with pytest.raises(SellEvidenceError) as error:
        assess(bad, ledger)
    assert error.value.code is SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR


def test_values_frozen_slotted_and_assessment_has_only_sources() -> None:
    root, ledger = scenario()
    a = assess(root, ledger)
    r = report(ledger)
    col = collection(ledger)
    for obj in (r.identity, r, trade(ledger), col.pages[0], col, a, a.findings[0]):
        assert not hasattr(obj, "__dict__")
        assert isinstance(hash(obj), int)
        field = dataclasses.fields(obj)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, field, getattr(obj, field))
    assert [f.name for f in dataclasses.fields(a)] == ["book", "ledger", "report", "collection"]


@pytest.mark.parametrize("value", [None, [], 1.0, "book"])
def test_assessment_rejects_raw_inputs(value: Any) -> None:
    root, ledger = scenario()
    with pytest.raises(SellEvidenceError):
        assess_sell_finalization(value, ledger, report(ledger))
    with pytest.raises(SellEvidenceError):
        assess_sell_finalization(root, value, report(ledger))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", "FIELD_MISSING"),
        ("kind", "MISSING"),
        ("source", 12),
        ("expected", []),
        ("observed", (12,)),
        ("observed", 1.0),
    ],
)
def test_diagnostics_direct_construction_checks(field: str, value: Any) -> None:
    values: dict[str, Any] = dict(code=C.FIELD_MISSING, kind=K.MISSING, source="report")
    values[field] = value
    with pytest.raises(SellEvidenceError):
        SellReconciliationFinding(**values)


def test_no_finalized_type_or_effective_operation_exposed() -> None:
    import gridbot.application as facade
    import gridbot.application.sell_reconciliation as module

    for name in ("FinalizedSell", "finalize_sell", "settle_sell", "release_sell", "confirm_sell"):
        assert not hasattr(module, name)
        assert not hasattr(facade, name)


@pytest.mark.parametrize("field", ["side", "order_type"])
def test_terminal_side_and_type_must_be_supplied_not_defaulted(field: str) -> None:
    _, ledger = scenario()
    source = report(ledger)
    kwargs = {
        f.name: getattr(source, f.name) for f in dataclasses.fields(source) if f.name != field
    }
    with pytest.raises(TypeError):
        ObservedSellOrderReport(**kwargs)


def test_trade_side_must_be_supplied_not_defaulted() -> None:
    _, ledger = scenario()
    source = trade(ledger)
    kwargs = {
        f.name: getattr(source, f.name) for f in dataclasses.fields(source) if f.name != "side"
    }
    with pytest.raises(TypeError):
        CollectedSellTrade(**kwargs)


def test_coherent_claims_for_another_order_still_do_not_prove_a15_binding() -> None:
    root, ledger = scenario()
    claimed = identity(ledger, order_ref="unbound-order")
    r = report(ledger, identity=claimed)
    t = trade(ledger, identity=claimed)
    col = collection(ledger, r, identity=claimed, pages=(SellTradePage("p", None, None, (t,)),))
    a = assess_sell_finalization(root, ledger, r, col)
    # A15 não possui order ID para confrontar esta declaração coerente. Não autenticar.
    assert a.state is PENDING
    has(a, C.ORDER_BINDING_UNCONFIRMED, K.UNCONFIRMED)
    has(a, C.EXTERNAL_COMPLETENESS_UNCONFIRMED, K.UNCONFIRMED)


def test_different_terminal_trace_is_same_observed_content() -> None:
    root, ledger = scenario()
    r = report(ledger)
    col = collection(ledger, r, order_before=dataclasses.replace(r, source_ref="another-trace"))
    assert C.COLLECTION_CHANGED not in codes(assess(root, ledger, collection=col))


def test_mixed_fees_multiple_fills_no_conversion() -> None:
    root, ledger = scenario("0.01", "0.00002", BTC)
    for index, asset in enumerate((USDT, Asset("BNB"), Asset("XYZ")), 2):
        ledger = record_sell_fill(
            ledger,
            fill(
                ledger,
                fill_ref=f"trade-{index}",
                executed_qty=q("0.007"),
                observed_quote=Money.parse("0.735", USDT),
                fee=Money.parse("0.001", asset),
            ),
        )
    a = assess(root, ledger)
    assert a.state is PENDING
    assert ledger.gross_executed_qty == q("0.031")
    assert ledger.net_observed_quote == Money.parse("3.254", USDT)
    assert ledger.fees_by_asset == tuple(
        Money.parse(n, Asset(asset))
        for asset, n in (("BNB", "0.001"), ("BTC", "0.00002"), ("USDT", "0.001"), ("XYZ", "0.001"))
    )
