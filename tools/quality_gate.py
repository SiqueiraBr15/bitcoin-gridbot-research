"""Finite, resumable pytest partitions with exact nodeids and compatible coverage.

Evidence directories must be new. Logs are local developer artifacts: review them
before sharing. No test settings, financial code or coverage thresholds are changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter, process_time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def identity() -> dict[str, object]:
    """Only compatible source/configuration/environment may share coverage."""
    from importlib.metadata import version

    paths = [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("research_console").rglob("*.py")]
    paths += [ROOT / name for name in ("pyproject.toml", "constraints.txt", "tests/conftest.py")]
    paths += [
        path
        for path in (ROOT / "tests").rglob("*.py")
        if not path.name.startswith("test_") and path.name != "conftest.py"
    ]
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: version(name) for name in ("coverage", "pytest", "pytest-cov", "hypothesis")
        },
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)},
        "hypothesis_profile": os.environ.get("HYPOTHESIS_PROFILE", "ci"),
    }


def partition(items: list[dict[str, Any]], size: int = 20) -> list[list[str]]:
    if size < 1:
        raise ValueError("partition size must be positive")
    nodes = [item["nodeid"] for item in items]
    if len(set(nodes)) != len(nodes):
        raise ValueError("duplicate collected nodeid")
    modules: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        modules[item["nodeid"].split("::")[0]].append(item)
    result: list[list[str]] = []
    for module in sorted(modules):
        batch: list[str] = []
        for item in modules[module]:
            if item["property"]:
                if batch:
                    result.append(batch)
                    batch = []
                result.append([item["nodeid"]])
            else:
                batch.append(item["nodeid"])
                if len(batch) == size:
                    result.append(batch)
                    batch = []
        if batch:
            result.append(batch)
    return result


class EvidencePlugin:
    def __init__(self, directory: Path, expected: list[str] | None = None) -> None:
        self.directory = directory
        self.expected = expected
        self.items: list[dict[str, Any]] = []

    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        if self.expected is not None:
            wanted = set(self.expected)
            selected = [item for item in items if item.nodeid in wanted]
            if {item.nodeid for item in selected} != wanted:
                raise ValueError("segment collection differs from inventory")
            config.hook.pytest_deselected(
                items=[item for item in items if item.nodeid not in wanted]
            )
            items[:] = selected
        for item in items:
            obj = getattr(item, "obj", None)
            self.items.append(
                {
                    "nodeid": item.nodeid,
                    "property": hasattr(obj, "hypothesis")
                    or "stateful" in item.nodeid
                    or "Machine::" in item.nodeid,
                }
            )
        write_json(self.directory / "collected.json", self.items)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        event = {
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "duration": report.duration,
        }
        if report.skipped:
            event["reason"] = str(report.longrepr)
        with (self.directory / "phases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")


def reconcile(
    expected: list[str], events: list[dict[str, Any]], exit_code: int | None
) -> dict[str, str]:
    if len(expected) != len(set(expected)):
        raise ValueError("duplicate expected nodeid")
    phases: dict[str, dict[str, str]] = defaultdict(dict)
    for event in events:
        node, phase = event["nodeid"], event["when"]
        if node not in expected or phase in phases[node]:
            raise ValueError("unexpected or duplicate test phase")
        phases[node][phase] = event["outcome"]
    result = {}
    for node in expected:
        records = phases[node]
        if "failed" in records.values():
            result[node] = "FAIL"
        elif exit_code != 0 or records.get("teardown") != "passed":
            result[node] = "INCOMPLETE"
        elif "skipped" in records.values():
            result[node] = "SKIP"
        elif all(records.get(phase) == "passed" for phase in ("setup", "call", "teardown")):
            result[node] = "PASS"
        else:
            result[node] = "INCOMPLETE"
    return result


def worker(directory: Path, collect: bool) -> int:
    started, cpu = perf_counter(), process_time()
    coverage = None
    if not collect:
        from coverage import Coverage

        coverage = Coverage(
            config_file=str(ROOT / "pyproject.toml"),
            data_file=str(directory / "execution.coverage"),
        )
        coverage.start()
    import pytest

    expected = None if collect else json.loads((directory / "expected.json").read_text())
    plugin = EvidencePlugin(directory, expected)
    target = "tests" if expected is None else expected[0].split("::")[0]
    args = (
        [target, "--collect-only", "-q"]
        if collect
        else [target, "-vv", "--durations=0", "--junitxml=" + str(directory / "junit.xml")]
    )
    code = int(pytest.main(args, plugins=[plugin]))
    if coverage is not None:
        coverage.stop()
        coverage.save()
    write_json(
        directory / "worker.json",
        {
            "exit_code": code,
            "wall_seconds": perf_counter() - started,
            "cpu_seconds": process_time() - cpu,
        },
    )
    return code


def launch(directory: Path, *, collect: bool = False, timeout: int = 300) -> dict[str, Any]:
    command = [sys.executable, "-m", "tools.quality_gate", "_worker", "--out", str(directory)]
    if collect:
        command.append("--collect-only")
    env = os.environ.copy()
    env["HYPOTHESIS_PROFILE"] = env.get("HYPOTHESIS_PROFILE", "ci")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    started = perf_counter()
    with (directory / "output.log").open("wb") as output:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            code: int | None = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(  # noqa: S603
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=15,
                    check=False,
                )
            else:
                process.kill()
            process.wait(timeout=15)
            code = None
    receipt = {
        "exit_code": code,
        "timeout_seconds": timeout,
        "elapsed_seconds": perf_counter() - started,
        "status": "TIMEOUT" if code is None else "PASS" if code == 0 else "FAIL",
        "log_sha256": digest(directory / "output.log"),
    }
    write_json(directory / "receipt.json", receipt)
    return receipt


def inventory(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=False)
    result = launch(directory, collect=True, timeout=45)
    if result["status"] != "PASS":
        return 1
    items = json.loads((directory / "collected.json").read_text())
    write_json(directory / "inventory.json", {"identity": identity(), "items": items})
    return 0


def campaign(
    inventory_path: Path,
    directory: Path,
    timeout: int,
    budget: int,
    pending_path: Path | None,
    max_cases: int = 20,
) -> int:
    import gzip

    current = json.loads(inventory_path.read_text())
    if current["identity"] != identity():
        raise ValueError("inventory identity is stale")
    directory.mkdir(parents=True, exist_ok=False)
    items = current["items"]
    if pending_path is not None:
        pending = set(json.loads(gzip.decompress(pending_path.read_bytes()))["pending_nodeids"])
        if not pending <= {item["nodeid"] for item in items}:
            raise ValueError("pending nodeids not present in inventory")
        items = [item for item in items if item["nodeid"] in pending]
    planned = partition(items, max_cases)
    write_json(
        directory / "plan.json",
        {
            "identity": current["identity"],
            "segments": planned,
            "runner_sha256": digest(Path(__file__)),
            "test_modules": {
                name: digest(ROOT / name)
                for name in sorted({item["nodeid"].split("::")[0] for item in items})
            },
        },
    )
    started = perf_counter()
    outcomes = []
    for index, nodes in enumerate(planned):
        remaining = budget - (perf_counter() - started)
        if remaining < 5:
            break
        segment = directory / f"segment-{index:04d}"
        segment.mkdir()
        write_json(segment / "expected.json", nodes)
        result = launch(segment, timeout=min(timeout, int(remaining)))
        phases_path = segment / "phases.jsonl"
        events = (
            [json.loads(line) for line in phases_path.read_text().splitlines()]
            if phases_path.exists()
            else []
        )
        statuses = reconcile(nodes, events, result["exit_code"])
        outcome = {"segment": segment.name, **result, "nodes": statuses}
        coverage_path = segment / "execution.coverage"
        if coverage_path.exists():
            outcome["coverage_sha256"] = digest(coverage_path)
        outcomes.append(outcome)
        write_json(directory / "progress.json", {"outcomes": outcomes, "planned": len(planned)})
        print(  # noqa: T201
            json.dumps(
                {
                    "segment": index,
                    "total": len(planned),
                    "status": result["status"],
                    "seconds": result["elapsed_seconds"],
                    "cases": len(nodes),
                }
            ),
            flush=True,
        )
    complete = len(outcomes) == len(planned) and all(
        all(status in ("PASS", "SKIP") for status in result["nodes"].values())
        for result in outcomes
    )
    write_json(
        directory / "result.json",
        {
            "identity": current["identity"],
            "outcomes": outcomes,
            "planned": len(planned),
            "status": "PASS" if complete else "PENDING",
            "elapsed_seconds": perf_counter() - started,
        },
    )
    return 0 if complete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["inventory", "run", "_worker"])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--pending", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--segment-seconds", type=int, default=300)
    parser.add_argument("--budget-seconds", type=int, default=5400)
    parser.add_argument("--max-cases", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.segment_seconds <= 1800 or not 5 <= args.budget_seconds <= 14400:
        parser.error("finite segment/budget limits required")
    if not 1 <= args.max_cases <= 100:
        parser.error("max-cases must be between 1 and 100")
    os.environ.setdefault("HYPOTHESIS_PROFILE", "ci")
    if args.mode == "_worker":
        return worker(args.out, args.collect_only)
    if args.mode == "inventory":
        return inventory(args.out)
    if args.inventory is None:
        parser.error("run requires --inventory")
    return campaign(
        args.inventory,
        args.out,
        args.segment_seconds,
        args.budget_seconds,
        args.pending,
        args.max_cases,
    )


if __name__ == "__main__":
    raise SystemExit(main())
