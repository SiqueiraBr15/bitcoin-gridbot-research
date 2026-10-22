from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from decimal import Inexact, localcontext
from fractions import Fraction
from itertools import permutations
from typing import Any, cast

import pytest

from gridbot.application.sell_candidate import (
    SellCandidateEligibility,
    SellCandidateTrustLimit,
    SellFinalizationCandidate,
)
from gridbot.application.sell_evidence import (
    SellCollectionStopReason,
    SellEvidenceError,
    SellTradeIdentityCoverage,
)
from gridbot.application.sell_fills import SellFillLedger
from gridbot.application.sell_reconciliation import (
    SellReconciliationCode,
    assess_sell_finalization,
)
from gridbot.domain import BTC, USDT, DomainError, Money, Qty
from gridbot.exchange.binance.offline_evidence import (
    OfflineIssueCode,
    OfflineSellSource,
    RawSellObservation,
    normalize_sell_observation,
)
from gridbot.exchange.binance.offline_replay import (
    OfflineSellReplay,
    OfflineSellReplayPlan,
    OfflineSellTape,
    replay_sell_observations,
)
from tests.application.test_external_sell_identity import native_scenario
from tests.application.test_sell_intents import forged


def wire_scenario(n: int = 1) -> OfflineSellReplay:
    root, ledger, report, collection = native_scenario(n)
    query = collection.query
    assert query is not None
    assert report.original_qty is not None
    assert report.cumulative_executed_qty is not None
    assert report.cumulative_quote is not None
    assert report.limit_price is not None
    order = {
        "symbol": str(report.identity.symbol),
        "orderId": int(report.identity.order_ref),
        "clientOrderId": report.identity.client_order_ref,
        "side": "SELL",
        "type": "LIMIT",
        "status": "FILLED",
        "origQty": str(report.original_qty.value),
        "executedQty": str(report.cumulative_executed_qty.value),
        "cummulativeQuoteQty": str(report.cumulative_quote.amount),
        "price": str(report.limit_price.value),
    }
    raw = RawSellObservation(
        "order", OfflineSellSource.ORDER, report.identity, json.dumps(order), query.collection_ref
    )
    observations = [raw]
    page_refs = []
    fills = {f.fill_ref: f for f in ledger.fills}
    for index, page in enumerate(collection.pages):
        name = "page-" + str(index)
        page_refs.append(name)
        trades = []
        for trade in page.trades:
            f = fills[trade.trade_ref]
            trades.append(
                {
                    "symbol": str(f.symbol),
                    "orderId": int(report.identity.order_ref),
                    "id": int(f.fill_ref),
                    "price": str(f.execution_price.value),
                    "qty": str(f.executed_qty.value),
                    "quoteQty": str(f.observed_quote.amount),
                    "commission": str(f.fee.amount),
                    "commissionAsset": f.fee.asset.code,
                    "isBuyer": False,
                    "isMaker": False,
                }
            )
        observations.append(
            RawSellObservation(
                name,
                OfflineSellSource.MY_TRADES_PAGE,
                report.identity,
                json.dumps(trades),
                query.collection_ref,
                page.cursor_from,
                page.next_cursor,
                page.requested_limit,
            )
        )
    plan = OfflineSellReplayPlan(
        query, "order", "order", "order", tuple(page_refs), SellCollectionStopReason.NO_MORE_RESULTS
    )
    return replay_sell_observations(root, OfflineSellTape(tuple(observations)), plan)


def edited(
    replay: OfflineSellReplay,
    ref: str,
    field: str,
    value: object,
    remove: bool = False,
    row: int = 0,
) -> OfflineSellReplay:
    observations = []
    for raw in replay.tape.observations:
        if raw.source_ref == ref:
            payload: Any = json.loads(raw.payload)
            data = payload[row] if isinstance(payload, list) else payload
            if remove:
                del data[field]
            else:
                data[field] = value
            raw = replace(raw, payload=json.dumps(payload))
        observations.append(raw)
    return replace(replay, tape=OfflineSellTape(tuple(observations)))


