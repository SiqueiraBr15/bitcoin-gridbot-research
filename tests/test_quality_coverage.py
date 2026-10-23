"""Reject incompatible or unearned coverage instead of inflating the gate."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from tools import quality_coverage
from tools.quality_coverage import export_campaign, verify_bundles
from tools.quality_gate import digest


def test_bundle_rejects_identity_overlap_timeout_and_changed_data(tmp_path: Path) -> None:
    inventory: dict[str, Any] = {"identity": {"config": "original"}, "items": [{"nodeid": "a"}]}
    data = tmp_path / "segment.coverage"
    data.write_bytes(b"test data for checksum, not a real coverage database")
    segment = {"nodes": {"a": "PASS"}, "coverage_file": data.name, "coverage_sha256": digest(data)}
    bundle = {"identity": inventory["identity"], "segments": [segment]}
    location = tmp_path / "bundle.json"
    assert verify_bundles(inventory, [(location, bundle)]) == ({"a": "PASS"}, [data])
    with pytest.raises(ValueError, match="identity"):
        verify_bundles(inventory, [(location, dict(bundle, identity={}))])
    with pytest.raises(ValueError, match="overlapping"):
        verify_bundles(inventory, [(location, bundle), (location, bundle)])
    with pytest.raises(ValueError, match="incomplete"):
        verify_bundles(
            inventory, [(location, dict(bundle, segments=[{"nodes": {"a": "INCOMPLETE"}}]))]
        )
    data.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_bundles(inventory, [(location, bundle)])


def test_bundle_rejects_unknown_nodes_duplicates_and_path_escape(tmp_path: Path) -> None:
    inventory: dict[str, Any] = {"identity": {}, "items": [{"nodeid": "a"}]}
    location = tmp_path / "bundle.json"
    with pytest.raises(ValueError, match="duplicate"):
        verify_bundles(dict(inventory, items=[{"nodeid": "a"}] * 2), [])
    with pytest.raises(ValueError, match="unknown"):
        verify_bundles(
            inventory, [(location, {"identity": {}, "segments": [{"nodes": {"b": "PASS"}}]})]
        )
    with pytest.raises(ValueError, match="escapes"):
        verify_bundles(
            inventory,
            [
                (
                    location,
                    {
                        "identity": {},
                        "segments": [
                            {"nodes": {"a": "PASS"}, "coverage_file": "../outside.coverage"}
                        ],
                    },
                )
            ],
        )


@pytest.mark.parametrize("status", ["PASS", "TIMEOUT"])
def test_campaign_export_never_certifies_timed_out_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setattr(quality_coverage, "ROOT", tmp_path)
    monkeypatch.setattr(quality_coverage, "identity", lambda: {"code": "fixed"})
    (tmp_path / "tools").mkdir()
    runner = tmp_path / "tools/quality_gate.py"
    runner.write_text("# fixed runner")
    module = tmp_path / "sample.py"
    module.write_text("# fixed tests")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"identity": {"code": "fixed"}, "items": [{"nodeid": "a"}]}))
    campaign = tmp_path / "campaign"
    segment = campaign / "segment-0000"
    segment.mkdir(parents=True)
    (campaign / "plan.json").write_text(
        json.dumps(
            {
                "identity": {"code": "fixed"},
                "segments": [["a"]],
                "test_modules": {"sample.py": digest(module)},
                "runner_sha256": digest(runner),
            }
        )
    )
    log = segment / "output.log"
    log.write_text("unit fixture only; not an actual pytest execution")
    (segment / "receipt.json").write_text(
        json.dumps(
            {
                "status": status,
                "exit_code": 0 if status == "PASS" else None,
                "log_sha256": digest(log),
                "elapsed_seconds": 1,
            }
        )
    )
    (segment / "expected.json").write_text('["a"]')
    (segment / "phases.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "nodeid": "a",
                    "when": phase,
                    "outcome": "passed",
                }
            )
            for phase in ("setup", "call", "teardown")
        )
    )
    (segment / "execution.coverage").write_bytes(b"unit checksum fixture, not real coverage")
    exported = tmp_path / "exported"
    assert export_campaign(inventory, campaign, exported, []) == 0
    pending = json.loads(gzip.decompress((exported / "pending.json.gz").read_bytes()))
    assert pending["pending_nodeids"] == ([] if status == "PASS" else ["a"])
    module.write_text("# changed after execution")
    with pytest.raises(ValueError, match="module changed"):
        export_campaign(inventory, campaign, tmp_path / "rejected", [])
