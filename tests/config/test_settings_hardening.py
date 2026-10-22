from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gridbot.config.errors import ConfigError
from gridbot.config.settings import Mode, load_settings


def test_dotenv_interpolation_cannot_read_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture.env"
    fixture.write_text("GRIDBOT_LOG_LEVEL=${GRIDBOT_AUDIT_AMBIENT}\n", encoding="utf-8")
    for ambient in ("ERROR", "DEBUG"):
        monkeypatch.setenv("GRIDBOT_AUDIT_AMBIENT", ambient)
        with pytest.raises(ValidationError):
            load_settings({}, fixture)
    assert load_settings({"GRIDBOT_LOG_LEVEL": "INFO"}, fixture).log_level == "INFO"


def test_dotenv_paths_defaults_and_file_variables_are_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture.env"
    fixture.write_text(
        "LOCAL=logs\nGRIDBOT_LOG_DIR=${LOCAL}\nGRIDBOT_DATA_DIR=${MISSING:-data}\nGRIDBOT_MODE=paper\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL", "outside")
    settings = load_settings({"GRIDBOT_MODE": "backtest"}, fixture)
    assert settings.log_dir == Path("${LOCAL}")
    assert settings.data_dir == Path("${MISSING:-data}")
    assert settings.mode == Mode.BACKTEST


@pytest.mark.parametrize("source", ["env", "dotenv", "dotenv_bare"])
def test_unknown_names_are_rejected_even_when_empty(tmp_path: Path, source: str) -> None:
    fixture = tmp_path / "fixture.env"
    env: dict[str, str] = {}
    if source == "env":
        env["gridbot_unknown_audit_option"] = ""
    else:
        fixture.write_text(
            "GRIDBOT_UNKNOWN_AUDIT_OPTION" + ("=" if source == "dotenv" else "") + "\n",
            encoding="utf-8",
        )
    with pytest.raises(ValidationError) as caught:
        load_settings(env, fixture)
    assert caught.value.errors(include_input=False)[0]["type"] == "extra_forbidden"


def test_empty_known_values_reserved_home_and_unrelated_variables(tmp_path: Path) -> None:
    assert load_settings({"GRIDBOT_MODE": "", "UNRELATED": ""}).mode == Mode.BACKTEST
    fixture = tmp_path / "fixture.env"
    fixture.write_text("GRIDBOT_HOME\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings({}, fixture)