def event(
    replay: OfflineSellReplay, execution_type: str = "TRADE", /, **changes: object
) -> RawSellObservation:
    order = json.loads(replay.tape.observations[0].payload)
    trade = json.loads(replay.tape.observations[1].payload)[0]
    payload = {
        "e": "executionReport",
        "s": "BTCUSDT",
        "i": order["orderId"],
        "c": order["clientOrderId"],
        "S": "SELL",
        "o": "LIMIT",
        "q": order["origQty"],
        "p": order["price"],
        "z": order["executedQty"],
        "Z": order["cummulativeQuoteQty"],
        "X": order["status"],
        "x": execution_type,
        "t": trade["id"],
        "I": 888888,
        "l": trade["qty"],
        "L": trade["price"],
        "Y": trade["quoteQty"],
        "n": trade["commission"],
        "N": trade["commissionAsset"],
        "m": False,
    }
    payload.update(changes)
    return RawSellObservation(
        "event",
        OfflineSellSource.EXECUTION_REPORT,
        replay.plan.query.identity,
        json.dumps({"subscriptionId": 0, "event": payload}),
        replay.plan.query.collection_ref,
    )


def replay_ledger(replay: OfflineSellReplay) -> SellFillLedger:
    ledger = replay.projection.ledger
    assert ledger is not None
    return ledger


@pytest.mark.parametrize("n", [1, 10, 50, 100])
def test_wire_pipeline_candidate_is_pure_and_never_authenticates(n: int) -> None:
    replay = wire_scenario(n)
    projection = replay.projection
    candidate = replay.candidate
    assert candidate is not None
    assert projection.quarantined_sources == ()
    assert candidate.trust_limit is SellCandidateTrustLimit.PROVIDED_EVIDENCE_STRUCTURAL_ONLY
    assert candidate.binding.identity == replay.plan.query.identity
    assert candidate.executed_qty == Qty.parse(".031")
    assert candidate.unexecuted_qty.is_zero
    assert candidate.gross_quote == Money.parse("3.255", USDT)
    assert candidate.net_quote.amount <= candidate.gross_quote.amount
    assert projection.ledger is not None
    assert candidate.fees_by_asset == projection.ledger.fees_by_asset
    assert {f.code for f in candidate.residual_findings} >= {
        SellReconciliationCode.EXTERNAL_IDENTITY_UNAUTHENTICATED,
        SellReconciliationCode.EXTERNAL_COMPLETENESS_UNCONFIRMED,
    }
    assert candidate.assessment.book is replay.book
    assert candidate.assessment.book.inventory_book is replay.book.inventory_book
    assert not hasattr(candidate, "trusted")
    assert not hasattr(candidate, "finalize_sell")


def test_mytrades_client_id_absence_is_explicit_not_invented() -> None:
    replay = wire_scenario()
    trade = normalize_sell_observation(replay.tape.observations[1]).trades[0]
    assert trade.identity.client_order_ref is None
    assert trade.identity_coverage is SellTradeIdentityCoverage.ORDER_ID_WITHOUT_CLIENT_ID
    with pytest.raises(SellEvidenceError):
        replace(trade, identity=replace(trade.identity, client_order_ref="other"))


@pytest.mark.parametrize("field", ["orderId", "symbol", "clientOrderId", "side", "type"])
def test_wrong_order_header_identity_and_type_block_candidate(field: str) -> None:
    value = {
        "orderId": 999,
        "symbol": "ETHUSDT",
        "clientOrderId": "other",
        "side": "BUY",
        "type": "MARKET",
    }[field]
    replay = edited(wire_scenario(), "order", field, value)
    assert replay.candidate is None
    assert replay.tape.observations[0].payload
    if field in {"orderId", "clientOrderId"}:
        assert any(
            i.code is OfflineIssueCode.IDENTITY_CONFLICT and i.field == "report.identity"
            for i in replay.projection.issues
        )


@pytest.mark.parametrize(
    "field", ["account_ref", "environment_ref", "venue_ref", "execution_ref", "cycle_ref"]
)
def test_same_numbers_wrong_declared_scope_is_quarantined(field: str) -> None:
    replay = wire_scenario()
    raw = replay.tape.observations[1]
    value = (
        replace(raw.scope.execution_ref, value="other")
        if field == "execution_ref"
        else (replace(raw.scope.cycle_ref, cycle_seq=1) if field == "cycle_ref" else "other")
    )
    changes: dict[str, Any] = {field: value}
    raw = replace(raw, scope=replace(raw.scope, **changes))
    replay = replace(
        replay,
        tape=OfflineSellTape((replay.tape.observations[0], raw, *replay.tape.observations[2:])),
    )
    assert replay.candidate is None
    assert OfflineIssueCode.IDENTITY_CONFLICT in {i.code for i in replay.projection.issues}
    assert any(i.field == "scope" for i in replay.projection.issues)


