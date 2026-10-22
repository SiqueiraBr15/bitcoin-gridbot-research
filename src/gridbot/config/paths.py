"""Política de caminhos de runtime (ADR-006). Nada é resolvido relativo ao CWD.

1. ``PROJECT_ROOT``:
   a. ``GRIDBOT_HOME`` do environment, se definido (precisa ser absoluto); senão
   b. o checkout que contém o pacote: ``<root>/src/gridbot`` com ``<root>/pyproject.toml``
      declarando ``name = "gridbot"``; senão
   c. erro (``ConfigError``): nenhuma heurística adicional, nenhum fallback para o CWD.
2. ``ENV_FILE`` = ``PROJECT_ROOT/.env``.
3. ``DATA_DIR`` / ``LOG_DIR``: ``GRIDBOT_DATA_DIR`` / ``GRIDBOT_LOG_DIR`` se definidos
   (absolutos usados como estão; relativos ancorados em ``PROJECT_ROOT``); senão
   ``PROJECT_ROOT/data`` e ``PROJECT_ROOT/logs``.
4. ``DB_PATH`` = ``DATA_DIR/<GRIDBOT_DB_FILENAME>``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gridbot.config.errors import ConfigError
from gridbot.config.settings import HOME_ENV_VAR, Settings, normalize_environment

PROJECT_NAME = "gridbot"
ENV_FILENAME = ".env"
DEFAULT_DATA_DIRNAME = "data"
DEFAULT_LOG_DIRNAME = "logs"


class RootSource(StrEnum):
    ENV = HOME_ENV_VAR
    SOURCE_CHECKOUT = "checkout do pacote"


@dataclass(frozen=True, slots=True)
class ProjectRoot:
    path: Path
    source: RootSource

    @property
    def env_file(self) -> Path:
        return self.path / ENV_FILENAME


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    project_root: Path
    root_source: RootSource
    env_file: Path
    data_dir: Path
    log_dir: Path
    db_path: Path


def installed_package_dir() -> Path:
    """Diretório real do pacote ``gridbot`` (independe do CWD)."""
    return Path(__file__).resolve().parents[1]


def resolve_project_root(env: Mapping[str, str], package_dir: Path) -> ProjectRoot:
    home = normalize_environment(env).get(HOME_ENV_VAR)
    if home:
        path = Path(home)
        if not path.is_absolute():
            raise ConfigError(f"{HOME_ENV_VAR} deve ser um caminho absoluto")
        return ProjectRoot(path.resolve(), RootSource.ENV)
    candidate = package_dir.parent.parent
    if (
        package_dir.name == PROJECT_NAME
        and package_dir.parent.name == "src"
        and _declares_project(candidate)
    ):
        return ProjectRoot(candidate, RootSource.SOURCE_CHECKOUT)
    raise ConfigError(
        f"raiz do projeto indeterminada: o pacote em {package_dir} não está num checkout "
        f"src/{PROJECT_NAME}; defina {HOME_ENV_VAR} com um caminho absoluto"
    )


def _declares_project(root: Path) -> bool:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    return isinstance(project, dict) and project.get("name") == PROJECT_NAME


def _anchor(root: Path, override: Path | None, default: str) -> Path:
    if override is None:
        return root / default
    return override if override.is_absolute() else root / override


def build_runtime_paths(root: ProjectRoot, settings: Settings) -> RuntimePaths:
    data_dir = _anchor(root.path, settings.data_dir, DEFAULT_DATA_DIRNAME)
    return RuntimePaths(
        project_root=root.path,
        root_source=root.source,
        env_file=root.env_file,
        data_dir=data_dir,
        log_dir=_anchor(root.path, settings.log_dir, DEFAULT_LOG_DIRNAME),
        db_path=data_dir / settings.db_filename,
    )
