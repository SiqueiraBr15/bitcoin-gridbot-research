"""Flat PAPER generations do not extend operational authority or financial registries."""

import ast
from pathlib import Path

import pytest
from tests.architecture import test_paper_isolation
from tests.architecture.test_backtest_isolation import copied_project, inject
from tests.architecture.test_core_isolation import _identifiers, imported_modules
from tests.backtest.test_safe_recenter import command, runtime

from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import COMMAND_TYPES
from gridbot.paper.generations import PaperRecenter
from gridbot.storage.paper_codec import encode_command

ROOT = Path(__file__).resolve().parents[2]


def assert_durable_boundary(root: Path) -> None:
    for name in (
        "paper_codec.py",
        "paper_journal.py",
        "financial_codec.py",
        "operational_journal.py",
    ):
        text = (root / "src/gridbot/storage" / name).read_text(encoding="utf8")
        assert "PaperRecenter" not in text
        assert "gridbot.paper.generations" not in text


def test_generation_contracts_have_no_io_core_or_exchange_dependencies() -> None:
    tree = ast.parse((ROOT / "src/gridbot/paper/generations.py").read_text(encoding="utf8"))
    assert not any(
        m.startswith(
            (
                "os",
                "sys",
                "pathlib",
                "sqlite3",
                "gridbot.storage",
                "gridbot.exchange",
                "gridbot.config",
                "gridbot.backtest",
            )
        )
        for m in imported_modules(tree)
    )
    assert not _identifiers(tree) & {
        "core_qty",
        "Wallet",
        "Balance",
        "open",
        "connect",
        "eval",
        "exec",
        "float",
        "place_order",
        "cancel_order",
    }
    financial_types: tuple[type[object], ...] = COMMAND_TYPES
    assert PaperRecenter not in financial_types
    assert_durable_boundary(ROOT)
    with pytest.raises(DomainError):
        encode_command(command(runtime()))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "filename", ["storage/paper_journal.py", "application/rogue.py", "backtest/rogue_generation.py"]
)
def test_generation_allowance_cannot_expand_into_new_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    replica = copied_project(tmp_path)
    monkeypatch.setattr(test_paper_isolation, "ROOT", replica)
    if filename == "storage/paper_journal.py":
        # Journal's existing PAPER allowance must not gain generation awareness.
        assert_durable_boundary(replica)
        inject(replica, filename, "from gridbot.paper.generations import PaperRecenter")
        with pytest.raises(AssertionError):
            assert_durable_boundary(replica)
    else:
        inject(replica, filename, "from gridbot.paper.generations import PaperRecenter")
        with pytest.raises(AssertionError):
            test_paper_isolation.test_production_never_imports_paper_and_registry_stays_closed()
