"""Independent predeclared A19.2 real study; simulated fills, unchanged finance.

Requires bounded parent watchdog. Never concatenate independently reset accounts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from typing import Any, ParamSpec, TypeVar
from unittest.mock import patch

from tests.capacity.paper_capacity import memory
from tests.paper.simulation_oracle import assert_source_conservation

from gridbot.backtest import data, engine
from gridbot.backtest import export as artifacts
from gridbot.backtest.configuration import dataset_spec, read_json, scenario
from gridbot.backtest.data import BacktestError, check
from gridbot.backtest.execution import ExecutionPolicy, VirtualOrder, crossed, selected_orders
from gridbot.backtest.metrics import Trade
from gridbot.domain import BTC, USDT, Candle, CandleSeries, Qty, Side
from gridbot.paper.simulation import PaperSimulation

P = ParamSpec("P")
R = TypeVar("R")


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf8")


def cycle_oracle(result: engine.BacktestResult) -> dict[str, object]:
    """Independent rational calculation from observed trades, including partials.

    Per-cycle costs below are identified whole BUY debit, not allocated fiscal PnL.
    All prefix points are independently checked against fills and retained BUY holds.
    Native source-command oracle separately proves that holds are authentic.
    """
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in result.trades:
        groups[str(trade.cycle_ref)].append(trade)
    cycles = []
    for ref, trades in groups.items():
        if not any(t.side is Side.SELL for t in trades):
            continue
        bought = sold = buy_base = sell_base = debit = proceeds = Fraction()
        for trade in trades:
            qty, price, fee = map(Fraction, (trade.qty.value, trade.price.value, trade.fee.amount))
            if trade.side is Side.BUY:
                bought += qty
                debit += qty * price + (fee if trade.fee.asset == USDT else 0)
                buy_base += fee if trade.fee.asset == BTC else 0
            else:
                sold += qty
                proceeds += qty * price - (fee if trade.fee.asset == USDT else 0)
                sell_base += fee if trade.fee.asset == BTC else 0
        cycles.append(
            dict(
                ref=ref,
                trades=artifacts.json_value(trades),
                bought=bought,
                sold=sold,
                buy_base_fee=buy_base,
                sell_base_fee=sell_base,
                btc_consumed=sold + sell_base,
                residual=bought - buy_base - sold - sell_base,
                identified_whole_buy_debit=debit,
                net_sell_proceeds=proceeds,
                realized_pnl=None,
            )
        )
    checked = 0
    for point in result.points:
        eligible = [t for t in result.trades if t.observed_at <= point.time]
        base = debit = credit = Fraction()
        for trade in eligible:
            qty, price, fee = map(Fraction, (trade.qty.value, trade.price.value, trade.fee.amount))
            if trade.side is Side.BUY:
                base += qty - (fee if trade.fee.asset == BTC else 0)
                debit += qty * price + (fee if trade.fee.asset == USDT else 0)
            else:
                base -= qty + (fee if trade.fee.asset == BTC else 0)
                credit += qty * price - (fee if trade.fee.asset == USDT else 0)
        held = Fraction(point.state.active_buy_reservations.amount)
        cash = Fraction(result.config.initial_quote.amount) - debit + credit - held
        nav = cash + held + base * Fraction(point.price.value)
        check(base == Fraction(point.state.remaining_grid_base.value), "independent BTC mismatch")
        check(cash == Fraction(point.state.available_quote.amount), "independent USDT mismatch")
        if point.equity is None:
            raise ValueError("diagnostic requires complete valuation")
        check(nav == Fraction(point.equity.amount), "independent NAV mismatch")
        check(cash >= 0, "negative cash")
        check(base >= Fraction(point.state.reserved_grid_base.value) >= 0, "BTC reserve mismatch")
        checked += 1
    return dict(cycles=cycles, points_checked=checked, tolerance="EXACT_ZERO")


def worker(dataset_path: Path, configuration: Path, output: Path, commit: str) -> None:
    begin = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    receipt = output / "measurement.json"
    stages: dict[str, dict[str, Any]] = {}
    order_counts: Counter[str] = Counter()
    terminals: list[dict[str, object]] = []

    def timed(name: str, function: Callable[P, R]) -> Callable[P, R]:
        def invoke(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                record = stages.setdefault(name, dict(calls=0, inclusive_s=0.0))
                record["calls"] += 1
                record["inclusive_s"] += time.perf_counter() - start

        return invoke

    write(receipt, dict(status="RUNNING", phase="ingestion", worker_pid=os.getpid()))
    wrappers = [
        (data, "_parse", "csv_parse_validation"),
        (Candle, "__post_init__", "candle_validation"),
        (CandleSeries, "__post_init__", "series_validation"),
        (engine._Runner, "schedule", "strategy"),
        (engine._Runner, "execute", "execution"),
        (engine._Runner, "benchmark", "benchmark"),
        (engine, "executable_quantity", "fill_quantity"),
        (engine._Runner, "reporting_snapshot", "native_reporting_views"),
        (PaperSimulation, "apply", "paper_accounting"),
        (engine, "equity_point", "metrics_points"),
        (engine, "summarize", "metrics_summary"),
    ]
    original_selection = selected_orders
    original_terminal = engine._Runner.terminal

    def selection(
        orders: tuple[VirtualOrder, ...], candle: Candle, policy: ExecutionPolicy
    ) -> tuple[tuple[VirtualOrder, ...], bool]:
        order_counts["candles_evaluated"] += 1
        if not orders:
            order_counts["candles_no_pending"] += 1
        chosen, ambiguous = original_selection(orders, candle, policy)
        for order in orders:
            order_counts["pending_order_bar_checks"] += 1
            if order.active_for(candle):
                order_counts["eligible_order_bar_checks"] += 1
                if not candle.low <= order.limit <= candle.high:
                    order_counts["limit_outside_bar"] += 1
                elif not crossed(order, candle, policy):
                    order_counts["penetration_or_buffer_refused"] += 1
                else:
                    order_counts["crossed_order_bar_checks"] += 1
            else:
                order_counts["not_yet_active_order_bar_checks"] += 1
        order_counts["selected_order_bar_checks"] += len(chosen)
        order_counts["ambiguous_candles"] += int(ambiguous)
        return chosen, ambiguous

    def terminal(runner: engine._Runner, order: VirtualOrder, qty: Qty, candle: Candle) -> None:
        age = runner.ages[order.ref]
        original_terminal(runner, order, qty, candle)
        terminals.append(
            dict(
                order=artifacts.json_value(order),
                qty=str(qty.value),
                observed_at=candle.close_time.isoformat(),
                eligible_age=age,
                outcome="FULL"
                if qty == order.qty
                else "NO_FILL"
                if qty.is_zero
                else "PARTIAL_CANCELED",
                reason=("TTL" if age >= runner.config.policy.ttl_bars else "PERIOD_END")
                if qty.is_zero
                else "SIMULATED_FILL",
                settled=order.ref not in runner.pending,
            )
        )

    with ExitStack() as contexts:
        contexts.enter_context(patch.object(engine, "selected_orders", selection))
        contexts.enter_context(patch.object(engine._Runner, "terminal", terminal))
        for owner, attribute, name in wrappers:
            contexts.enter_context(
                patch.object(owner, attribute, timed(name, getattr(owner, attribute)))
            )
        csv_path, spec = dataset_spec(read_json(dataset_path))
        start = time.perf_counter()
        dataset = data.read_csv(dataset_path.parent / csv_path, spec)
        ingestion = time.perf_counter() - start
        config = scenario(read_json(configuration))
        write(receipt, dict(status="RUNNING", phase="engine", worker_pid=os.getpid()))
        start = time.perf_counter()
        result = engine.run_backtest(dataset, config, code_commit=commit)
        execution = time.perf_counter() - start
        write(receipt, dict(status="RUNNING", phase="oracle", worker_pid=os.getpid()))
        start = time.perf_counter()
        conservation = assert_source_conservation(result.sources, result.points[-1].state)
        independent = cycle_oracle(result)
        oracle = time.perf_counter() - start
        start = time.perf_counter()
        manifest = artifacts.export_run(result, output / "artifacts", dataset=dataset)
        export = time.perf_counter() - start
    last = result.points[-1]
    summary = dict(
        status="PASS",
        scope="A19_2_INDEPENDENT_DECLARED_REAL_WINDOW",
        order_diagnostics=dict(order_counts),
        order_terminals=terminals,
        outside_range_candles=sum(
            not config.grid.lower_price <= c.close <= config.grid.upper_price
            for c in dataset.series
        ),
        last_fill=result.trades[-1].observed_at if result.trades else None,
        candles=len(dataset.series),
        dataset_sha256=dataset.sha256,
        source_events=result.sources.revision,
        metrics=result.metrics,
        benchmark=result.benchmark,
        comparison=artifacts.comparison(result.metrics, result.benchmark),
        decisions=dict(Counter(str(d.kind) for d in result.decisions)),
        details=dict(Counter(str(d.detail) for d in result.decisions)),
        buy_fills=sum(t.side is Side.BUY for t in result.trades),
        sell_fills=sum(t.side is Side.SELL for t in result.trades),
        conservation=conservation,
        independent_oracle=independent,
        recycled_proceeds_upper_bound=result.metrics.settled_sell_proceeds,
        recycled_spending_initial_capital_first_lower_bound=max(
            Fraction(),
            Fraction(result.metrics.buy_spending.amount) - Fraction(config.initial_quote.amount),
        ),
        final_nav_oracle=(
            Fraction(last.state.available_quote.amount)
            + Fraction(last.state.active_buy_reservations.amount)
            + Fraction(last.state.remaining_grid_base.value) * Fraction(last.price.value)
        ),
        limitations=result.cost_limitations,
        no_intrabar_drawdown=True,
        realized_pnl=None,
    )
    write(output / "study_results.json", artifacts.json_value(summary))
    with (output / "btc_position.csv").open("w", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            ["close_time_utc", "btc", "reserved_btc", "btc_equivalent", "benchmark_btc"]
        )
        for point, bh in zip(result.points, result.benchmark_points, strict=True):
            writer.writerow(
                [
                    point.time.isoformat(),
                    point.state.remaining_grid_base.value,
                    point.state.reserved_grid_base.value,
                    Fraction(point.quote_btc_equity.amount) / Fraction(point.price.value),
                    bh.state.remaining_grid_base.value,
                ]
            )
    write(
        receipt,
        dict(
            status="PASS",
            worker_pid=os.getpid(),
            elapsed_s=time.perf_counter() - begin,
            ingestion_s=ingestion,
            engine_s=execution,
            oracle_s=oracle,
            export_s=export,
            stages=stages,
            memory=memory(os.getpid()),
            artifact_manifest=manifest,
            note="Inclusive timings overlap; independent interval; no joining account resets.",
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    try:
        worker(args.dataset, args.configuration, args.output, args.code_commit)
    except BacktestError as exc:
        write(
            args.output / "measurement.json",
            dict(status="BLOCKED_INVALID_EXPERIMENT", error=str(exc), worker_pid=os.getpid()),
        )
        raise
