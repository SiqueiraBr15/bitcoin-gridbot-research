"""Fechamento do replay sem elevar evidência local a autoridade externa."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from gridbot.application.sell_terminal import (
    ReconciledSellEvidence,
    SellNoFillOutcome,
    SellStructuralState,
    SellTerminalOutcome,
)
from gridbot.exchange.binance.offline_replay import OfflineSellTape
from tests.application.test_offline_sell_evidence import edited, wire_scenario


@pytest.mark.parametrize(
    ("status", "qty", "outcome"),
    [
        ("CANCELED", "0.015", SellTerminalOutcome.PARTIAL_EXECUTION),
        ("EXPIRED", "0.015", SellTerminalOutcome.PARTIAL_EXECUTION),
        ("EXPIRED_IN_MATCH", "0.015", SellTerminalOutcome.PARTIAL_EXECUTION),
        ("CANCELED", "0", SellTerminalOutcome.NO_EXECUTION),
        ("EXPIRED", "0", SellTerminalOutcome.NO_EXECUTION),
        ("EXPIRED_IN_MATCH", "0", SellTerminalOutcome.NO_EXECUTION),
        ("REJECTED", "0", SellTerminalOutcome.NO_EXECUTION),
    ],
)
def test_raw_partial_and_no_fill_use_real_terminal_policy(
    status: str, qty: str, outcome: SellTerminalOutcome
) -> None:
    source = wire_scenario()
    quote = "1.575" if qty != "0" else "0"
    source = edited(source, "order", "status", status)
    source = edited(source, "order", "executedQty", qty)
    source = edited(source, "order", "cummulativeQuoteQty", quote)
    if qty == "0":
        raw = replace(source.tape.observations[1], payload="[]", next_cursor=None)
        source = replace(
            source,
            tape=OfflineSellTape((source.tape.observations[0], raw)),
            plan=replace(source.plan, page_refs=("page-0",)),
        )
    else:
        source = edited(source, "page-0", "qty", qty)
        source = edited(source, "page-0", "quoteQty", quote)
    result = source.terminal_reconciliation
    assert result.outcome is outcome
    assert result.book == source.book
    if qty == "0":
        assert isinstance(result.evidence, SellNoFillOutcome)
    else:
        evidence = result.evidence
        assert isinstance(evidence, ReconciledSellEvidence)
        assert evidence.unexecuted_qty.value == Decimal("0.016")


def test_complete_replay_exposes_structural_execution_only() -> None:
    source = wire_scenario()
    result = source.terminal_reconciliation
    assert result.state is SellStructuralState.STRUCTURALLY_RECONCILED
    assert result.outcome is SellTerminalOutcome.FULL_EXECUTION
    assert isinstance(result.evidence, ReconciledSellEvidence)
    assert source.candidate is not None
    assert result.evidence.executed_qty.value == source.candidate.executed_qty.value
    assert source.book == result.book


@pytest.mark.parametrize(
    ("ref", "field", "value"),
    [
        ("order", "status", "NEW"),
        ("order", "status", "PARTIALLY_FILLED"),
        ("order", "status", "NOT_A_STATUS"),
        ("order", "cummulativeQuoteQty", None),
        ("page-0", "commission", None),
        ("page-0", "quoteQty", None),
        ("page-0", "qty", None),
        ("page-0", "qty", "0.032"),
        ("page-0", "quoteQty", "0"),
        ("page-0", "quoteQty", "3.254"),
        ("page-0", "commissionAsset", "BTC"),
    ],
)
def test_incomplete_conflicting_or_open_raw_never_concludes(
    ref: str, field: str, value: object
) -> None:
    source = wire_scenario()
    if field == "commissionAsset":
        source = edited(source, ref, "commission", "0.001")
    source = edited(source, ref, field, value)
    result = source.terminal_reconciliation
    assert result.evidence is None
    assert result.outcome is None
    assert result.state is not SellStructuralState.STRUCTURALLY_RECONCILED


def test_identical_raw_repeat_is_not_another_fill() -> None:
    source = wire_scenario()
    duplicate = replace(source, tape=source.tape.capture(source.tape.observations[1]))
    result = duplicate.terminal_reconciliation
    assert isinstance(result.evidence, ReconciledSellEvidence)
    assert result.ledger is not None
    assert result.evidence.executed_qty.value == result.ledger.context.requested_qty.value
    assert len(result.ledger.fills) == 1


@pytest.mark.parametrize("change", ["new-trade", "changed-fee", "changed-terminal", "missing-fee"])
def test_late_capture_is_preserved_and_old_plan_does_not_hide_it(change: str) -> None:
    source = wire_scenario()
    raw = source.tape.observations[1]
    payload = json.loads(raw.payload)
    if change == "new-trade":
        payload[0]["id"] = 999
    elif change == "changed-fee":
        payload[0]["commission"] = "0.02"
    elif change == "missing-fee":
        del payload[0]["commission"]
    else:
        raw = source.tape.observations[0]
        payload = json.loads(raw.payload)
        payload["status"] = "CANCELED"
    late = replace(
        raw, source_ref="late", collection_ref="capture-late", payload=json.dumps(payload)
    )
    replay = replace(source, tape=source.tape.capture(late))
    assert len(replay.tape.observations) == 4
    assert replay.terminal_reconciliation.evidence is None
    assert replay.terminal_reconciliation.findings


def test_equivalent_new_capture_repeat_refreshes_without_increasing_totals() -> None:
    source = wire_scenario()
    repeat = replace(
        source.tape.observations[1], source_ref="repeat", collection_ref="capture-late"
    )
    replay = replace(source, tape=source.tape.capture(repeat))
    result = replay.terminal_reconciliation
    assert isinstance(result.evidence, ReconciledSellEvidence)
    assert result.ledger is not None
    assert result.evidence.executed_qty.value == result.ledger.context.requested_qty.value
    assert len(replay.tape.observations) == 4


def test_new_complete_capture_can_resolve_previously_missing_fee() -> None:
    incomplete = edited(wire_scenario(), "page-0", "commission", None, remove=True)
    current = wire_scenario()
    renamed = tuple(
        replace(raw, source_ref="new-" + raw.source_ref, collection_ref="capture-new")
        for raw in current.tape.observations
    )
    plan = replace(
        current.plan,
        query=replace(current.plan.query, collection_ref="capture-new"),
        report_ref="new-order",
        before_ref="new-order",
        after_ref="new-order",
        page_refs=("new-page-0", "new-page-1"),
    )
    replay = replace(
        current, tape=OfflineSellTape((*incomplete.tape.observations, *renamed)), plan=plan
    )
    assert len(replay.tape.observations) == 6
    assert isinstance(replay.terminal_reconciliation.evidence, ReconciledSellEvidence)


def test_foreign_order_is_not_added_to_execution() -> None:
    source = wire_scenario()
    foreign = replace(
        source.tape.observations[1],
        source_ref="foreign",
        scope=replace(source.plan.query.identity, order_ref="999"),
        collection_ref="capture-foreign",
    )
    replay = replace(source, tape=source.tape.capture(foreign))
    result = replay.terminal_reconciliation
    assert isinstance(result.evidence, ReconciledSellEvidence)
    assert result.ledger is not None
    assert len(result.ledger.fills) == 1


def test_duplicate_selected_source_never_hides_late_incomplete_evidence() -> None:
    source = wire_scenario()
    missing = edited(source, "page-0", "commission", None, remove=True).tape.observations[1]
    late = replace(missing, source_ref="late-missing", collection_ref="capture-late")
    tape = source.tape.capture(late).capture(source.tape.observations[-1])
    result = replace(source, tape=tape).terminal_reconciliation
    assert result.evidence is None
    assert result.state is SellStructuralState.PENDING_EVIDENCE
    assert len(tape.observations) == 5


@pytest.mark.parametrize("index", [0, 1])
def test_declared_scope_cannot_hide_foreign_identity_inside_omitted_payload(index: int) -> None:
    source = wire_scenario()
    raw = source.tape.observations[index]
    changed = edited(source, raw.source_ref, "orderId", 999).tape.observations[index]
    late = replace(changed, source_ref="identity-conflict", collection_ref="capture-late")
    result = replace(source, tape=source.tape.capture(late)).terminal_reconciliation
    assert result.evidence is None
    assert result.state is SellStructuralState.CONTRADICTORY_EVIDENCE


def test_late_empty_page_with_unassessed_continuation_is_not_equivalent() -> None:
    source = wire_scenario()
    late = replace(
        source.tape.observations[-1],
        source_ref="late-page",
        collection_ref="capture-late",
        next_cursor="999",
    )
    result = replace(source, tape=source.tape.capture(late)).terminal_reconciliation
    assert result.evidence is None
    assert result.state is SellStructuralState.PENDING_EVIDENCE


@pytest.mark.parametrize(
    ("source_ref", "field", "value"),
    [
        ("order", "origQty", "0.032"),
        ("order", "price", "101"),
        ("order", "side", "BUY"),
        ("order", "executedQty", "0.032"),
        ("order", "cummulativeQuoteQty", "3.3"),
        ("order", "symbol", "ETHUSDT"),
        ("page-0", "commission", "-0.1"),
    ],
)
def test_fresh_capture_cannot_hide_known_invalid_old_open_sources(
    source_ref: str, field: str, value: str
) -> None:
    current = wire_scenario()
    old = edited(edited(current, "order", "status", "PARTIALLY_FILLED"), source_ref, field, value)
    renamed = tuple(
        replace(raw, source_ref="new-" + raw.source_ref, collection_ref="capture-new")
        for raw in current.tape.observations
    )
    plan = replace(
        current.plan,
        query=replace(current.plan.query, collection_ref="capture-new"),
        report_ref="new-order",
        before_ref="new-order",
        after_ref="new-order",
        page_refs=("new-page-0", "new-page-1"),
    )
    replay = replace(current, tape=OfflineSellTape((*old.tape.observations, *renamed)), plan=plan)
    result = replay.terminal_reconciliation
    assert result.evidence is None
    assert len(replay.tape.observations) == 6


def test_old_partial_report_can_precede_consistent_completed_capture() -> None:
    current = wire_scenario()
    old = edited(current, "order", "status", "PARTIALLY_FILLED")
    old = edited(old, "order", "executedQty", "0.015")
    old = edited(old, "order", "cummulativeQuoteQty", "1.575")
    renamed = tuple(
        replace(raw, source_ref="new-" + raw.source_ref, collection_ref="capture-new")
        for raw in current.tape.observations
    )
    plan = replace(
        current.plan,
        query=replace(current.plan.query, collection_ref="capture-new"),
        report_ref="new-order",
        before_ref="new-order",
        after_ref="new-order",
        page_refs=("new-page-0", "new-page-1"),
    )
    replay = replace(current, tape=OfflineSellTape((*old.tape.observations, *renamed)), plan=plan)
    assert isinstance(replay.terminal_reconciliation.evidence, ReconciledSellEvidence)
