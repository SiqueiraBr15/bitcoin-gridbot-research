"""Public demo contracts, including corrupted fill evidence and no hidden IO."""

import socket
import urllib.request
from dataclasses import replace
from decimal import Decimal
from typing import Any, NoReturn

import pytest
from examples.paper_cycle import demonstrate, synthetic_run, verify_conservation

from gridbot.domain import USDT, Money


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    def reject_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("The public demonstration must not access the network")

    with pytest.MonkeyPatch.context() as guard:
        guard.setattr(socket.socket, "connect", reject_network)
        guard.setattr(urllib.request, "urlopen", reject_network)
        return demonstrate()


def test_public_demo_has_two_independent_wallets_and_a_losing_path(
    report: dict[str, Any],
) -> None:
    assert report["notice"] == "FICTIONAL_INPUTS_NOT_HISTORICAL_PERFORMANCE"
    assert report["network_requests"] == report["real_orders"] == 0
    scenarios = report["scenarios"]
    assert {r["scenario"] for r in scenarios} == {"round_trip", "falling_mark"}
    assert all(r["initial_usdt"] == "100" for r in scenarios)
    assert all(r["native_replay_equal"] and r["rational_residual"] == "0" for r in scenarios)
    assert any(Decimal(r["final_nav_usdt"]) < 100 for r in scenarios)
    assert any(f["side"] == "SELL" for r in scenarios for f in r["fills"])
    assert any(e["kind"] == "PaperPrepareBuy" for r in scenarios for e in r["commands"])


def test_public_demo_is_deterministic(report: dict[str, Any]) -> None:
    assert demonstrate() == report


def test_rational_oracle_rejects_corrupted_fee() -> None:
    result = synthetic_run("round_trip")
    changed = replace(result.trades[0], fee=Money.parse("1", USDT))
    corrupted = replace(result, trades=(changed, *result.trades[1:]))
    with pytest.raises(ValueError, match="Conservation"):
        verify_conservation(corrupted)
