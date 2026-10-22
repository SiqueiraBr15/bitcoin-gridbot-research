"""A17.4: contraexemplos de ordem, falhas de driver e barreiras independentes."""

from __future__ import annotations

import json
import sqlite3
import stat
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gridbot.application.operational_persistence import (
    MarkOperationalSellUncertain,
    PersistenceError,
    PersistenceErrorCode,
)
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.journal_paths import _check_node
from gridbot.storage.operational_journal import SQLiteOperationalJournal, _scope_key
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.application.test_operational_grid import ref
from tests.storage.test_journal_corruption import (
    drop_update_guards,
    rehash_journal,
    restore_update_guards,
)
from tests.storage.test_operational_journal import (
    assert_conserved,
    bound_sell,
    funded_plan,
    journal_start,
)


def test_other_order_same_execution_and_cycle_stays_outside_active_tape(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    raw = source.tape.observations[0]
    payload = json.loads(raw.payload)
    payload["orderId"] = 999
    foreign_order = replace(
        raw,
        source_ref="another-order",
        scope=replace(raw.scope, order_ref="999"),
        payload=json.dumps(payload),
    )
    state = store.append_raw_observations(
        state.scope, state.revision, (*source.tape.observations, foreign_order)
    )
    reopened = SQLiteOperationalJournal.open(store.policy)
    replay = reopened.replay_observations(state.scope, source.plan)
    assert len(replay.tape.observations) == 3
    assert replay.candidate is not None
    assert len(reopened.recover(state.scope).receipts) == 4
    assert reopened.recover(state.scope).receipts[-1].raw == foreign_order
    assert_conserved(state)


def test_rehashed_incompatible_historical_command_has_typed_corruption(tmp_path: Path) -> None:
    store, _state = bound_sell(tmp_path)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        drop_update_guards(connection)
        connection.execute(
            "UPDATE entries SET payload=? WHERE sequence=2",
            (encode_contract(MarkOperationalSellUncertain(ref())),),
        )
        rehash_journal(connection)
        restore_update_guards(connection)
    original = store.policy.database_path().read_bytes()
    with pytest.raises(PersistenceError) as error:
        SQLiteOperationalJournal.open(store.policy)
    assert error.value.code is PersistenceErrorCode.CORRUPT_DATABASE
    assert error.value.__cause__ is not None
    assert store.policy.database_path().read_bytes() == original


def test_private_persist_rechecks_stale_revision_before_any_insert(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    newer = store.commit_operational_transition(state.scope, state.revision, funded_plan(state))
    with store._session(write=True) as connection:
        with pytest.raises(PersistenceError) as error:
            store._persist(
                connection, state.scope, state.book, state.revision, (("RAW", None, None),)
            )
        assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
    assert store.load_operational_state(state.scope) == newer


def test_native_update_zero_rows_is_checked_inside_transaction(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)

    def inject() -> None:
        with store._session(write=True) as connection:
            # DDL fault AFTER schema validation, not a normal concurrent writer.
            connection.execute(
                "CREATE TRIGGER injected_ignore BEFORE UPDATE ON heads "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
            store._persist(
                connection,
                state.scope,
                state.book,
                state.revision,
                (("TRANSITION", funded_plan(state), None),),
            )

    with pytest.raises(PersistenceError) as error:
        inject()
    assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
    assert store.load_operational_state(state.scope) == state


class CloseFault(sqlite3.Connection):
    def close(self) -> None:
        raise sqlite3.OperationalError("synthetic close failure")


@pytest.mark.parametrize("commit_first", [False, True])
def test_native_commit_lost_ack_requires_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_first: bool
) -> None:
    store, state = journal_start(tmp_path)

    class CommitFault(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if sql == "COMMIT":
                if commit_first:
                    super().execute(sql, parameters)
                raise sqlite3.OperationalError("synthetic lost commit acknowledgement")
            return super().execute(sql, parameters)

    connection = sqlite3.connect(store.policy.database_path(), autocommit=True, factory=CommitFault)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=EXTRA")
    with monkeypatch.context() as scoped:
        scoped.setattr(SQLiteOperationalJournal, "_connect", lambda _self: connection)
        with pytest.raises(PersistenceError) as error:
            store.commit_operational_transition(state.scope, state.revision, funded_plan(state))
        assert error.value.code is PersistenceErrorCode.COMMIT_UNCERTAIN
    recovered = SQLiteOperationalJournal.open(store.policy).load_operational_state(state.scope)
    assert recovered.revision == state.revision + commit_first
    assert len(recovered.book.inventory_book.funded_buy_book.reservations) == int(commit_first)
    assert_conserved(recovered)


@pytest.mark.parametrize("point", ["during_integrity", "after_snapshot_prepared", "after_event"])
def test_io_failure_before_commit_preserves_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    store, state = bound_sell(tmp_path)
    original = store.recover(state.scope)

    def fail(_self: SQLiteOperationalJournal, name: str) -> None:
        if name == point:
            raise OSError("synthetic IO interruption")

    with monkeypatch.context() as scoped:
        scoped.setattr(SQLiteOperationalJournal, "_checkpoint", fail)
        with pytest.raises(PersistenceError) as error:
            store.append_raw_observation(
                state.scope, state.revision, wire_scenario().tape.observations[0]
            )
        assert error.value.code is PersistenceErrorCode.IO_ERROR
    assert store.recover(state.scope) == original


def fault_connection(
    monkeypatch: pytest.MonkeyPatch, store: SQLiteOperationalJournal
) -> CloseFault:
    connection = sqlite3.connect(store.policy.database_path(), autocommit=True, factory=CloseFault)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=EXTRA")
    monkeypatch.setattr(SQLiteOperationalJournal, "_connect", lambda _self: connection)
    return connection


def test_explicit_rollback_releases_transaction_even_when_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state = journal_start(tmp_path)
    with monkeypatch.context() as scoped:
        connection = fault_connection(scoped, store)
        try:

            def fail() -> None:
                with store._session(write=True) as current:
                    current.execute("INSERT INTO states VALUES ('injected','not-a-state')")
                    raise RuntimeError("synthetic body fault")

            with pytest.raises((sqlite3.Error, PersistenceError)):
                fail()
            assert not connection.in_transaction
            assert connection.execute(
                "SELECT count(*) FROM states WHERE digest='injected'"
            ).fetchone() == (0,)
        finally:
            sqlite3.Connection.close(connection)
    assert store.load_operational_state(state.scope) == state


def test_close_failure_after_confirmed_commit_is_typed_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state = journal_start(tmp_path)
    with monkeypatch.context() as scoped:
        connection = fault_connection(scoped, store)
        try:
            with pytest.raises(PersistenceError) as error:
                store.commit_operational_transition(state.scope, state.revision, funded_plan(state))
            assert error.value.code is PersistenceErrorCode.COMMIT_UNCERTAIN
        finally:
            sqlite3.Connection.close(connection)
    recovered = store.load_operational_state(state.scope)
    assert recovered.revision == state.revision + 1
    assert len(recovered.book.inventory_book.funded_buy_book.reservations) == 1
    assert_conserved(recovered)


def test_unknown_reparse_attribute_is_independently_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unsupported provider tag: lexical resolution and regular-file type alone
    # cannot establish safety. Model Windows lstat without inventing a real provider.
    path = tmp_path / "provider-file"
    path.write_text("fixture", encoding="utf8")
    details = SimpleNamespace(
        st_mode=stat.S_IFREG,
        st_nlink=1,
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024),
    )
    monkeypatch.setattr(Path, "lstat", lambda _self: details)
    with pytest.raises(PersistenceError) as error:
        _check_node(path, directory=False, optional=False)
    assert error.value.code is PersistenceErrorCode.PATH_UNSAFE


@pytest.mark.parametrize("field", ["normalized", "issues", "quarantined_sources"])
def test_codec_rejects_null_in_mandatory_projection_tuple(tmp_path: Path, field: str) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    payload = json.loads(encode_contract(store.recover(state.scope).replays[-1]))
    payload["value"]["fields"][field] = None
    with pytest.raises(PersistenceError):
        decode_contract(json.dumps(payload))
    assert store.load_operational_state(state.scope) == state


def test_receipt_classification_requires_compatible_duplicate_link(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    state = store.append_raw_observation(
        state.scope, state.revision, wire_scenario().tape.observations[0]
    )
    receipt = store.recover(state.scope).receipts[0]
    with pytest.raises(TypeError):
        replace(receipt, classification=ReceiptClassification.DUPLICATE_IDENTICAL)


def test_truncated_head_is_only_detected_with_external_known_anchor(tmp_path: Path) -> None:
    # A complete prior DB copy is valid internally. This is a demonstrated trust
    # limit, not a decoder failure or automatic reset path.
    store, old = journal_start(tmp_path)
    backup = tmp_path / "prior-copy.sqlite3"
    source = sqlite3.connect(store.policy.database_path(), autocommit=True)
    target = sqlite3.connect(backup, autocommit=True)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    new = store.commit_operational_transition(old.scope, old.revision, funded_plan(old))
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute(
            "SELECT revision FROM heads WHERE scope_key=?", (_scope_key(old.scope),)
        ).fetchone() == (0,)
    assert new.revision > old.revision


@pytest.mark.parametrize("kind", ["missing", "extra", "bool-schema", "class", "enum"])
def test_adversarial_codec_shape_rejects_without_mutation(tmp_path: Path, kind: str) -> None:
    store, state = journal_start(tmp_path)
    data: Any = json.loads(encode_contract(state.book))
    if kind == "missing":
        del data["value"]["fields"]["sell_attempts"]
    elif kind == "extra":
        data["value"]["fields"]["invented_capital"] = 0
    elif kind == "bool-schema":
        data["schema"] = True
    elif kind == "class":
        data["value"]["type"] = "FinalizedSell"
    else:
        data["value"] = {"enum": ["Side", "NOT_A_SIDE"]}
    with pytest.raises(PersistenceError):
        decode_contract(json.dumps(cast(dict[str, Any], data)))
    assert store.load_operational_state(state.scope) == state
