"""Destino explícito local; nenhuma observação escolhe o caminho do banco."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.infra.locations import LocationRisk, assess_location


@dataclass(frozen=True, slots=True)
class JournalPathPolicy:
    """Diretório permitido fornecido pelo operador, sem default/CWD/env implícito.

    Reparse points/hardlinks são recusados também nos sidecars. Inspeção anterior
    ao uso não oferece isolamento contra troca hostil concorrente pelo mesmo usuário.
    ACL/backup externo protegido continuam requisitos operacionais futuros.
    """

    directory: Path
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.directory, Path) or not self.directory.is_absolute():
            raise PersistenceError(PersistenceErrorCode.PATH_UNSAFE, "diretório absoluto requerido")
        if type(self.environment) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or any(type(part) is not str for part in item)
            for item in self.environment
        ):
            raise PersistenceError(
                PersistenceErrorCode.PATH_UNSAFE, "environment explícito inválido"
            )
        if len(dict(self.environment)) != len(self.environment):
            raise PersistenceError(PersistenceErrorCode.PATH_UNSAFE, "environment repetido")
        self.database_path()

    def database_path(self) -> Path:
        try:
            lexical = self.directory
            if (
                ".." in lexical.parts
                or assess_location(lexical, dict(self.environment)).risk is not LocationRisk.LOCAL
            ):
                raise PersistenceError(PersistenceErrorCode.PATH_UNSAFE, "destino não local/normal")
            for ancestor in (*reversed(lexical.parents), lexical):
                _check_node(ancestor, directory=True, optional=False)
            resolved = lexical.resolve(strict=True)
            if (
                resolved != lexical
                or assess_location(resolved, dict(self.environment)).risk is not LocationRisk.LOCAL
            ):
                raise PersistenceError(PersistenceErrorCode.PATH_UNSAFE, "destino real divergente")
            database = resolved / "gridbot-state.sqlite3"
            for suffix in ("", "-journal", "-wal", "-shm"):
                _check_node(
                    database.with_name(database.name + suffix), directory=False, optional=True
                )
            if any(
                database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm")
            ):
                raise PersistenceError(
                    PersistenceErrorCode.PATH_UNSAFE, "sidecar de modo não autorizado"
                )
            return database
        except OSError as exc:
            raise PersistenceError(PersistenceErrorCode.PATH_UNSAFE, "destino inacessível") from exc


def _check_node(path: Path, *, directory: bool, optional: bool) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        if optional:
            return
        raise PersistenceError(
            PersistenceErrorCode.PATH_UNSAFE, "diretório permitido ausente"
        ) from None
    reparse = getattr(details, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    correct_type = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode)
    if (
        reparse
        or stat.S_ISLNK(details.st_mode)
        or not correct_type
        or (not directory and details.st_nlink != 1)
    ):
        raise PersistenceError(
            PersistenceErrorCode.PATH_UNSAFE, "link/reparse/tipo de arquivo recusado"
        )
