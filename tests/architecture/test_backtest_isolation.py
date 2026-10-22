import ast
import shutil
from dataclasses import fields
from pathlib import Path

import pytest
from tests.architecture import test_paper_isolation, test_sell_reconciliation_isolation
from tests.architecture.import_boundaries import imported_targets
from tests.architecture.test_core_isolation import imported_modules

from gridbot.backtest.engine import BacktestConfig, BacktestResult

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/gridbot/backtest"


def test_backtester_has_no_network_credentials_or_operational_execution_dependencies() -> None:
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf8"))
        imports = imported_modules(tree)
        forbidden = (
            "socket",
            "http",
            "urllib",
            "requests",
            "httpx",
            "ccxt",
            "binance",
            "random",
            "secrets",
            "uuid",
            "gridbot.config",
            "gridbot.exchange",
            "gridbot.storage.operational_journal",
        )
        assert not any(
            module == name or module.startswith(name + ".")
            for name in forbidden
            for module in imports
        )
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                assert name not in {
                    "now",
                    "utcnow",
                    "time",
                    "perf_counter",
                    "monotonic",
                    "getenv",
                    "place_order",
                    "cancel_order",
                    "get_balance",
                    "eval",
                    "exec",
                }


def test_pure_engine_and_views_cannot_import_io_or_production_authority() -> None:
    for filename in [
        "engine.py",
        "execution.py",
        "metrics.py",
        "paper_bridge.py",
        "lifecycle.py",
        "interruption.py",
        "recenter.py",
        "partial_grid.py",
    ]:
        tree = ast.parse((PACKAGE / filename).read_text(encoding="utf8"))
        assert not any(
            module.startswith(
                (
                    "os",
                    "sys",
                    "sqlite3",
                    "pathlib",
                    "gridbot.storage",
                    "gridbot.config",
                    "gridbot.exchange",
                )
            )
            for module in imported_modules(tree)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                assert name not in {
                    "open",
                    "read_text",
                    "read_bytes",
                    "write_text",
                    "write_bytes",
                    "connect",
                }
    assert BacktestResult.__bases__ == (object,)
    assert not (
        {f.name for f in fields(BacktestConfig)} & {"core", "core_btc", "wallet", "api_key"}
    )
    for filename in [
        "storage/financial_codec.py",
        "storage/operational_journal.py",
        "config/modes.py",
    ]:
        assert "BacktestResult" not in (ROOT / "src/gridbot" / filename).read_text(encoding="utf8")


def assert_no_reverse_dependency(root: Path) -> None:
    for path in (root / "src/gridbot").rglob("*.py"):
        if path.is_relative_to(root / "src/gridbot/backtest"):
            continue
        targets = imported_targets(ast.parse(path.read_text(encoding="utf8")), path, root / "src")
        assert not any(
            m == "gridbot.backtest" or m.startswith("gridbot.backtest.") for m in targets
        )


def test_existing_layers_cannot_depend_on_backtest() -> None:
    assert_no_reverse_dependency(ROOT)


def test_observers_and_interruption_gate_cannot_apply_financial_transitions() -> None:
    for name in ("lifecycle.py", "interruption.py"):
        tree = ast.parse((PACKAGE / name).read_text(encoding="utf8"))
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert not calls & {
            "apply",
            "settle_buy",
            "settle_sell",
            "confirm_sell",
            "confirm_buy",
            "PaperInitialState",
        }


def copied_project(tmp_path: Path) -> Path:
    replica = tmp_path / "replica"
    shutil.copytree(ROOT / "src/gridbot", replica / "src/gridbot")
    return replica


def inject(replica: Path, filename: str, statement: str) -> None:
    path = replica / "src/gridbot" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf8") as stream:
        stream.write("\n" + statement + "\n")


@pytest.mark.parametrize(
    ("filename", "statement"),
    [
        ("backtest/new_consumer.py", "from ..paper import simulation"),
        ("backtest/paper/rogue.py", "import gridbot.paper.simulation"),
        ("application/operational_grid.py", "from gridbot import paper"),
    ],
)
def test_paper_allowlist_rejects_unapproved_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, statement: str
) -> None:
    replica = copied_project(tmp_path)
    monkeypatch.setattr(test_paper_isolation, "ROOT", replica)
    test_paper_isolation.test_production_never_imports_paper_and_registry_stays_closed()
    inject(replica, filename, statement)
    with pytest.raises(AssertionError):
        test_paper_isolation.test_production_never_imports_paper_and_registry_stays_closed()


@pytest.mark.parametrize(
    ("filename", "statement"),
    [
        ("backtest/engine.py", "from ..application import sell_evidence"),
        ("backtest/new_consumer.py", "import gridbot.application.sell_reconciliation"),
    ],
)
def test_a17_bridge_exception_cannot_expand_to_other_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, statement: str
) -> None:
    replica = copied_project(tmp_path)
    files = [replica / p.relative_to(ROOT) for p in test_sell_reconciliation_isolation.FILES]
    monkeypatch.setattr(test_sell_reconciliation_isolation, "ROOT", replica)
    monkeypatch.setattr(test_sell_reconciliation_isolation, "FILES", files)
    test_sell_reconciliation_isolation.test_earlier_modules_never_import_a17()
    inject(replica, filename, statement)
    with pytest.raises(AssertionError):
        test_sell_reconciliation_isolation.test_earlier_modules_never_import_a17()


@pytest.mark.parametrize(
    "statement",
    [
        "import gridbot.backtest.engine",
        "from gridbot import backtest",
        "from .. import backtest",
    ],
)
def test_reverse_dependency_guard_detects_absolute_and_relative_imports(
    tmp_path: Path, statement: str
) -> None:
    replica = copied_project(tmp_path)
    assert_no_reverse_dependency(replica)
    inject(replica, "application/operational_grid.py", statement)
    with pytest.raises(AssertionError):
        assert_no_reverse_dependency(replica)
