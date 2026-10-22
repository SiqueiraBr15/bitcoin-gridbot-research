"""A17.4: backup manual selado e restore em destino novo, sem ativação operacional."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

from gridbot.application.operational_persistence import (
    OperationalScope,
    PersistenceError,
    PersistenceErrorCode,
    require_revision,
)
from gridbot.storage.financial_codec import (
    _non_json_number,
    _pairs,
    decode_contract,
    encode_contract,
)
from gridbot.storage.journal_paths import JournalPathPolicy, _check_node
from gridbot.storage.operational_journal import SQLiteOperationalJournal, _scope_key

E = PersistenceErrorCode
_MANIFEST = "gridbot-backup-manifest.json"


@dataclass(frozen=True, slots=True)
class JournalAnchor:
    scope: OperationalScope
    revision: int
    last_sequence: int
    state_digest: str
    trail_digest: str

    def __post_init__(self) -> None:
        if type(self.scope) is not OperationalScope:
            raise PersistenceError(E.INVALID_STATE, "anchor sem escopo conhecido")
        replace(self.scope)
        require_revision(self.revision)
        require_revision(self.last_sequence)
        if not self.last_sequence:
            raise PersistenceError(E.INVALID_STATE, "anchor sem sequência")
        for value in (self.state_digest, self.trail_digest):
            if (
                type(value) is not str
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise PersistenceError(E.INVALID_STATE, "anchor/digest inválido")


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    anchors: tuple[JournalAnchor, ...]
    database_digest: str


def _anchors(
    store: SQLiteOperationalJournal, connection: sqlite3.Connection
) -> tuple[JournalAnchor, ...]:
    result = []
    references: set[str] = set()
    for key, scope_text in connection.execute(
        "SELECT scope_key,scope_payload FROM heads ORDER BY scope_key"
    ):
        scope = decode_contract(scope_text)
        if type(scope) is not OperationalScope or _scope_key(scope) != key:
            raise PersistenceError(E.CORRUPT_DATABASE, "scope/anchor divergentes")
        recovered = store._read(connection, scope)
        row = connection.execute(
            "SELECT state_digest,last_sequence,tip_hash FROM revisions "
            "WHERE scope_key=? AND revision=?",
            (key, recovered.state.revision),
        ).fetchone()
        if row is None:
            raise PersistenceError(E.CORRUPT_DATABASE, "anchor sem revisão")
        result.append(JournalAnchor(scope, recovered.state.revision, row[1], row[0], row[2]))
        references.update(
            r[0]
            for r in connection.execute(
                "SELECT state_digest FROM revisions WHERE scope_key=?", (key,)
            )
        )
    if references != {r[0] for r in connection.execute("SELECT digest FROM states")}:
        raise PersistenceError(E.CORRUPT_DATABASE, "snapshot órfão no backup")
    if not result:
        raise PersistenceError(E.EMPTY_DATABASE, "backup requer autoridade inicializada")
    return tuple(result)


def inspect_anchors(store: SQLiteOperationalJournal) -> tuple[JournalAnchor, ...]:
    with store._session(write=False) as connection:
        return _anchors(store, connection)


def _file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            result.update(block)
    return result.hexdigest()


def _manifest_path(policy: JournalPathPolicy) -> Path:
    path = policy.database_path().parent / _MANIFEST
    _check_node(path, directory=False, optional=True)
    return path


def _write_manifest(policy: JournalPathPolicy, verified: VerifiedBackup) -> None:
    body = {
        "version": 1,
        "schema": 1,
        "codec": 1,
        "projection": 1,
        "database_digest": verified.database_digest,
        "anchors": [
            {
                "scope": encode_contract(a.scope),
                "revision": a.revision,
                "last_sequence": a.last_sequence,
                "state_digest": a.state_digest,
                "trail_digest": a.trail_digest,
            }
            for a in verified.anchors
        ],
    }
    data = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(data) > 2_000_000:
        raise PersistenceError(E.LIMIT_EXCEEDED, "manifest excede limite")
    with _manifest_path(policy).open("x", encoding="ascii") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create_verified_backup(
    source: SQLiteOperationalJournal,
    destination: JournalPathPolicy,
    *,
    timeout_seconds: int = 15,
    _expected_capture: tuple[JournalAnchor, ...] | None = None,
) -> VerifiedBackup:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
        raise PersistenceError(E.INVALID_STATE, "backup timeout deve ser 1..60 segundos")
    path = destination.database_path()
    manifest = _manifest_path(destination)
    if path.exists() or manifest.exists():
        raise PersistenceError(E.DUPLICATE_SCOPE, "destino existente; nenhuma sobrescrita")
    try:
        with source._session(write=False) as reader:
            anchors = _anchors(source, reader)
            if _expected_capture is not None and anchors != _expected_capture:
                raise PersistenceError(
                    E.CORRUPT_DATABASE, "fonte mudou antes da cópia; nenhum destino criado"
                )
            source._checkpoint("before_backup")
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            target = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, autocommit=True)
            try:
                target.execute("PRAGMA synchronous=EXTRA")
                target.execute("PRAGMA foreign_keys=ON")
                target.execute("PRAGMA trusted_schema=OFF")
                deadline = time.monotonic() + timeout_seconds

                def progress(_status: int, _remaining: int, _total: int) -> None:
                    source._checkpoint("during_backup")
                    if time.monotonic() > deadline:
                        raise PersistenceError(E.BUSY, "backup interrompido por limite de tempo")

                reader.backup(target, pages=32, progress=progress, sleep=0.01)
            finally:
                target.close()
        copied = SQLiteOperationalJournal.open(destination)
        if inspect_anchors(copied) != anchors:
            raise PersistenceError(E.CORRUPT_DATABASE, "backup não corresponde à visão capturada")
        verified = VerifiedBackup(anchors, _file_hash(path))
        _write_manifest(destination, verified)
        return verified
    except PersistenceError:
        raise
    except FileExistsError as exc:
        raise PersistenceError(
            E.DUPLICATE_SCOPE, "destino foi ocupado; preservar arquivos"
        ) from exc
    except (sqlite3.Error, OSError) as exc:
        raise PersistenceError(
            E.IO_ERROR, "backup incompleto; preservar para investigação"
        ) from exc


def verify_backup(policy: JournalPathPolicy) -> VerifiedBackup:
    try:
        path = policy.database_path()
        if path.with_name(path.name + "-journal").exists():
            raise PersistenceError(
                E.CORRUPT_DATABASE, "backup com journal pendente; não recuperar automaticamente"
            )
        with _manifest_path(policy).open(encoding="ascii") as stream:
            text = stream.read(2_000_001)
        if len(text) > 2_000_000:
            raise PersistenceError(E.LIMIT_EXCEEDED, "manifest excede limite")
        body = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_non_json_number,
            parse_constant=_non_json_number,
        )
        if type(body) is not dict or set(body) != {
            "version",
            "schema",
            "codec",
            "projection",
            "database_digest",
            "anchors",
        }:
            raise PersistenceError(E.UNKNOWN_SCHEMA, "manifest desconhecido")
        if any(
            type(body[k]) is not int or body[k] != 1
            for k in ("version", "schema", "codec", "projection")
        ):
            raise PersistenceError(E.UNKNOWN_SCHEMA, "versão de backup desconhecida")
        if type(body["anchors"]) is not list:
            raise PersistenceError(E.INVALID_STATE, "anchors ausentes")
        anchors = []
        for item in body["anchors"]:
            if type(item) is not dict or set(item) != {
                "scope",
                "revision",
                "last_sequence",
                "state_digest",
                "trail_digest",
            }:
                raise PersistenceError(E.INVALID_STATE, "anchor parcial")
            scope = decode_contract(item["scope"])
            if type(scope) is not OperationalScope:
                raise PersistenceError(E.SCOPE_MISMATCH, "anchor de tipo desconhecido")
            anchors.append(
                JournalAnchor(
                    scope,
                    item["revision"],
                    item["last_sequence"],
                    item["state_digest"],
                    item["trail_digest"],
                )
            )
        expected = VerifiedBackup(tuple(anchors), body["database_digest"])
        if _file_hash(path) != expected.database_digest:
            raise PersistenceError(E.CORRUPT_DATABASE, "backup/file hash divergente")
        copied = SQLiteOperationalJournal.open(policy)
        if (
            inspect_anchors(copied) != expected.anchors
            or _file_hash(path) != expected.database_digest
        ):
            raise PersistenceError(E.CORRUPT_DATABASE, "backup/anchors divergentes")
        return expected
    except PersistenceError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        raise PersistenceError(E.CORRUPT_DATABASE, "backup inválido; não reparar") from exc


def restore_verified_backup(
    source: JournalPathPolicy,
    destination: JournalPathPolicy,
    *,
    expected_anchors: tuple[JournalAnchor, ...],
) -> VerifiedBackup:
    verified = verify_backup(source)
    if type(expected_anchors) is not tuple or any(
        type(a) is not JournalAnchor for a in expected_anchors
    ):
        raise PersistenceError(E.INVALID_STATE, "anchor externa explícita requerida")
    expected_anchors = tuple(replace(a) for a in expected_anchors)
    store = SQLiteOperationalJournal.open(source)
    with store._session(write=False) as connection:
        for anchor in expected_anchors:
            # A trusted known prefix must exist verbatim, not only have a smaller revision.
            row = connection.execute(
                "SELECT state_digest,last_sequence,tip_hash FROM revisions "
                "WHERE scope_key=? AND revision=?",
                (_scope_key(anchor.scope), anchor.revision),
            ).fetchone()
            if row != (anchor.state_digest, anchor.last_sequence, anchor.trail_digest):
                raise PersistenceError(
                    E.REVISION_CONFLICT, "backup antigo/divergente da anchor conhecida"
                )
    copied = create_verified_backup(store, destination, _expected_capture=verified.anchors)
    if copied.anchors != verified.anchors:
        raise PersistenceError(E.CORRUPT_DATABASE, "fonte de restore mudou; preservar destino")
    return copied
