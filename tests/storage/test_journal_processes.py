"""Crashes reais de processo e CAS concorrente com barreira explícita."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from gridbot.application.operational_persistence import (
    PersistenceError,
    PersistenceErrorCode,
    VersionedOperationalState,
)
from gridbot.storage.financial_codec import encode_contract
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.application.test_operational_grid import ref
from tests.storage.test_operational_journal import (
    assert_conserved,
    bound_sell,
    funded_plan,
    journal_start,
)

ROOT = Path(__file__).resolve().parents[2]


def worker_input(path: Path, state: VersionedOperationalState, operation: str) -> Path:
    command = funded_plan(state) if operation == "transition" else None
    source = wire_scenario()
    path.write_text(
        json.dumps(
            {
                "scope": encode_contract(state.scope),
                "operation": operation,
                "command": encode_contract(command),
                "raw": encode_contract(source.tape.observations),
                "plan": encode_contract(source.plan),
            }
        ),
        encoding="utf8",
    )
    return path


def worker_command(directory: Path, inputs: Path, mode: str, point: str = "none") -> list[str]:
    return [
        sys.executable,
        "-m",
        "tests.storage.journal_worker",
        str(directory),
        str(inputs),
        mode,
        point,
    ]


def worker_env() -> dict[str, str]:
    return dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT),
    )


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
def test_abrupt_exit_atomic_root_plus_related_evidence(tmp_path: Path, point: str) -> None:
    store, state = journal_start(tmp_path)
    inputs = worker_input(tmp_path / "inputs.json", state, "transition")
    crashed = subprocess.run(
        worker_command(tmp_path, inputs, "crash", point),
        cwd=ROOT,
        env=worker_env(),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert crashed.returncode == 71, crashed.stderr
    recovered_process = subprocess.run(
        worker_command(tmp_path, inputs, "recover"),
        cwd=ROOT,
        env=worker_env(),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert recovered_process.returncode == 0, recovered_process.stderr
    result = json.loads(recovered_process.stdout)
    if point == "after_commit":
        assert result["revision"] == state.revision + 1
        assert len(result["raw"]) == 3
    else:
        assert result["revision"] == state.revision
        assert result["raw"] == []
        assert result["state"] == encode_contract(state.book)
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert_conserved(recovered.state)


@pytest.mark.parametrize("point", ["during_read", "during_integrity", "during_replay"])
def test_read_integrity_and_replay_crash_preserve_committed_material(
    tmp_path: Path, point: str
) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    inputs = worker_input(tmp_path / "inputs.json", state, "replay")
    before = store.recover(state.scope)
    crashed = subprocess.run(
        worker_command(tmp_path, inputs, "recover", point),
        cwd=ROOT,
        env=worker_env(),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert crashed.returncode == 71, crashed.stderr
    reopened = subprocess.run(
        worker_command(tmp_path, inputs, "recover"),
        cwd=ROOT,
        env=worker_env(),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout)["revision"] == state.revision
    assert SQLiteOperationalJournal.open(store.policy).recover(state.scope) == before


@pytest.mark.parametrize("operation", ["transition", "raw"])
def test_two_processes_same_revision_have_one_winner(tmp_path: Path, operation: str) -> None:
    store, state = journal_start(tmp_path)
    inputs = worker_input(tmp_path / "inputs.json", state, operation)
    command = worker_command(tmp_path, inputs, "race")
    processes = [
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=worker_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        ready = [pool.submit(p.stdout.readline) for p in processes if p.stdout is not None]
        assert len(ready) == 2
        assert [future.result(timeout=20) for future in ready] == ["READY\n", "READY\n"]
        completed = [pool.submit(p.communicate, "GO\n", timeout=20) for p in processes]
        results = [future.result(timeout=25) for future in completed]
        assert all(p.returncode == 0 for p in processes), results
        statuses = sorted(json.loads(stdout)["status"] for stdout, _ in results)
        assert statuses == ["REVISION_CONFLICT", "committed"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        pool.shutdown(wait=True, cancel_futures=True)
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert recovered.state.revision == state.revision + 1
    if operation == "transition":
        assert len(recovered.state.book.inventory_book.funded_buy_book.reservations) == 1
        assert len(recovered.receipts) == 3
    else:
        assert recovered.state.book == state.book
        assert len(recovered.receipts) == 3
    assert_conserved(recovered.state)


def test_two_connections_busy_is_bounded_no_retry_and_then_recovery(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    second = replace(store, busy_timeout_ms=20)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(PersistenceError) as error:
            second.commit_operational_transition(state.scope, 0, funded_plan(state))
        assert error.value.code is PersistenceErrorCode.BUSY
        lock.execute("ROLLBACK")
    assert store.load_operational_state(state.scope) == state
    updated = second.commit_operational_transition(state.scope, 0, funded_plan(state))
    assert updated.revision == 1


def test_two_threads_different_cells_use_revision_to_preserve_winner(tmp_path: Path) -> None:
    import threading

    store, state = journal_start(tmp_path)
    barrier = threading.Barrier(2, timeout=10)
    base = funded_plan(state)

    def attempt(cell: int) -> str:
        loaded = store.load_operational_state(state.scope)
        barrier.wait()
        try:
            store.commit_operational_transition(
                loaded.scope, loaded.revision, replace(base, cycle_ref=ref(cell))
            )
        except PersistenceError as error:
            return error.code.value
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, cell) for cell in (0, 1)]
        assert sorted(f.result(timeout=15) for f in futures) == ["REVISION_CONFLICT", "committed"]
    recovered = store.load_operational_state(state.scope)
    assert len(recovered.book.inventory_book.funded_buy_book.reservations) == 1
    assert_conserved(recovered)
