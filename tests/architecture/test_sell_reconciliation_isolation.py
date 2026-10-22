"""Fronteira A17: observação e diagnóstico, sem efeito econômico nem prova fictícia."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tests.architecture.import_boundaries import imported_targets
from tests.architecture.test_core_isolation import CORE_STDLIB, _identifiers, imported_modules

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    ROOT / "src/gridbot/application" / name
    for name in (
        "sell_evidence.py",
        "sell_reconciliation.py",
        "sell_order_binding.py",
        "sell_terminal.py",
        "sell_economics.py",
    )
]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_a17_imports_only_pure_layers(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module in imported_modules(tree):
        assert module.split(".")[0] in CORE_STDLIB or module.startswith(
            ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio", "gridbot.application")
        )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_effects_precision_changes_io_or_finalization_proof(path: Path) -> None:
    names = _identifiers(ast.parse(path.read_text(encoding="utf-8")))
    forbidden = {
        "confirm_sell",
        "confirm_buy",
        "settle_sell",
        "release_sell",
        "ExchangePort",
        "Balance",
        "Wallet",
        "FeeSchedule",
        "FinalizedSell",
        "finalize_sell",
        "is_complete",
        "open",
        "read_text",
        "write_text",
        "connect",
        "sqlite3",
        "Path",
        "datetime",
        "time",
        "uuid",
        "random",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
        "api_key",
        "get_balance",
        "place_order",
        "cancel_order",
        "pnl",
        "harvest",
    }
    assert not names & forbidden
    # Reconhecer float para recusá-lo é obrigatório; conversão para float é proibida.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
        for node in ast.walk(tree)
    )


def test_earlier_modules_never_import_a17() -> None:
    for path in sorted((ROOT / "src/gridbot").rglob("*.py")):
        if path in FILES or path in (
            ROOT / "src/gridbot/application/__init__.py",
            ROOT / "src/gridbot/application/sell_order_binding.py",
            ROOT / "src/gridbot/application/sell_candidate.py",
            ROOT / "src/gridbot/exchange/binance/offline_evidence.py",
            ROOT / "src/gridbot/exchange/binance/offline_replay.py",
            ROOT / "src/gridbot/exchange/binance/offline_terminal.py",
            ROOT / "src/gridbot/storage/financial_codec.py",
            ROOT / "src/gridbot/storage/journal_models.py",
            ROOT / "src/gridbot/storage/operational_journal.py",
            ROOT / "src/gridbot/storage/paper_codec.py",
            ROOT / "src/gridbot/paper/accounting.py",
            # Only this A19 bridge constructs native synthetic SELL evidence.
            ROOT / "src/gridbot/backtest/paper_bridge.py",
        ):
            continue
        modules = imported_targets(ast.parse(path.read_text(encoding="utf-8")), path, ROOT / "src")
        assert not modules & {
            "gridbot.application.sell_evidence",
            "gridbot.application.sell_reconciliation",
        }


def test_assessment_does_not_store_decision_financial_cache_or_mutate_root_fields() -> None:
    tree = ast.parse(FILES[1].read_text(encoding="utf-8"))
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SellReconciliationAssessment"
    )
    fields = {
        n.target.id
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    assert fields == {"book", "ledger", "report", "collection"}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "replace"
        ):
            assert not {kw.arg for kw in node.keywords} & {
                "inventory_book",
                "reservations",
                "funded_buy_book",
                "grid_state",
                "sell_attempts",
                "fills",
                "base_fee_hold",
                "external_sell_bindings",
            }


def test_binding_has_only_identity_and_side_and_no_inverse_dependencies() -> None:
    tree = ast.parse(FILES[2].read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ExternalSellOrderBinding"
    )
    assert {
        n.target.id
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    } == {"identity", "side"}
    assert "gridbot.application.operational_grid" not in imported_modules(tree)
    root = ROOT / "src/gridbot/application/operational_grid.py"
    modules = imported_modules(ast.parse(root.read_text(encoding="utf-8")))
    assert "gridbot.application.sell_order_binding" in modules
    assert "gridbot.application.sell_reconciliation" not in modules
    for layer in ("domain", "strategy", "portfolio"):
        for path in (ROOT / "src/gridbot" / layer).glob("*.py"):
            assert not any(
                m.startswith("gridbot.application")
                for m in imported_modules(ast.parse(path.read_text(encoding="utf-8")))
            )
