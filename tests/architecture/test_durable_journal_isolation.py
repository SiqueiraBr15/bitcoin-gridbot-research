"""A17.3 permite SQLite somente atrás dos contratos puros de autoridade local."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tests.architecture.test_core_isolation import _identifiers, imported_modules

SRC = Path(__file__).resolve().parents[2] / "src/gridbot"
NEW_FILES = [
    SRC / "application/operational_persistence.py",
    SRC / "storage/financial_codec.py",
    SRC / "storage/journal_models.py",
    SRC / "storage/journal_paths.py",
    SRC / "storage/operational_journal.py",
    SRC / "storage/journal_backup.py",
]


@pytest.mark.parametrize("path", NEW_FILES, ids=lambda path: path.name)
def test_persistence_never_sends_orders_settles_sell_or_converts_to_float(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf8"))
    assert not _identifiers(tree) & {
        "confirm_sell",
        "settle_sell",
        "finalize_sell",
        "FinalizedSell",
        "Balance",
        "Wallet",
        "place_order",
        "send_order",
        "cancel_order",
        "get_balance",
        "FeeSchedule",
        "getcontext",
        "setcontext",
        "quantize",
        "pickle",
        "eval",
        "exec",
        "__import__",
        "requests",
        "httpx",
        "socket",
        "websockets",
        "aiohttp",
        "ccxt",
    }
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "confirm_sell"
        for node in ast.walk(tree)
    )


def test_sql_and_filesystem_remain_outside_economic_core() -> None:
    for package in ("domain", "strategy", "portfolio", "application"):
        for path in (SRC / package).rglob("*.py"):
            modules = imported_modules(ast.parse(path.read_text(encoding="utf8")))
            assert not any(
                module.startswith(("sqlite3", "gridbot.storage", "gridbot.infra"))
                for module in modules
            )


def test_write_port_has_commands_and_no_unrestricted_snapshot_save() -> None:
    from inspect import signature

    from gridbot.application.operational_persistence import OperationalStatePort
    from gridbot.storage.operational_journal import SQLiteOperationalJournal

    assert {name for name in vars(OperationalStatePort) if not name.startswith("_")} == {
        "load_operational_state",
        "commit_operational_transition",
    }
    args = set(signature(SQLiteOperationalJournal.commit_operational_transition).parameters)
    assert {"scope", "expected_revision", "transition"} <= args
    assert not args & {"next_state", "new_book", "callback", "function"}
    assert not hasattr(SQLiteOperationalJournal, "save")


def test_codec_has_literal_registry_and_known_fields_without_dynamic_import() -> None:
    from dataclasses import fields

    from gridbot.storage.financial_codec import _CONTRACTS

    for name, (cls, names) in _CONTRACTS.items():
        assert name == cls.__name__
        assert names == tuple(field.name for field in fields(cls))
