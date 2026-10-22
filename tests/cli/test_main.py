from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import gridbot
from gridbot.cli.main import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"gridbot {gridbot.__version__}"


def test_version_is_pre_release() -> None:
    assert gridbot.__version__ == "0.1.0.dev0"


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "doctor" in capsys.readouterr().out


def test_doctor_from_external_cwd_uses_checkout_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.chdir(external)
    code = main(["doctor"])
    out = capsys.readouterr().out
    checkout = Path(__file__).resolve().parents[2]
    (root_line,) = [line for line in out.splitlines() if " project_root " in line]
    assert root_line.endswith(f"{checkout} (via checkout do pacote)")
    assert list(external.iterdir()) == []  # nada criado no diretório externo
    expected = {"Resultado: READY": 0, "Resultado: WARNING": 1, "Resultado: BLOCKED": 2}
    assert expected[out.strip().splitlines()[-1]] == code


def test_cli_uses_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GRIDBOT_HOME", str(tmp_path))
    monkeypatch.setenv("GRIDBOT_MODE", "live")
    assert main(["doctor"]) == 2
    out = capsys.readouterr().out
    assert "LIVE_NOT_IMPLEMENTED" in out
    assert str(tmp_path.resolve()) in out


def test_module_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gridbot", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"gridbot {gridbot.__version__}"
