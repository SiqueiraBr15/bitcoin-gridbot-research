"""Dedicated PAPER journal: isolated schema/file, source events, CAS and atomic append."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gridbot.application.operational_persistence import require_revision
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import PaperBook, PaperCommand, paper_transition
from gridbot.storage.journal_paths import JournalPathPolicy, _check_node
from gridbot.storage.paper_codec import (
    MARKER,
    MAX_TEXT,
    decode_command,
    decode_initial,
    encode_command,
    encode_initial,
    text_bytes,
)

MAX_EVENTS = 256
MAX_HISTORY_BYTES = 16_000_000
TABLES = (
    "CREATE TABLE paper_meta (id INTEGER PRIMARY KEY CHECK(id=1), marker TEXT NOT NULL, "
    "initial TEXT NOT NULL, digest TEXT NOT NULL)",
    "CREATE TABLE paper_events (sequence INTEGER PRIMARY KEY CHECK(sequence>0), "
    "payload TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL)",
    "CREATE TRIGGER paper_meta_no_update BEFORE UPDATE ON paper_meta "
    "BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER paper_meta_no_delete BEFORE DELETE ON paper_meta "
    "BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER paper_events_no_update BEFORE UPDATE ON paper_events "
    "BEGIN SELECT RAISE(ABORT,'append only'); END",
    "CREATE TRIGGER paper_events_no_delete BEFORE DELETE ON paper_events "
    "BEGIN SELECT RAISE(ABORT,'append only'); END",
)


class PaperPersistenceCode(StrEnum):
    UNSAFE_PATH = "UNSAFE_PATH"
    EXISTS = "EXISTS"
    FOREIGN_DATABASE = "FOREIGN_DATABASE"
    CORRUPT_DATABASE = "CORRUPT_DATABASE"
    COMMIT_UNCERTAIN = "COMMIT_UNCERTAIN"
    IO_ERROR = "IO_ERROR"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class PaperPersistenceError(DomainError):
    def __init__(self, code: PaperPersistenceCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def _before_commit(connection: sqlite3.Connection) -> None:
    """Private boundary for bounded crash tests; never a caller supplied callback."""


def _commit(connection: sqlite3.Connection) -> None:
    connection.execute("COMMIT")


def _after_commit(connection: sqlite3.Connection) -> None:
    """Private response boundary; a failure after COMMIT is uncertain."""


def _close(connection: sqlite3.Connection) -> None:
    connection.close()


@dataclass(frozen=True, slots=True)
class PaperJournal:
    directory: Path
    file_identity: tuple[int, int]

    @staticmethod
    def _path(directory: Path) -> Path:
        # Reuse only filesystem checks, never the operational state port or database.
        policy = JournalPathPolicy(directory)
        production_path = policy.database_path()
        if production_path.exists():
            raise PaperPersistenceError(
                PaperPersistenceCode.UNSAFE_PATH,
                "PAPER needs a directory without production authority",
            )
        path = directory / "gridbot-paper.sqlite3"
        for suffix in ("", "-journal", "-wal", "-shm"):
            _check_node(path.with_name(path.name + suffix), directory=False, optional=True)
        if any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm")):
            raise PaperPersistenceError(PaperPersistenceCode.UNSAFE_PATH, "PAPER WAL/SHM forbidden")
        return path

    @classmethod
    def create(cls, directory: Path, book: PaperBook) -> PaperJournal:
        if type(book) is not PaperBook or book.entries:
            raise PaperPersistenceError(
                PaperPersistenceCode.FOREIGN_DATABASE, "initial PAPER book only"
            )
        book._frame()
        path = cls._path(directory)
        try:
            path.touch(exist_ok=False)
        except FileExistsError as exc:
            raise PaperPersistenceError(
                PaperPersistenceCode.EXISTS, "PAPER destination occupied"
            ) from exc
        connection = sqlite3.connect(path, isolation_level=None, timeout=2)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=EXTRA")
            connection.execute("BEGIN IMMEDIATE")
            for ddl in TABLES:
                connection.execute(ddl)
            initial = encode_initial(book.initial)
            connection.execute(
                "INSERT INTO paper_meta VALUES(1,?,?,?)", (MARKER, initial, _hash(initial))
            )
            connection.execute("COMMIT")
        finally:
            connection.close()
        return cls.open(directory)

    @classmethod
    def open(cls, directory: Path) -> PaperJournal:
        path = cls._path(directory)
        if not path.is_file():
            raise PaperPersistenceError(
                PaperPersistenceCode.FOREIGN_DATABASE, "PAPER database absent"
            )
        details = path.stat()
        result = cls(directory, (details.st_dev, details.st_ino))
        result.recover()
        return result

    def _connect(self, *, write: bool) -> sqlite3.Connection:
        path = self._path(self.directory)
        details = path.stat()
        if (details.st_dev, details.st_ino) != self.file_identity:
            raise PaperPersistenceError(PaperPersistenceCode.UNSAFE_PATH, "PAPER file replaced")
        mode = "rw" if write else "ro"
        connection = sqlite3.connect(
            path.as_uri() + "?mode=" + mode, uri=True, isolation_level=None, timeout=2
        )
        return connection

    def _read(self, connection: sqlite3.Connection) -> tuple[PaperBook, str]:
        try:
            schema = {
                r[0]
                for r in connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            if schema != set(TABLES):
                raise PaperPersistenceError(
                    PaperPersistenceCode.FOREIGN_DATABASE, "non-PAPER schema"
                )
            meta = connection.execute("SELECT id,marker,initial,digest FROM paper_meta").fetchall()
            if len(meta) != 1 or meta[0][0] != 1 or meta[0][1] != MARKER:
                raise PaperPersistenceError(
                    PaperPersistenceCode.FOREIGN_DATABASE, "PAPER marker missing"
                )
            text, previous = meta[0][2:]
            if type(text) is not str or len(text) > MAX_TEXT or _hash(text) != previous:
                raise PaperPersistenceError(
                    PaperPersistenceCode.CORRUPT_DATABASE, "initial digest/size"
                )
            book = PaperBook(decode_initial(text))
            count, total_bytes = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM paper_events"
            ).fetchone()
            if count > MAX_EVENTS or total_bytes + text_bytes(text) > MAX_HISTORY_BYTES:
                raise PaperPersistenceError(
                    PaperPersistenceCode.CORRUPT_DATABASE, "PAPER resource bound"
                )
            rows = connection.execute(
                "SELECT sequence,payload,previous,digest FROM paper_events "
                "ORDER BY sequence LIMIT ?",
                (MAX_EVENTS + 1,),
            ).fetchall()
            if len(rows) > MAX_EVENTS:
                raise PaperPersistenceError(
                    PaperPersistenceCode.CORRUPT_DATABASE, "PAPER event bound"
                )
            events = []
            for expected, (sequence, payload, prior, digest) in enumerate(rows, 1):
                if (
                    type(sequence) is not int
                    or sequence != expected
                    or type(payload) is not str
                    or len(payload) > MAX_TEXT
                    or prior != previous
                    or digest != _hash(str(sequence) + "\n" + prior + "\n" + payload)
                ):
                    raise PaperPersistenceError(
                        PaperPersistenceCode.CORRUPT_DATABASE, "PAPER event chain"
                    )
                events.append(decode_command(payload))
                previous = digest
            # Revalidate the entire authorized source history, no financial cache trusted.
            return PaperBook(book.initial, tuple(events)), previous
        except PaperPersistenceError:
            raise
        except (
            sqlite3.Error,
            DomainError,
            ValueError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            raise PaperPersistenceError(
                PaperPersistenceCode.CORRUPT_DATABASE, "invalid PAPER history"
            ) from exc

    def recover(self) -> PaperBook:
        # SQLite may need to roll back a hot PAPER journal after a process crash.
        connection = self._connect(write=True)
        try:
            connection.execute("BEGIN")
            book, _ = self._read(connection)
            return book
        finally:
            connection.close()

    def commit(self, expected_revision: int, command: PaperCommand) -> PaperBook:
        require_revision(expected_revision)
        connection = self._connect(write=True)
        committed = False
        commit_started = False
        try:
            # Verify marker/schema before any PRAGMA that could change a foreign file.
            self._read(connection)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=EXTRA")
            connection.execute("BEGIN IMMEDIATE")
            book, previous = self._read(connection)
            updated = paper_transition(book, expected_revision, command)
            if updated is book:
                connection.execute("ROLLBACK")
                return book
            if len(updated.entries) > MAX_EVENTS:
                raise PaperPersistenceError(
                    PaperPersistenceCode.CAPACITY_EXCEEDED, "PAPER history full; no event appended"
                )
            payload = encode_command(command)
            current_bytes = connection.execute(
                "SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM paper_events"
            ).fetchone()[0]
            initial_bytes = connection.execute(
                "SELECT length(CAST(initial AS BLOB)) FROM paper_meta"
            ).fetchone()[0]
            if current_bytes + initial_bytes + text_bytes(payload) > MAX_HISTORY_BYTES:
                raise PaperPersistenceError(
                    PaperPersistenceCode.CAPACITY_EXCEEDED, "PAPER UTF-8 history full"
                )
            sequence = len(updated.entries)
            digest = _hash(str(sequence) + "\n" + previous + "\n" + payload)
            connection.execute(
                "INSERT INTO paper_events VALUES(?,?,?,?)", (sequence, payload, previous, digest)
            )
            _before_commit(connection)
            commit_started = True
            _commit(connection)
            committed = True
            _after_commit(connection)
            return updated
        except BaseException as exc:
            if committed or (commit_started and not connection.in_transaction):
                raise PaperPersistenceError(
                    PaperPersistenceCode.COMMIT_UNCERTAIN, "recover PAPER before retry"
                ) from exc
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            try:
                _close(connection)
            except Exception as exc:
                if committed:
                    raise PaperPersistenceError(
                        PaperPersistenceCode.COMMIT_UNCERTAIN, "PAPER close after commit; recover"
                    ) from exc
                raise
