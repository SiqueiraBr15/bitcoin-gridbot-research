from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.backtest.continuity import (
    Eligibility,
    aggregate_hour,
    assess,
    continuous_input,
    independent_window,
    verify_derivation,
)
from gridbot.backtest.data import HEADER, BacktestError, CsvFormat, DatasetSpec
from gridbot.domain import Timeframe
from gridbot.marketdata.archive_contract import ArchiveError, Month
from tests.backtest.test_archives import monthly

START = datetime(2023, 3, 24, 10, tzinfo=UTC)


def minute_source(
    *, missing: int | None = None, partial: bool = False, volume: str = ".1"
) -> bytes:
    rows = [",".join(HEADER)]
    for i in range(60):
        if i == missing:
            continue
        begin = START + timedelta(minutes=i)
        end = begin + timedelta(seconds=41 if partial and i == 59 else 60)
        rows.append(f"{begin.isoformat()},{end.isoformat()},100,110,90,105,{volume}")
    return ("\n".join(rows) + "\n").encode()


def spec() -> DatasetSpec:
    return DatasetSpec(
        "synthetic minute fixtures",
        True,
        Timeframe.minutes(1),
        START,
        START + timedelta(hours=1),
        CsvFormat.UTC_V1,
    )


def test_exact_complete_hour_aggregation_and_original_bytes() -> None:
    raw = minute_source()
    before = hashlib.sha256(raw).hexdigest()
    bar = aggregate_hour(raw, spec())
    assert tuple(str(p.value) for p in (bar.open, bar.high, bar.low, bar.close)) == (
        "100",
        "110",
        "90",
        "105",
    )
    assert str(bar.volume.value) == "6.0"
    assert bar.open_time == START
    assert bar.close_time == START + timedelta(hours=1)
    assert hashlib.sha256(raw).hexdigest() == before


@given(st.integers(min_value=0, max_value=59))
@settings(max_examples=20, deadline=None)
def test_any_missing_minute_refuses_reconstruction(index: int) -> None:
    with pytest.raises(BacktestError):
        aggregate_hour(minute_source(missing=index), spec())


def test_partial_zero_trade_minute_is_not_a_complete_hour() -> None:
    with pytest.raises(BacktestError):
        aggregate_hour(minute_source(partial=True, volume="0"), spec())


def test_complete_zero_volume_is_valid_data_but_not_proof_of_market_halt() -> None:
    raw = minute_source(volume="0")
    assert aggregate_hour(raw, spec()).volume.is_zero
    assert assess(raw, spec()).classification is Eligibility.CONTINUOUS_VERIFIED
    assert assess(raw, spec()).classification is not Eligibility.DOCUMENTED_MARKET_INTERRUPTION


@pytest.mark.parametrize("conflict", [False, True])
def test_granular_reference_agreement_and_divergence(conflict: bool) -> None:
    hourly = (
        ",".join(HEADER)
        + "\n"
        + START.isoformat()
        + ","
        + (START + timedelta(hours=1)).isoformat()
        + ",100,110,90,105,"
        + ("7" if conflict else "6")
        + "\n"
    ).encode()
    hour_spec = replace(spec(), timeframe=Timeframe.hours(1))
    if conflict:
        with pytest.raises(BacktestError, match="disagreement"):
            verify_derivation(minute_source(), spec(), hourly, hour_spec)
    else:
        assert verify_derivation(minute_source(), spec(), hourly, hour_spec) == aggregate_hour(
            minute_source(), spec()
        )


@pytest.mark.parametrize("kind", ["unaligned", "two_hours", "wrong_timeframe"])
def test_wrong_aggregation_contract_refuses(kind: str) -> None:
    value = spec()
    if kind == "unaligned":
        value = replace(value, start=START + timedelta(minutes=1))
    elif kind == "two_hours":
        value = replace(value, end=START + timedelta(hours=2))
    else:
        value = replace(value, timeframe=Timeframe.hours(1))
    with pytest.raises(BacktestError):
        aggregate_hour(minute_source(), value)


