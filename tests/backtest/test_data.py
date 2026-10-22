from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from gridbot.backtest.data import (
    HEADER,
    BacktestError,
    ChronologicalSplit,
    CsvFormat,
    Dataset,
    DatasetSpec,
    read_csv,
)
from gridbot.domain import Timeframe

START = datetime(2024, 1, 1, tzinfo=UTC)


def spec(count: int = 3) -> DatasetSpec:
    return DatasetSpec(
        "synthetic unit fixture",
        True,
        Timeframe.minutes(1),
        START,
        START + timedelta(minutes=count),
        CsvFormat.UTC_V1,
    )


def row(i: int = 0, values: str = "100,110,90,105,10") -> str:
    opened = (START + timedelta(minutes=i)).isoformat()
    closed = (START + timedelta(minutes=i + 1)).isoformat()
    return f"{opened},{closed},{values}\n"


def raw(rows: str | None = None) -> bytes:
    return (
        ",".join(HEADER) + "\n" + ("".join(row(i) for i in range(3)) if rows is None else rows)
    ).encode()


def test_csv_sources_hash_and_coverage(tmp_path: Path) -> None:
    source = raw()
    dataset = Dataset(source, replace(spec(), expected_sha256=sha256(source).hexdigest()))
    assert dataset.manifest()["complete"] is True
    assert dataset.manifest()["candles"] == 3
    assert dataset.sha256 == sha256(source).hexdigest()
    path = tmp_path / "candles.csv"
    path.write_bytes(source)
    assert read_csv(path, dataset.spec) == dataset
    with pytest.raises(BacktestError, match="hash mismatch"):
        Dataset(source.replace(b"105", b"106"), dataset.spec)


@pytest.mark.parametrize(
    "values",
    [
        "0,110,90,105,10",
        "-1,110,90,105,10",
        "100,80,90,105,10",
        "100,110,101,105,10",
        "100,110,90,120,10",
        "100,110,90,105,-1",
        "NaN,110,90,105,10",
        "100,Infinity,90,105,10",
        "100,110,90,105,NaN",
        "1e100,110,90,105,10",
        "1e-100,110,90,105,10",
        "12345678901234567890123456789012345,110,90,105,10",
        "100,110,90,105,1_000",
        "100,110,90,105",
        "100,110,90,105,10,extra",
    ],
)
def test_invalid_ohlc_and_precision(values: str) -> None:
    with pytest.raises(BacktestError):
        Dataset(raw(row(values=values)), spec())


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"wrong\n",
        ",".join(HEADER).encode(),
        raw(row(1) + row(0)),
        raw(row(0) + row(0)),
        raw(row().replace("+00:00", "")),
        raw(row().replace("+00:00", "+01:00")),
        raw(row().replace("00:01:00", "00:00:30")),
        raw(row().replace("2024-01-01", "not-a-date")),
        b"\xff",
    ],
)
def test_bad_schema_dates_order_duplicates_and_empty(source: bytes) -> None:
    with pytest.raises(BacktestError):
        Dataset(source, spec())


def test_gap_and_missing_edges_are_reported_without_imputation() -> None:
    dataset = Dataset(raw(row(0) + row(2)), spec())
    assert len(dataset.series) == 2
    assert dataset.series.gaps[0].missing_bars == 1
    assert dataset.manifest()["gaps"]
    assert dataset.manifest()["complete"] is False
    prefix = Dataset(raw(row(1) + row(2)), spec())
    assert prefix.manifest()["missing_prefix_us"] == 60_000_000


@pytest.mark.parametrize(("unit", "multiplier"), [("ms", 1000), ("us", 1)])
def test_explicit_public_kline_layout_inclusive_end(unit: str, multiplier: int) -> None:
    epoch_us = (START - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1)
    opened = epoch_us // multiplier
    closed = opened + 60_000_000 // multiplier - 1
    source = f"{opened},100,110,90,105,10,{closed},1000,5,5,500,0\n".encode()
    dataset = Dataset(source, replace(spec(1), format=CsvFormat.BINANCE_KLINES_12, epoch_unit=unit))
    assert dataset.series.candles[0].open_time == START
    assert dataset.series.candles[0].close_time == START + timedelta(minutes=1)
    with pytest.raises(BacktestError):
        Dataset(source, replace(dataset.spec, epoch_unit="us" if unit == "ms" else "ms"))


def test_temporal_split_is_disjoint_and_rejects_partial_bars() -> None:
    dataset = Dataset(raw(), spec())
    split = ChronologicalSplit(
        START,
        START + timedelta(minutes=1),
        START + timedelta(minutes=2),
        START + timedelta(minutes=3),
    )
    segments = [split.segment(dataset, name) for name in ["development", "validation", "test"]]
    assert [len(x) for x in segments] == [1, 1, 1]
    assert len({c.open_time for s in segments for c in s}) == 3
    with pytest.raises(BacktestError):
        replace(split, development_end=START + timedelta(seconds=30)).segment(
            dataset, "development"
        )
    with pytest.raises(BacktestError):
        replace(split, validation_end=split.development_end)
