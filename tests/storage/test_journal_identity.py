"""Namespaces persistentes de ordem/trade e alias de client ID sem autoridade global."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from gridbot.application.operational_persistence import (
    BindOperationalExternalSell,
    BindOperationalSell,
)
from gridbot.exchange.binance.offline_replay import OfflineSellTape
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_external_sell_identity import binding
from tests.application.test_offline_sell_evidence import edited, event, wire_scenario
from tests.application.test_operational_grid import context, ref
from tests.storage.test_operational_journal import assert_conserved, bound_sell, durable_sell


def test_same_trade_and_client_id_in_two_orders_never_share_execution(tmp_path: Path) -> None:
    store, state = durable_sell(tmp_path, (0, 1))
    source = wire_scenario()
    for cell in (0, 1):
        state = store.commit_operational_transition(
            state.scope, state.revision, BindOperationalSell(ref(cell), context(state.book, cell))
        )
        order_binding = binding(state.book, cell, order_ref=str(123 + cell))
        state = store.commit_operational_transition(
            state.scope, state.revision, BindOperationalExternalSell(ref(cell), order_binding)
        )
    originals = state.book
    plans = []
    for cell in (0, 1):
        existing_binding = state.book.external_binding_for(ref(cell))
        assert existing_binding is not None
        observations = []
        for raw in source.tape.observations:
            payload = json.loads(raw.payload)
            if isinstance(payload, dict):
                payload["orderId"] = 123 + cell
                payload["price"] = str(state.book.grid_state.cells[cell].cell.sell_price.value)
            else:
                for trade in payload:
                    trade["orderId"] = 123 + cell
            observations.append(
                replace(raw, scope=existing_binding.identity, payload=json.dumps(payload))
            )
        plan = replace(
            source.plan, query=replace(source.plan.query, identity=existing_binding.identity)
        )
        plans.append(plan)
        state = store.append_raw_observations(state.scope, state.revision, tuple(observations))
        state = store.record_replay(state.scope, state.revision, plan)
    reopened = SQLiteOperationalJournal.open(store.policy)
    for cell, plan in enumerate(plans):
        replay = reopened.replay_observations(state.scope, plan)
        assert len(replay.tape.observations) == 3
        candidate = replay.candidate
        assert candidate is not None
        assert candidate.binding.cycle_ref == ref(cell)
        assert candidate.binding.identity.order_ref == str(123 + cell)
        assert candidate.binding.identity.client_order_ref == "client-123"
        assert candidate.executed_qty.value == Decimal("0.031")
        assert [f.fill_ref for f in candidate.assessment.ledger.fills] == ["101"]
        assert len(reopened.receipts_for_order(state.scope, plan.query.identity)) == 3
    assert reopened.load_operational_state(state.scope).book == originals
    assert_conserved(state)


def test_same_trade_from_page_and_event_deduplicates_after_real_restart(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    raw_event = event(source)
    plan = replace(source.plan, event_refs=("event",))
    state = store.append_raw_observations(
        state.scope, state.revision, (*source.tape.observations, raw_event, raw_event)
    )
    state = store.record_replay(state.scope, state.revision, plan)
    reopened = SQLiteOperationalJournal.open(store.policy)
    replay = reopened.replay_observations(state.scope, plan)
    candidate = replay.candidate
    assert candidate is not None
    assert len(candidate.assessment.ledger.fills) == 1
    assert candidate.executed_qty.value == Decimal("0.031")
    assert (
        reopened.recover(state.scope).receipts[-1].classification
        is ReceiptClassification.DUPLICATE_IDENTICAL
    )
    assert len(replay.tape.observations) == 5
    assert_conserved(state)


def test_unselected_current_report_quarantine_is_durable(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    raw = replace(
        edited(source, "order", "cummulativeQuoteQty", "4").tape.observations[0],
        source_ref="unselected-report",
    )
    state = store.append_raw_observations(
        state.scope, state.revision, (*source.tape.observations, raw)
    )
    state = store.record_replay(state.scope, state.revision, source.plan)
    reopened = SQLiteOperationalJournal.open(store.policy)
    assert reopened.recover(state.scope).replays[-1].quarantined_sources == ("unselected-report",)
    assert reopened.replay_observations(state.scope, source.plan).candidate is None
    assert reopened.recover(state.scope).receipts[-1].raw == raw
    assert_conserved(state)


@pytest.mark.parametrize("field", ["account_ref", "environment_ref", "venue_ref"])
def test_same_numeric_order_and_trade_other_namespace_preserved_outside_projection(
    tmp_path: Path, field: str
) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    raw = source.tape.observations[1]
    foreign_identity = (
        replace(raw.scope, account_ref="another")
        if field == "account_ref"
        else replace(raw.scope, environment_ref="another")
        if field == "environment_ref"
        else replace(raw.scope, venue_ref="another")
    )
    foreign = replace(raw, scope=foreign_identity)
    state = store.append_raw_observations(
        state.scope, state.revision, (*source.tape.observations, foreign)
    )
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert recovered.receipts[-1].classification is ReceiptClassification.FOREIGN_SCOPE
    actual = store.replay_observations(state.scope, source.plan)
    expected = replace(source, book=state.book, tape=OfflineSellTape(source.tape.observations))
    assert actual.projection == expected.projection
    assert len(actual.tape.observations) == 3
    assert_conserved(recovered.state)
