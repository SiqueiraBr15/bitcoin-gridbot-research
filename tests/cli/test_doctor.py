from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path, PureWindowsPath

import pytest

from gridbot.cli.doctor import (
    Check,
    DoctorContext,
    Status,
    check_python,
    overall,
    render_report,
    run_doctor,
)
from gridbot.infra.locations import DRIVE_REMOTE, LocationRisk, assess_location

ONEDRIVE_PROJECT = PureWindowsPath(r"C:\Users\ExampleUser\OneDrive\Projects\sample")
SAFE_PROJECT = PureWindowsPath(r"C:\dev\gridbot")
FAKE_SECRET = hashlib.sha256(b"gridbot-doctor-test-secret").hexdigest()

RESTRICTED_ACL = "C:\\dev\\gridbot\\.env NT AUTHORITY\\SYSTEM:(F)\n  DESKTOP\\me:(F)\n"
BROAD_ACL = "C:\\dev\\gridbot\\.env BUILTIN\\Users:(I)(RX)\n  NT AUTHORITY\\Authenticated Users:(M)"


def make_ctx(root: Path, **overrides: object) -> DoctorContext:
    """Contexto com environment injetado: raiz do projeto via GRIDBOT_HOME."""
    ctx = DoctorContext(
        env={"GRIDBOT_HOME": str(root)},
        python_version=(3, 13, 16),
        pointer_bits=64,
        in_venv=True,
        venv_prefix=root / ".venv",
        package_dir=root / "src" / "gridbot",
        create_dirs=False,
        platform="win32",
        drive_type=None,
        git_tracked=lambda _path: False,
        acl_reader=lambda _path: RESTRICTED_ACL,
    )
    return replace(ctx, **overrides)  # type: ignore[arg-type]


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


# ------------------------------------------------------------------ G: OneDrive/rede detectados


@pytest.mark.parametrize(
    ("path", "env"),
    [
        (ONEDRIVE_PROJECT, {}),
        (ONEDRIVE_PROJECT, {"OneDrive": r"C:\Users\ExampleUser\OneDrive"}),
        (PureWindowsPath(r"C:\Users\x\OneDrive - Contoso\proj"), {}),
        (PureWindowsPath(r"C:\Users\x\Contoso\SharePoint - Time\proj"), {}),
        (PureWindowsPath(r"D:\Sync\proj"), {"ONEDRIVECOMMERCIAL": r"D:\Sync"}),
        (PureWindowsPath(r"D:\Sync"), {"onedriveconsumer": r"d:\sync"}),
    ],
)
def test_onedrive_and_sharepoint_paths_are_cloud_sync(
    path: PureWindowsPath, env: dict[str, str]
) -> None:
    assert assess_location(path, env, drive_type=None).risk is LocationRisk.CLOUD_SYNC


@pytest.mark.parametrize(
    "path",
    [
        PureWindowsPath(r"\\fileserver\share\gridbot"),
        PureWindowsPath(r"\\?\UNC\fileserver\share\gridbot"),
    ],
)
def test_unc_paths_are_network(path: PureWindowsPath) -> None:
    assert assess_location(path, {}, drive_type=None).risk is LocationRisk.NETWORK


def test_mapped_network_drive_is_network() -> None:
    def remote(_root: str) -> int:
        return DRIVE_REMOTE

    result = assess_location(PureWindowsPath(r"Z:\gridbot"), {}, drive_type=remote)
    assert result.risk is LocationRisk.NETWORK


def test_other_sync_folders_are_warned() -> None:
    result = assess_location(PureWindowsPath(r"C:\Users\x\Dropbox\gridbot"), {}, drive_type=None)
    assert result.risk is LocationRisk.OTHER_SYNC


def test_doctor_blocks_project_inside_onedrive(tmp_path: Path) -> None:
    project = tmp_path / "OneDrive" / "Programas" / "Binance"
    project.mkdir(parents=True)
    checks = run_doctor(make_ctx(project, create_dirs=True))
    named = by_name(checks)
    assert named["project_root.location"].status is Status.BLOCKED
    assert named["data_dir.location"].status is Status.BLOCKED
    assert named["database"].detail == "não verificado (data_dir bloqueado)"
    assert list(project.iterdir()) == []  # bloqueado => nada é criado nem gravado
    assert overall(checks) is Status.BLOCKED
    assert "Resultado: BLOCKED" in render_report(checks)


def test_doctor_blocks_onedrive_from_injected_env_var(tmp_path: Path) -> None:
    env = {"GRIDBOT_HOME": str(tmp_path), "OneDrive": str(tmp_path)}
    checks = run_doctor(make_ctx(tmp_path, env=env))
    assert by_name(checks)["project_root.location"].status is Status.BLOCKED


# ------------------------------------------------------------------ H: caminho local seguro


