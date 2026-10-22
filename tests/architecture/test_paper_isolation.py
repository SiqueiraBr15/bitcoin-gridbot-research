import ast
from pathlib import Path

import pytest
from tests.architecture.import_boundaries import imported_targets
from tests.architecture.test_core_isolation import CORE_STDLIB, _identifiers, imported_modules

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "src/gridbot/paper/accounting.py"


def test_paper_sources_are_pure_and_cannot_call_operational_journal() -> None:
    tree = ast.parse(PAPER.read_text(encoding="utf8"))
    for module in imported_modules(tree):
        assert module.split(".")[0] in CORE_STDLIB or module.startswith(
            ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio", "gridbot.application")
        )
    assert not _identifiers(tree) & {
        "OperationalStatePort",
        "SQLiteOperationalJournal",
        "connect",
        "open",
        "api_key",
        "ExchangePort",
        "Wallet",
        "Balance",
        "requests",
        "get_balance",
        "place_order",
        "core_qty",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"float", "eval", "exec"}
    book = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PaperBook")
    assert {
        n.target.id
        for n in book.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    } == {"initial", "entries"}
    assert not book.bases


def test_production_never_imports_paper_and_registry_stays_closed() -> None:
    allowed = {
        ROOT / "src/gridbot/storage/paper_codec.py",
        ROOT / "src/gridbot/storage/paper_journal.py",
        # A19 is an offline consumer of PAPER, with no operational authority.
        ROOT / "src/gridbot/backtest/engine.py",
        ROOT / "src/gridbot/backtest/metrics.py",
        ROOT / "src/gridbot/backtest/paper_bridge.py",
        ROOT / "src/gridbot/backtest/export.py",
        # A19.3 read-only capture/gate; cannot apply commands or resume execution.
        ROOT / "src/gridbot/backtest/interruption.py",
        # A19.4 flat-only offline executor and its explicitly versioned source envelope.
        ROOT / "src/gridbot/backtest/recenter.py",
        ROOT / "src/gridbot/backtest/generation_codec.py",
        # A19.6 bounded PAPER executor and its offline replay envelope.
        ROOT / "src/gridbot/backtest/partial_grid.py",
        ROOT / "src/gridbot/backtest/partial_sources.py",
    }
    for path in (ROOT / "src/gridbot").rglob("*.py"):
        if path.is_relative_to(ROOT / "src/gridbot/paper") or path in allowed:
            continue
        assert not any(
            m.startswith("gridbot.paper")
            for m in imported_targets(
                ast.parse(path.read_text(encoding="utf8")), path, ROOT / "src"
            )
        )
    journal = (ROOT / "src/gridbot/storage/paper_journal.py").read_text(encoding="utf8")
    assert "gridbot-paper.sqlite3" in journal
    assert (
        "GRIDBOT_PAPER_ACCOUNTING_181_V1"
        in (ROOT / "src/gridbot/storage/paper_codec.py").read_text()
    )
    assert "PaperBook" not in (ROOT / "src/gridbot/storage/financial_codec.py").read_text()


@pytest.mark.parametrize("name", ["paper_codec.py", "paper_journal.py"])
def test_paper_storage_cannot_read_credentials_or_activate_exchange(name: str) -> None:
    tree = ast.parse((ROOT / "src/gridbot/storage" / name).read_text(encoding="utf8"))
    modules = imported_modules(tree)
    assert not any(
        module.startswith(
            ("gridbot.config", "gridbot.cli", "gridbot.exchange", "requests", "http", "socket")
        )
        for module in modules
    )
    assert not _identifiers(tree) & {
        "api_key",
        "api_secret",
        "environ",
        "getenv",
        "ExchangePort",
        "OperationalStatePort",
        "SQLiteOperationalJournal",
        "place_order",
        "wallet",
        "core_qty",
        "exec",
        "eval",
    }
