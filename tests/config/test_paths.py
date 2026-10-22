"""Política de paths (ADR-006): resultado idêntico para qualquer CWD."""

from __future__ import annotations

from pathlib import Path

import pytest

from gridbot.config.errors import ConfigError
from gridbot.config.loader import load_config
from gridbot.config.paths import (
    RootSource,
    installed_package_dir,
    resolve_project_root,
)


def make_checkout(root: Path, name: str = "gridbot") -> Path:
    """Cria ``<root>/pyproject.toml`` + ``<root>/src/gridbot`` e devolve o package_dir."""
    package_dir = root / "src" / "gridbot"
    package_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    return package_dir


def test_real_installed_package_resolves_to_this_checkout() -> None:
    package_dir = installed_package_dir()
    root = resolve_project_root({}, package_dir)
    assert root.source is RootSource.SOURCE_CHECKOUT
    assert root.path == Path(__file__).resolve().parents[2]
    assert (root.path / "pyproject.toml").is_file()


def test_checkout_root_and_default_dirs(tmp_path: Path) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    config = load_config({}, package_dir)
    root = tmp_path / "proj"
    assert config.paths.project_root == root
    assert config.paths.root_source is RootSource.SOURCE_CHECKOUT
    assert config.paths.env_file == root / ".env"
    assert config.paths.data_dir == root / "data"
    assert config.paths.log_dir == root / "logs"
    assert config.paths.db_path == root / "data" / "gridbot.sqlite3"


def test_paths_do_not_depend_on_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    elsewhere_a = tmp_path / "elsewhere_a"
    elsewhere_b = tmp_path / "deep" / "elsewhere_b"
    elsewhere_a.mkdir()
    elsewhere_b.mkdir(parents=True)
    env = {"GRIDBOT_DATA_DIR": "custom-data", "GRIDBOT_LOG_DIR": "custom-logs"}

    monkeypatch.chdir(elsewhere_a)
    first = load_config(env, package_dir).paths
    monkeypatch.chdir(elsewhere_b)
    second = load_config(env, package_dir).paths
    monkeypatch.chdir(package_dir)
    third = load_config(env, package_dir).paths

    assert first == second == third
    assert first.data_dir == tmp_path / "proj" / "custom-data"  # relativo => raiz, não CWD
    assert not any(elsewhere_a.iterdir())
    assert not any(elsewhere_b.iterdir())


def test_dotenv_is_read_from_project_root_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    (tmp_path / "proj" / ".env").write_text("GRIDBOT_LOG_LEVEL=DEBUG\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("GRIDBOT_LOG_LEVEL=ERROR\n", encoding="utf-8")  # isca
    monkeypatch.chdir(cwd)
    assert load_config({}, package_dir).settings.log_level == "DEBUG"


def test_home_env_overrides_checkout(tmp_path: Path) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    home = tmp_path / "runtime-home"
    config = load_config({"GRIDBOT_HOME": str(home)}, package_dir)
    assert config.paths.project_root == home.resolve()
    assert config.paths.root_source is RootSource.ENV
    assert config.paths.data_dir == home.resolve() / "data"


def test_absolute_dir_overrides_are_used_as_is(tmp_path: Path) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    data = tmp_path / "abs-data"
    config = load_config({"GRIDBOT_DATA_DIR": str(data)}, package_dir)
    assert config.paths.data_dir == data
    assert config.paths.db_path == data / "gridbot.sqlite3"


@pytest.mark.parametrize("home", ["relative/path", "data"])
def test_relative_home_is_rejected(tmp_path: Path, home: str) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    with pytest.raises(ConfigError, match="absoluto"):
        resolve_project_root({"GRIDBOT_HOME": home}, package_dir)


def test_non_checkout_install_requires_home(tmp_path: Path) -> None:
    site_packages = tmp_path / "Lib" / "site-packages" / "gridbot"
    site_packages.mkdir(parents=True)
    with pytest.raises(ConfigError, match="GRIDBOT_HOME"):
        resolve_project_root({}, site_packages)


def test_foreign_pyproject_is_not_accepted_as_root(tmp_path: Path) -> None:
    package_dir = make_checkout(tmp_path / "other", name="outro-projeto")
    with pytest.raises(ConfigError):
        resolve_project_root({}, package_dir)


def test_invalid_pyproject_is_not_accepted_as_root(tmp_path: Path) -> None:
    package_dir = make_checkout(tmp_path / "proj")
    (tmp_path / "proj" / "pyproject.toml").write_text("não é toml [", encoding="utf-8")
    with pytest.raises(ConfigError):
        resolve_project_root({}, package_dir)
