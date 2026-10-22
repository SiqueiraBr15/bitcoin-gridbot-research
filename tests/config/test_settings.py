from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from gridbot.config.errors import ConfigError
from gridbot.config.modes import (
    LIVE_NOT_IMPLEMENTED,
    MODE_NOT_IMPLEMENTED,
    LiveNotImplementedError,
    ModeNotRunnableError,
    ensure_mode_runnable,
)
from gridbot.config.settings import (
    Mode,
    Settings,
    describe_validation_error,
    load_settings,
    normalize_environment,
)

# Gerado em runtime para não existir literal parecido com secret no repositório.
FAKE_SECRET = hashlib.sha256(b"gridbot-settings-test-secret").hexdigest()
FAKE_KEY = hashlib.sha256(b"gridbot-settings-test-key").hexdigest()


def test_defaults_are_backtest_without_credentials() -> None:
    settings = load_settings({})
    assert settings.mode is Mode.BACKTEST
    assert settings.data_dir is None  # default resolvido pela política de paths
    assert settings.db_filename == "gridbot.sqlite3"
    assert not settings.has_exchange_credentials


def test_values_come_only_from_the_given_env() -> None:
    settings = load_settings({"GRIDBOT_MODE": "paper", "GRIDBOT_LOG_LEVEL": "DEBUG", "PATH": "x"})
    assert settings.mode is Mode.PAPER
    assert settings.log_level == "DEBUG"


def test_settings_never_read_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDBOT_MODE", "live")  # environment real "A"
    assert Settings().mode is Mode.BACKTEST  # nenhuma fonte implícita
    assert load_settings({}).mode is Mode.BACKTEST  # environment injetado "B" vazio
    assert load_settings({"GRIDBOT_MODE": "testnet"}).mode is Mode.TESTNET


def test_env_keys_are_case_insensitive_and_conflicts_fail() -> None:
    assert load_settings({"gridbot_mode": "paper"}).mode is Mode.PAPER
    with pytest.raises(ConfigError) as excinfo:
        normalize_environment({"GRIDBOT_MODE": "paper", "gridbot_mode": "live"})
    assert "paper" not in str(excinfo.value)


def test_empty_values_are_treated_as_absent() -> None:
    assert load_settings({"GRIDBOT_BINANCE_API_SECRET": ""}).binance_api_secret is None


def test_dotenv_file_is_loaded_and_env_has_priority(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"GRIDBOT_MODE=paper\nGRIDBOT_BINANCE_API_SECRET={FAKE_SECRET}\n", encoding="utf-8"
    )
    settings = load_settings({"GRIDBOT_MODE": "backtest"}, env_file)
    assert settings.mode is Mode.BACKTEST
    assert settings.binance_api_secret is not None
    assert settings.binance_api_secret.get_secret_value() == FAKE_SECRET


def test_missing_dotenv_file_is_ignored(tmp_path: Path) -> None:
    assert load_settings({}, tmp_path / ".env").mode is Mode.BACKTEST


def test_home_is_not_allowed_inside_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"GRIDBOT_HOME={tmp_path}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings({}, env_file)


@pytest.mark.parametrize("source", ["env", "dotenv"])
def test_unknown_prefixed_key_is_rejected(tmp_path: Path, source: str) -> None:
    env_file = tmp_path / ".env"
    if source == "dotenv":
        env_file.write_text("GRIDBOT_MDOE=live\n", encoding="utf-8")
        env: dict[str, str] = {}
    else:
        env = {"GRIDBOT_MDOE": "live"}
    with pytest.raises(ValidationError) as excinfo:
        load_settings(env, env_file)
    assert any(m.startswith("GRIDBOT_MDOE") for m in describe_validation_error(excinfo.value))


def test_settings_are_immutable() -> None:
    settings = load_settings({})
    with pytest.raises(ValidationError):
        settings.mode = Mode.LIVE  # type: ignore[misc]


# ------------------------------------------------------------------ secrets (E)


def test_secrets_never_appear_in_repr_str_or_dumps() -> None:
    settings = load_settings(
        {"GRIDBOT_BINANCE_API_KEY": FAKE_KEY, "GRIDBOT_BINANCE_API_SECRET": FAKE_SECRET}
    )
    rendered = [
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        str(settings.model_dump()),
        repr(settings.binance_api_secret),
        f"{settings.binance_api_key}",
    ]
    for text in rendered:
        assert FAKE_SECRET not in text
        assert FAKE_KEY not in text
    assert settings.has_exchange_credentials


def test_validation_errors_do_not_echo_inputs() -> None:
    env = {
        "GRIDBOT_BINANCE_API_SECRET": FAKE_SECRET,
        "GRIDBOT_DB_FILENAME": FAKE_KEY,  # valor inválido para o campo
        "GRIDBOT_MODE": "turbo",
    }
    with pytest.raises(ValidationError) as excinfo:
        load_settings(env)
    messages = [str(excinfo.value), *describe_validation_error(excinfo.value)]
    for text in messages:
        assert FAKE_SECRET not in text
        assert FAKE_KEY not in text
        assert "turbo" not in text
    described = describe_validation_error(excinfo.value)
    assert any(m.startswith("GRIDBOT_MODE:") for m in described)
    assert any(m.startswith("GRIDBOT_DB_FILENAME:") for m in described)


# ------------------------------------------------------------------ modos (F)


def test_backtest_is_runnable() -> None:
    ensure_mode_runnable(Mode.BACKTEST)


def test_live_is_blocked_even_when_configured() -> None:
    settings = load_settings(
        {
            "GRIDBOT_MODE": "live",
            "GRIDBOT_BINANCE_API_KEY": FAKE_KEY,
            "GRIDBOT_BINANCE_API_SECRET": FAKE_SECRET,
        }
    )
    assert settings.mode is Mode.LIVE
    with pytest.raises(LiveNotImplementedError) as excinfo:
        ensure_mode_runnable(settings.mode)
    assert excinfo.value.code == LIVE_NOT_IMPLEMENTED
    assert LIVE_NOT_IMPLEMENTED in str(excinfo.value)


@pytest.mark.parametrize("mode", [Mode.PAPER, Mode.TESTNET])
def test_future_modes_are_not_runnable_yet(mode: Mode) -> None:
    with pytest.raises(ModeNotRunnableError) as excinfo:
        ensure_mode_runnable(mode)
    assert excinfo.value.code == MODE_NOT_IMPLEMENTED


def test_raw_string_mode_is_rejected() -> None:
    with pytest.raises(TypeError):
        ensure_mode_runnable("backtest")  # type: ignore[arg-type]
