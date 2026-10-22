"""Corrupção local, inclusive hashes reescritos sem alterar semântica do journal."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from gridbot.application import GridOperationalBook, SellInventoryBook
from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.storage.financial_codec import encode_contract
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import (
    _TRIGGERS,
    _ZERO_HASH,
    SQLiteOperationalJournal,
    _hash,
)
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.storage.test_operational_journal import bound_sell, journal_start


def drop_update_guards(connection: sqlite3.Connection) -> None:
    for statement in (
        "DROP TRIGGER states_no_update",
        "DROP TRIGGER revisions_no_update",
        "DROP TRIGGER entries_no_update",
        "DROP TRIGGER heads_cas",
    ):
        connection.execute(statement)


def restore_update_guards(connection: sqlite3.Connection) -> None:
    for name in ("states_no_update", "revisions_no_update", "entries_no_update", "heads_cas"):
        connection.execute(_TRIGGERS[name])


def rehash_journal(connection: sqlite3.Connection) -> None:
    """Adversário de teste reescreve cadeia; coerência econômica ainda deve bloquear."""
    for (scope_key,) in connection.execute("SELECT scope_key FROM heads").fetchall():
        parent = _ZERO_HASH
        tips: dict[int, tuple[int, str]] = {}
        for sequence, revision, kind, payload, source_key in connection.execute(
            "SELECT sequence,revision,kind,payload,source_key FROM entries "
            "WHERE scope_key=? ORDER BY sequence",
            (scope_key,),
        ).fetchall():
            digest = _hash(
                encode_contract((scope_key, sequence, revision, kind, payload, parent, source_key))
            )
            connection.execute(
                "UPDATE entries SET previous_hash=?,digest=? WHERE scope_key=? AND sequence=?",
                (parent, digest, scope_key, sequence),
            )
            parent = digest
            tips[revision] = sequence, digest
        for revision, (sequence, digest) in tips.items():
            connection.execute(
                "UPDATE revisions SET last_sequence=?,tip_hash=? WHERE scope_key=? AND revision=?",
                (sequence, digest, scope_key, revision),
            )
        last_revision = max(tips)
        sequence, digest = tips[last_revision]
        connection.execute(
            "UPDATE heads SET last_sequence=?,tip_hash=? WHERE scope_key=?",
            (sequence, digest, scope_key),
        )


@pytest.mark.parametrize(
    "change", ["hash", "sequence", "revision", "payload", "source-index", "tip"]
)
def test_payload_sequence_revision_and_index_corruption_fail_closed(
    tmp_path: Path, change: str
) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        drop_update_guards(connection)
        statements = {
            "hash": "UPDATE entries SET digest='bad' WHERE kind='RAW'",
            "sequence": "UPDATE entries SET sequence=sequence+10000 WHERE kind='RAW'",
            "revision": "UPDATE heads SET revision=9223372036854775806",
            "payload": "UPDATE entries SET payload='{' WHERE kind='RAW'",
            "source-index": "UPDATE entries SET source_key='wrong' WHERE kind='RAW'",
            "tip": "UPDATE heads SET tip_hash='wrong'",
        }
        connection.execute(statements[change])
        restore_update_guards(connection)
    original_bytes = store.policy.database_path().read_bytes()
    with pytest.raises(PersistenceError):
        SQLiteOperationalJournal.open(store.policy)
    assert store.policy.database_path().read_bytes() == original_bytes


@pytest.mark.parametrize(
    "change", ["json", "decimal", "asset", "unknown-class", "partial", "rewrap"]
)
def test_snapshot_valid_hash_does_not_bypass_financial_or_continuity_checks(
    tmp_path: Path, change: str
) -> None:
    store, state = bound_sell(tmp_path)
    if change == "rewrap":
        lost = GridOperationalBook(SellInventoryBook(state.book.inventory_book.funded_buy_book))
        payload_text = encode_contract(lost)
    elif change == "json":
        payload_text = "{"
    else:
        payload: Any = json.loads(encode_contract(state.book))
        funded = payload["value"]["fields"]["inventory_book"]["fields"]["funded_buy_book"]["fields"]
        if change == "decimal":
            funded["initial_quote_capital"]["fields"]["amount"]["decimal"][1] = "NaN"
        elif change == "asset":
            funded["initial_quote_capital"]["fields"]["asset"]["fields"]["code"] = "usdt"
        elif change == "unknown-class":
            payload["value"]["type"] = "UnknownRoot"
        else:
            del funded["settled_reservations"]
        payload_text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = _hash(payload_text)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        drop_update_guards(connection)
        connection.execute("INSERT OR IGNORE INTO states VALUES (?,?)", (digest, payload_text))
        connection.execute(
            "UPDATE revisions SET state_digest=? WHERE revision=?", (digest, state.revision)
        )
        restore_update_guards(connection)
    before = store.policy.database_path().read_bytes()
    with pytest.raises(PersistenceError) as error:
        store.load_operational_state(state.scope)
    assert error.value.code in {
        PersistenceErrorCode.CORRUPT_DATABASE,
        PersistenceErrorCode.CORRUPT_JSON,
        PersistenceErrorCode.INVALID_DECIMAL,
        PersistenceErrorCode.INVALID_STATE,
        PersistenceErrorCode.UNKNOWN_SCHEMA,
    }
    assert store.policy.database_path().read_bytes() == before


def test_rehashed_quarantine_cannot_be_erased_by_projection_edit(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = edited(wire_scenario(), "page-0", "commission", None, remove=True)
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    record = store.recover(state.scope).replays[0]
    assert record.quarantined_sources
    forged = replace(record, quarantined_sources=(), issues=())
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        drop_update_guards(connection)
        connection.execute(
            "UPDATE entries SET payload=? WHERE kind='REPLAY'", (encode_contract(forged),)
        )
        rehash_journal(connection)
        restore_update_guards(connection)
    with pytest.raises(PersistenceError) as error:
        store.recover(state.scope)
    assert error.value.code is PersistenceErrorCode.CORRUPT_DATABASE


def test_valid_bootstrap_payload_cannot_change_without_snapshot_digest(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    payload = json.loads(encode_contract(state.book))
    funded = payload["value"]["fields"]["inventory_book"]["fields"]["funded_buy_book"]["fields"]
    funded["initial_quote_capital"]["fields"]["amount"]["decimal"] = [0, "21", 0]
    changed = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        drop_update_guards(connection)
        connection.execute("UPDATE states SET payload=?", (changed,))
        restore_update_guards(connection)
    with pytest.raises(PersistenceError) as error:
        store.load_operational_state(state.scope)
    assert error.value.code is PersistenceErrorCode.CORRUPT_DATABASE


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE unknown_table (v TEXT)",
        "DROP INDEX entries_source",
        "DROP TRIGGER entries_no_delete",
        "PRAGMA user_version=2",
    ],
)
def test_unknown_or_partial_schema_never_migrates_silently(tmp_path: Path, ddl: str) -> None:
    store, _ = journal_start(tmp_path)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        connection.execute(ddl)
    with pytest.raises(PersistenceError) as error:
        SQLiteOperationalJournal.open(store.policy)
    assert error.value.code is PersistenceErrorCode.UNKNOWN_SCHEMA


@pytest.mark.parametrize("payload", [b"not SQLite", b"SQLite format 3\x00" + b"broken"])
def test_invalid_database_is_preserved(tmp_path: Path, payload: bytes) -> None:
    policy = JournalPathPolicy(tmp_path)
    policy.database_path().write_bytes(payload)
    with pytest.raises(PersistenceError):
        SQLiteOperationalJournal.open(policy)
    assert policy.database_path().read_bytes() == payload


def test_file_replacement_is_detected_before_opening_new_authority(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    original = store.policy.database_path()
    original.rename(tmp_path / "preserved.sqlite3")
    original.write_bytes(b"replacement")
    with pytest.raises(PersistenceError) as error:
        store.load_operational_state(state.scope)
    assert error.value.code is PersistenceErrorCode.PATH_UNSAFE
    assert original.read_bytes() == b"replacement"


@pytest.mark.parametrize("component", ["OneDrive", "SharePoint", "Dropbox", "Google Drive"])
def test_synchronized_directory_is_rejected_before_database_creation(
    tmp_path: Path, component: str
) -> None:
    forbidden = tmp_path / component
    forbidden.mkdir()
    with pytest.raises(PersistenceError):
        JournalPathPolicy(forbidden)
    assert not list(forbidden.iterdir())


def test_relative_missing_env_alias_and_network_destinations_are_rejected(tmp_path: Path) -> None:
    for directory in (Path("relative"), tmp_path / "absent", Path(r"\\server\share\gridbot")):
        with pytest.raises(PersistenceError):
            JournalPathPolicy(directory)
    with pytest.raises(PersistenceError):
        JournalPathPolicy(tmp_path, (("OneDrive", str(tmp_path.parent)),))


def test_junction_and_sidecar_links_are_rejected_without_following(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    destination = tmp_path / "real"
    destination.mkdir()
    alias = tmp_path / "alias"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(destination)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
    else:
        alias.symlink_to(destination, target_is_directory=True)
    with pytest.raises(PersistenceError):
        JournalPathPolicy(alias)
    assert not list(destination.iterdir())
    policy = JournalPathPolicy(destination)
    secret_free_file = tmp_path / "fixture-file"
    secret_free_file.write_text("fixture", encoding="utf8")
    sidecar = policy.database_path().with_name("gridbot-state.sqlite3-journal")
    os.link(secret_free_file, sidecar)
    with pytest.raises(PersistenceError):
        policy.database_path()
    assert secret_free_file.read_text(encoding="utf8") == "fixture"


def test_read_only_and_create_permission_failures_are_typed_without_new_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    policy = JournalPathPolicy(tmp_path)

    def denied(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("synthetic permissions")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "open", denied)
        with pytest.raises(PersistenceError) as error:
            SQLiteOperationalJournal.create(policy)
        assert error.value.code is PersistenceErrorCode.IO_ERROR
    assert not policy.database_path().exists()
    store, state = journal_start(tmp_path)

    def cannot_connect(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("synthetic read-only")

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite3, "connect", cannot_connect)
        with pytest.raises(PersistenceError) as error:
            store.load_operational_state(state.scope)
        assert error.value.code is PersistenceErrorCode.IO_ERROR
    assert store.load_operational_state(state.scope) == state