def test_local_path_is_safe() -> None:
    result = assess_location(SAFE_PROJECT, {"OneDrive": r"C:\Users\ExampleUser\OneDrive"}, None)
    assert result.risk is LocationRisk.LOCAL


def test_doctor_ready_on_safe_local_path(tmp_path: Path) -> None:
    """Item H, com environment totalmente injetado."""
    checks = run_doctor(make_ctx(tmp_path, create_dirs=True))
    assert overall(checks) is Status.READY, render_report(checks)
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert by_name(checks)["database"].status is Status.READY
    assert not (tmp_path / "data" / "gridbot.sqlite3").exists()  # sonda não cria o banco


def test_doctor_does_not_create_dirs_without_flag(tmp_path: Path) -> None:
    checks = run_doctor(make_ctx(tmp_path))
    named = by_name(checks)
    assert named["data_dir"].status is Status.WARNING
    assert "--create-dirs" in (named["data_dir"].hint or "")
    assert not (tmp_path / "data").exists()
    assert overall(checks) is Status.WARNING


# ------------------------------------------------------------------ Python / venv


@pytest.mark.parametrize(
    ("version", "bits", "expected"),
    [
        ((3, 13, 16), 64, Status.READY),
        ((3, 14, 7), 64, Status.WARNING),
        ((3, 12, 9), 64, Status.BLOCKED),
        ((3, 13, 16), 32, Status.BLOCKED),
    ],
)
def test_python_version_policy(version: tuple[int, int, int], bits: int, expected: Status) -> None:
    assert check_python(version, bits).status is expected


def test_outside_venv_is_warning(tmp_path: Path) -> None:
    checks = run_doctor(make_ctx(tmp_path, in_venv=False, create_dirs=True))
    assert by_name(checks)["venv"].status is Status.WARNING


# ------------------------------------------------------------------ config / modo


def with_env(root: Path, **extra: str) -> dict[str, str]:
    return {"GRIDBOT_HOME": str(root), **extra}


def test_live_mode_is_blocked_by_doctor(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, env=with_env(tmp_path, GRIDBOT_MODE="live"), create_dirs=True)
    mode = by_name(run_doctor(ctx))["mode"]
    assert mode.status is Status.BLOCKED
    assert "LIVE_NOT_IMPLEMENTED" in mode.detail


def test_invalid_config_is_blocked_without_leaking(tmp_path: Path) -> None:
    checks = run_doctor(make_ctx(tmp_path, env=with_env(tmp_path, GRIDBOT_DB_FILENAME=FAKE_SECRET)))
    config = by_name(checks)["config"]
    assert config.status is Status.BLOCKED
    assert "GRIDBOT_DB_FILENAME" in config.detail
    assert FAKE_SECRET not in render_report(checks)


def test_credentials_in_phase_zero_are_warned_not_printed(tmp_path: Path) -> None:
    env = with_env(tmp_path, GRIDBOT_BINANCE_API_SECRET=FAKE_SECRET)
    checks = run_doctor(make_ctx(tmp_path, env=env, create_dirs=True))
    assert by_name(checks)["config"].status is Status.WARNING
    assert FAKE_SECRET not in render_report(checks)


# ------------------------------------------------------------------ fonte única de environment


def test_real_env_a_does_not_interfere_with_injected_env_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    decoy = tmp_path / "decoy"
    # Environment real "A": tudo que bloquearia ou desviaria o diagnóstico.
    monkeypatch.setenv("GRIDBOT_MODE", "live")
    monkeypatch.setenv("GRIDBOT_DATA_DIR", str(decoy))
    monkeypatch.setenv("GRIDBOT_HOME", str(decoy))
    monkeypatch.setenv("OneDrive", str(root))
    # Environment injetado "B": só a raiz.
    checks = run_doctor(make_ctx(root, env=with_env(root), create_dirs=True))
    named = by_name(checks)
    assert overall(checks) is Status.READY, render_report(checks)
    assert named["mode"].status is Status.READY
    assert named["project_root"].detail.startswith(str(root.resolve()))
    assert str(root.resolve() / "data") in named["data_dir"].detail
    assert not decoy.exists()


def test_injected_mode_controls_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDBOT_MODE", "backtest")  # real "A" diz backtest...
    ctx = make_ctx(tmp_path, env=with_env(tmp_path, GRIDBOT_MODE="live"), create_dirs=True)
    checks = run_doctor(ctx)  # ...mas o injetado "B" diz live
    assert by_name(checks)["mode"].status is Status.BLOCKED
    assert overall(checks) is Status.BLOCKED


