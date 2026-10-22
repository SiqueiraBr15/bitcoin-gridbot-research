"""Run explicitly: python -m tests.capacity.paper_capacity --output tmp/capacity.json.

No OHLC model: legitimate supplied fills, unchanged DELETE/EXTRA, and public commits.
Budgets are administrative experiment limits, never performance targets.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from ctypes import wintypes
from pathlib import Path
from statistics import median
from typing import Any

from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperBook,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
)
from gridbot.storage.paper_journal import MAX_EVENTS, PaperJournal
from tests.paper.fixtures import buy_result, commit, evidence, initial, prepare_buy, reserve_sell
from tests.paper.hardening_fixtures import raw_oracle


class _Memory(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("faults", wintypes.DWORD),
        *(
            (name, ctypes.c_size_t)
            for name in (
                "peak_rss",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "private_bytes",
                "peak_private_bytes",
            )
        ),
    ]


def memory(pid: int) -> dict[str, int]:
    """Windows process working set and private commitment, not Python-only heap."""
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Memory), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return {}
    try:
        value = _Memory()
        value.cb = ctypes.sizeof(value)
        if not query(handle, ctypes.byref(value), value.cb):
            return {}
        return {name: int(getattr(value, name)) for name in ("rss", "peak_rss", "private_bytes")}
    finally:
        kernel.CloseHandle(handle)


def _write(path: Path, result: object) -> None:
    path.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf8")


def worker(count: int, output: Path, scenario: str) -> None:
    directory = output.parent / (output.stem + "-journal")
    directory.mkdir(exist_ok=False)
    book = initial((Money.parse("1", Asset("BNB")),))
    store = PaperJournal.create(directory, book)
    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "requested_cycles": count,
        "status": "RUNNING",
        "cycles": records,
        "complete_full_cycles": 0,
        "extra_partial": 0,
        "extra_no_fill": 0,
        "worker_pid": os.getpid(),
    }
    _write(output, result)
    begin = time.perf_counter()

    def save(candidate: PaperBook) -> None:
        nonlocal book
        before = len(book.entries)
        updated = store.commit(before, candidate.entries[-1])
        assert updated == candidate
        assert len(updated.entries) == before + 1
        book = updated

    def one(cell: int, status: OrderStatus, qty: str | None, fees: tuple[Money, ...]) -> None:
        save(prepare_buy(book, cell))
        save(commit(book, PaperSettleBuy(buy_result(book, cell))))
        candidate, execution = reserve_sell(book, cell)
        save(candidate)
        observed = evidence(book, execution, status=status, qty=qty, fees=fees)
        before_proceeds = book.settled_sell_proceeds
        save(commit(book, PaperObserveSell(observed)))
        assert book.settled_sell_proceeds == before_proceeds
        apply = PaperApplySell(execution, len(book.entries))
        save(commit(book, apply))
        assert store.commit(len(book.entries), apply) == book
        if qty == "0":
            release = PaperReleaseNoFill(execution)
            save(commit(book, release))
            assert store.commit(len(book.entries), release) == book

    for cycle in range(count):
        started = time.perf_counter()
        cpu = time.process_time()
        one(0, OrderStatus.FILLED, None, (Money.parse(".01", USDT),))
        result["complete_full_cycles"] = cycle + 1
        if cycle == 2 and scenario == "mixed":
            one(
                1,
                OrderStatus.CANCELED,
                ".030",
                (
                    Money.parse(".00004", BTC),
                    Money.parse(".00105", USDT),
                    Money.parse(".00001", Asset("BNB")),
                ),
            )
            result["extra_partial"] = 1
        if cycle == 4 and scenario == "mixed":
            one(2, OrderStatus.CANCELED, "0", (Money.zero(USDT),))
            result["extra_no_fill"] = 1
        operation_seconds = time.perf_counter() - started
        validation = time.perf_counter()
        financial = raw_oracle(book)
        validation_seconds = time.perf_counter() - validation
        restart_seconds = 0.0
        if (cycle + 1) % 3 == 0:
            restarted = time.perf_counter()
            store = PaperJournal.open(directory)
            assert store.recover() == book
            restart_seconds = time.perf_counter() - restarted
        records.append(
            {
                "full_cycle": cycle + 1,
                "events": len(book.entries),
                "operation_s": operation_seconds,
                "oracle_s": validation_seconds,
                "open_plus_recover_s": restart_seconds,
                "cpu_s": time.process_time() - cpu,
                "elapsed_s": time.perf_counter() - begin,
                "memory": memory(os.getpid()),
                "database_bytes": (directory / "gridbot-paper.sqlite3").stat().st_size,
                "financial": {key: str(value) for key, value in financial.items()},
            }
        )
        _write(output, result)
    replay_started = time.perf_counter()
    book._frame()
    result["final_replay_s"] = time.perf_counter() - replay_started
    recover_started = time.perf_counter()
    assert store.recover() == book
    result["final_recover_s"] = time.perf_counter() - recover_started
    values = sorted(float(record["operation_s"]) for record in records)
    result.update(
        status="PASS",
        elapsed_s=time.perf_counter() - begin,
        p50_operation_s=median(values),
        p95_operation_s=values[(95 * len(values) + 99) // 100 - 1] if len(values) >= 20 else None,
        p95_note=(
            "nearest rank only with >=20 full-cycle samples; includes declared side scenarios"
        ),
    )
    _write(output, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, nargs="+", default=[10, 50, 100, 300])
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--max-rss-mib", type=int, default=512)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--scenario", choices=["mixed", "full"], default="mixed")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.worker is not None:
        worker(args.worker, args.output, args.scenario)
        return
    if os.name != "nt" or args.seconds <= 0 or args.max_rss_mib <= 0:
        parser.error("Windows and positive resource budgets required")
    if any(count <= 0 for count in args.cycles) or args.cycles != sorted(set(args.cycles)):
        parser.error("cycle counts must be positive, increasing and unique")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    stopped = False
    for count in args.cycles:
        events = count * 5
        if args.scenario == "mixed":
            events += (5 if count >= 3 else 0) + (6 if count >= 5 else 0)
        if events > MAX_EVENTS or stopped:
            results.append(
                {
                    "cycles": count,
                    "status": "NOT_EXECUTED",
                    "reason": "total event cap"
                    if events > MAX_EVENTS
                    else "prior resource budget reached",
                    "required_events": events,
                }
            )
            continue
        path = args.output.with_name(args.output.stem + f"-{count}.json")
        command = [
            sys.executable,
            "-m",
            "tests.capacity.paper_capacity",
            "--worker",
            str(count),
            "--output",
            str(path),
            "--scenario",
            args.scenario,
        ]
        begin = time.perf_counter()
        with path.with_suffix(".log").open("w", encoding="utf8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            reason = None
            peak_rss = 0
            telemetry_pid = process.pid
            while process.poll() is None:
                if path.exists():
                    with suppress(ValueError, KeyError):
                        telemetry_pid = json.loads(path.read_text(encoding="utf8"))["worker_pid"]
                measured = memory(telemetry_pid)
                peak_rss = max(peak_rss, measured.get("peak_rss", 0))
                if time.perf_counter() - begin > args.seconds:
                    reason = "TIMEOUT"
                elif measured.get("rss", 0) > args.max_rss_mib * 1024**2:
                    reason = "MEMORY_LIMIT"
                if reason:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                    process.wait(timeout=30)
                    break
                time.sleep(0.25)
        status = reason or ("PASS" if process.returncode == 0 else "FAIL")
        results.append(
            {
                "cycles": count,
                "status": status,
                "command": command,
                "pid": process.pid,
                "exit_code": process.returncode,
                "elapsed_s": time.perf_counter() - begin,
                "peak_rss_bytes": peak_rss,
                "telemetry_pid": telemetry_pid,
                "partial_result": json.loads(path.read_text(encoding="utf8"))
                if path.exists()
                else None,
            }
        )
        stopped = status != "PASS"
        _write(
            args.output,
            {
                "seconds_per_case": args.seconds,
                "max_rss_mib": args.max_rss_mib,
                "max_events_total": MAX_EVENTS,
                "results": results,
            },
        )
    _write(
        args.output,
        {
            "seconds_per_case": args.seconds,
            "max_rss_mib": args.max_rss_mib,
            "max_events_total": MAX_EVENTS,
            "results": results,
        },
    )
    if any(result["status"] in {"FAIL", "TIMEOUT", "MEMORY_LIMIT"} for result in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
