"""Exercise the actual research adapter, including serialized lifecycle evidence."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts.a19_4_study import diagnostics, study

from gridbot.backtest.configuration import configuration
from gridbot.backtest.data import BacktestError
from gridbot.backtest.execution import BNB
from gridbot.backtest.export import json_value, replay_sources
from gridbot.backtest.recenter import run_recenter_backtest
from gridbot.domain import Money
from tests.backtest.test_engine import config, dataset


def test_lifecycle_evidence_serializes_native_generations_and_trade_links() -> None:
    market = dataset(("80,80,80,80,10",) * 168 + ("80,81,69,80,10", "80,91,79,90,10"))
    run = run_recenter_backtest(
        market, config(), code_commit="test", policy="P2", configuration_ref="CFG:UNIT"
    )
    report = json.loads(json.dumps(json_value(diagnostics(market, run))))
    assert report["reconfigurations"] == 1
    assert report["transition_oracle"][0]["economic_state_unchanged"]
    assert len(report["generations"]) == 2
    generation = report["generations"][1]
    assert generation["original_experiment_configuration"] == configuration(config())
    assert generation["linked_operations"]
    assert len(generation["fees"]) == len(generation["linked_operations"])
    assert generation["cycle_refs"]
    assert report["candidates"][0]["plan"]["supplied_plan_sha256"]


@pytest.mark.parametrize("funded", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_research_worker_exports_replayable_sources_or_refuses_incomplete_cash_reference(
    tmp_path: Path, funded: bool, mixed: bool
) -> None:
    market = dataset(("80,80,80,80,10",) * 168 + ("80,81,69,80,10", "80,91,79,90,10"))
    if mixed:
        market = dataset(("105,105,105,105,10", "105,106,99,105,10", "105,120,80,105,10"))
    cfg = config()
    if funded:
        cfg = replace(cfg, third_asset_funding=(Money.parse("1", BNB),))
    raw = market.raw
    # Input files are explicit supplied offline sources, never exchange access.
    (tmp_path / "input.csv").write_bytes(raw)
    spec = market.spec
    manifest = dict(
        version=1,
        csv_path="input.csv",
        origin=spec.origin,
        synthetic=spec.synthetic,
        timeframe_seconds=60,
        start=spec.start.isoformat(),
        end=spec.end.isoformat(),
        format=spec.format.value,
        epoch_unit=spec.epoch_unit,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(manifest), encoding="utf8")
    cfg_path = tmp_path / "configuration.json"
    cfg_path.write_text(json.dumps(configuration(cfg)), encoding="utf8")
    output = tmp_path / "result"
    if funded:
        with pytest.raises(BacktestError, match="third-asset funding"):
            study(dataset_path, cfg_path, output, "test", "P2", "CFG:UNIT")
        assert not (output / "lifecycle.json").exists()
        return
    study(dataset_path, cfg_path, output, "test", "P2", "CFG:UNIT")
    lifecycle = json.loads((output / "lifecycle.json").read_text(encoding="utf8"))
    assert lifecycle["reconfigurations"] == (0 if mixed else 1)
    if mixed:
        result = json.loads((output / "study_results.json").read_text(encoding="utf8"))
        assert result["details"]["DEFER_MIXED"] > 0
    sources = output / "artifacts" / "paper_sources.jsonl"
    replay = replay_sources(sources, max_events=cfg.max_events)
    assert len(replay.generations) == (1 if mixed else 2)
