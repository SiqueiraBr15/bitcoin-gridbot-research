"""Two tiny synthetic PAPER paths with an independent asset-conservation oracle.

Prices 90..110 are deliberately fictional and are not historical Bitcoin data.
No files, clock, credentials, network or persistent trading state are used.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

from gridbot.backtest.data import HEADER, CsvFormat, Dataset, DatasetSpec
from gridbot.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from gridbot.backtest.execution import ExecutionPolicy, FeeModel, MixedPolicy
from gridbot.domain import (
    BTCUSDT,
    USDT,
    FeeSchedule,
    LiquidityRole,
    MarketRules,
    Money,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Side,
    Timeframe,
)
from gridbot.paper.simulation import PaperSimulation
from gridbot.strategy import ArithmeticGridSpec

START = datetime(2024, 1, 1, tzinfo=UTC)
PATHS = {
    "round_trip": ("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,10"),
    "falling_mark": ("100,110,90,105,10", "100,106,89,100,10", "90,91,69,70,10"),
}


def synthetic_run(name: str) -> BacktestResult:
    """Use the unchanged native runner and explicit miniature teaching inputs."""
    rows = [
        f"{(START + timedelta(minutes=i)).isoformat()},"
        f"{(START + timedelta(minutes=i + 1)).isoformat()},{values}"
        for i, values in enumerate(PATHS[name])
    ]
    raw = (",".join(HEADER) + "\n" + "\n".join(rows) + "\n").encode()
    dataset = Dataset(
        raw,
        DatasetSpec(
            "FICTIONAL_PRICES_NOT_BITCOIN_HISTORY",
            True,
            Timeframe.minutes(1),
            START,
            START + timedelta(minutes=len(rows)),
            CsvFormat.UTC_V1,
        ),
    )
    rules = MarketRules(
        BTCUSDT,
        PriceRules(Price.parse(".01")),
        QuantityRules(Qty.parse(".001"), Qty.parse(".001")),
        NotionalRules.parse("1"),
    )
    policy = ExecutionPolicy(
        FeeModel(
            FeeSchedule.parse(".001", ".002"),
            LiquidityRole.MAKER,
            LiquidityRole.TAKER,
            USDT,
            USDT,
            None,
        ),
        # Explicit zero spread/slippage, 50% participation; teaching inputs only.
        Decimal("0"),
        Decimal("0"),
        Decimal(".5"),
        timedelta(0),
        3,
        False,
        MixedPolicy.DEFER_MIXED,
    )
    config = BacktestConfig(
        ArithmeticGridSpec(BTCUSDT, Price.parse("90"), Price.parse("110"), 2),
        rules,
        Money.parse("100", USDT),
        Money.parse("90", USDT),
        policy,
        "SIM:PUBLIC_DEMO_" + name.upper(),
        1000,
        "Explicit fictional fees and filters; not authenticated market conditions",
        START,
        START + timedelta(days=1),
    )
    return run_backtest(dataset, config, code_commit="SYNTHETIC_PUBLIC_DEMO_V1")


def verify_conservation(result: BacktestResult) -> int:
    """Rebuild wallets from fills using rational arithmetic, independently of PAPER."""
    cash, btc = Fraction(result.config.initial_quote.amount), Fraction(0)
    filled = 0
    for point in result.points:
        while filled < len(result.trades) and result.trades[filled].observed_at <= point.time:
            trade = result.trades[filled]
            if trade.fee.asset != USDT:
                raise ValueError("This miniature oracle explicitly supports USDT fees only")
            quantity, price, fee = (
                Fraction(trade.qty.value),
                Fraction(trade.price.value),
                Fraction(trade.fee.amount),
            )
            if trade.side is Side.BUY:
                cash -= quantity * price + fee
                btc += quantity
            else:
                cash += quantity * price - fee
                btc -= quantity
            if cash < 0 or btc < 0:
                raise ValueError("Negative synthetic wallet")
            filled += 1
        actual_cash = Fraction(point.state.available_quote.amount) + Fraction(
            point.state.active_buy_reservations.amount
        )
        actual_btc = Fraction(point.state.remaining_grid_base.value)
        nav = cash + btc * Fraction(point.price.value)
        if (cash, btc, nav) != (actual_cash, actual_btc, Fraction(point.quote_btc_equity.amount)):
            raise ValueError("Conservation mismatch")
    if filled != len(result.trades):
        raise ValueError("A fill has no corresponding mark")
    replay = PaperSimulation.replay(result.sources, run_ref=result.config.run_ref, max_events=1000)
    if replay.snapshot() != result.points[-1].state:
        raise ValueError("Native command replay mismatch")
    return len(result.points)


def demonstrate() -> dict[str, object]:
    reports = []
    for name in PATHS:
        result = synthetic_run(name)
        verified = verify_conservation(result)
        final = result.points[-1]
        reports.append(
            {
                "scenario": name,
                "dataset_sha256": result.dataset_manifest["sha256"],
                "initial_usdt": str(result.config.initial_quote.amount),
                "commands": [
                    {"revision": event.revision, "kind": type(event.command).__name__}
                    for event in result.sources.events
                ],
                "fills": [
                    {
                        "side": trade.side.value,
                        "quantity_btc": str(trade.qty.value),
                        "price_usdt": str(trade.price.value),
                        "fee_usdt": str(trade.fee.amount),
                        "observed_at": trade.observed_at.isoformat(),
                    }
                    for trade in result.trades
                ],
                "final_available_usdt": str(final.state.available_quote.amount),
                "final_reserved_usdt": str(final.state.active_buy_reservations.amount),
                "final_physical_btc": str(final.state.remaining_grid_base.value),
                "final_mark_usdt": str(final.price.value),
                "final_nav_usdt": str(final.quote_btc_equity.amount),
                "verified_marks": verified,
                "rational_residual": "0",
                "native_replay_equal": True,
            }
        )
    return {
        "schema": "GRIDBOT_SYNTHETIC_DEMO_V1",
        "notice": "FICTIONAL_INPUTS_NOT_HISTORICAL_PERFORMANCE",
        "independent_accounts": True,
        "network_requests": 0,
        "real_orders": 0,
        "scenarios": reports,
    }


def main() -> None:
    print(json.dumps(demonstrate(), indent=2, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
