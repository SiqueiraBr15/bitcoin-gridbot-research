"""Finite offline P0/P2/P2L worker. Invoke under a bounded parent watchdog.

No download, configuration mutation, parameter search or trading credentials.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from fractions import Fraction
from pathlib import Path

from scripts.a19_4_study import closed_bar, decision_record
from tests.capacity.paper_capacity import memory

from gridbot.backtest.configuration import configuration, dataset_spec, read_json, scenario
from gridbot.backtest.data import check, read_csv
from gridbot.backtest.export import _sources, json_value
from gridbot.backtest.metrics import EquityPoint, Trade
from gridbot.backtest.partial_grid import PartialDecision, run_partial_backtest
from gridbot.backtest.partial_sources import encode_partial_sources, replay_partial_sources
from gridbot.backtest.recenter import run_recenter_backtest
from gridbot.domain import BTC, USDT, Money, Side
from gridbot.paper.simulation import PaperSimulation
from gridbot.paper.two_generation import PartialSourceLog


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(json_value(value), sort_keys=True, indent=2) + "\n", encoding="utf8")


def partial_decision_record(decision: PartialDecision) -> dict[str, object]:
    plan = decision.plan
    return dict(
        at=decision.at,
        applied=decision.applied,
        blocker=decision.blocker,
        plan=None
        if plan is None
        else dict(
            revision=plan.revision,
            generation_ref=plan.generation_ref,
            mark=plan.mark,
            costs=plan.costs,
            notional_ceiling=plan.notional_ceiling,
            configuration_ref=plan.configuration_ref,
            allocation=plan.allocation,
            signal=[closed_bar(c) for c in plan.signal],
        ),
    )


def oracle(
    points: tuple[EquityPoint, ...], trades: tuple[Trade, ...], initial: Money
) -> dict[str, object]:
    cash, base, spending, proceeds = Fraction(initial.amount), Fraction(), Fraction(), Fraction()
    for point in points:
        for trade in trades:
            if trade.observed_at != point.time:
                continue
            q, fee = Fraction(trade.qty.value), Fraction(trade.fee.amount)
            notional = Fraction(trade.price.value) * q
            if trade.side is Side.BUY:
                debit = notional + (fee if trade.fee.asset == USDT else 0)
                cash -= debit
                spending += debit
                base += q - (fee if trade.fee.asset == BTC else 0)
            else:
                credit = notional - (fee if trade.fee.asset == USDT else 0)
                cash += credit
                proceeds += credit
                base -= q + (fee if trade.fee.asset == BTC else 0)
        s = point.state
        check(
            cash == Fraction(s.available_quote.amount) + Fraction(s.active_buy_reservations.amount),
            "Fraction cash mismatch",
        )
        check(base == Fraction(s.remaining_grid_base.value), "Fraction BTC mismatch")
        check(
            spending == Fraction(s.buy_spending.amount)
            and proceeds == Fraction(s.settled_sell_proceeds.amount),
            "Fraction flow mismatch",
        )
        check(
            cash + base * Fraction(point.price.value) == Fraction(point.quote_btc_equity.amount),
            "Fraction NAV mismatch",
        )
        check(
            s.available_quote.amount >= 0 and base >= Fraction(s.reserved_grid_base.value) >= 0,
            "negative/overreserved asset",
        )
    return dict(
        points=len(points),
        tolerance="EXACT_ZERO",
        cash=cash,
        grid_base=base,
        buy_spending=spending,
        settled_proceeds=proceeds,
    )


def worker(dataset_path: Path, config_path: Path, output: Path, policy: str, commit: str) -> None:
    begin = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    receipt = output / "measurement.json"
    write(receipt, dict(status="RUNNING", worker_pid=os.getpid()))
    try:
        filename, spec = dataset_spec(read_json(dataset_path))
        market = read_csv((dataset_path.parent / filename).resolve(), spec)
        config = scenario(read_json(config_path))
        write(output / "configuration.json", configuration(config))
        if policy == "P2L":
            partial = run_partial_backtest(market, config, code_commit=commit)
            metrics, benchmark = partial.metrics, partial.benchmark
            points, bh_points = partial.points, partial.benchmark_points
            trades, bh_trades = partial.trades, partial.benchmark_trades
            sources, bh_sources = partial.sources, partial.benchmark_sources
            lifecycle: object = [partial_decision_record(d) for d in partial.candidates]
            extra = dict(
                new_generations=partial.new_generations,
                new_buys=partial.new_buys,
                legacy_sells=partial.legacy_sells,
                base_by_generation=partial.base_by_generation,
            )
        else:
            native = run_recenter_backtest(
                market,
                config,
                code_commit=commit,
                policy=policy,
                configuration_ref="CFG:A19_4:"
                + hashlib.sha256(config_path.read_bytes()).hexdigest(),
            )
            result = native.result
            metrics, benchmark = result.metrics, result.benchmark
            points, bh_points = result.points, result.benchmark_points
            trades, bh_trades = result.trades, result.benchmark_trades
            sources, bh_sources = result.sources, result.benchmark_sources
            lifecycle = [decision_record(d) for d in native.decisions]
            extra = dict(
                new_generations=sum(d.applied for d in native.decisions),
                new_buys=None,
                legacy_sells=None,
                base_by_generation=None,
            )
        source_file = output / "paper_sources.json"
        if isinstance(sources, PartialSourceLog):
            encoded = encode_partial_sources(sources)
            source_file.write_text(encoded + "\n", encoding="utf8")
            rebuilt = replay_partial_sources(encoded, max_events=config.max_events)
            check(rebuilt.snapshot() == points[-1].state, "encoded recovery mismatch")
        else:
            _sources(source_file, sources)
            replay = PaperSimulation.replay(
                sources, run_ref=sources.run_ref, max_events=config.max_events
            )
            check(replay.snapshot() == points[-1].state, "native recovery mismatch")
        _sources(output / "benchmark_sources.jsonl", bh_sources)
        oracles = dict(
            grid=oracle(points, trades, config.initial_quote),
            benchmark=oracle(bh_points, bh_trades, config.initial_quote),
        )
        write(output / "operations.json", trades)
        write(output / "benchmark_operations.json", bh_trades)
        write(output / "lifecycle.json", lifecycle)
        with (output / "equity.csv").open("w", encoding="utf8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(
                (
                    "time",
                    "mark",
                    "grid_nav",
                    "bh_nav",
                    "available_usdt",
                    "buy_holds_usdt",
                    "grid_btc",
                    "sell_holds_btc",
                    "revision",
                )
            )
            for grid, bh in zip(points, bh_points, strict=True):
                check(grid.equity is not None and bh.equity is not None, "incomplete valuation")
                if grid.equity is None or bh.equity is None:
                    raise ValueError("valuation required")
                s = grid.state
                writer.writerow(
                    (
                        grid.time.isoformat(),
                        grid.price.value,
                        grid.equity.amount,
                        bh.equity.amount,
                        s.available_quote.amount,
                        s.active_buy_reservations.amount,
                        s.remaining_grid_base.value,
                        s.reserved_grid_base.value,
                        s.revision,
                    )
                )
        write(
            output / "result.json",
            dict(
                classification="EXPLORATORY_IN_SAMPLE",
                policy=policy,
                code_commit=commit,
                dataset=market.manifest(),
                metrics=metrics,
                benchmark=benchmark,
                maximum_close_exposure=max(
                    (p.exposure for p in points if p.exposure is not None), default=None
                ),
                final_state=points[-1].state,
                oracle=oracles,
                **extra,
                paper_sources_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
                configuration_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
            ),
        )
        write(
            receipt,
            dict(
                status="PASS",
                worker_pid=os.getpid(),
                elapsed_s=str(time.perf_counter() - begin),
                memory=memory(os.getpid()),
            ),
        )
    except Exception as exc:
        write(
            receipt,
            dict(
                status="BLOCKED",
                worker_pid=os.getpid(),
                elapsed_s=str(time.perf_counter() - begin),
                error_type=type(exc).__name__,
                error=str(exc),
                memory=memory(os.getpid()),
            ),
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policy", required=True, choices=("P0", "P2", "P2L"))
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    worker(args.dataset, args.configuration, args.output, args.policy, args.code_commit)


if __name__ == "__main__":
    main()
