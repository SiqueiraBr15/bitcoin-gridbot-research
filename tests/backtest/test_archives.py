from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gridbot.backtest.archives import import_corpus, month_dataset
from gridbot.backtest.data import BacktestError
from gridbot.marketdata.archive_contract import MONTHS as ALL_MONTHS
from gridbot.marketdata.archive_contract import ArchiveError, Month


def monthly(month: Month, *, bad: str = "") -> tuple[bytes, bytes]:
    unit = 1000 if month.unit == "ms" else 1
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    opened = month.start
    rows = []
    while opened < month.end:
        start = (opened - epoch) // timedelta(microseconds=unit)
        end = (opened + timedelta(hours=1) - epoch) // timedelta(microseconds=unit) - 1
        rows.append([start, "100", "110", "90", "105", "10", end, "1000", 10, "5", "500", 0])
        opened += timedelta(hours=1)
    if bad == "gap":
        rows.pop(10)
    elif bad == "duplicate":
        rows.insert(10, rows[10])
    elif bad == "ohlc":
        rows[10][2] = "99"
    elif bad == "unit":
        rows[10][0] = int(str(rows[10][0])) * 1000
    elif bad == "truncated":
        rows[-1].pop()
    elif bad == "nonstandard_zero_volume_close":
        # Observed structure in official March 2023 archive; never extend its close.
        rows[10][5] = "0"
        rows[10][6] = int(str(rows[10][0])) + 2_381_646
    text = io.StringIO(newline="")
    csv.writer(text, lineterminator="\n").writerows(rows)
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(month.stem + ".csv", text.getvalue())
    raw = archive_bytes.getvalue()
    official = f"{hashlib.sha256(raw).hexdigest()}  {month.stem}.zip\n".encode()
    return raw, official


def test_actual_epoch_rules_and_transition_without_global_division() -> None:
    december, january = Month(2024, 12), Month(2025, 1)
    dec = month_dataset(*monthly(december), december)
    jan = month_dataset(*monthly(january), january)
    assert len(dec.series) == len(jan.series) == 744
    assert dec.series.candles[-1].close_time == jan.series.candles[0].open_time
    assert jan.series.candles[0].open_time == datetime(2025, 1, 1, tzinfo=UTC)
    assert jan.series.candles[0].close_time == datetime(2025, 1, 1, 1, tzinfo=UTC)
    assert dec.manifest()["epoch_unit"] == "ms"
    assert jan.manifest()["epoch_unit"] == "us"


@pytest.mark.parametrize(
    "bad", ["gap", "duplicate", "ohlc", "unit", "truncated", "nonstandard_zero_volume_close"]
)
def test_invalid_month_cannot_become_eligible(bad: str) -> None:
    month = Month(2025, 1)
    raw, official = monthly(month, bad=bad)
    with pytest.raises((BacktestError, ArchiveError)):
        month_dataset(raw, official, month)


def test_missing_corpus_never_emits_partial_result(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_corpus(tmp_path)
    assert not list(tmp_path.iterdir())


def test_complete_offline_corpus_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    for month in ALL_MONTHS:
        raw, official = monthly(month)
        (tmp_path / (month.stem + ".zip")).write_bytes(raw)
        (tmp_path / (month.stem + ".zip.CHECKSUM")).write_bytes(official)
    a, b = import_corpus(tmp_path), import_corpus(tmp_path)
    assert a.dataset.raw == b.dataset.raw
    assert a.dataset.sha256 == b.dataset.sha256
    assert len(a.dataset.series) == 35064
    assert a.dataset.manifest()["complete"] is True
    assert len(a.months) == 48
    assert a.dataset.spec.synthetic is False  # provenance declaration, not authenticity proof
    first = tmp_path / (ALL_MONTHS[0].stem + ".zip")
    first.write_bytes(first.read_bytes() + b"tamper")
    with pytest.raises(ArchiveError, match="checksum"):
        import_corpus(tmp_path)
