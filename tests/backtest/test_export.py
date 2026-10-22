import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from gridbot.backtest.configuration import configuration, dataset_spec, parse_json, scenario
from gridbot.backtest.data import BacktestError
from gridbot.backtest.engine import BacktestResult, run_backtest
from gridbot.backtest.export import export_run, json_value, replay_sources
from gridbot.paper.simulation import SimulationError
from tests.backtest.test_engine import config, dataset


@pytest.fixture(scope="module")
def result() -> BacktestResult:
    return run_backtest(dataset(), config(), code_commit="export-unit")


def test_closed_configuration_roundtrip_and_financial_strings() -> None:
    document = configuration(config())
    assert scenario(parse_json(json.dumps(document))) == config()
    with pytest.raises(BacktestError):
        scenario(dict(document, core_btc="1"))
    with pytest.raises(BacktestError):
        scenario(dict(document, version=True))
    with pytest.raises(BacktestError):
        scenario(dict(document, capital_usdt=100))
    with pytest.raises(TypeError):
        json_value(1.5)


def test_large_json_node_quota_is_independent_of_file_and_depth_quota() -> None:
    source = "[" + ",".join("0" for _ in range(600_000)) + "]"
    with pytest.raises(BacktestError, match="node quota"):
        parse_json(source)


def test_explicit_json_depth_boundary_does_not_depend_on_python_recursion_limit() -> None:
    assert isinstance(parse_json("[" * 128 + "0" + "]" * 128), list)
    with pytest.raises(BacktestError, match="depth"):
        parse_json("[" * 129 + "0" + "]" * 129)


@pytest.mark.parametrize(
    "source",
    [
        '{"a":1,"a":2}',
        '{"fee":0.1}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":12345678901234567890}',
        "[" * 2000 + "]" * 2000,
    ],
    ids=["duplicate", "fraction", "nan", "infinity", "integer", "depth"],
)
def test_duplicate_fractional_and_deep_json_rejected(source: str) -> None:
    with pytest.raises(BacktestError):
        parse_json(source)


def test_export_is_reproducible_complete_and_replayable(
    tmp_path: Path,
    result: BacktestResult,
) -> None:
    a, b = tmp_path / "first", tmp_path / "second"
    one = export_run(result, a, dataset=dataset())
    two = export_run(result, b, dataset=dataset())
    assert one == two
    for path in a.iterdir():
        assert path.read_bytes() == (b / path.name).read_bytes()
    manifest = json.loads((a / "export_manifest.json").read_text())
    assert manifest["complete"] is True
    for artifact in manifest["artifacts"]:
        assert hashlib.sha256((a / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    replay = replay_sources(a / "paper_sources.jsonl", max_events=config().max_events)
    assert replay.snapshot() == result.points[-1].state
    benchmark = replay_sources(a / "benchmark_sources.jsonl", max_events=8)
    assert benchmark.snapshot() == result.benchmark_points[-1].state
    assert scenario(json.loads((a / "configuration.json").read_text())) == config()
    filename, spec = dataset_spec(json.loads((a / "dataset.json").read_text()))
    assert filename == "input.csv"
    assert spec.expected_sha256 == dataset().sha256
    assert "SYNTHETIC TEST DATA" in (a / "report.md").read_text()
    with pytest.raises(FileExistsError):
        export_run(result, a, dataset=dataset())


def test_export_wrong_dataset_and_incomplete_source_refuse(
    tmp_path: Path, result: BacktestResult
) -> None:
    foreign = replace(dataset(), raw=dataset().raw.replace(b"105", b"104"))
    with pytest.raises(BacktestError, match="differs"):
        export_run(result, tmp_path / "wrong", dataset=foreign)
    assert not (tmp_path / "wrong").exists()
    folder = tmp_path / "valid"
    export_run(result, folder, dataset=dataset())
    path = folder / "paper_sources.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(SimulationError):
        replay_sources(path, max_events=1000)


def test_offline_cli_uses_exported_inputs_without_credential_or_mode_change(
    tmp_path: Path,
    result: BacktestResult,
) -> None:
    folder = tmp_path / "inputs"
    export_run(result, folder, dataset=dataset())
    output = tmp_path / "cli-output"
    command = [
        sys.executable,
        "-m",
        "gridbot.backtest",
        "--dataset",
        str(folder / "dataset.json"),
        "--configuration",
        str(folder / "configuration.json"),
        "--output",
        str(output),
        "--code-commit",
        "export-unit",
    ]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    assert (folder / "result.json").read_bytes() == (output / "result.json").read_bytes()
    assert (folder / "operations.csv").read_bytes() == (output / "operations.csv").read_bytes()
    assert "OFFLINE_BACKTEST_EXPORTED" in done.stdout
    refused = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert refused.returncode == 2


def test_cli_missing_source_refuses_without_creating_an_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gridbot.backtest.__main__ import main

    output = tmp_path / "absent-output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gridbot.backtest",
            "--dataset",
            str(tmp_path / "missing.json"),
            "--configuration",
            str(tmp_path / "configuration.json"),
            "--output",
            str(output),
            "--code-commit",
            "unit-refusal",
        ],
    )
    assert main() == 2
    assert not output.exists()
    assert "BACKTEST_REFUSED" in capsys.readouterr().err
