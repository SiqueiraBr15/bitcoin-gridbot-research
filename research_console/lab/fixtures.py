"""Hand-authored fictional observations, not historical prices or backtests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Any

from research_console.lab.packs import write_pack
from research_console.risk import display


def metadata(name: str, end: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pack_id": name,
        "title": "SYNTHETIC DEMO " + name,
        "source_kind": "SYNTHETIC_DEMO",
        "data_nature": "SYNTHETIC",
        "flow_convention": "NO_EXTERNAL_FLOWS_DECLARED",
        "created_at": "2020-01-01T00:00:00+00:00",
        "dataset_identity": name,
        "producer_version": "G4_FIXTURES_V1",
        "study_identity": name,
        "start": "2020-01-01T00:00:00+00:00",
        "end": end,
        "timezone": "UTC",
        "currency": "USDT",
        "units": ["UTC", "USDT_PER_BTC", "USDT", "BTC", "USDT"],
        "sampling_seconds": 86400,
        "license": "CC0-1.0",
        "redistribution": "PUBLIC",
        "limitations": [
            "Preços inteiramente fictícios",
            "Sem fluxos externos declarados",
            "Taxas zero apenas nesta fixture matemática",
            "Não é desempenho de estratégia",
        ],
    }


def example(name: str, prices: list[str]) -> bytes:
    times = [
        (datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i)).isoformat()
        for i in range(len(prices))
    ]
    accounts = []
    for policy, cash, btc in (("BTC_HOLD", "0", "10"), ("CASH", "100", "0"), ("MIX", "50", "5")):
        points = [
            [t, p, cash, btc, display(Fraction(cash) + Fraction(btc) * Fraction(p))]
            for t, p in zip(times, prices, strict=True)
        ]
        accounts.append(
            {
                "account_id": policy,
                "policy": policy,
                "benchmark": "CASH",
                "window_id": name,
                "cost_scenario": "SYNTHETIC_ZERO_COST",
                "start": times[0],
                "end": times[-1],
                "initial_nav": points[0][4],
                "fees_usdt": "0",
                "points": points,
            }
        )
    return write_pack(metadata(name, times[-1]), {"accounts": accounts, "aggregates": []})


def bundled() -> dict[str, bytes]:
    return {
        "favorable": example("favorable", ["10", "11", "12", "13"]),
        "unfavorable": example("unfavorable", ["10", "9.5", "9", "8.5"]),
        "risk_violation": example("risk_violation", ["10", "9", "7", "10", "8", "6"]),
    }
