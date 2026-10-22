"""A broken/timed-out test process must never become a green verification report."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from tools import verify


def test_timeout_and_failure_do_not_become_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "targets", lambda profile: ["tests/first.py", "tests/second.py"])
    calls = []

    def fail(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(subprocess, "run", fail)
    code, report = verify.run("smoke", 1)
    assert code == 1
    assert report["status"] == "INCOMPLETE"
    assert len(calls) == 1

    def timeout(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    code, report = verify.run("smoke", 1)
    assert code == 1
    assert report["status"] == "INCOMPLETE"


def test_all_profile_preserves_all_collected_module_paths() -> None:
    paths = {
        p.relative_to(verify.ROOT).as_posix() for p in Path(verify.ROOT, "tests").rglob("test_*.py")
    }
    assert set(verify.targets("all")) == paths
    assert len(paths) > 100
