"""Higiene do repositório: secrets fora do Git desde o primeiro commit."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gridbot.config.settings import Mode, load_settings

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")

REQUIRED_IGNORES = [
    ".env",
    ".env.*",
    "!.env.example",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".coverage",
    "htmlcov/",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "logs/",
    "runs/",
    "tmp/",
    "dist/",
    "build/",
]


def test_gitignore_has_required_entries() -> None:
    lines = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    missing = [entry for entry in REQUIRED_IGNORES if entry not in lines]
    assert not missing


def test_env_example_has_no_secret_values() -> None:
    for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if any(word in key for word in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            assert value == "", f"{key} deve ficar vazio em .env.example"


def test_env_example_is_a_valid_config_template() -> None:
    settings = load_settings({}, ROOT / ".env.example")
    assert settings.mode is Mode.BACKTEST
    assert settings.data_dir is None  # vazio => default ancorado na raiz
    assert not settings.has_exchange_credentials


@pytest.mark.skipif(GIT is None or not (ROOT / ".git").exists(), reason="requer repositório Git")
@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        (".env", True),
        (".env.local", True),
        (".env.production", True),
        (".env.example", False),
        ("data/gridbot.sqlite3", True),
        ("logs/gridbot.jsonl", True),
        ("runs/bt-1/result.json", True),
        ("candles.parquet", True),
        ("src/gridbot/domain/values.py", False),
    ],
)
def test_git_ignores_sensitive_and_runtime_files(path: str, ignored: bool) -> None:
    assert GIT is not None
    result = subprocess.run([GIT, "check-ignore", "--no-index", "-q", path], cwd=ROOT, check=False)
    assert (result.returncode == 0) is ignored
