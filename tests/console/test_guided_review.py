"""G5 presentation oracles use independent Fraction arithmetic and real HTTP."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from research_console.server import LocalServer
from tests.console.test_lab_http import call
from tests.console.test_lab_http import lab_server as lab_server


@pytest.mark.parametrize("name", ["favorable", "unfavorable", "risk_violation"])
def test_guided_api_snapshot_has_independent_wallet_and_risk_oracles(name: str) -> None:
    fixtures = json.loads(
        (Path(__file__).parents[1] / "fixtures/g5_guided_analysis.json").read_text()
    )
    fixture = next(f for f in fixtures["cases"] if f["study"]["pack_id"] == name)
    analysis: dict[str, Any] = fixture["analysis"]
    for account in analysis["accounts"]:
        row = next(r for r in analysis["rows"] if r["account_id"] == account["account_id"])
        metric = row["metrics"]["exact"]
        values = []
        for _, price, cash, btc, nav in account["points"]:
            assert Fraction(nav) == Fraction(cash) + Fraction(btc) * Fraction(price)
            values.append(Fraction(nav))
        last = account["points"][-1]
        peak_losses = [
            (values[i] - values[j]) / values[i]
            for i in range(len(values))
            for j in range(i, len(values))
        ]
        drawdown = max(peak_losses)
        assert Fraction(metric["nav_final"]) == values[-1]
        assert Fraction(metric["return_usdt"]) == values[-1] - values[0]
        assert Fraction(metric["return_ratio"]) == values[-1] / values[0] - 1
        assert Fraction(metric["btc_physical"]) == Fraction(last[3])
        assert Fraction(metric["btc_equivalent"]) == values[-1] / Fraction(last[1])
        assert Fraction(metric["cash_usdt"]) == Fraction(last[2])
        assert Fraction(metric["max_drawdown"]) == drawdown
        assert row["metrics"]["risk"]["violates_20_percent"] == (drawdown > Fraction(1, 5))
        assert row["benchmark"] == "CASH"
    assert len({r["group_id"] for r in analysis["rows"]}) == 1


@pytest.mark.parametrize("asset", ["review_model.js", "review_view.js"])
def test_guided_assets_have_same_origin_policy_and_fixed_allowlist(
    lab_server: tuple[LocalServer, str], asset: str
) -> None:
    server, cookie = lab_server
    status, body, headers = call(server, cookie, "/" + asset)
    assert status == 200
    assert b"GridGuidedReview" in body
    assert "javascript" in headers["Content-Type"]
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert call(server, cookie, "/" + asset + "/../server.py")[0] == 404
    assert call(server, cookie, "/api/lab/guided-review")[0] == 404
    assert call(server, cookie, "/" + asset, extra={"Origin": "https://example.invalid"})[0] == 403
