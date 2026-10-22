import ast
from pathlib import Path

from tests.architecture.test_core_isolation import imported_modules

from gridbot.marketdata.archive_contract import ALLOWED_URLS

ROOT = Path(__file__).resolve().parents[2]


def test_network_edge_does_not_import_financial_or_operational_authority() -> None:
    for name in ["public_archives.py", "archive_contract.py"]:
        path = ROOT / "src/gridbot/marketdata" / name
        imports = imported_modules(ast.parse(path.read_text(encoding="utf8")))
        assert not any(
            m.startswith(
                (
                    "gridbot.paper",
                    "gridbot.application",
                    "gridbot.portfolio",
                    "gridbot.strategy",
                    "gridbot.backtest",
                    "gridbot.storage",
                    "gridbot.exchange",
                    "gridbot.config",
                )
            )
            for m in imports
        )
    for url in ALLOWED_URLS:
        assert url.startswith(
            "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-"
        )
        assert url.endswith((".zip", ".zip.CHECKSUM"))
        assert "?" not in url


def test_offline_archive_validation_cannot_import_acquisition_edge() -> None:
    for relative in ["backtest/archives.py", "marketdata/archive_contract.py"]:
        path = ROOT / "src/gridbot" / relative
        imports = imported_modules(ast.parse(path.read_text(encoding="utf8")))
        assert "gridbot.marketdata.public_archives" not in imports
        assert not any(m.startswith(("urllib", "http", "socket", "requests")) for m in imports)
