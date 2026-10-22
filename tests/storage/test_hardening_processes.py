"""Barreiras determinísticas de concorrência e crashes com obrigações existentes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gridbot.application.operational_persistence import OperationalScope
from gridbot.storage.financial_codec import encode_contract
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.storage.journal_oracle import audit_assets, audit_observed, audit_rows
from tests.storage.test_operational_journal import bound_sell

ROOT = Path(__file__).resolve().parents[2]


def start(
    directory: Path, mode: str, operation: str = "raw", point: str = "none"
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.storage.hardening_worker",
            str(directory),
            str(directory / "scope.json"),
            mode,
            operation,
            point,
        ],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT)),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf8",
    )


def line(process: subprocess.Popen[str]) -> dict[str, object]:
    assert process.stdout is not None
    value = json.loads(process.stdout.readline())
    assert type(value) is dict
    return value


def send(process: subprocess.Popen[str], value: str) -> None:
    assert process.stdin is not None
    process.stdin.write(value + "\n")
    process.stdin.flush()


def cleanup(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def seeded(directory: Path) -> tuple[SQLiteOperationalJournal, int]:
    store, state = bound_sell(directory)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    (directory / "scope.json").write_text(encode_contract(state.scope), encoding="utf8")
    audit_assets(state)
    audit_observed(store.replay_observations(state.scope, source.plan))
    return store, state.revision


@pytest.mark.parametrize("operations", [("finance", "raw"), ("raw", "raw"), ("raw", "conflict")])
def test_two_instances_mixed_and_duplicate_writers_linearize(
    tmp_path: Path, operations: tuple[str, str]
) -> None:
    store, revision = seeded(tmp_path)
    processes = [start(tmp_path, "race", op) for op in operations]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        ready = [f.result(timeout=30) for f in [pool.submit(line, p) for p in processes]]
        assert [r["revision"] for r in ready] == [revision, revision]
        for process in processes:
            send(process, "GO")
        results = [f.result(timeout=30) for f in [pool.submit(line, p) for p in processes]]
        assert sorted(str(r["status"]) for r in results) == ["COMMITTED", "REVISION_CONFLICT"]
        state = store.load_operational_state(decode_scope(tmp_path))
        assert state.revision == revision + 1
        audit_assets(state)
        if operations[0] != "finance":
            old_count = len(store.recover(state.scope).receipts)
            state = store.append_raw_observation(
                state.scope, state.revision, wire_scenario().tape.observations[0]
            )
            receipts = store.recover(state.scope).receipts
            assert len(receipts) == old_count + 1
            assert receipts[-1].classification is ReceiptClassification.DUPLICATE_IDENTICAL
        audit_rows(store.policy.database_path())
    finally:
        cleanup(processes)
        pool.shutdown(wait=True, cancel_futures=True)


def decode_scope(directory: Path) -> OperationalScope:
    from gridbot.storage.financial_codec import decode_contract

    scope = decode_contract((directory / "scope.json").read_text(encoding="utf8"))
    assert type(scope) is OperationalScope
    return scope


def test_reader_retains_snapshot_until_writer_commit_barrier(tmp_path: Path) -> None:
    store, revision = seeded(tmp_path)
    reader = start(tmp_path, "reader")
    writer = start(tmp_path, "staged", point="before_commit")
    processes = [reader, writer]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        assert pool.submit(line, reader).result(timeout=30)["revision"] == revision
        assert pool.submit(line, writer).result(timeout=30)["staged"] is True
        send(reader, "CHECK")
        assert pool.submit(line, reader).result(timeout=30)["same_snapshot"] is True
        assert reader.wait(timeout=10) == 0
        send(writer, "COMMIT")
        assert pool.submit(line, writer).result(timeout=30)["status"] == "COMMITTED"
        assert writer.wait(timeout=10) == 0
        state = store.load_operational_state(decode_scope(tmp_path))
        assert state.revision == revision + 1
        audit_rows(store.policy.database_path(), expected_receipts=4)
        audit_assets(state)
    finally:
        cleanup(processes)
        pool.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize(
    "point",
    [
        "before_transaction",
        "after_begin",
        "after_snapshot_prepared",
        "after_snapshot_written",
        "after_event",
        "after_cas",
        "before_commit",
        "after_commit",
    ],
)
def test_crash_preserves_confirmed_raw_bindings_and_reservations(
    tmp_path: Path, point: str
) -> None:
    store, revision = seeded(tmp_path)
    original = store.recover(decode_scope(tmp_path))
    crashed = start(tmp_path, "crash", "finance", point)
    try:
        _stdout, stderr = crashed.communicate(timeout=30)
        assert crashed.returncode == 77, stderr
    finally:
        cleanup([crashed])
    processes = [start(tmp_path, "recover"), start(tmp_path, "recover")]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        assert all(f.result(timeout=30)["ready"] for f in [pool.submit(line, p) for p in processes])
        for process in processes:
            send(process, "GO")
        recovered = [f.result(timeout=30) for f in [pool.submit(line, p) for p in processes]]
        assert recovered[0] == recovered[1]
        current = SQLiteOperationalJournal.open(store.policy).recover(original.state.scope)
        assert current.receipts[:3] == original.receipts
        assert (
            current.state.book.external_sell_bindings == original.state.book.external_sell_bindings
        )
        assert (
            current.state.book.inventory_book.reservations
            == original.state.book.inventory_book.reservations
        )
        assert current.state.revision == revision + (point == "after_commit")
        assert len(current.receipts) == 3 + (3 if point == "after_commit" else 0)
        audit_assets(current.state)
        audit_rows(store.policy.database_path(), expected_receipts=len(current.receipts))
    finally:
        cleanup(processes)
        pool.shutdown(wait=True, cancel_futures=True)