@pytest.mark.parametrize(
    "field",
    ["qty", "price", "quoteQty", "commission", "commissionAsset", "id", "orderId", "isBuyer"],
)
@pytest.mark.parametrize("case", ["missing", "null", "numeric", "negative", "nan"])
def test_adversarial_trade_fields_are_retained_and_blocked(field: str, case: str) -> None:
    value = {"null": None, "numeric": 1.2, "negative": "-1", "nan": "NaN", "missing": None}[case]
    replay = edited(wire_scenario(), "page-0", field, value, remove=case == "missing")
    raw = replay.tape.observations[1]
    projection = replay.projection
    assert projection.quarantined_sources
    assert replay.candidate is None
    assert projection.normalized[1].raw is raw
    assert raw.payload in [o.payload for o in replay.tape.observations]


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "origQty",
        "executedQty",
        "cummulativeQuoteQty",
        "price",
        "side",
        "type",
        "symbol",
        "orderId",
    ],
)
@pytest.mark.parametrize("case", ["missing", "null"])
def test_order_missing_fields_never_become_zero_or_filled(field: str, case: str) -> None:
    replay = edited(wire_scenario(), "order", field, None, remove=case == "missing")
    assert replay.candidate is None
    assert replay.projection.quarantined_sources


@pytest.mark.parametrize(
    "payload", ["{", "[]", "null", "1", '{"qty":NaN}', '{"qty":Infinity}', '{"x":1,"x":2}', "{}"]
)
def test_raw_capture_precedes_json_and_financial_validation(payload: str) -> None:
    replay = wire_scenario()
    raw = replace(replay.tape.observations[0], payload=payload)
    tape = OfflineSellTape().capture(raw)
    assert tape.observations[0].payload == payload
    assert normalize_sell_observation(raw).issues
    assert "payload=" not in repr(raw)


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-Infinity", "-1", "+1", "1e-3", "1_0", " 1 ", "0", "9" * 129]
)
def test_invalid_execution_price_and_wire_grammar(value: str) -> None:
    replay = edited(wire_scenario(), "page-0", "price", value)
    assert replay.candidate is None
    assert replay.projection.quarantined_sources


@pytest.mark.parametrize("trade_id", [-1, True, 1.0, "01", "\uff11\uff12", "9" * 21])
def test_native_trade_id_sentinels_and_noncanonical_ids(trade_id: object) -> None:
    replay = edited(wire_scenario(), "page-0", "id", trade_id)
    assert replay.candidate is None
    assert replay.projection.quarantined_sources


def test_unknown_fields_remain_in_raw_and_are_enumerated() -> None:
    replay = edited(wire_scenario(), "page-0", "conditionalNewField", {"raw": [1, None]})
    normalized = normalize_sell_observation(replay.tape.observations[1])
    assert "row:0.conditionalNewField" in normalized.unknown_fields
    assert "conditionalNewField" in normalized.raw.payload
    assert replay.candidate is not None


@pytest.mark.parametrize(
    "execution_type", ["NEW", "CANCELED", "REPLACED", "REJECTED", "EXPIRED", "TRADE_PREVENTION"]
)
def test_non_trade_events_and_sentinel_ids_do_not_create_fills(execution_type: str) -> None:
    replay = wire_scenario()
    raw = event(replay, execution_type, t=-1, l="0", L="0", n="0", N=None)
    normalized = normalize_sell_observation(raw)
    assert normalized.non_trade
    assert normalized.trades == ()
    assert not normalized.issues
    replay = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert replay.candidate is not None
    assert len(replay_ledger(replay).fills) == 1


def test_event_trade_id_not_execution_id_and_exact_cross_source_deduplication() -> None:
    replay = wire_scenario()
    raw = event(replay)
    normalized = normalize_sell_observation(raw)
    assert normalized.trades[0].trade_ref == "101"
    replay = replace(
        replay,
        tape=replay.tape.capture(raw).capture(raw),
        plan=replace(replay.plan, event_refs=("event",)),
    )
    assert replay.candidate is not None
    assert len(replay_ledger(replay).fills) == 1


