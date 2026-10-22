"""Reproducible informational artifacts in a new directory; no overwrite or activation."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

from gridbot.backtest.configuration import configuration, integer, parse_json, text
from gridbot.backtest.configuration import fields as object_fields
from gridbot.backtest.data import MAX_BYTES, Dataset, check
from gridbot.backtest.engine import BacktestResult
from gridbot.backtest.generation_codec import decode_generation, encode_generation
from gridbot.backtest.metrics import Metrics
from gridbot.domain import BTC, Money
from gridbot.domain.decimals import financial
from gridbot.paper.generations import PaperRecenter
from gridbot.paper.simulation import PaperSimulation, SimulationEvent, SimulationLog
from gridbot.storage.paper_codec import (
    decode_command,
    decode_initial,
    encode_command,
    encode_initial,
)


def json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Fraction):
        return dict(numerator=value.numerator, denominator=value.denominator)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        check(all(type(k) is str for k in value), "text JSON keys required")
        return {k: json_value(v) for k, v in value.items()}
    raise TypeError("unsupported artifact value; floats are forbidden")


def _json(value: object) -> str:
    return json.dumps(json_value(value), ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def comparison(grid: Metrics, benchmark: Metrics) -> dict[str, object]:
    complete = grid.final_equity is not None and benchmark.final_equity is not None
    status = "INCOMPLETE_VALUATION"
    difference: Money | None = None
    if complete and grid.final_equity is not None and benchmark.final_equity is not None:
        difference = grid.final_equity - benchmark.final_equity
        status = (
            "GRID_ABOVE_BUY_AND_HOLD"
            if difference.amount > 0
            else "GRID_BELOW_BUY_AND_HOLD"
            if difference.amount < 0
            else "EQUAL_EQUITY"
        )
    if benchmark.fills == 0 and benchmark.initial_quote.amount > 0:
        status = "BENCHMARK_NOT_EXECUTED"
        difference = None
    with financial():
        btc_difference = Money(grid.final_grid_btc.value - benchmark.final_grid_btc.value, BTC)
    return dict(
        status=status,
        equity_difference=difference,
        physical_btc_difference=btc_difference,
        physical_btc_and_equity_are_independent=True,
    )


def _csv(path: Path, header: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _sources(path: Path, log: SimulationLog) -> None:
    with path.open("w", encoding="utf8", newline="") as stream:
        header = dict(
            version=log.version,
            run_ref=log.run_ref,
            revision=log.revision,
            initial=json.loads(encode_initial(log.initial)),
        )
        head = json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n"
        size = len(head)
        check(size <= MAX_BYTES, "exported source replay quota exceeded")
        stream.write(head)
        for event in log.events:
            line = (
                json.dumps(
                    dict(
                        run_ref=event.run_ref,
                        revision=event.revision,
                        command=json.loads(
                            encode_generation(event.command)
                            if isinstance(event.command, PaperRecenter)
                            else encode_command(event.command)
                        ),
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            size += len(line)  # ensure_ascii=True: byte count equals character count.
            check(size <= MAX_BYTES, "exported source replay quota exceeded")
            stream.write(line)


def replay_sources(path: Path, *, max_events: int) -> PaperSimulation:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    check(len(raw) <= MAX_BYTES, "exported source replay quota exceeded")
    rows = raw.decode("utf8").splitlines()
    check(1 <= len(rows) <= 10_001, "bounded complete source log required")
    header = object_fields(parse_json(rows[0]), "version run_ref revision initial")
    version = integer(header["version"])
    check(version in (1, 2), "unknown source wrapper version")
    initial = decode_initial(json.dumps(header["initial"]))
    events = []
    for row in rows[1:]:
        event = object_fields(parse_json(row), "run_ref revision command")
        events.append(
            SimulationEvent(
                text(event["run_ref"]),
                integer(event["revision"]),
                decode_generation(json.dumps(event["command"]))
                if type(event["command"]) is dict and "recenter_schema" in event["command"]
                else decode_command(json.dumps(event["command"])),
            )
        )
    run_ref = text(header["run_ref"])
    log = SimulationLog(run_ref, initial, tuple(events), integer(header["revision"]), version)
    return PaperSimulation.replay(log, run_ref=run_ref, max_events=max_events)


def _amount(value: Money | None) -> str:
    return "INCOMPLETE" if value is None else str(value.amount) + " " + value.asset.code


def markdown(result: BacktestResult) -> str:
    manifest = result.dataset_manifest
    source_kind = (
        "SYNTHETIC TEST DATA — NOT HISTORICAL PROFITABILITY"
        if manifest["synthetic"]
        else "DECLARED HISTORICAL DATA — OFFLINE SOURCE"
    )
    rows = []
    for label, g, b in [
        (
            "Final equity MTM",
            _amount(result.metrics.final_equity),
            _amount(result.benchmark.final_equity),
        ),
        (
            "Available USDT",
            _amount(result.metrics.available_quote),
            _amount(result.benchmark.available_quote),
        ),
        (
            "Physical BTC",
            str(result.metrics.final_grid_btc.value),
            str(result.benchmark.final_grid_btc.value),
        ),
        (
            "BTC equivalent (exact ratio)",
            str(result.metrics.final_btc_equivalent),
            str(result.benchmark.final_btc_equivalent),
        ),
        (
            "Return percent (exact ratio)",
            str(result.metrics.return_pct),
            str(result.benchmark.return_pct),
        ),
        (
            "Max drawdown (fraction)",
            str(result.metrics.max_drawdown),
            str(result.benchmark.max_drawdown),
        ),
        ("Fills", str(result.metrics.fills), str(result.benchmark.fills)),
        ("Complete GRID cycles", str(result.metrics.cycles), "not applicable"),
    ]:
        rows.append(f"| {label} | {g} | {b} |")
    compared = comparison(result.metrics, result.benchmark)
    return (
        f"# GridBot offline backtest\n\n{source_kind}\n\n"
        f"Code version supplied: `{result.code_commit}`. "
        f"Dataset SHA256: `{manifest['sha256']}`.\n\n"
        f"Origin: {manifest['origin']}. UTC interval: {manifest['start']} to {manifest['end']}. "
        f"Candles: {manifest['candles']}; interval seconds: {manifest['timeframe_seconds']}; "
        f"gaps: {manifest['gaps']}.\n\n"
        "| Metric | GRID | Buy-and-hold |\n|---|---|---|\n" + "\n".join(rows) + "\n\n"
        f"Comparison: **{compared['status']}**. Physical BTC and marked wealth are separate.\n\n"
        "Configuration, fees/filter assumptions and validity: configuration.json. "
        "Exact metrics, fees by asset, funding, limitations and axes: result.json. "
        "Temporal inventory/wealth: equity.csv. Operations: operations.csv. "
        "Decisions including ambiguity/inactivity: decisions.csv. Native financial sources: "
        "paper_sources.jsonl / benchmark_sources.jsonl. input.csv preserves the exact dataset.\n\n"
        "OHLC_INTRABAR_PATH_UNKNOWN. Penetration/touch, liquidity cap, spread/slippage buffers, "
        "latency and side-priority are hypothetical execution rules, not exchange evidence. "
        "LIMIT fills use the limit; benchmark uses adverse eligible opening price, "
        "quantity capped by that bar volume and observed at its close. No inferred queue/path. "
        "Capital-time mean exposure is integral(BTC_MTM dt)/integral(NAV dt), left-close samples, "
        "not the arithmetic mean of per-candle ratios.\n\n"
        "Proceeds are not profit; MTM is not realized profit; physical BTC is not BTC equivalent. "
        "PaperCostStudy is a proportional hypothesis with explicit indeterminate cases. "
        "No CORE, transfer, credential, real order, LIVE readiness or empirical profitability "
        "is implied. Missing third-asset valuation prevents complete equity/return. "
        "Synthetic and historical inputs are never pooled as empirical evidence.\n"
    )


def export_run(result: BacktestResult, directory: Path, *, dataset: Dataset) -> dict[str, object]:
    dataset = replace(dataset)
    check(
        dataset.manifest() == result.dataset_manifest, "export dataset differs from executed bytes"
    )
    # mkdir refuses any existing output, including a partial earlier export.
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "input.csv").write_bytes(dataset.raw)
    (directory / "configuration.json").write_text(
        _json(configuration(result.config)), encoding="utf8"
    )
    manifest = dict(result.dataset_manifest)
    (directory / "dataset.json").write_text(
        _json(
            dict(
                version=1,
                csv_path="input.csv",
                origin=dataset.spec.origin,
                synthetic=dataset.spec.synthetic,
                timeframe_seconds=manifest["timeframe_seconds"],
                start=manifest["start"],
                end=manifest["end"],
                format=dataset.spec.format.value,
                epoch_unit=dataset.spec.epoch_unit,
                sha256=dataset.sha256,
            )
        ),
        encoding="utf8",
    )
    summary = dict(
        version=1,
        code_commit=result.code_commit,
        dataset=manifest,
        metrics=result.metrics,
        benchmark=result.benchmark,
        comparison=comparison(result.metrics, result.benchmark),
        final_state=result.points[-1].state,
        benchmark_final_state=result.benchmark_points[-1].state,
        cost_limitations=result.cost_limitations,
        event_count=result.sources.revision,
        authority="TRANSIENT_PAPER_ONLY_NOT_AN_IMPORTABLE_BALANCE",
        mean_exposure_convention="CAPITAL_TIME_WEIGHTED_LEFT_CLOSE",
        ratios="EXACT_NUMERATOR_DENOMINATOR; money/price/quantity are Decimal strings",
    )
    (directory / "result.json").write_text(_json(summary), encoding="utf8")
    _csv(
        directory / "operations.csv",
        (
            "scope",
            "order_ref",
            "cell",
            "cycle",
            "side",
            "bar_open_utc",
            "observed_at_utc",
            "price",
            "qty",
            "fee",
            "fee_asset",
            "liquidity",
        ),
        (
            (
                scope,
                t.order_ref,
                t.cycle_ref.cell_index,
                t.cycle_ref.cycle_seq,
                t.side.value,
                t.bar_open.isoformat(),
                t.observed_at.isoformat(),
                t.price.value,
                t.qty.value,
                t.fee.amount,
                t.fee.asset.code,
                t.liquidity.value,
            )
            for scope, trades in [
                ("GRID", result.trades),
                ("BUY_AND_HOLD", result.benchmark_trades),
            ]
            for t in trades
        ),
    )
    _csv(
        directory / "equity.csv",
        (
            "close_time_utc",
            "mark",
            "btc",
            "reserved_btc",
            "available_usdt",
            "reserved_usdt",
            "quote_btc_equity",
            "complete_equity",
            "exposure_ratio",
            "utilization_ratio",
            "benchmark_btc",
            "benchmark_complete_equity",
        ),
        (
            (
                p.time.isoformat(),
                p.price.value,
                p.state.remaining_grid_base.value,
                p.state.reserved_grid_base.value,
                p.state.available_quote.amount,
                p.state.active_buy_reservations.amount,
                p.quote_btc_equity.amount,
                None if p.equity is None else p.equity.amount,
                p.exposure,
                p.utilization,
                b.state.remaining_grid_base.value,
                None if b.equity is None else b.equity.amount,
            )
            for p, b in zip(result.points, result.benchmark_points, strict=True)
        ),
    )
    _csv(
        directory / "decisions.csv",
        ("time_utc", "kind", "reference", "detail"),
        ((d.time.isoformat(), d.kind, d.ref, d.detail) for d in result.decisions),
    )
    _csv(
        directory / "events.csv",
        ("revision", "run_ref", "command_type"),
        ((e.revision, e.run_ref, type(e.command).__name__) for e in result.sources.events),
    )
    _sources(directory / "paper_sources.jsonl", result.sources)
    _sources(directory / "benchmark_sources.jsonl", result.benchmark_sources)
    (directory / "report.md").write_text(markdown(result), encoding="utf8")
    artifacts = []
    for path in sorted(directory.iterdir()):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1_048_576), b""):
                digest.update(chunk)
        artifacts.append(dict(path=path.name, bytes=path.stat().st_size, sha256=digest.hexdigest()))
    receipt = dict(
        version=1,
        complete=True,
        artifacts=artifacts,
        note="Completion manifest written last; "
        "missing manifest means interrupted/incomplete export. "
        "Hashes are reproducibility checks, not authentication or a durable financial checkpoint.",
    )
    (directory / "export_manifest.json").write_text(_json(receipt), encoding="utf8")
    return cast(dict[str, object], json_value(receipt))
