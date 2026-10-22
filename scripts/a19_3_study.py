"""Bounded-parent A19.3 study: native P0 finance, causal P1 observation, blocked P2."""

from __future__ import annotations

import argparse
from datetime import timedelta
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

from scripts.a19_2_study import worker, write

from gridbot.backtest import engine
from gridbot.backtest.data import BacktestError, Dataset, check
from gridbot.backtest.export import json_value
from gridbot.backtest.lifecycle import RangeObserver, plan_recenter
from gridbot.strategy import build_arithmetic_grid


def require_lifecycle_funding(config: engine.BacktestConfig) -> None:
    check(
        not config.third_asset_funding,
        "A19.3 lifecycle reference does not admit third-asset funding",
    )


def lifecycle_diagnostics(
    market: Dataset, result: engine.BacktestResult, policy: str
) -> dict[str, object]:
    cfg = result.config
    require_lifecycle_funding(cfg)
    observer = RangeObserver(build_arithmetic_grid(cfg.grid, cfg.rules), 168)
    candidates = []
    plans = []
    for bar in market.series:
        if policy == "P1":
            observer, candidate = observer.observe(bar)
            if candidate is not None:
                candidates.append(
                    dict(
                        close_time=bar.close_time,
                        reference=bar.close,
                        timeframe_seconds=bar.timeframe.duration // timedelta(seconds=1),
                        consecutive=candidate.consecutive,
                    )
                )
                plan = plan_recenter(candidate, cfg.rules)
                plans.append(
                    dict(
                        candidate_time=bar.close_time,
                        proposed=plan.proposed,
                        blockers=plan.blockers,
                        executable=plan.executable,
                    )
                )
    points = result.points
    cash_time = holds_time = btc_time = nav_time = Fraction()
    for left, right in pairwise(points):
        duration = (right.time - left.time) // timedelta(seconds=1)
        check(duration > 0, "ordered points required")
        cash_time += Fraction(left.state.available_quote.amount) * duration
        holds_time += Fraction(left.state.active_buy_reservations.amount) * duration
        btc_time += Fraction(left.btc_mark.amount) * duration
        nav_time += Fraction(left.quote_btc_equity.amount) * duration
    check(cash_time + holds_time + btc_time == nav_time, "capital-time conservation")
    final = points[-1]
    return dict(
        classification="EXPLORATORY_IN_SAMPLE",
        lifecycle_policy=policy,
        semantics="P1 causal closed-bar observer replay; no financial feedback into native P0",
        candidate_threshold=168,
        candidates=candidates,
        p2_plans=plans,
        p2_status="BLOCKED_NO_ATOMIC_MIGRATION",
        reconfigurations=0,
        reconfiguration_costs=[],
        no_forced_sale=True,
        outside_closed_bar_count=sum(
            not cfg.grid.lower_price <= bar.close <= cfg.grid.upper_price for bar in market.series
        ),
        outside_sample_duration_seconds=sum(
            bar.timeframe.duration // timedelta(seconds=1)
            for bar in market.series
            if not cfg.grid.lower_price <= bar.close <= cfg.grid.upper_price
        ),
        duration_semantics="closed-bar classification times interval duration, not intrabar dwell",
        bars_btc_positive=sum(p.state.remaining_grid_base.value > 0 for p in points),
        bars_buy_holds_positive=sum(p.state.active_buy_reservations.amount > 0 for p in points),
        bars_sell_reserves_positive=sum(p.state.reserved_grid_base.value > 0 for p in points),
        bars_no_armed_buy=sum(not any(c.can_buy for c in p.state.grid_state.cells) for p in points),
        cell_bar_waiting_sell=sum(
            c.phase.value == "WAITING_SELL" for p in points for c in p.state.grid_state.cells
        ),
        cash_time_fraction=cash_time / nav_time if nav_time else None,
        buy_hold_time_fraction=holds_time / nav_time if nav_time else None,
        btc_time_fraction=btc_time / nav_time if nav_time else None,
        cash_time_integral=cash_time,
        holds_time_integral=holds_time,
        btc_time_integral=btc_time,
        nav_time_integral=nav_time,
        integration="left samples first close to last close; first warmup hour excluded",
        idle_cash_reference=dict(
            initial_quote=cfg.initial_quote,
            final_equity=cfg.initial_quote,
            return_pct=Fraction(),
            max_drawdown=Fraction(),
            final_grid_btc="0",
            final_btc_equivalent=Fraction(cfg.initial_quote.amount) / Fraction(final.price.value),
            exposure=Fraction(),
            idle_fraction=Fraction(1),
            buys=0,
            sells=0,
            cycles=0,
            fees=[],
            proceeds="0",
            reconfigurations=0,
        ),
        grid_minus_cash=Fraction(final.quote_btc_equity.amount)
        - Fraction(cfg.initial_quote.amount),
        note="state and decision/barrier counts overlap; do not sum as exclusive causal durations",
    )


def study(dataset: Path, configuration: Path, output: Path, commit: str, policy: str) -> None:
    original = engine.run_backtest

    def observe(
        market: Dataset, cfg: engine.BacktestConfig, *, code_commit: str
    ) -> engine.BacktestResult:
        require_lifecycle_funding(cfg)
        result = original(market, cfg, code_commit=code_commit)
        write(output / "lifecycle.json", json_value(lifecycle_diagnostics(market, result, policy)))
        return result

    with patch.object(engine, "run_backtest", observe):
        worker(dataset, configuration, output, commit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--policy", choices=["P0", "P1"], required=True)
    args = parser.parse_args()
    try:
        study(args.dataset, args.configuration, args.output, args.code_commit, args.policy)
    except BacktestError as exc:
        write(
            args.output / "measurement.json",
            dict(status="BLOCKED_INVALID_EXPERIMENT", error=str(exc)),
        )
        raise
