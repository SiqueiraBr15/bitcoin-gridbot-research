"""A18 has source-only views and cannot apply effects or become journal authority."""

import ast
from pathlib import Path

from tests.architecture.test_core_isolation import _identifiers, imported_modules

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/gridbot/application/sell_economics.py"


def test_only_canonical_sources_and_no_financial_cache() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf8"))
    expected = {
        "SellEconomicAssessment": {"reconciliation"},
        "SellEconomicProjection": {"reconciliation"},
        "SellEconomicSettlementPlan": {
            "assessment",
            "current_book",
            "current_reference",
            "prior_claims",
        },
    }
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        if cls.name in expected:
            fields = {
                n.target.id
                for n in cls.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
            }
            assert fields == expected[cls.name]
    names = _identifiers(tree)
    assert not names & {
        "settle_funded_buy",
        "release_sell",
        "confirm_sell",
        "confirm_buy",
        "settle_operational_buy",
        "_persist",
        "execute",
        "commit",
        "connect",
        "apply_live_settlement",
        "float",
        "wallet",
        "core_qty",
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "replace"
        ):
            assert not {k.arg for k in node.keywords} & {
                "inventory_book",
                "reservations",
                "funded_buy_book",
                "grid_state",
                "fills",
            }


def test_older_production_modules_do_not_depend_on_a18() -> None:
    for path in (ROOT / "src/gridbot").rglob("*.py"):
        if path in (SOURCE, ROOT / "src/gridbot/paper/accounting.py"):
            continue
        assert "gridbot.application.sell_economics" not in imported_modules(
            ast.parse(path.read_text(encoding="utf8"))
        )
