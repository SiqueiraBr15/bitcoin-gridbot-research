"""Carregamento completo da configuração: raiz -> .env -> Settings -> paths.

Todo ponto de entrada usa ``load_config(env, package_dir)``. A CLI passa ``os.environ`` e
``installed_package_dir()``; testes passam um environment próprio. Nada lê ``os.environ``
nem o CWD por conta própria.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gridbot.config.paths import RuntimePaths, build_runtime_paths, resolve_project_root
from gridbot.config.settings import Settings, load_settings


@dataclass(frozen=True, slots=True)
class AppConfig:
    settings: Settings
    paths: RuntimePaths


def load_config(env: Mapping[str, str], package_dir: Path) -> AppConfig:
    root = resolve_project_root(env, package_dir)
    settings = load_settings(env, root.env_file)
    return AppConfig(settings=settings, paths=build_runtime_paths(root, settings))
