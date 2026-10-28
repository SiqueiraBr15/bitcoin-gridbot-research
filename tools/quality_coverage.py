"""Consolidate explicitly certified, compatible quality-gate evidence bundles.

A bundle has identity, segments[{nodes, coverage_file?, coverage_sha256?}].
Paths are relative to the bundle. Certification of legacy logs is a separate audit
step: this tool verifies inventory, disjoint ownership, current source and hashes.
Only complete segment data may contribute coverage. No threshold is overridden.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from pathlib import Path
from typing import Any

from tools.quality_gate import ROOT, digest, identity, reconcile, write_json


def validate_measured_files(paths: list[Path], expected: set[Path]) -> None:
    """A declared source setting alone does not constrain coverage report inputs."""
    from coverage import CoverageData

    measured: set[Path] = set()
    for path in paths:
        data = CoverageData(basename=str(path))
        data.read()
        if not data.has_arcs():
            raise ValueError("branch coverage is required")
        files = {Path(name).resolve() for name in data.measured_files()}
        if not files <= expected:
            raise ValueError("coverage contains foreign source files")
        measured.update(files)
    if measured != expected:
        raise ValueError("production source inventory incomplete")


def export_campaign(
    inventory_path: Path, campaign_path: Path, directory: Path, prior_bundles: list[Path]
) -> int:
    """Export completed segments only, and a deterministic remaining-node manifest."""
    inventory = json.loads(inventory_path.read_text())
    plan = json.loads((campaign_path / "plan.json").read_text())
    if inventory["identity"] != identity() or plan["identity"] != inventory["identity"]:
        raise ValueError("incompatible campaign identity")
    for name, checksum in plan["test_modules"].items():
        if digest(ROOT / name) != checksum:
            raise ValueError("test module changed after planning")
    if digest(ROOT / "tools/quality_gate.py") != plan["runner_sha256"]:
        raise ValueError("runner changed after planning")
    directory.mkdir(parents=True, exist_ok=False)
    segments = []
    for index, nodes in enumerate(plan["segments"]):
        source = campaign_path / f"segment-{index:04d}"
        receipt_path = source / "receipt.json"
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text())
        if digest(source / "output.log") != receipt["log_sha256"]:
            raise ValueError("execution log changed")
        if receipt["status"] != "PASS" or receipt["exit_code"] != 0:
            continue
        if json.loads((source / "expected.json").read_text()) != nodes:
            raise ValueError("expected nodeids changed")
        events = [json.loads(line) for line in (source / "phases.jsonl").read_text().splitlines()]
        statuses = reconcile(nodes, events, receipt["exit_code"])
        if any(value not in ("PASS", "SKIP") for value in statuses.values()):
            raise ValueError("PASS receipt has incomplete phases")
        coverage_source = source / "execution.coverage"
        coverage_target = directory / (source.name + ".coverage")
        shutil.copyfile(coverage_source, coverage_target)
        segments.append(
            {
                "name": source.name,
                "nodes": statuses,
                "coverage_file": coverage_target.name,
                "coverage_sha256": digest(coverage_target),
                "elapsed_seconds": receipt["elapsed_seconds"],
                "log_sha256": receipt["log_sha256"],
                "phases_sha256": digest(source / "phases.jsonl"),
            }
        )
    bundle = {"identity": inventory["identity"], "segments": segments}
    bundle_path = directory / "bundle.json"
    bundles = [(path, json.loads(path.read_text())) for path in prior_bundles]
    statuses, _paths = verify_bundles(inventory, [*bundles, (bundle_path, bundle)])
    pending = sorted({item["nodeid"] for item in inventory["items"]} - statuses.keys())
    write_json(bundle_path, bundle)
    (directory / "pending.json.gz").write_bytes(
        gzip.compress(json.dumps({"pending_nodeids": pending}).encode(), mtime=0)
    )
    print(json.dumps({"complete_segments": len(segments), "remaining": len(pending)}))  # noqa: T201
    return 0


def verify_bundles(
    inventory: dict[str, Any], bundles: list[tuple[Path, dict[str, Any]]]
) -> tuple[dict[str, str], list[Path]]:
    expected = {item["nodeid"] for item in inventory["items"]}
    if len(expected) != len(inventory["items"]):
        raise ValueError("duplicate inventory nodeid")
    statuses: dict[str, str] = {}
    coverage_files = []
    for location, bundle in bundles:
        if bundle["identity"] != inventory["identity"]:
            raise ValueError("incompatible evidence identity")
        for segment in bundle["segments"]:
            nodes = segment["nodes"]
            if not nodes or set(nodes) - expected or set(nodes) & statuses.keys():
                raise ValueError("unknown, empty or overlapping segment")
            if any(status not in ("PASS", "SKIP") for status in nodes.values()):
                raise ValueError("incomplete or failed segment cannot certify coverage")
            statuses.update(nodes)
            if "coverage_file" in segment:
                path = (location.parent / segment["coverage_file"]).resolve()
                if not path.is_relative_to(location.parent.resolve()):
                    raise ValueError("coverage path escapes bundle")
                if digest(path) != segment["coverage_sha256"]:
                    raise ValueError("coverage checksum mismatch")
                if path in coverage_files:
                    raise ValueError("duplicate coverage input")
                coverage_files.append(path)
    return statuses, coverage_files


def consolidate(inventory_path: Path, bundle_paths: list[Path], directory: Path) -> int:
    from coverage import Coverage

    inventory = json.loads(inventory_path.read_text())
    if inventory["identity"] != identity():
        raise ValueError("current code/configuration differs from evidence")
    bundles = [(path, json.loads(path.read_text())) for path in bundle_paths]
    statuses, paths = verify_bundles(inventory, bundles)
    if not paths:
        raise ValueError("no completed coverage files")
    validate_measured_files(
        paths,
        {
            path.resolve()
            for folder in ("src/gridbot", "research_console")
            for path in (ROOT / folder).rglob("*.py")
        },
    )
    directory.mkdir(parents=True, exist_ok=False)
    coverage = Coverage(
        config_file=str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
        data_file=str(directory / "global.coverage"),
    )
    coverage.combine(data_paths=[str(path) for path in paths], keep=True, strict=True)
    coverage.save()
    percent = coverage.json_report(outfile=str(directory / "coverage.json"))
    coverage.html_report(directory=str(directory / "html"))
    threshold = coverage.config.fail_under
    passed = percent >= threshold
    complete = len(statuses) == len(inventory["items"])
    result = {
        "tests_status": "PASS" if complete else "PENDING",
        "covered_tests": len(statuses),
        "expected_tests": len(inventory["items"]),
        "pending_nodeids": sorted(
            {item["nodeid"] for item in inventory["items"]} - statuses.keys()
        ),
        "coverage_status": "PASS" if passed else "FAIL",
        "coverage_percent": percent,
        "fail_under": threshold,
        "branch": coverage.config.branch,
        "source": coverage.config.source,
        "input_files": [
            {"sha256": digest(path), "bundle_relative_name": path.name} for path in paths
        ],
        "combined_sha256": digest(directory / "global.coverage"),
        "report_sha256": digest(directory / "coverage.json"),
    }
    write_json(directory / "result.json", result)
    print(json.dumps(result, indent=2))  # noqa: T201
    return 0 if passed and complete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["bundle", "combine"])
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--bundle", action="append", type=Path, default=[])
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.mode == "bundle":
        if args.campaign is None:
            parser.error("bundle requires --campaign")
        return export_campaign(args.inventory, args.campaign, args.out, args.bundle)
    if not args.bundle:
        parser.error("combine requires --bundle")
    return consolidate(args.inventory, args.bundle, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
