"""Configuração tipada (pydantic-settings) com environment injetado explicitamente.

``Settings`` não lê nenhuma fonte implícita: nem ``os.environ`` nem ``.env``. A única forma
de carregá-la é ``load_settings(env, env_file)``, que recebe o environment como argumento.
A CLI passa ``os.environ``; testes e o doctor passam o mapping que quiserem. Assim existe
uma única fonte de verdade por execução.

Secrets usam ``SecretStr``: ``repr``/``str``/JSON nunca mostram o valor, e erros de
validação não incluem o input (``hide_input_in_errors``).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from gridbot.config.errors import ConfigError

ENV_PREFIX = "GRIDBOT_"
HOME_ENV_VAR = "GRIDBOT_HOME"
# Variáveis GRIDBOT_* resolvidas antes da Settings (política de paths, ADR-006).
RESERVED_ENV_VARS = frozenset({HOME_ENV_VAR})


class Mode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    mode: Mode = Mode.BACKTEST
    # None = default ancorado na raiz do projeto; relativo = relativo à raiz (nunca ao CWD).
    data_dir: Path | None = None
    log_dir: Path | None = None
    db_filename: str = Field(default="gridbot.sqlite3", pattern=r"^[A-Za-z0-9_.-]+\.sqlite3$")
    log_level: LogLevel = "INFO"

    # Não usadas antes da Fase C.5. Nunca logar, nunca imprimir.
    binance_api_key: SecretStr | None = None
    binance_api_secret: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Nenhuma leitura implícita de os.environ/.env: só valores passados explicitamente.
        return (init_settings,)

    @property
    def has_exchange_credentials(self) -> bool:
        return self.binance_api_key is not None or self.binance_api_secret is not None


def normalize_environment(env: Mapping[str, str | None]) -> dict[str, str]:
    """Chaves em maiúsculas (semântica do Windows); conflito de grafia é erro."""
    normalized: dict[str, str] = {}
    for key, value in env.items():
        if value is None:
            continue
        upper = key.upper()
        if upper in normalized and normalized[upper] != value:
            raise ConfigError(f"variável definida com grafias diferentes: {upper}")
        normalized[upper] = value
    return normalized


def _settings_values(env: Mapping[str, str]) -> dict[str, str]:
    return {
        key.removeprefix(ENV_PREFIX).lower(): value
        for key, value in env.items()
        if key.startswith(ENV_PREFIX)
        and key not in RESERVED_ENV_VARS
        and (value != "" or key.removeprefix(ENV_PREFIX).lower() not in Settings.model_fields)
    }


def load_settings(env: Mapping[str, str], env_file: Path | None = None) -> Settings:
    """Monta a ``Settings`` a partir de ``env`` (prioridade) e de ``env_file`` opcional.

    Regras: só chaves ``GRIDBOT_*`` são consideradas; valores conhecidos vazios são ausentes;
    chave ``GRIDBOT_*`` desconhecida é erro (``extra="forbid"``), venha do env ou do arquivo.
    Valores do arquivo são literais: não há interpolação de variáveis ou ambiente global.
    """
    values: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        file_env = normalize_environment(
            {
                key: "" if value is None else value
                for key, value in dotenv_values(
                    env_file, encoding="utf-8", interpolate=False
                ).items()
            }
        )
        if HOME_ENV_VAR in file_env:
            raise ConfigError(f"{HOME_ENV_VAR} não pode ser definido no .env (ele localiza o .env)")
        values.update(_settings_values(file_env))
    values.update(_settings_values(normalize_environment(env)))
    return Settings.model_validate(values)


def describe_validation_error(exc: ValidationError) -> list[str]:
    """Erros por variável (``GRIDBOT_X: msg``), sem os valores recebidos (podem ser secrets)."""
    messages = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = [str(part) for part in err["loc"]]
        name = f"{ENV_PREFIX}{loc[0].upper()}" if loc else "<root>"
        messages.append(f"{'.'.join([name, *loc[1:]])}: {err['msg']}")
    return messages