@pytest.mark.parametrize("field", ["Y", "n", "m", "c", "i", "t", "N"])
def test_conflicting_event_is_not_averaged_or_merged(field: str) -> None:
    replay = wire_scenario()
    values = {"Y": "3", "n": "0.02", "m": True, "c": "other", "i": 999, "t": -1, "N": None}
    raw = event(replay, **{field: values[field]})
    replay = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert replay.candidate is None
    assert replay.projection.quarantined_sources


def test_capture_permutation_and_duplicate_receipts_are_deterministic() -> None:
    replay = wire_scenario()
    expected = replay.projection
    for observations in permutations(replay.tape.observations):
        changed = replace(replay, tape=OfflineSellTape(observations))
        assert changed.projection == expected
        assert replace(changed, tape=changed.tape.capture(observations[0])).projection == expected
        assert changed.candidate == replay.candidate


def test_same_source_ref_conflicting_raw_is_order_independent_and_retained() -> None:
    replay = wire_scenario()
    raw = replay.tape.observations[1]
    conflict = replace(raw, payload="[]")
    left = replace(replay, tape=replay.tape.capture(conflict))
    right = replace(replay, tape=OfflineSellTape(tuple(reversed(left.tape.observations))))
    assert left.projection == right.projection
    assert left.candidate is None
    assert len(left.tape.observations) == 4
    assert OfflineIssueCode.RAW_CONFLICT in {i.code for i in left.projection.issues}


@pytest.mark.parametrize(
    "status",
    ["NEW", "PARTIALLY_FILLED", "CANCELED", "EXPIRED", "REJECTED", "PENDING_NEW", "UNKNOWN"],
)
def test_full_qty_does_not_override_status_or_pending_policy(status: str) -> None:
    replay = edited(wire_scenario(), "order", "status", status)
    assert replay.candidate is None


@pytest.mark.parametrize("status", ["CANCELED", "EXPIRED"])
@pytest.mark.parametrize("qty", ["0", "0.01"])
def test_partial_and_no_fill_terminal_candidates_keep_all_reservations(
    status: str, qty: str
) -> None:
    replay = wire_scenario()
    quote = "0" if qty == "0" else "1.05"
    replay = edited(
        edited(edited(replay, "order", "status", status), "order", "executedQty", qty),
        "order",
        "cummulativeQuoteQty",
        quote,
    )
    if qty == "0":
        observations = [
            replay.tape.observations[0],
            replace(replay.tape.observations[1], payload="[]", next_cursor=None),
        ]
        replay = replace(
            replay,
            tape=OfflineSellTape(tuple(observations)),
            plan=replace(replay.plan, page_refs=("page-0",)),
        )
    else:
        replay = edited(
            edited(edited(replay, "page-0", "qty", qty), "page-0", "quoteQty", quote),
            "page-0",
            "commission",
            "0",
        )
    candidate = replay.candidate
    assert candidate is not None
    assert candidate.executed_qty == Qty.parse(qty)
    assert candidate.unexecuted_qty == Qty.parse(".031") - Qty.parse(qty)
    assert candidate.assessment.book.inventory_book is replay.book.inventory_book


@pytest.mark.parametrize("asset", ["BTC", "USDT", "BNB"])
def test_multicurrency_fees_are_separate_and_fraction_conservation(asset: str) -> None:
    fee = "0.00001" if asset != "USDT" else "0.01"
    replay = edited(
        edited(wire_scenario(), "page-0", "commissionAsset", asset), "page-0", "commission", fee
    )
    candidate = replay.candidate
    assert candidate is not None
    ledger = candidate.assessment.ledger
    assert ledger.fees_by_asset[0].asset.code == asset
    x = sum((Fraction(f.executed_qty.value) for f in ledger.fills), Fraction())
    b = sum((Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == BTC), Fraction())
    y = sum((Fraction(f.observed_quote.amount) for f in ledger.fills), Fraction())
    u = sum((Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == USDT), Fraction())
    assert x <= Fraction(ledger.context.requested_qty.value)
    assert b <= Fraction(ledger.context.intent.base_fee_hold.value)
    assert x + b <= Fraction(ledger.context.requested_qty.value) + Fraction(
        ledger.context.intent.base_fee_hold.value
    )
    assert x + b <= Fraction(ledger.context.intent.finalized_buy.net_acquired_base_qty.value)
    assert Fraction(candidate.net_quote.amount) == y - u