@pytest.mark.parametrize("kind", ["gap", "edge", "partial", "duplicate", "timestamp"])
def test_eligibility_is_not_checksum_boolean(kind: str) -> None:
    raw = minute_source(
        missing=20 if kind == "gap" else 0 if kind == "edge" else None, partial=kind == "partial"
    )
    if kind == "duplicate":
        raw += raw.splitlines(keepends=True)[-1]
    if kind == "timestamp":
        raw = raw.replace(b"2023-03-24T10:01", b"2023-03-24T09:01")
    result = assess(raw, spec())
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    expected = (
        Eligibility.NOT_ELIGIBLE_FOR_CONTINUOUS_BACKTEST
        if kind in ["gap", "edge"]
        else Eligibility.INCOMPLETE_OR_UNRESOLVED
    )
    assert result.classification is expected


def install(root: Path, month: Month, bad: str = "") -> None:
    raw, checksum = monthly(month, bad=bad)
    (root / (month.stem + ".zip")).write_bytes(raw)
    (root / (month.stem + ".zip.CHECKSUM")).write_bytes(checksum)


def test_independent_ms_us_window_is_deterministic_and_cannot_join_resets(tmp_path: Path) -> None:
    a, b = Month(2024, 12), Month(2025, 1)
    install(tmp_path, a)
    install(tmp_path, b)
    left, right = a.end - timedelta(hours=2), b.start + timedelta(hours=2)
    window = independent_window(tmp_path, left, right)
    other = independent_window(tmp_path, left, right)
    assert window.dataset.raw == other.dataset.raw
    assert window.dataset.manifest()["complete"] is True
    assert len(window.dataset.series) == 4
    assert [x["source_epoch_unit"] for x in window.sources] == ["ms", "us"]
    assert all(x["excluded_rows"] == 742 for x in window.sources)
    assert window.reset_initial_state is True
    assert continuous_input((window,)) is window.dataset
    with pytest.raises(BacktestError, match="resets"):
        continuous_input((window, other))
    with pytest.raises(BacktestError, match="resets"):
        continuous_input(())


def test_partial_outside_window_is_explicitly_excluded_not_repaired(tmp_path: Path) -> None:
    month = Month(2023, 3)
    install(tmp_path, month, "nonstandard_zero_volume_close")
    snapshots = {p: p.read_bytes() for p in tmp_path.iterdir()}
    # Fixture's anomaly is at the eleventh hour, before this explicit study window.
    window = independent_window(tmp_path, month.start + timedelta(hours=12), month.end)
    assert window.sources[0]["excluded_rows"] == 12
    assert len(window.dataset.series) == 732
    with pytest.raises(BacktestError):
        independent_window(tmp_path, month.start, month.end)
    assert all(p.read_bytes() == raw for p, raw in snapshots.items())


@pytest.mark.parametrize("bad", ["gap", "duplicate", "ohlc", "unit", "truncated"])
def test_selected_bad_rows_refuse_window(tmp_path: Path, bad: str) -> None:
    month = Month(2023, 3)
    install(tmp_path, month, bad)
    with pytest.raises(BacktestError):
        independent_window(tmp_path, month.start, month.end)


def test_changed_source_checksum_and_missing_archive_refuse(tmp_path: Path) -> None:
    month = Month(2023, 3)
    with pytest.raises(FileNotFoundError):
        independent_window(tmp_path, month.start, month.end)
    install(tmp_path, month)
    archive = tmp_path / (month.stem + ".zip")
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(ArchiveError, match="checksum"):
        independent_window(tmp_path, month.start, month.end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, START),
        (START + timedelta(minutes=1), START + timedelta(hours=1)),
        (datetime(2021, 1, 1, tzinfo=UTC), START),
    ],
)
def test_invalid_study_bounds_refuse(tmp_path: Path, start: datetime, end: datetime) -> None:
    with pytest.raises(BacktestError):
        independent_window(tmp_path, start, end)