def test_paths_and_location_checks_use_the_injected_env(tmp_path: Path) -> None:
    env = with_env(tmp_path, GRIDBOT_DATA_DIR="custom-data", GRIDBOT_LOG_DIR="custom-logs")
    checks = run_doctor(make_ctx(tmp_path, env=env, create_dirs=True))
    named = by_name(checks)
    root = tmp_path.resolve()
    assert str(root / "custom-data") in named["data_dir"].detail
    assert str(root / "custom-logs") in named["log_dir"].detail
    assert (root / "custom-data").is_dir()
    assert not (root / "data").exists()


def test_doctor_result_does_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.chdir(external)
    checks = run_doctor(make_ctx(root, env=with_env(root), create_dirs=True))
    assert overall(checks) is Status.READY, render_report(checks)
    assert (root / "data").is_dir()
    assert list(external.iterdir()) == []


def test_missing_root_is_blocked_and_not_created(tmp_path: Path) -> None:
    root = tmp_path / "nao-existe"
    checks = run_doctor(make_ctx(root, create_dirs=True))
    assert by_name(checks)["project_root"].status is Status.BLOCKED
    assert not root.exists()


def test_unresolvable_root_is_blocked(tmp_path: Path) -> None:
    checks = run_doctor(make_ctx(tmp_path, env={}))  # sem GRIDBOT_HOME, sem checkout
    root = by_name(checks)["project_root"]
    assert root.status is Status.BLOCKED
    assert "GRIDBOT_HOME" in root.detail


# ------------------------------------------------------------------ .env


def write_env(root: Path) -> Path:
    env_file = root / ".env"
    env_file.write_text("GRIDBOT_MODE=backtest\n", encoding="utf-8")
    return env_file


def test_absent_env_file_is_ready(tmp_path: Path) -> None:
    assert by_name(run_doctor(make_ctx(tmp_path)))["env_file"].status is Status.READY


def test_tracked_env_file_is_blocked(tmp_path: Path) -> None:
    write_env(tmp_path)
    checks = run_doctor(make_ctx(tmp_path, git_tracked=lambda _p: True, create_dirs=True))
    assert by_name(checks)["env_file.git"].status is Status.BLOCKED
    assert overall(checks) is Status.BLOCKED


def test_env_file_git_unknown_is_warning(tmp_path: Path) -> None:
    write_env(tmp_path)
    checks = run_doctor(make_ctx(tmp_path, git_tracked=lambda _p: None, create_dirs=True))
    assert by_name(checks)["env_file.git"].status is Status.WARNING


@pytest.mark.parametrize(
    ("acl", "expected"),
    [(RESTRICTED_ACL, Status.READY), (BROAD_ACL, Status.WARNING), (None, Status.WARNING)],
)
def test_env_file_windows_acl(tmp_path: Path, acl: str | None, expected: Status) -> None:
    write_env(tmp_path)
    reader: Callable[[Path], str | None] = lambda _p: acl  # noqa: E731
    checks = run_doctor(make_ctx(tmp_path, acl_reader=reader, create_dirs=True))
    assert by_name(checks)["env_file.acl"].status is expected


def test_env_file_posix_permissions_too_open(tmp_path: Path) -> None:
    env_file = write_env(tmp_path)
    os.chmod(env_file, 0o644)  # no Windows, st_mode de arquivo comum é 0o666
    checks = run_doctor(make_ctx(tmp_path, platform="linux", create_dirs=True))
    assert by_name(checks)["env_file.acl"].status is Status.WARNING


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 600 não se aplica ao Windows")
def test_env_file_posix_permissions_restricted(tmp_path: Path) -> None:
    env_file = write_env(tmp_path)
    os.chmod(env_file, 0o600)
    checks = run_doctor(make_ctx(tmp_path, platform="linux", create_dirs=True))
    assert by_name(checks)["env_file.acl"].status is Status.READY


# ------------------------------------------------------------------ diretórios / banco


def test_data_dir_that_is_a_file_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("não sou diretório", encoding="utf-8")
    checks = run_doctor(make_ctx(tmp_path, create_dirs=True))
    assert by_name(checks)["data_dir"].status is Status.BLOCKED


def test_existing_healthy_database_is_ready(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    with closing(sqlite3.connect(tmp_path / "data" / "gridbot.sqlite3")) as conn:
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.commit()
    checks = run_doctor(make_ctx(tmp_path, create_dirs=True))
    database = by_name(checks)["database"]
    assert database.status is Status.READY
    assert "quick_check=ok" in database.detail


def test_corrupt_database_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "gridbot.sqlite3").write_bytes(b"isto nao e um banco sqlite" * 100)
    checks = run_doctor(make_ctx(tmp_path, create_dirs=True))
    assert by_name(checks)["database"].status is Status.BLOCKED


def test_report_shows_hints_only_for_problems(tmp_path: Path) -> None:
    report = render_report(run_doctor(make_ctx(tmp_path)))
    assert "-> crie explicitamente com: gridbot doctor --create-dirs" in report
    assert report.splitlines()[-1] == "Resultado: WARNING"
