"""Portable local-path checks and a crash-released, nonblocking writer lock."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from research_console.risk import require

RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


def no_links(path: Path) -> None:
    require(
        path.is_absolute() and not str(path).startswith(("\\\\", "//")),
        "Pasta local absoluta exigida",
    )
    for part in path.parts[1:]:
        require(
            ":" not in part
            and not part.endswith((" ", "."))
            and part.split(".", 1)[0].upper() not in RESERVED,
            "Nome de caminho não portátil",
        )
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            "Links e reparse points recusados",
        )


@contextmanager
def writer_lock(root: Path) -> Iterator[None]:
    path = root / ".gridbot-writer-lock-v1"
    no_links(path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        require(
            stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 1,
            "Lock local inválido",
        )
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Biblioteca ocupada. Tente novamente") from error
        try:
            # Windows locks may cover an empty range. Initialize only after ownership:
            # another writer can already hold that byte even while its size is zero.
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            no_links(root)
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if sys.platform == "win32":
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