@pytest.mark.parametrize(
    ("field", "value"), [("qty", "0.032"), ("commission", "4"), ("price", "101"), ("qty", "0")]
)
def test_financial_refusal_preserves_raw_and_never_accepts_subset(field: str, value: str) -> None:
    replay = edited(wire_scenario(), "page-0", field, value)
    assert replay.candidate is None
    assert OfflineIssueCode.FINANCIAL_QUARANTINE in {i.code for i in replay.projection.issues}
    assert replay_ledger(replay).fills == ()


def test_quote_fee_prefix_is_re_evaluatable_without_relaxing_a16() -> None:
    replay = wire_scenario(1)
    payload = json.loads(replay.tape.observations[1].payload)
    payload[0].update(qty="0.01", quoteQty="1.05", commission="1.06", commissionAsset="USDT")
    raw = replace(replay.tape.observations[1], payload=json.dumps(payload))
    early = replace(
        replay,
        tape=OfflineSellTape((replay.tape.observations[0], raw, replay.tape.observations[2])),
    )
    assert replay_ledger(early).fills == ()
    assert OfflineIssueCode.FINANCIAL_QUARANTINE in {i.code for i in early.projection.issues}
    second = {**payload[0], "id": 104, "commission": "0"}
    late = event(replay, t=104, l="0.01", Y="1.05", n="0", N="USDT")
    late_replay = replace(
        early, tape=early.tape.capture(late), plan=replace(early.plan, event_refs=("event",))
    )
    ledger = replay_ledger(late_replay)
    assert ledger.gross_observed_quote == Money.parse("2.10", USDT)
    assert ledger.net_observed_quote == Money.parse("1.04", USDT)
    assert raw.payload == early.tape.observations[1].payload
    assert late_replay.candidate is None  # report/collection still omit the late trade
    assert second["id"] == 104


@pytest.mark.parametrize("code", [-1007, -2013, 500])
def test_source_error_and_history_absence_remain_unknown(code: int) -> None:
    replay = wire_scenario()
    raw = replace(
        replay.tape.observations[0], payload=json.dumps({"code": code, "msg": "synthetic"})
    )
    replay = replace(replay, tape=OfflineSellTape((raw, *replay.tape.observations[1:])))
    assert replay.candidate is None
    assert OfflineIssueCode.SOURCE_ERROR in {i.code for i in replay.projection.issues}


@pytest.mark.parametrize(
    "field", ["cursor_from", "next_cursor", "collection_ref", "requested_limit"]
)
def test_pagination_and_capture_metadata_integrity(field: str) -> None:
    replay = wire_scenario()
    changes: dict[str, Any] = {field: "999" if field != "requested_limit" else 1}
    raw = replace(replay.tape.observations[1], **changes)
    replay = replace(
        replay,
        tape=OfflineSellTape((replay.tape.observations[0], raw, *replay.tape.observations[2:])),
    )
    assert replay.candidate is None


def test_missing_late_observation_replayed_when_received() -> None:
    replay = wire_scenario()
    early = replace(
        replay, tape=OfflineSellTape((replay.tape.observations[0], replay.tape.observations[2]))
    )
    assert early.candidate is None
    late = replace(early, tape=early.tape.capture(replay.tape.observations[1]))
    assert late.candidate is not None
    assert late.projection == replay.projection


def test_stale_root_and_direct_forged_candidate_cannot_pass() -> None:
    replay = wire_scenario()
    stale = replace(replay.book, sell_attempts=(), external_sell_bindings=())
    changed = replace(replay, book=stale)
    assert changed.candidate is None
    assert changed.projection.ledger is None
    candidate = replay.candidate
    assert candidate is not None
    a = assess_sell_finalization(
        stale,
        candidate.assessment.ledger,
        candidate.assessment.report,
        candidate.assessment.collection,
    )
    assert not SellCandidateEligibility(a).is_structurally_eligible
    with pytest.raises(SellEvidenceError):
        SellFinalizationCandidate(a)
    with pytest.raises(SellEvidenceError):
        _ = forged(candidate, assessment=a).executed_qty


@pytest.mark.parametrize("payload", ["{", "[]"])
def test_current_capture_refused_or_unselected_page_cannot_be_hidden_by_plan(payload: str) -> None:
    replay = wire_scenario()
    extra = replace(replay.tape.observations[1], source_ref="unselected", payload=payload)
    changed = replace(replay, tape=replay.tape.capture(extra))
    assert changed.candidate is None
    assert OfflineIssueCode.UNASSESSED_SOURCE in {i.code for i in changed.projection.issues}
    assert extra in changed.tape.observations


