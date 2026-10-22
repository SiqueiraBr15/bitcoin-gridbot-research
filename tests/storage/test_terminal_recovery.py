"""A17.5: derivação na revisão atual sem persistir outra autoridade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.application.sell_evidence import SellEvidenceError
from gridbot.application.sell_terminal import (
    ReconciledSellEvidence,
    SellStructuralState,
    validate_terminal_reconciliation_against_current,
)
from gridbot.storage.journal_backup import create_verified_backup, restore_verified_backup
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.application.test_operational_grid import ref
from tests.storage.journal_oracle import audit_assets, audit_rows
from tests.storage.test_journal_backup import destination
from tests.storage.test_operational_journal import bound_sell, funded_plan


def test_terminal_result_survives_restart_and_is_read_only(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    before = store.recover(state.scope)
    before_bytes = store.policy.database_path().read_bytes()
    result = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    reopened = SQLiteOperationalJournal.open(store.policy)
    assert reopened.reconcile_sell_terminal(state.scope, state.revision, source.plan) == result
    assert store.recover(state.scope) == before
    assert store.policy.database_path().read_bytes() == before_bytes
    assert result.journal_reference is not None
    assert result.journal_reference.receipt_sequences == tuple(r.sequence for r in before.receipts)
    assert isinstance(result.evidence, ReconciledSellEvidence)
    validate_terminal_reconciliation_against_current(result, state.book, result.journal_reference)
    audit_assets(state)
    audit_rows(store.policy.database_path(), expected_receipts=3)


def test_late_raw_rejects_stale_revision_and_old_reference(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    result = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    original = state
    conflict = replace(source.tape.observations[1], payload="[]")
    state = store.append_raw_observation(state.scope, state.revision, conflict)
    with pytest.raises(PersistenceError) as error:
        store.reconcile_sell_terminal(state.scope, original.revision, source.plan)
    assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
    current = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    assert current.evidence is None
    with pytest.raises(SellEvidenceError):
        validate_terminal_reconciliation_against_current(
            result, state.book, current.journal_reference
        )
    assert store.recover(state.scope).receipts[-1].classification is (
        ReceiptClassification.DUPLICATE_CONFLICTING
    )
    assert state.book == original.book
    audit_assets(state)


def test_duplicate_ref_refreshes_revision_but_not_quantities(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    original = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    state = store.append_raw_observation(state.scope, state.revision, source.tape.observations[1])
    current = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    assert isinstance(current.evidence, ReconciledSellEvidence)
    assert isinstance(original.evidence, ReconciledSellEvidence)
    assert current.evidence.executed_qty == original.evidence.executed_qty
    assert current.journal_reference != original.journal_reference
    assert len(store.recover(state.scope).receipts) == 4
    assert state.book == original.book


def test_other_cell_requires_new_cas_revision_without_invalidating_conclusion(
    tmp_path: Path,
) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    original = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    state = store.commit_operational_transition(
        state.scope, state.revision, replace(funded_plan(state), cycle_ref=ref(1))
    )
    current = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    assert current.state is SellStructuralState.STRUCTURALLY_RECONCILED
    assert current.outcome == original.outcome
    assert current.journal_reference is not None
    assert original.journal_reference is not None
    assert (
        current.journal_reference.receipt_sequences == original.journal_reference.receipt_sequences
    )
    assert isinstance(current.evidence, ReconciledSellEvidence)
    assert isinstance(original.evidence, ReconciledSellEvidence)
    assert current.evidence.executed_qty == original.evidence.executed_qty
    with pytest.raises(SellEvidenceError):
        validate_terminal_reconciliation_against_current(
            original, state.book, current.journal_reference
        )
    validate_terminal_reconciliation_against_current(current, state.book, current.journal_reference)
    audit_assets(state)


def test_missing_fee_quarantine_preserved_after_new_capture_and_restore(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, state = bound_sell(origin.directory)
    source = wire_scenario()
    missing = edited(source, "page-0", "commission", None, remove=True)
    state = store.append_raw_observations(state.scope, state.revision, missing.tape.observations)
    state = store.record_replay(state.scope, state.revision, missing.plan)
    old = store.recover(state.scope)
    assert old.replays[-1].quarantined_sources
    renamed = tuple(
        replace(raw, source_ref="new-" + raw.source_ref, collection_ref="capture-new")
        for raw in source.tape.observations
    )
    plan = replace(
        source.plan,
        query=replace(source.plan.query, collection_ref="capture-new"),
        report_ref="new-order",
        before_ref="new-order",
        after_ref="new-order",
        page_refs=("new-page-0", "new-page-1"),
    )
    state = store.append_raw_observations(state.scope, state.revision, renamed)
    state = store.record_replay(state.scope, state.revision, plan)
    result = store.reconcile_sell_terminal(state.scope, state.revision, plan)
    assert isinstance(result.evidence, ReconciledSellEvidence)
    before = store.recover(state.scope)
    assert before.replays[: len(old.replays)] == old.replays
    assert len(before.receipts) == 6
    backup = destination(tmp_path, "backup")
    captured = create_verified_backup(store, backup)
    restored = destination(tmp_path, "restored")
    restore_verified_backup(backup, restored, expected_anchors=captured.anchors)
    reopened = SQLiteOperationalJournal.open(restored)
    assert reopened.reconcile_sell_terminal(state.scope, state.revision, plan) == result
    assert reopened.recover(state.scope) == before
    audit_assets(state)


def test_foreign_replay_scope_cannot_claim_current_journal(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    foreign = replace(
        source.plan,
        query=replace(
            source.plan.query, identity=replace(source.plan.query.identity, account_ref="other")
        ),
    )
    with pytest.raises(PersistenceError) as error:
        store.reconcile_sell_terminal(state.scope, state.revision, foreign)
    assert error.value.code is PersistenceErrorCode.SCOPE_MISMATCH
    assert store.load_operational_state(state.scope) == state


@pytest.mark.parametrize("field", ["executedQty", "commission"])
def test_new_capture_preserves_and_blocks_invalid_historical_sources(
    tmp_path: Path, field: str
) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    old = edited(source, "order", "status", "PARTIALLY_FILLED")
    old = (
        edited(old, "order", field, "0.032")
        if field == "executedQty"
        else edited(old, "page-0", field, "-0.1")
    )
    state = store.append_raw_observations(state.scope, state.revision, old.tape.observations)
    state = store.record_replay(state.scope, state.revision, old.plan)
    previous = store.recover(state.scope)
    renamed = tuple(
        replace(raw, source_ref="new-" + raw.source_ref, collection_ref="capture-new")
        for raw in source.tape.observations
    )
    plan = replace(
        source.plan,
        query=replace(source.plan.query, collection_ref="capture-new"),
        report_ref="new-order",
        before_ref="new-order",
        after_ref="new-order",
        page_refs=("new-page-0", "new-page-1"),
    )
    state = store.append_raw_observations(state.scope, state.revision, renamed)
    reopened = SQLiteOperationalJournal.open(store.policy)
    assert reopened.reconcile_sell_terminal(state.scope, state.revision, plan).evidence is None
    recovered = reopened.recover(state.scope)
    assert recovered.replays == previous.replays
    assert len(recovered.receipts) == 6
    assert state.book == previous.state.book
