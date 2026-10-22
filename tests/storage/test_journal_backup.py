"""Backup nativo consistente, integridade selada e restore sem ativação."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.storage.journal_backup import (
    JournalAnchor,
    create_verified_backup,
    inspect_anchors,
    restore_verified_backup,
    verify_backup,
)
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.storage.journal_oracle import audit_assets, audit_rows
from tests.storage.test_hardening_processes import cleanup, decode_scope, line, seeded, send, start
from tests.storage.test_operational_journal import funded_plan, journal_start


def destination(root: Path, name: str) -> JournalPathPolicy:
    path = root / name
    path.mkdir()
    return JournalPathPolicy(path)


def manifest(policy: JournalPathPolicy) -> Path:
    return policy.database_path().parent / "gridbot-backup-manifest.json"


def test_backup_and_restore_preserve_full_authority_and_observations(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, _revision = seeded(origin.directory)
    scope = decode_scope(origin.directory)
    before = store.recover(scope)
    backup = destination(tmp_path, "backup")
    copied = create_verified_backup(store, backup)
    assert verify_backup(backup) == copied
    restored = destination(tmp_path, "restored")
    assert restore_verified_backup(backup, restored, expected_anchors=copied.anchors) == copied
    recovered = SQLiteOperationalJournal.open(restored).recover(scope)
    assert recovered == before
    assert store.recover(scope) == before
    audit_rows(restored.database_path(), expected_receipts=3)
    audit_assets(recovered.state)


def test_known_newer_anchor_rejects_old_backup_before_creating_destination(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, state = journal_start(origin.directory)
    old = destination(tmp_path, "old")
    create_verified_backup(store, old)
    state = store.commit_operational_transition(state.scope, state.revision, funded_plan(state))
    current = inspect_anchors(store)
    restored = destination(tmp_path, "restored")
    with pytest.raises(PersistenceError) as error:
        restore_verified_backup(old, restored, expected_anchors=current)
    assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
    assert not restored.database_path().exists()
    assert store.load_operational_state(state.scope) == state


def test_known_prefix_allows_newer_backup_and_empty_anchor_is_explicit_limit(
    tmp_path: Path,
) -> None:
    origin = destination(tmp_path, "origin")
    store, state = journal_start(origin.directory)
    known = inspect_anchors(store)
    store.commit_operational_transition(state.scope, state.revision, funded_plan(state))
    backup = destination(tmp_path, "backup")
    captured = create_verified_backup(store, backup)
    restored = destination(tmp_path, "restored")
    assert restore_verified_backup(backup, restored, expected_anchors=known) == captured
    unanchored = destination(tmp_path, "unanchored")
    assert restore_verified_backup(backup, unanchored, expected_anchors=()) == captured


@pytest.mark.parametrize("existing", ["database", "manifest"])
def test_existing_destination_is_preserved(tmp_path: Path, existing: str) -> None:
    origin = destination(tmp_path, "origin")
    store, _state = journal_start(origin.directory)
    backup = destination(tmp_path, "backup")
    occupied = backup.database_path() if existing == "database" else manifest(backup)
    occupied.write_bytes(b"preserve")
    with pytest.raises(PersistenceError) as error:
        create_verified_backup(store, backup)
    assert error.value.code is PersistenceErrorCode.DUPLICATE_SCOPE
    assert occupied.read_bytes() == b"preserve"


@pytest.mark.parametrize("stage", ["before_backup", "during_backup"])
def test_interruption_cannot_produce_verified_backup(tmp_path: Path, stage: str) -> None:
    origin = destination(tmp_path, "origin")
    store, state = journal_start(origin.directory)
    backup = destination(tmp_path, "backup")

    def fail(_self: SQLiteOperationalJournal, name: str) -> None:
        if name == stage:
            raise OSError("synthetic backup interruption")

    with (
        patch.object(SQLiteOperationalJournal, "_checkpoint", fail),
        pytest.raises(PersistenceError) as error,
    ):
        create_verified_backup(store, backup)
    assert error.value.code is PersistenceErrorCode.IO_ERROR
    assert not manifest(backup).exists()
    with pytest.raises(PersistenceError):
        verify_backup(backup)
    assert store.load_operational_state(state.scope) == state


@pytest.mark.parametrize(
    "damage",
    [
        "header",
        "manifest-json",
        "version",
        "boolean-version",
        "extra",
        "missing",
        "digest",
        "anchor-revision",
        "anchor-scope",
        "anchor-digest",
        "empty",
        "duplicate",
        "float",
        "repeated-key",
        "oversized",
        "pending-journal",
    ],
)
def test_corrupt_backup_rejected_without_repair(tmp_path: Path, damage: str) -> None:
    origin = destination(tmp_path, "origin")
    store, _state = journal_start(origin.directory)
    backup = destination(tmp_path, "backup")
    create_verified_backup(store, backup)
    body = json.loads(manifest(backup).read_text(encoding="ascii"))
    if damage == "header":
        with backup.database_path().open("r+b") as stream:
            stream.write(b"BROKEN HEADER!!!")
    elif damage == "manifest-json":
        manifest(backup).write_text("{", encoding="ascii")
    elif damage in {"version", "boolean-version"}:
        body["version"] = 2 if damage == "version" else True
    elif damage == "extra":
        body["extra"] = None
    elif damage == "missing":
        del body["codec"]
    elif damage == "digest":
        body["database_digest"] = "0" * 64
    elif damage == "anchor-revision":
        body["anchors"][0]["revision"] += 1
    elif damage == "anchor-scope":
        body["anchors"][0]["scope"] = "{}"
    elif damage == "anchor-digest":
        body["anchors"][0]["trail_digest"] = "z" * 64
    elif damage == "empty":
        body["anchors"] = []
    elif damage == "duplicate":
        body["anchors"] *= 2
    elif damage == "float":
        body["anchors"][0]["revision"] = 0.0
    elif damage == "repeated-key":
        manifest(backup).write_text('{"version":1,"version":1}', encoding="ascii")
    elif damage == "oversized":
        manifest(backup).write_text(" " * 2_000_001, encoding="ascii")
    else:
        backup.database_path().with_name("gridbot-state.sqlite3-journal").write_bytes(b"pending")
    if damage not in {"header", "manifest-json", "repeated-key", "oversized", "pending-journal"}:
        manifest(backup).write_text(json.dumps(body), encoding="ascii")
    original_db = backup.database_path().read_bytes()
    original_manifest = manifest(backup).read_bytes()
    with pytest.raises(PersistenceError):
        verify_backup(backup)
    assert backup.database_path().read_bytes() == original_db
    assert manifest(backup).read_bytes() == original_manifest


@pytest.mark.parametrize("timeout", [0, 61, True, -1])
def test_invalid_timeout_has_no_effect(tmp_path: Path, timeout: int) -> None:
    origin = destination(tmp_path, "origin")
    store, _state = journal_start(origin.directory)
    backup = destination(tmp_path, "backup")
    with pytest.raises(PersistenceError):
        create_verified_backup(store, backup, timeout_seconds=timeout)
    assert not backup.database_path().exists()


def test_divergent_known_anchor_is_not_accepted_by_revision_only(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, _state = journal_start(origin.directory)
    backup = destination(tmp_path, "backup")
    captured = create_verified_backup(store, backup)
    divergent = replace(captured.anchors[0], state_digest="0" * 64)
    restored = destination(tmp_path, "restored")
    with pytest.raises(PersistenceError) as error:
        restore_verified_backup(backup, restored, expected_anchors=(divergent,))
    assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
    assert not restored.database_path().exists()


def test_backup_captures_confirmed_duplicate_and_quarantine(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, _revision = seeded(origin.directory)
    scope = decode_scope(origin.directory)
    state = store.load_operational_state(scope)
    raw = wire_scenario().tape.observations[0]
    state = store.append_raw_observation(scope, state.revision, replace(raw, payload="[]"))
    state = store.record_replay(scope, state.revision, wire_scenario().plan)
    before = store.recover(scope)
    assert before.replays[-1].quarantined_sources
    backup = destination(tmp_path, "backup")
    create_verified_backup(store, backup)
    assert SQLiteOperationalJournal.open(backup).recover(scope) == before


def test_anchor_revalidates_nested_scope(tmp_path: Path) -> None:
    store, _state = journal_start(tmp_path)
    anchor = inspect_anchors(store)[0]
    object.__setattr__(anchor.scope, "account_ref", "")
    with pytest.raises(PersistenceError):
        JournalAnchor(
            anchor.scope,
            anchor.revision,
            anchor.last_sequence,
            anchor.state_digest,
            anchor.trail_digest,
        )


def test_backup_is_consistent_while_another_process_stages_write(tmp_path: Path) -> None:
    origin = destination(tmp_path, "origin")
    store, revision = seeded(origin.directory)
    known = inspect_anchors(store)
    backup = destination(tmp_path, "backup")
    processes = []
    pool = ThreadPoolExecutor(max_workers=1)

    def stage(_self: SQLiteOperationalJournal, point: str) -> None:
        if point == "before_backup":
            writer = start(origin.directory, "staged", point="before_commit")
            processes.append(writer)
            assert pool.submit(line, writer).result(timeout=30)["staged"] is True

    try:
        with patch.object(SQLiteOperationalJournal, "_checkpoint", stage):
            captured = create_verified_backup(store, backup)
        assert captured.anchors == known
        send(processes[0], "COMMIT")
        assert pool.submit(line, processes[0]).result(timeout=30)["status"] == "COMMITTED"
        assert processes[0].wait(timeout=10) == 0
        assert inspect_anchors(store)[0].revision == revision + 1
        assert verify_backup(backup) == captured
        audit_rows(backup.database_path(), expected_receipts=3)
    finally:
        cleanup(processes)
        pool.shutdown(wait=True, cancel_futures=True)