def test_archived_capture_remains_visible_without_being_relabelled_as_current() -> None:
    replay = wire_scenario()
    old = replace(
        replay.tape.observations[1], source_ref="old", collection_ref="old-capture", payload="{"
    )
    changed = replace(replay, tape=replay.tape.capture(old))
    assert changed.candidate is not None
    assert any(i.code is OfflineIssueCode.SOURCE_NOT_SELECTED for i in changed.projection.issues)
    assert normalize_sell_observation(old).issues


@pytest.mark.parametrize("kind", ["ORDER", "EXECUTION_REPORT"])
def test_unselected_current_report_cannot_hide_financial_contradiction(kind: str) -> None:
    replay = wire_scenario()
    raw = (
        edited(replay, "order", "cummulativeQuoteQty", "4").tape.observations[0]
        if kind == "ORDER"
        else event(replay, "NEW", Z="4", t=-1, l="0", L="0", n="0", N=None)
    )
    raw = replace(raw, source_ref="unselected-report")
    changed = replace(replay, tape=replay.tape.capture(raw))
    assert changed.candidate is None
    assert raw in changed.tape.observations
    assert "unselected-report" in changed.projection.quarantined_sources
    assert any(
        issue.code is OfflineIssueCode.UNASSESSED_SOURCE and issue.source_ref == "unselected-report"
        for issue in changed.projection.issues
    )


def test_precision_failure_after_normalization_is_explicit_and_retains_raw() -> None:
    replay = edited(wire_scenario(), "page-0", "price", "9" * 40)
    normalized = normalize_sell_observation(replay.tape.observations[1])
    assert not normalized.issues
    projection = replay.projection
    assert replay.candidate is None
    assert projection.assessment is None
    assert OfflineIssueCode.FINANCIAL_PRECISION_ERROR in {i.code for i in projection.issues}
    assert normalized.raw.payload == replay.tape.observations[1].payload


def test_base_fee_above_hold_quarantined_without_using_core() -> None:
    replay = edited(
        edited(wire_scenario(), "page-0", "commissionAsset", "BTC"),
        "page-0",
        "commission",
        ".000101",
    )
    # Wire requires leading digit; syntactically valid observation must reach A16.
    replay = edited(replay, "page-0", "commission", "0.000101")
    assert replay.candidate is None
    assert any(i.detail == "BASE_FEE_EXCEEDS_HOLD" for i in replay.projection.issues)
    assert replay_ledger(replay).fills == ()


@pytest.mark.parametrize("target", ["report", "event", "page"])
def test_wrong_selected_source_kind_is_explicit(target: str) -> None:
    replay = wire_scenario()
    if target == "report":
        plan = replace(replay.plan, report_ref="page-0")
    elif target == "event":
        plan = replace(replay.plan, event_refs=("order",))
    else:
        plan = replace(replay.plan, page_refs=("order",))
    changed = replace(replay, plan=plan)
    assert changed.candidate is None
    assert changed.projection.quarantined_sources


@pytest.mark.parametrize(
    "target", ["tape", "page-refs", "event-refs", "duplicate-refs", "raw-kind", "payload", "limit"]
)
def test_runtime_input_contracts_do_not_accept_mutable_or_wrong_types(target: str) -> None:
    replay = wire_scenario()

    def operation() -> None:
        if target == "tape":
            OfflineSellTape(cast(Any, list(replay.tape.observations)))
        elif target == "page-refs":
            replace(replay.plan, page_refs=cast(Any, ["page-0"]))
        elif target == "event-refs":
            replace(replay.plan, event_refs=cast(Any, ["event"]))
        elif target == "duplicate-refs":
            replace(replay.plan, page_refs=("page-0", "page-0"))
        elif target == "raw-kind":
            replace(replay.tape.observations[0], kind=cast(Any, "ORDER"))
        elif target == "payload":
            replace(replay.tape.observations[0], payload=cast(Any, {}))
        else:
            replace(replay.tape.observations[0], requested_limit=cast(Any, True))

    with pytest.raises((DomainError, TypeError)):
        operation()


