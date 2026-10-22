from pathlib import Path

from gridbot.backtest.engine import run_backtest
from gridbot.backtest.export import export_run, replay_sources
from tests.backtest.test_engine import config, dataset
from tests.paper.simulation_oracle import assert_source_conservation


def test_engine_and_export_replay_retain_more_than_256_financial_events(tmp_path: Path) -> None:
    values = ["100,110,90,105,10"]
    for _ in range(26):
        values.extend(["100,106,89,100,10", "100,111,99,110,10"])
    market = dataset(tuple(values))
    result = run_backtest(market, config(), code_commit="synthetic-long-history")
    assert result.metrics.cycles == 52
    assert result.sources.revision == 260
    assert_source_conservation(result.sources, result.points[-1].state)
    folder = tmp_path / "retained-financial-sources"
    export_run(result, folder, dataset=market)
    assert len((folder / "paper_sources.jsonl").read_text().splitlines()) == 261
    recovered = replay_sources(folder / "paper_sources.jsonl", max_events=config().max_events)
    assert recovered.snapshot() == result.points[-1].state
    assert len(recovered.source_log().events) == 260
