"""Verificação de acesso ao SQLite. Repositórios e schema entram na Fase A (ADR-003)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SqliteProbe:
    ok: bool
    detail: str


def probe_sqlite(db_path: Path) -> SqliteProbe:
    """Verifica o banco sem alterá-lo.

    - banco existente: abre somente leitura e roda ``PRAGMA quick_check``;
    - banco inexistente: grava e apaga um banco temporário no mesmo diretório.
    """
    if db_path.exists():
        return _check_existing(db_path)
    return _check_writable_dir(db_path.parent)


def _check_existing(db_path: Path) -> SqliteProbe:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        return SqliteProbe(False, f"falha ao abrir {db_path}: {exc}")
    if row is not None and row[0] == "ok":
        return SqliteProbe(True, f"{db_path} íntegro (quick_check=ok)")
    return SqliteProbe(False, f"{db_path} com problema (quick_check={row!r})")


def _check_writable_dir(directory: Path) -> SqliteProbe:
    if not directory.is_dir():
        return SqliteProbe(False, f"diretório do banco não existe: {directory}")
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".gridbot-probe-", suffix=".sqlite3", dir=directory)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with closing(sqlite3.connect(tmp)) as conn:
                conn.execute("CREATE TABLE probe (v TEXT NOT NULL)")
                conn.execute("INSERT INTO probe (v) VALUES ('ok')")
                conn.commit()
                row = conn.execute("SELECT v FROM probe").fetchone()
        finally:
            tmp.unlink(missing_ok=True)
    except (OSError, sqlite3.Error) as exc:
        return SqliteProbe(False, f"SQLite não consegue gravar em {directory}: {exc}")
    if row != ("ok",):
        return SqliteProbe(False, f"SQLite leu valor inesperado em {directory}: {row!r}")
    return SqliteProbe(
        True,
        f"banco ainda não criado; SQLite {sqlite3.sqlite_version} grava/lê em {directory}",
    )
