"""SQLite local/offline A17.3: raiz, revisões CAS e evidências transacionais.

Hash local detecta alterações acidentais; não autentica Binance ou impede um ator
com escrita no banco de reescrever a cadeia. Sem efeitos econômicos SELL/rede.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.operational_persistence import (
    OperationalScope,
    OperationalTransition,
    PersistenceError,
    PersistenceErrorCode,
    VersionedOperationalState,
    apply_operational_transition,
    require_revision,
    validate_pristine_bootstrap,
)
from gridbot.application.sell_evidence import SellOrderIdentity
from gridbot.application.sell_terminal import SellJournalReference, SellTerminalReconciliation
from gridbot.domain.errors import DomainError
from gridbot.exchange.binance.offline_evidence import RawSellObservation
from gridbot.exchange.binance.offline_replay import (
    OfflineSellReplay,
    OfflineSellReplayPlan,
    OfflineSellTape,
    replay_sell_observations,
)
from gridbot.exchange.binance.offline_terminal import reconcile_offline_sell_terminal
from gridbot.storage.financial_codec import decode_contract, encode_contract, revalidate_contract
from gridbot.storage.journal_models import (
    DurableRawReceipt,
    DurableReplayRecord,
    ReceiptClassification,
    replay_record,
)
from gridbot.storage.journal_paths import JournalPathPolicy

_E = PersistenceErrorCode
_ZERO_HASH = "0" * 64
_TRANSITIONS = frozenset(
    {
        "PrepareOperationalBuy",
        "BindOperationalBuy",
        "MarkOperationalBuyUncertain",
        "SettleOperationalBuy",
        "ReserveOperationalSell",
        "PrepareOperationalSell",
        "MarkOperationalSellUncertain",
        "BindOperationalSell",
        "BindOperationalExternalSell",
    }
)
_SENSITIVE = re.compile(
    r'(?i)(?:["\'](?:api[_-]?key|secret|signature|access[_-]?token|authorization|x-mbx-apikey)["\']\s*:'
    r"|(?:proxy-)?authorization\s*:|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^\s/]+@)"
)

_TABLES = {
    "meta": (
        "CREATE TABLE meta (version INTEGER NOT NULL, codec INTEGER NOT NULL, p"
        "rojection INTEGER NOT NULL) STRICT"
    ),
    "heads": (
        "CREATE TABLE heads (scope_key TEXT PRIMARY KEY, scope_payload TEXT NOT"
        " NULL, revision INTEGER NOT NULL CHECK(revision >= 0), last_sequence I"
        "NTEGER NOT NULL CHECK(last_sequence > 0), tip_hash TEXT NOT NULL) STRI"
        "CT"
    ),
    "states": "CREATE TABLE states (digest TEXT PRIMARY KEY, payload TEXT NOT NULL) STRICT",
    "revisions": (
        "CREATE TABLE revisions (scope_key TEXT NOT NULL REFERENCES heads(scope"
        "_key), revision INTEGER NOT NULL CHECK(revision >= 0), state_digest TE"
        "XT NOT NULL REFERENCES states(digest), last_sequence INTEGER NOT NULL,"
        " tip_hash TEXT NOT NULL, PRIMARY KEY(scope_key, revision)) STRICT"
    ),
    "entries": (
        "CREATE TABLE entries (scope_key TEXT NOT NULL, sequence INTEGER NOT NU"
        "LL CHECK(sequence > 0), revision INTEGER NOT NULL CHECK(revision >= 0)"
        ", kind TEXT NOT NULL CHECK(kind IN ('BOOTSTRAP','TRANSITION','RAW','RE"
        "PLAY')), payload TEXT NOT NULL, previous_hash TEXT NOT NULL, digest TE"
        "XT NOT NULL, source_key TEXT, PRIMARY KEY(scope_key, sequence), FOREIG"
        "N KEY(scope_key, revision) REFERENCES revisions(scope_key, revision) D"
        "EFERRABLE INITIALLY DEFERRED) STRICT"
    ),
}
_INDEXES = {
    "entries_source": "CREATE INDEX entries_source ON entries(scope_key, source_key)",
}
_TRIGGERS = {
    f"{table}_no_{operation.lower()}": (
        f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
    )
    for table in ("meta", "states", "revisions", "entries")
    for operation in ("UPDATE", "DELETE")
}
_TRIGGERS.update(
    {
        "heads_no_delete": (
            "CREATE TRIGGER heads_no_delete BEFORE DELETE ON heads BEGIN SELECT RAI"
            "SE(ABORT, 'authority'); END"
        ),
        "heads_cas": (
            "CREATE TRIGGER heads_cas BEFORE UPDATE ON heads WHEN NEW.scope_key != "
            "OLD.scope_key OR NEW.scope_payload != OLD.scope_payload OR NEW.revisio"
            "n != OLD.revision + 1 OR NEW.last_sequence <= OLD.last_sequence BEGIN "
            "SELECT RAISE(ABORT, 'CAS'); END"
        ),
    }
)
_SCHEMA = {
    **{name: ("table", sql) for name, sql in _TABLES.items()},
    **{name: ("index", sql) for name, sql in _INDEXES.items()},
    **{name: ("trigger", sql) for name, sql in _TRIGGERS.items()},
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _scope_key(scope: OperationalScope) -> str:
    return _hash(encode_contract(revalidate_contract(scope, OperationalScope)))


def _external_scope(identity: SellOrderIdentity) -> OperationalScope:
    return OperationalScope(
        identity.venue_ref, identity.account_ref, identity.environment_ref, identity.symbol
    )


def _source_key(raw: RawSellObservation) -> str:
    identity = raw.scope
    return _hash(
        encode_contract(
            (
                _external_scope(identity),
                identity.order_ref,
                identity.execution_ref,
                identity.cycle_ref,
                raw.kind,
                raw.collection_ref,
                raw.source_ref,
            )
        )
    )


def _classification(
    scope: OperationalScope,
    raw: RawSellObservation,
    sequence: int,
    index: dict[str, tuple[int, dict[str, int]]],
) -> tuple[ReceiptClassification, int | None]:
    # Índice derivado apenas de recibos já conferidos nesta transação. Não é cache
    # de autoridade e não sobrevive à operação. Igualdade usa bytes, não só hash.
    if _external_scope(raw.scope) != scope:
        return ReceiptClassification.FOREIGN_SCOPE, None
    key = _source_key(raw)
    payload = encode_contract(raw)
    same = index.get(key)
    if same is None:
        index[key] = (sequence, {payload: sequence})
        return ReceiptClassification.RECEIVED, None
    original_sequence, variants = same
    identical = variants.get(payload)
    if identical is not None:
        return ReceiptClassification.DUPLICATE_IDENTICAL, identical
    variants[payload] = sequence
    return ReceiptClassification.DUPLICATE_CONFLICTING, original_sequence


def _tape(
    scope: OperationalScope, receipts: tuple[DurableRawReceipt, ...], plan: OfflineSellReplayPlan
) -> tuple[OfflineSellTape, tuple[int, ...]]:
    if _external_scope(plan.query.identity) != scope:
        raise PersistenceError(_E.SCOPE_MISMATCH, "plano de replay de outro escopo")
    target = plan.query.identity
    selected = tuple(
        r
        for r in receipts
        if (
            _external_scope(r.raw.scope) == scope
            and r.raw.scope.order_ref == target.order_ref
            and r.raw.scope.execution_ref == target.execution_ref
            and r.raw.scope.cycle_ref == target.cycle_ref
        )
    )
    return OfflineSellTape(tuple(r.raw for r in selected)), tuple(r.sequence for r in selected)


def _sql_error(exc: sqlite3.Error) -> PersistenceError:
    code = getattr(exc, "sqlite_errorcode", 0) & 255
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return PersistenceError(_E.BUSY, "bloqueio SQLite; nenhuma decisão repetida")
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CONSTRAINT):
        return PersistenceError(_E.CORRUPT_DATABASE, "estrutura SQLite inválida")
    return PersistenceError(_E.IO_ERROR, "operação SQLite falhou")


def _validate_timeout(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 5000:
        raise PersistenceError(_E.INVALID_STATE, "busy timeout deve ser 0..5000 ms")


@dataclass(frozen=True, slots=True)
class JournalRecovery:
    state: VersionedOperationalState
    receipts: tuple[DurableRawReceipt, ...]
    replays: tuple[DurableReplayRecord, ...]


@dataclass(frozen=True, slots=True)
class SQLiteOperationalJournal:
    """Conexão por operação; sessões SQLite não são compartilhadas entre threads.

    Novas transações revalidam o histórico em uma visão consistente. Revisão inclui
    evidências/replay: uma captura concorrente também invalida decisão financeira stale.
    Nenhuma API salva livremente um snapshot financeiro recebido do chamador.
    """

    policy: JournalPathPolicy
    file_identity: tuple[int, int]
    busy_timeout_ms: int = 500

    def __post_init__(self) -> None:
        _validate_timeout(self.busy_timeout_ms)
        self._path()

    @classmethod
    def create(
        cls, policy: JournalPathPolicy, *, busy_timeout_ms: int = 500
    ) -> SQLiteOperationalJournal:
        """Criação exclusiva explícita. Falha não apaga arquivo parcial para investigação."""
        _validate_timeout(busy_timeout_ms)
        path = policy.database_path()
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError as exc:
            raise PersistenceError(
                _E.DUPLICATE_SCOPE, "banco já existe; abrir explicitamente"
            ) from exc
        except OSError as exc:
            raise PersistenceError(_E.IO_ERROR, "não foi possível criar banco") from exc
        details = path.stat()
        store = cls(policy, (details.st_dev, details.st_ino), busy_timeout_ms)
        try:
            with closing(store._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for _, sql in _SCHEMA.values():
                        connection.execute(sql)
                    connection.execute("INSERT INTO meta VALUES (1,1,1)")
                    connection.execute("PRAGMA user_version=1")
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise _sql_error(exc) from exc
        store.verify_journal_integrity()
        return store

    @classmethod
    def open(
        cls, policy: JournalPathPolicy, *, busy_timeout_ms: int = 500
    ) -> SQLiteOperationalJournal:
        _validate_timeout(busy_timeout_ms)
        path = policy.database_path()
        try:
            details = path.stat()
        except FileNotFoundError as exc:
            raise PersistenceError(
                _E.NOT_FOUND, "banco ausente; nenhum bootstrap automático"
            ) from exc
        except OSError as exc:
            raise PersistenceError(_E.IO_ERROR, "banco inacessível") from exc
        if details.st_size == 0:
            raise PersistenceError(
                _E.EMPTY_DATABASE, "arquivo vazio; não inicializar silenciosamente"
            )
        store = cls(policy, (details.st_dev, details.st_ino), busy_timeout_ms)
        store.verify_journal_integrity()
        return store

    def _path(self) -> Path:
        path = self.policy.database_path()
        try:
            details = path.stat()
        except FileNotFoundError as exc:
            raise PersistenceError(_E.NOT_FOUND, "banco removido; não recriar") from exc
        if (details.st_dev, details.st_ino) != self.file_identity:
            raise PersistenceError(_E.PATH_UNSAFE, "arquivo substituído desde a abertura")
        return path

    def _connect(self) -> sqlite3.Connection:
        path = self._path()
        connection = sqlite3.connect(
            path.as_uri() + "?mode=rw",
            uri=True,
            timeout=self.busy_timeout_ms / 1000,
            autocommit=True,
        )
        try:
            self._path()
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=EXTRA")
            connection.execute("PRAGMA trusted_schema=OFF")
            if (
                connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
                or connection.execute("PRAGMA synchronous").fetchone() != (3,)
                or connection.execute("PRAGMA journal_mode").fetchone() != ("delete",)
            ):
                raise PersistenceError(
                    _E.UNKNOWN_SCHEMA, "configuração de durabilidade incompatível"
                )
        except BaseException:
            connection.close()
            raise
        return connection

    def _checkpoint(self, point: str) -> None:
        """Pontos determinísticos substituídos somente em subprocessos/testes isolados."""

    @contextmanager
    def _session(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        committed = False
        outcome_uncertain = False
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            self._checkpoint("before_transaction")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._checkpoint("after_begin")
            self._schema(connection)
            yield connection
            if write:
                self._checkpoint("before_commit")
                try:
                    outcome_uncertain = True
                    connection.execute("COMMIT")
                except sqlite3.Error as exc:
                    raise PersistenceError(
                        _E.COMMIT_UNCERTAIN, "commit não confirmado; recuperar antes de decidir"
                    ) from exc
                committed = True
                self._checkpoint("after_commit")
            else:
                connection.execute("ROLLBACK")
        except BaseException as exc:
            if connection is not None and connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error as rollback_error:
                    outcome_uncertain = True
                    raise PersistenceError(
                        _E.COMMIT_UNCERTAIN, "rollback não confirmado; recuperar"
                    ) from rollback_error
            if committed and isinstance(exc, Exception):
                raise PersistenceError(
                    _E.COMMIT_UNCERTAIN, "commit confirmado, resposta interrompida; recuperar"
                ) from exc
            if isinstance(exc, sqlite3.Error):
                raise _sql_error(exc) from exc
            if isinstance(exc, OSError):
                raise PersistenceError(_E.IO_ERROR, "operação de arquivo falhou") from exc
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError) as close_error:
                    raise PersistenceError(
                        _E.COMMIT_UNCERTAIN if outcome_uncertain or committed else _E.IO_ERROR,
                        "fechamento não confirmado; recuperar antes de decidir",
                    ) from close_error

    def _schema(self, connection: sqlite3.Connection) -> None:
        self._checkpoint("during_integrity")
        if connection.execute("PRAGMA user_version").fetchone() != (1,):
            raise PersistenceError(
                _E.UNKNOWN_SCHEMA, "schema desconhecido/parcial; migração explícita requerida"
            )
        actual = {
            name: (kind, sql)
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != _SCHEMA:
            raise PersistenceError(_E.UNKNOWN_SCHEMA, "DDL diferente do schema conhecido")
        if connection.execute("SELECT * FROM meta").fetchall() != [(1, 1, 1)]:
            raise PersistenceError(_E.UNKNOWN_SCHEMA, "versão de contratos incompatível")
        if (
            connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise PersistenceError(_E.CORRUPT_DATABASE, "integridade SQLite inválida")

    def _read(self, connection: sqlite3.Connection, scope: OperationalScope) -> JournalRecovery:
        self._checkpoint("during_read")
        key = _scope_key(scope)
        head = connection.execute(
            "SELECT scope_payload,revision,last_sequence,tip_hash FROM heads WHERE scope_key=?",
            (key,),
        ).fetchone()
        if head is None:
            raise PersistenceError(_E.NOT_FOUND, "escopo sem autoridade persistida")
        scope_text, head_revision, head_sequence, head_hash = head
        if scope_text != encode_contract(scope):
            raise PersistenceError(_E.CORRUPT_DATABASE, "escopo/head incompatível")
        revisions = connection.execute(
            (
                "SELECT revision,state_digest,last_sequence,tip_hash FROM revisions WHE"
                "RE scope_key=? ORDER BY revision"
            ),
            (key,),
        ).fetchall()
        entries = connection.execute(
            (
                "SELECT sequence,revision,kind,payload,previous_hash,digest,source_key "
                "FROM entries WHERE scope_key=? ORDER BY sequence"
            ),
            (key,),
        ).fetchall()
        if (
            not revisions
            or len(revisions) != head_revision + 1
            or any(row[0] != index for index, row in enumerate(revisions))
        ):
            raise PersistenceError(_E.CORRUPT_DATABASE, "sequência de revisões quebrada")
        if len(entries) != head_sequence or any(
            row[0] != index for index, row in enumerate(entries, start=1)
        ):
            raise PersistenceError(_E.CORRUPT_DATABASE, "sequência de journal quebrada")
        snapshots: dict[str, GridOperationalBook] = {}
        for _, state_digest, _, _ in revisions:
            if state_digest in snapshots:
                continue
            row = connection.execute(
                "SELECT payload FROM states WHERE digest=?", (state_digest,)
            ).fetchone()
            if row is None or _hash(row[0]) != state_digest:
                raise PersistenceError(_E.CORRUPT_DATABASE, "snapshot/hash ausente ou divergente")
            book = decode_contract(row[0])
            if type(book) is not GridOperationalBook or encode_contract(book) != row[0]:
                raise PersistenceError(_E.INVALID_STATE, "snapshot parcial/tipo não canônico")
            VersionedOperationalState(scope, 0, book)
            snapshots[state_digest] = book
        receipts: list[DurableRawReceipt] = []
        raw_index: dict[str, tuple[int, dict[str, int]]] = {}
        replays: list[DurableReplayRecord] = []
        previous_hash = _ZERO_HASH
        previous_state: GridOperationalBook | None = None
        entry_index = 0
        for revision, state_digest, last_sequence, tip_hash in revisions:
            book = snapshots[state_digest]
            events = []
            while entry_index < len(entries) and entries[entry_index][1] == revision:
                row = entries[entry_index]
                sequence, _, kind, payload, parent_hash, digest, source_key = row
                if parent_hash != previous_hash or digest != _hash(
                    encode_contract(
                        (key, sequence, revision, kind, payload, parent_hash, source_key)
                    )
                ):
                    raise PersistenceError(_E.CORRUPT_DATABASE, "cadeia de hashes inválida")
                event = decode_contract(payload)
                if encode_contract(event) != payload:
                    raise PersistenceError(_E.INVALID_STATE, "evento não canônico")
                events.append((kind, event, sequence, source_key))
                previous_hash = digest
                entry_index += 1
            if (
                not events
                or last_sequence != entries[entry_index - 1][0]
                or tip_hash != previous_hash
            ):
                raise PersistenceError(_E.CORRUPT_DATABASE, "revisão sem commit completo")
            if revision == 0:
                if (
                    len(events) != 1
                    or events[0][0] != "BOOTSTRAP"
                    or events[0][1] != scope
                    or events[0][3] is not None
                ):
                    raise PersistenceError(_E.CORRUPT_DATABASE, "bootstrap inválido")
                validate_pristine_bootstrap(book)
            else:
                if previous_state is None:
                    raise PersistenceError(_E.CORRUPT_DATABASE, "pai financeiro ausente")
                expected_book = previous_state
                for kind, event, sequence, source_key in events:
                    if kind == "TRANSITION":
                        if type(event).__name__ not in _TRANSITIONS or source_key is not None:
                            raise PersistenceError(
                                _E.INVALID_STATE, "comando histórico desconhecido"
                            )
                        try:
                            expected_book = apply_operational_transition(
                                expected_book, cast(OperationalTransition, event)
                            )
                        except PersistenceError:
                            raise
                        except DomainError as transition_error:
                            raise PersistenceError(
                                _E.CORRUPT_DATABASE, "comando histórico incompatível com a raiz"
                            ) from transition_error
                    elif kind == "RAW":
                        if (
                            type(event) is not DurableRawReceipt
                            or event.sequence != sequence
                            or event.revision != revision
                        ):
                            raise PersistenceError(
                                _E.INVALID_STATE, "recibo/seq/revisão incompatível"
                            )
                        classification, duplicate = _classification(
                            scope, event.raw, sequence, raw_index
                        )
                        if (event.classification, event.duplicate_of) != (
                            classification,
                            duplicate,
                        ) or source_key != _source_key(event.raw):
                            raise PersistenceError(
                                _E.CORRUPT_DATABASE, "índice/classificação raw incompatível"
                            )
                        receipts.append(event)
                    elif kind == "REPLAY":
                        if (
                            type(event) is not DurableReplayRecord
                            or event.input_revision != revision - 1
                            or source_key is not None
                        ):
                            raise PersistenceError(
                                _E.INVALID_STATE, "projeção/revisão incompatível"
                            )
                        self._checkpoint("during_replay")
                        tape, sequences = _tape(scope, tuple(receipts), event.plan)
                        projection = replay_sell_observations(
                            expected_book, tape, event.plan
                        ).projection
                        if encode_contract(event) != encode_contract(
                            replay_record(event.plan, revision - 1, sequences, projection)
                        ):
                            raise PersistenceError(
                                _E.CORRUPT_DATABASE, "projeção/quarentena divergente do raw"
                            )
                        replays.append(event)
                    else:
                        raise PersistenceError(_E.INVALID_STATE, "evento desconhecido na revisão")
                if encode_contract(expected_book) != encode_contract(book):
                    raise PersistenceError(
                        _E.CORRUPT_DATABASE, "snapshot diverge da transição autorizada"
                    )
            previous_state = book
        if (
            entry_index != len(entries)
            or previous_hash != head_hash
            or revisions[-1][2:] != (head_sequence, head_hash)
        ):
            raise PersistenceError(_E.CORRUPT_DATABASE, "head/journal/revisão divergente")
        return JournalRecovery(
            VersionedOperationalState(scope, head_revision, snapshots[revisions[-1][1]]),
            tuple(receipts),
            tuple(replays),
        )

    def _persist(
        self,
        connection: sqlite3.Connection,
        scope: OperationalScope,
        book: GridOperationalBook,
        expected_revision: int | None,
        events: tuple[tuple[str, object, str | None], ...],
    ) -> VersionedOperationalState:
        key = _scope_key(scope)
        head = connection.execute(
            "SELECT revision,last_sequence,tip_hash FROM heads WHERE scope_key=?", (key,)
        ).fetchone()
        if expected_revision is None:
            if head is not None:
                raise PersistenceError(_E.DUPLICATE_SCOPE, "autoridade já inicializada")
            revision, sequence, previous_hash = 0, 0, _ZERO_HASH
        else:
            require_revision(expected_revision)
            if head is None or head[0] != expected_revision:
                raise PersistenceError(_E.REVISION_CONFLICT, "revisão stale; reavaliar sem retry")
            revision, sequence, previous_hash = expected_revision + 1, head[1], head[2]
        state = VersionedOperationalState(
            scope, revision, revalidate_contract(book, GridOperationalBook)
        )
        state_payload = encode_contract(state.book)
        state_digest = _hash(state_payload)
        self._checkpoint("after_snapshot_prepared")
        connection.execute(
            "INSERT OR IGNORE INTO states VALUES (?,?)", (state_digest, state_payload)
        )
        self._checkpoint("after_snapshot_written")
        if connection.execute(
            "SELECT payload FROM states WHERE digest=?", (state_digest,)
        ).fetchone() != (state_payload,):
            raise PersistenceError(_E.CORRUPT_DATABASE, "digest de snapshot conflitante")
        rows = []
        for kind, event, source in events:
            sequence += 1
            payload = encode_contract(event)
            digest = _hash(
                encode_contract((key, sequence, revision, kind, payload, previous_hash, source))
            )
            rows.append((key, sequence, revision, kind, payload, previous_hash, digest, source))
            previous_hash = digest
        if not rows:
            raise PersistenceError(_E.INVALID_STATE, "commit exige evento")
        if expected_revision is None:
            connection.execute(
                "INSERT INTO heads VALUES (?,?,?,?,?)",
                (key, encode_contract(scope), revision, sequence, previous_hash),
            )
        connection.execute(
            "INSERT INTO revisions VALUES (?,?,?,?,?)",
            (key, revision, state_digest, sequence, previous_hash),
        )
        connection.executemany("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)", rows)
        self._checkpoint("after_event")
        if expected_revision is not None:
            cursor = connection.execute(
                (
                    "UPDATE heads SET revision=?,last_sequence=?,tip_hash=? WHERE scope_key"
                    "=? AND revision=?"
                ),
                (revision, sequence, previous_hash, key, expected_revision),
            )
            if cursor.rowcount != 1:
                raise PersistenceError(_E.REVISION_CONFLICT, "CAS não atualizou uma autoridade")
        self._checkpoint("after_cas")
        return state

    def initialize_scope(
        self, scope: OperationalScope, pristine_book: GridOperationalBook
    ) -> VersionedOperationalState:
        scope = revalidate_contract(scope, OperationalScope)
        book = revalidate_contract(pristine_book, GridOperationalBook)
        validate_pristine_bootstrap(book)
        with self._session(write=True) as connection:
            result = self._persist(connection, scope, book, None, (("BOOTSTRAP", scope, None),))
        return result

    def recover(self, scope: OperationalScope) -> JournalRecovery:
        scope = revalidate_contract(scope, OperationalScope)
        with self._session(write=False) as connection:
            result = self._read(connection, scope)
        return result

    def load_operational_state(self, scope: OperationalScope) -> VersionedOperationalState:
        return self.recover(scope).state

    def commit_operational_transition(
        self,
        scope: OperationalScope,
        expected_revision: int,
        transition: OperationalTransition,
        evidence_entries: tuple[RawSellObservation, ...] = (),
    ) -> VersionedOperationalState:
        require_revision(expected_revision)
        scope = revalidate_contract(scope, OperationalScope)
        command = decode_contract(encode_contract(transition))
        if type(command).__name__ not in _TRANSITIONS:
            raise PersistenceError(_E.INVALID_STATE, "nenhum save de snapshot arbitrário")
        with self._session(write=True) as connection:
            recovery = self._read(connection, scope)
            if recovery.state.revision != expected_revision:
                raise PersistenceError(
                    _E.REVISION_CONFLICT, "revisão stale; nenhuma decisão repetida"
                )
            book = apply_operational_transition(
                recovery.state.book, cast(OperationalTransition, command)
            )
            head = connection.execute(
                "SELECT last_sequence FROM heads WHERE scope_key=?", (_scope_key(scope),)
            ).fetchone()
            if head is None:
                raise PersistenceError(_E.CORRUPT_DATABASE, "head ausente")
            rows = self._raw_events(recovery, evidence_entries, first_offset=head[0] + 2)
            result = self._persist(
                connection, scope, book, expected_revision, (("TRANSITION", command, None), *rows)
            )
        return result

    def _raw_events(
        self,
        recovery: JournalRecovery,
        observations: tuple[RawSellObservation, ...],
        *,
        first_offset: int,
    ) -> tuple[tuple[str, object, str | None], ...]:
        if type(observations) is not tuple or len(observations) > 1000:
            raise PersistenceError(_E.LIMIT_EXCEEDED, "captura exige tuple de até 1000 recibos")
        # Sequência local inclui também commits/replays; não usar número de recibos.
        scope = recovery.state.scope
        raw_index: dict[str, tuple[int, dict[str, int]]] = {}
        for receipt in recovery.receipts:
            _classification(scope, receipt.raw, receipt.sequence, raw_index)
        result = []
        # O chamador fornece a sequência head da MESMA transação abaixo.
        for raw in observations:
            checked = revalidate_contract(raw, RawSellObservation)
            if _SENSITIVE.search(checked.payload):
                raise PersistenceError(
                    _E.SENSITIVE_INPUT, "entrada contém marcador de credencial; não persistir"
                )
            classification, duplicate = _classification(scope, checked, first_offset, raw_index)
            receipt = DurableRawReceipt(
                first_offset, recovery.state.revision + 1, checked, classification, duplicate
            )
            result.append(("RAW", receipt, _source_key(checked)))
            first_offset += 1
        return tuple(result)

    def append_raw_observations(
        self,
        scope: OperationalScope,
        expected_revision: int,
        observations: tuple[RawSellObservation, ...],
    ) -> VersionedOperationalState:
        require_revision(expected_revision)
        scope = revalidate_contract(scope, OperationalScope)
        with self._session(write=True) as connection:
            recovery = self._read(connection, scope)
            if recovery.state.revision != expected_revision:
                raise PersistenceError(_E.REVISION_CONFLICT, "captura stale; reavaliar")
            head = connection.execute(
                "SELECT last_sequence FROM heads WHERE scope_key=?", (_scope_key(scope),)
            ).fetchone()
            if head is None:
                raise PersistenceError(_E.CORRUPT_DATABASE, "head ausente")
            rows = self._raw_events(recovery, observations, first_offset=head[0] + 1)
            result = self._persist(connection, scope, recovery.state.book, expected_revision, rows)
        return result

    def append_raw_observation(
        self,
        scope: OperationalScope,
        expected_revision: int,
        observation: RawSellObservation,
    ) -> VersionedOperationalState:
        return self.append_raw_observations(scope, expected_revision, (observation,))

    def replay_observations(
        self, scope: OperationalScope, plan: OfflineSellReplayPlan
    ) -> OfflineSellReplay:
        recovery = self.recover(scope)
        plan = revalidate_contract(plan, OfflineSellReplayPlan)
        tape, _ = _tape(scope, recovery.receipts, plan)
        return replay_sell_observations(recovery.state.book, tape, plan)

    def receipts_for_order(
        self, scope: OperationalScope, identity: SellOrderIdentity
    ) -> tuple[DurableRawReceipt, ...]:
        """Busca por chave composta; client ID não é chave global de ordem."""
        recovery = self.recover(scope)
        identity = revalidate_contract(identity, SellOrderIdentity)
        if _external_scope(identity) != scope:
            raise PersistenceError(_E.SCOPE_MISMATCH, "busca de outra conta/ambiente")
        return tuple(
            receipt
            for receipt in recovery.receipts
            if _external_scope(receipt.raw.scope) == scope
            and receipt.raw.scope.order_ref == identity.order_ref
        )

    def record_replay(
        self, scope: OperationalScope, expected_revision: int, plan: OfflineSellReplayPlan
    ) -> VersionedOperationalState:
        require_revision(expected_revision)
        scope = revalidate_contract(scope, OperationalScope)
        plan = revalidate_contract(plan, OfflineSellReplayPlan)
        with self._session(write=True) as connection:
            recovery = self._read(connection, scope)
            if recovery.state.revision != expected_revision:
                raise PersistenceError(_E.REVISION_CONFLICT, "replay de revisão stale")
            self._checkpoint("during_replay")
            tape, sequences = _tape(scope, recovery.receipts, plan)
            projection = replay_sell_observations(recovery.state.book, tape, plan).projection
            record = replay_record(plan, expected_revision, sequences, projection)
            result = self._persist(
                connection,
                scope,
                recovery.state.book,
                expected_revision,
                (("REPLAY", record, None),),
            )
        return result

    def reconcile_sell_terminal(
        self, scope: OperationalScope, expected_revision: int, plan: OfflineSellReplayPlan
    ) -> SellTerminalReconciliation:
        """Derivação read-only na revisão exata, sem schema novo ou efeito financeiro."""
        require_revision(expected_revision)
        scope = revalidate_contract(scope, OperationalScope)
        plan = revalidate_contract(plan, OfflineSellReplayPlan)
        with self._session(write=False) as connection:
            recovery = self._read(connection, scope)
            if recovery.state.revision != expected_revision:
                raise PersistenceError(_E.REVISION_CONFLICT, "reconciliação de revisão stale")
            tape, sequences = _tape(scope, recovery.receipts, plan)
            replay = replay_sell_observations(recovery.state.book, tape, plan)
            result = reconcile_offline_sell_terminal(
                replay, journal_reference=SellJournalReference(scope, expected_revision, sequences)
            )
        return result

    def verify_journal_integrity(self) -> None:
        with self._session(write=False) as connection:
            referenced: set[str] = set()
            for scope_key, scope_payload in connection.execute(
                "SELECT scope_key,scope_payload FROM heads ORDER BY scope_key"
            ):
                scope = decode_contract(scope_payload)
                if type(scope) is not OperationalScope or _scope_key(scope) != scope_key:
                    raise PersistenceError(_E.CORRUPT_DATABASE, "escopo alterado")
                self._read(connection, scope)
                referenced.update(
                    row[0]
                    for row in connection.execute(
                        "SELECT state_digest FROM revisions WHERE scope_key=?", (scope_key,)
                    )
                )
            actual = {row[0] for row in connection.execute("SELECT digest FROM states")}
            if actual != referenced:
                raise PersistenceError(_E.CORRUPT_DATABASE, "snapshot órfão/desconhecido")
