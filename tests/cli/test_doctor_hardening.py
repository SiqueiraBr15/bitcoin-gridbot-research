from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.cli.test_doctor import by_name, make_ctx

from gridbot.cli.doctor import Status, check_directory, check_location, run_doctor


def directory_alias(alias: Path, target: Path) -> None:
    """Fixture de junction Windows sem elevação; symlink de diretório em POSIX."""
    if sys.platform == "win32":
        # Paths gerados pelo pytest: nenhuma pasta pessoal/real é redirecionada.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    else:
        alias.symlink_to(target, target_is_directory=True)


def test_junction_target_is_blocked_before_probe_or_directory_creation(tmp_path: Path) -> None:
    target = tmp_path / "OneDrive" / "fake-data"
    target.mkdir(parents=True)
    alias = tmp_path / "local-alias"
    directory_alias(alias, target)
    ctx = make_ctx(tmp_path, env={"OneDrive": str(target.parent)}, create_dirs=True)
    with patch("gridbot.cli.doctor._check_writable", side_effect=AssertionError("must not probe")):
        checks = check_directory("data_dir", alias, ctx)
        new = check_directory("log_dir", alias / "new-logs", ctx)
    assert checks[0].status == Status.BLOCKED
    assert new[0].status == Status.BLOCKED
    assert not (target / "new-logs").exists()
    assert list(target.iterdir()) == []


def test_local_alias_is_usable_without_changing_outside_project_policy(tmp_path: Path) -> None:
    target = tmp_path / "outside-project"
    target.mkdir()
    alias = tmp_path / "local-alias"
    directory_alias(alias, target)
    checks = check_directory("data_dir", alias, make_ctx(tmp_path))
    assert all(c.status == Status.READY for c in checks)
    assert str(target.resolve()) in checks[0].detail


def test_broken_alias_and_its_missing_child_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "missing-target"
    alias = tmp_path / "broken-alias"
    directory_alias(alias, target)
    ctx = make_ctx(tmp_path, create_dirs=True)
    for path in (alias, alias / "child"):
        assert check_directory("data_dir", path, ctx)[0].status == Status.BLOCKED
    assert not target.exists()


@pytest.mark.parametrize(
    "error", [OSError("synthetic denied"), RuntimeError("synthetic link loop")]
)
def test_resolution_failures_block_without_probing_or_raising(
    tmp_path: Path, error: Exception
) -> None:
    with patch.object(Path, "resolve", side_effect=error):
        assert check_location("test", tmp_path, make_ctx(tmp_path)).status == Status.BLOCKED
        checks = run_doctor(make_ctx(tmp_path))
    assert by_name(checks)["project_root"].status == Status.BLOCKED


def test_lexically_blocked_location_does_not_resolve(tmp_path: Path) -> None:
    path = tmp_path / "OneDrive" / "data"
    with patch.object(Path, "resolve", side_effect=AssertionError("must not resolve")):
        assert check_location("data", path, make_ctx(tmp_path)).status == Status.BLOCKED


def test_failed_create_directory_reports_blocked(tmp_path: Path) -> None:
    with patch.object(Path, "mkdir", side_effect=PermissionError("synthetic denied")):
        checks = check_directory(
            "data_dir", tmp_path / "missing", make_ctx(tmp_path, create_dirs=True)
        )
    assert checks[-1].status == Status.BLOCKED


def test_database_alias_target_is_blocked_before_sqlite_probe(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "logs").mkdir()
    target = tmp_path / "OneDrive" / "fake-database"
    target.mkdir(parents=True)
    directory_alias(data / "gridbot.sqlite3", target)
    with patch("gridbot.cli.doctor.check_database", side_effect=AssertionError("must not probe")):
        checks = by_name(run_doctor(make_ctx(tmp_path)))
    assert checks["database.location"].status == Status.BLOCKED
    assert checks["database"].status == Status.WARNING


def test_existing_env_in_blocked_location_is_not_loaded(tmp_path: Path) -> None:
    project = tmp_path / "OneDrive" / "fake-project"
    project.mkdir(parents=True)
    (project / ".env").write_text("GRIDBOT_MODE=backtest\n", encoding="utf-8")
    with patch("gridbot.cli.doctor.check_settings", side_effect=AssertionError("must not load")):
        checks = by_name(run_doctor(make_ctx(project)))
    assert checks["env_file.location"].status == Status.BLOCKED


def test_environment_and_acl_are_not_modified(tmp_path: Path) -> None:
    environment = dict(os.environ)
    ctx = replace(make_ctx(tmp_path), acl_reader=lambda _: "synthetic restricted")
    run_doctor(ctx)
    assert dict(os.environ) == environment
