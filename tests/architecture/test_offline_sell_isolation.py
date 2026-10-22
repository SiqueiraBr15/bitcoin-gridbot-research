"""A17.2: ACL pura depende do core; o core nunca depende da ACL Binance."""

import ast
from pathlib import Path

import pytest
from tests.architecture.test_core_isolation import CORE_STDLIB, _identifiers, imported_modules

SRC = Path(__file__).resolve().parents[2] / "src/gridbot"
FILES = [
    SRC / "application/sell_candidate.py",
    *sorted((SRC / "exchange/binance").glob("offline_*.py")),
]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_offline_layers_have_no_io_and_no_financial_effects(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module in imported_modules(tree):
        assert module.split(".")[0] in CORE_STDLIB | {"json"} or module.startswith(
            ("gridbot.application", "gridbot.domain", "gridbot.exchange.binance.offline_")
        )
    names = _identifiers(tree)
    assert not names & {
        "confirm_sell",
        "settle_sell",
        "release_sell",
        "FinalizedSell",
        "finalize_sell",
        "ExchangePort",
        "Balance",
        "Wallet",
        "Core",
        "connect",
        "Path",
        "open",
        "write_text",
        "read_text",
        "datetime",
        "time",
        "uuid",
        "random",
        "sqlite3",
        "requests",
        "httpx",
        "websockets",
        "api_key",
        "place_order",
        "cancel_order",
        "getcontext",
        "setcontext",
        "quantize",
        "FeeSchedule",
        "pnl",
        "trusted",
    }
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"
        for n in ast.walk(tree)
    )


def test_all_core_layers_never_import_binance_acl() -> None:
    for package in ("domain", "strategy", "portfolio", "application", "risk", "execution"):
        for path in (SRC / package).rglob("*.py"):
            assert not any(
                m.startswith("gridbot.exchange")
                for m in imported_modules(ast.parse(path.read_text(encoding="utf-8")))
            )


def test_candidate_and_replay_store_sources_without_mutable_authority_cache() -> None:
    from dataclasses import fields

    from gridbot.application.sell_candidate import SellFinalizationCandidate
    from gridbot.exchange.binance.offline_replay import OfflineSellReplay, OfflineSellTape

    assert {f.name for f in fields(SellFinalizationCandidate)} == {"assessment"}
    assert {f.name for f in fields(OfflineSellReplay)} == {"book", "tape", "plan"}
    assert {f.name for f in fields(OfflineSellTape)} == {"observations"}
