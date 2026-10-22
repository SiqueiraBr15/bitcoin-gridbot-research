import ast
from pathlib import Path

from tests.architecture.test_core_isolation import imported_modules

from gridbot.paper.simulation import PaperSimulation

ROOT = Path(__file__).resolve().parents[2]


def test_simulation_only_imports_owned_pure_contracts_and_local_lock() -> None:
    tree = ast.parse((ROOT / "src/gridbot/paper/simulation.py").read_text(encoding="utf8"))
    allowed = {"__future__", "copy", "dataclasses", "enum", "threading"}
    for module in imported_modules(tree):
        assert module in allowed or module.startswith(
            (
                "gridbot.paper.accounting",
                "gridbot.paper.generations",
                "gridbot.domain",
                "gridbot.application",
                "gridbot.portfolio",
                "gridbot.strategy",
            )
        )
    forbidden = {
        "connect",
        "open",
        "read_text",
        "write_text",
        "api_key",
        "api_secret",
        "getenv",
        "environ",
        "place_order",
        "cancel_order",
        "wallet",
        "core_qty",
        "float",
        "eval",
        "exec",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in forbidden


def test_simulation_has_no_authority_inheritance_or_production_registry_entry() -> None:
    assert PaperSimulation.__bases__ == (object,)
    for path in [
        "storage/paper_codec.py",
        "storage/paper_journal.py",
        "storage/financial_codec.py",
        "storage/operational_journal.py",
        "config/modes.py",
    ]:
        text = (ROOT / "src/gridbot" / path).read_text(encoding="utf8")
        assert "PaperSimulation" not in text
        assert "SimulationSnapshot" not in text