@pytest.mark.parametrize(
    "payload",
    [
        '{"event":null}',
        '{"e":"balanceUpdate"}',
        '{"event":{"e":"executionReport","x":"UNKNOWN"}}',
        '{"code":-1007}',
        "[null,1]",
    ],
)
def test_event_wrappers_and_page_shape_failures_are_retained(payload: str) -> None:
    replay = wire_scenario()
    kind = (
        OfflineSellSource.MY_TRADES_PAGE
        if payload.startswith("[")
        else OfflineSellSource.EXECUTION_REPORT
    )
    raw = replace(replay.tape.observations[0], kind=kind, payload=payload)
    result = normalize_sell_observation(raw)
    assert result.issues
    assert result.raw.payload == payload


def test_bounded_payload_and_deep_json_do_not_escape_normalization() -> None:
    raw = wire_scenario().tape.observations[0]
    for payload in (raw.payload + " " * 2_000_001, "[" * 2000 + "]" * 2000):
        result = normalize_sell_observation(replace(raw, payload=payload))
        assert result.issues
        assert result.raw.payload == payload


def test_bound_root_without_external_binding_is_explicitly_quarantined() -> None:
    replay = wire_scenario()
    root = replace(replay.book, external_sell_bindings=())
    changed = replace(replay, book=root)
    assert changed.candidate is None
    assert any(i.field == "binding" and i.source_ref == "book" for i in changed.projection.issues)


def test_foreign_trade_and_buy_side_have_specific_quarantine_not_stamped_fill() -> None:
    replay = edited(wire_scenario(), "page-0", "orderId", 999)
    assert any(i.field == "trade.identity" for i in replay.projection.issues)
    assert replay_ledger(replay).fills == ()
    replay = edited(wire_scenario(), "page-0", "isBuyer", True)
    assert any(i.detail == "INVALID_FILL" for i in replay.projection.issues)
    assert replay_ledger(replay).fills == ()


def test_divergent_observed_quote_remains_literal_in_financial_projection() -> None:
    replay = edited(wire_scenario(), "page-0", "quoteQty", "3")
    assert replay.candidate is None
    assert replay_ledger(replay).gross_observed_quote == Money.parse("3", USDT)
    assert replay_ledger(replay).quote_discrepancy_refs == ("101",)


@pytest.mark.parametrize("suffix", [',"orderId":999,"orderId":123', ',"newField":NaN'])
def test_duplicate_keys_and_non_json_constants_cannot_hide_in_otherwise_valid_order(
    suffix: str,
) -> None:
    raw = wire_scenario().tape.observations[0]
    raw = replace(raw, payload=raw.payload[:-1] + suffix + "}")
    normalized = normalize_sell_observation(raw)
    assert normalized.report is None
    assert any(
        i.code is OfflineIssueCode.MALFORMED and i.field == "payload" for i in normalized.issues
    )


@pytest.mark.parametrize(
    ("field", "normalized_field"),
    [
        ("qty", "executed_qty"),
        ("quoteQty", "observed_quote"),
        ("commission", "fee"),
        ("price", "execution_price"),
    ],
)
def test_missing_trade_data_stays_none_in_normalized_record(
    field: str, normalized_field: str
) -> None:
    replay = edited(wire_scenario(), "page-0", field, None, remove=True)
    normalized = normalize_sell_observation(replay.tape.observations[1])
    assert getattr(normalized.trades[0], normalized_field) is None


def test_plan_does_not_assign_one_ref_to_page_and_event() -> None:
    replay = wire_scenario()
    with pytest.raises(DomainError):
        replace(replay.plan, event_refs=("page-0",))


def test_precision_failure_in_forged_root_is_not_missing_evidence() -> None:
    replay = wire_scenario()
    reservation = forged(
        replay.book.inventory_book.reservations[0], base_fee_hold=Qty.parse("1e-100")
    )
    root = forged(
        replay.book, inventory_book=forged(replay.book.inventory_book, reservations=(reservation,))
    )
    changed = replace(replay, book=root)
    assert changed.candidate is None
    assert changed.projection.ledger is None
    assert any(
        i.code is OfflineIssueCode.FINANCIAL_PRECISION_ERROR for i in changed.projection.issues
    )


@pytest.mark.parametrize("value", [None, 0, "false"])
def test_maker_flag_must_be_boolean_when_provided(value: object) -> None:
    changed = edited(wire_scenario(), "page-0", "isMaker", value)
    assert changed.candidate is None
    assert any(i.field == "row:0.isMaker" for i in changed.projection.issues)


