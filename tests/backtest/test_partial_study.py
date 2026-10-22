"""Study artifacts preserve signal bars without serializing unsupported timeframes."""

import hashlib
import json
from pathlib import Path

import pytest
from scripts import a19_6_study
from scripts.a19_6_study import partial_decision_record

from gridbot.backtest.export import json_value
from gridbot.backtest.partial_grid import PartialDecision
from tests.paper.test_two_generation import plan, prepared


def test_partial_signal_export_contains_all_168_closed_bars() -> None:
    request = plan(prepared())
    record = partial_decision_record(
        PartialDecision(request.signal[-1].close_time.isoformat(), True, request, "")
    )
    value = json_value(record)
    encoded = json.dumps(value)
    restored = json.loads(encoded)
    bars = restored["plan"]["signal"]
    assert len(bars) == 168
    assert bars[-1]["close_time"] == request.signal[-1].close_time.isoformat()
    assert bars[-1]["close"]["value"] == str(request.mark.value)


def test_blocked_partial_candidate_does_not_invent_a_plan() -> None:
    record = partial_decision_record(
        PartialDecision("known-time", False, None, "THIRD_GENERATION_FORBIDDEN")
    )
    restored = json.loads(json.dumps(json_value(record)))
    assert restored["plan"] is None
    assert restored["applied"] is False


@pytest.mark.parametrize("policy", ["P2", "P2L"])
def test_full_worker_exports_financial_results_and_replay_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    from gridbot.backtest.configuration import configuration
    from tests.backtest.test_engine import config, dataset

    market = dataset(("80,80,80,80,10",) * 168 + ("80,81,69,80,10", "80,91,79,90,10"))
    raw = market.raw
    (tmp_path / "input.csv").write_bytes(raw)
    manifest = dict(
        version=1,
        csv_path="input.csv",
        origin=market.spec.origin,
        synthetic=True,
        timeframe_seconds=60,
        start=market.spec.start.isoformat(),
        end=market.spec.end.isoformat(),
        format=market.spec.format.value,
        epoch_unit=market.spec.epoch_unit,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    manifest_path = tmp_path / "dataset.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    cfg_path = tmp_path / "configuration.json"
    cfg_path.write_text(json.dumps(configuration(config())), encoding="utf8")
    monkeypatch.setattr(a19_6_study, "memory", lambda _: {})
    output = tmp_path / "out"
    a19_6_study.worker(manifest_path, cfg_path, output, policy, "test")
    result = json.loads((output / "result.json").read_text())
    receipt = json.loads((output / "measurement.json").read_text())
    assert receipt["status"] == "PASS"
    assert result["oracle"]["grid"]["points"] == 170
    assert result["new_generations"] == 1
    assert (output / "paper_sources.json").stat().st_size > 0
