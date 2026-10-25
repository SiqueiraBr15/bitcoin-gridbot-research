"""An empty mutex file must never be initialized before exclusive ownership."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from research_console.lab.storage import writer_lock


def observe_lock(monkeypatch: pytest.MonkeyPatch, held: set[int], *, busy: bool) -> None:
    if sys.platform == "win32":
        import msvcrt

        original = msvcrt.locking

        def locking(descriptor: int, mode: int, count: int) -> None:
            if mode == msvcrt.LK_NBLCK:
                if busy:
                    raise OSError(13, "SYNTHETIC competing empty-file owner")
                original(descriptor, mode, count)
                held.add(descriptor)
            else:
                original(descriptor, mode, count)
                held.remove(descriptor)

        monkeypatch.setattr(msvcrt, "locking", locking)
    else:
        import fcntl

        original_flock = fcntl.flock

        def flock(descriptor: int, operation: int) -> None:
            if operation & fcntl.LOCK_EX:
                if busy:
                    raise OSError(13, "SYNTHETIC competing empty-file owner")
                original_flock(descriptor, operation)
                held.add(descriptor)
            else:
                original_flock(descriptor, operation)
                held.remove(descriptor)

        monkeypatch.setattr(fcntl, "flock", flock)


def test_empty_lock_initialization_requires_exclusive_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    held: set[int] = set()
    observe_lock(monkeypatch, held, busy=False)
    original_write = os.write

    def checked_write(descriptor: int, raw: bytes) -> int:
        assert descriptor in held, "persistent initialization before mutex ownership"
        return original_write(descriptor, raw)

    monkeypatch.setattr(os, "write", checked_write)
    with writer_lock(root):
        assert held
    assert not held
    assert (root / ".gridbot-writer-lock-v1").read_bytes() == b"\0"


def test_contended_empty_lock_is_busy_without_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    held: set[int] = set()
    observe_lock(monkeypatch, held, busy=True)
    with pytest.raises(ValueError, match="Biblioteca ocupada"), writer_lock(root):
        pytest.fail("contended writer entered critical section")
    assert (root / ".gridbot-writer-lock-v1").read_bytes() == b""
    assert not held