def test_absent_maker_role_is_not_inferred_from_limit_order() -> None:
    changed = edited(wire_scenario(), "page-0", "isMaker", None, remove=True)
    assert changed.candidate is not None
    assert replay_ledger(changed).fills[0].liquidity is None


def test_unknown_execution_type_and_invalid_client_are_explicit() -> None:
    replay = wire_scenario()
    raw = event(replay, "FUTURE_TYPE")
    assert any(
        i.code is OfflineIssueCode.UNSUPPORTED and i.field == "x"
        for i in normalize_sell_observation(raw).issues
    )
    changed = edited(replay, "order", "clientOrderId", " bad-client")
    assert changed.candidate is None
    assert any(i.field == "identity" for i in changed.projection.issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("z", "0"),
        ("Z", "0"),
        ("z", "0.032"),
        ("Z", "4"),
        ("q", "0.032"),
        ("p", "103"),
        ("o", "MARKET"),
        ("X", "REJECTED"),
        ("X", "CANCELED"),
        ("X", "EXPIRED"),
    ],
)
def test_selected_event_cumulative_and_authorization_conflicts_block_candidate(
    field: str, value: str
) -> None:
    replay = wire_scenario()
    raw = event(replay, **{field: value})
    changed = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert changed.candidate is None
    assert "event" in changed.projection.quarantined_sources
    expected_fields = {
        ("z", "0"): {"event.status_qty", "event.executed"},
        ("z", "0.032"): {"event.status_qty", "event.terminal_qty"},
        ("Z", "0"): {"event.quote", "event.quote_qty"},
        ("Z", "4"): {"event.terminal_quote"},
        ("q", "0.032"): {"event.original_qty"},
        ("p", "103"): {"event.limit"},
        ("o", "MARKET"): {"event.type"},
        ("X", "REJECTED"): {"event.status_qty", "event.terminal_status"},
        ("X", "CANCELED"): {"event.terminal_status"},
        ("X", "EXPIRED"): {"event.terminal_status"},
    }
    assert {i.field for i in changed.projection.issues} >= expected_fields[field, value]


def test_non_trade_event_also_must_match_sell_authorization() -> None:
    replay = wire_scenario()
    raw = event(replay, "NEW", S="BUY", t=-1, l="0", L="0", n="0", N=None)
    changed = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert changed.candidate is None
    assert any(i.field == "event.side" for i in changed.projection.issues)


def test_execution_report_used_as_terminal_cannot_hide_its_trade_half() -> None:
    replay = wire_scenario()
    raw = event(replay, n="0.01")
    changed = replace(
        replay,
        tape=replay.tape.capture(raw),
        plan=replace(replay.plan, report_ref="event", before_ref="event", after_ref="event"),
    )
    assert changed.candidate is None
    assert OfflineIssueCode.TRADE_CONFLICT in {i.code for i in changed.projection.issues}


def test_selected_event_capture_must_match_query_capture() -> None:
    replay = wire_scenario()
    raw = replace(event(replay), collection_ref="other-capture")
    changed = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert changed.candidate is None
    assert any(i.field == "capture" for i in changed.projection.issues)


@pytest.mark.parametrize(("qty", "quote"), [("0", "1"), ("0.02", "1")])
def test_non_trade_event_cumulative_quote_respects_quantity_and_sell_limit(
    qty: str, quote: str
) -> None:
    replay = wire_scenario()
    raw = event(replay, "NEW", X="NEW", z=qty, Z=quote, t=-1, l="0", L="0", n="0", N=None)
    changed = replace(
        replay, tape=replay.tape.capture(raw), plan=replace(replay.plan, event_refs=("event",))
    )
    assert changed.candidate is None
    assert any(i.field == "event.quote_qty" for i in changed.projection.issues)


def test_immutability_and_small_decimal_context_preserved() -> None:
    replay = wire_scenario()
    with localcontext() as ctx:
        ctx.prec = 2
        candidate = replay.candidate
        assert candidate is not None
        assert candidate.gross_quote == Money.parse("3.255", USDT)
        assert ctx.prec == 2
        assert not ctx.flags[Inexact]
    for obj in (replay, replay.tape, replay.plan, replay.tape.observations[0], candidate):
        with pytest.raises(FrozenInstanceError):
            cast(Any, obj).unexpected = 0
    assert replay.projection == replay.projection
