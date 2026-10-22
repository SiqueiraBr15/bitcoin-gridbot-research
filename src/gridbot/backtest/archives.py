"""Offline validation/normalization of the finite Spot monthly public corpus."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from gridbot.backtest.data import HEADER, CsvFormat, Dataset, DatasetSpec, check
from gridbot.domain import Timeframe
from gridbot.marketdata.archive_contract import (
    MAX_CHECKSUM_BYTES,
    MAX_ZIP_BYTES,
    MONTHS,
    Month,
    unpack,
)


@dataclass(frozen=True, slots=True)
class ImportedCorpus:
    dataset: Dataset
    months: tuple[dict[str, object], ...]


def month_dataset(raw: bytes, official: bytes, month: Month) -> Dataset:
    dataset = Dataset(
        unpack(raw, official, month),
        DatasetSpec(
            month.url,
            False,
            Timeframe.hours(1),
            month.start,
            month.end,
            CsvFormat.BINANCE_KLINES_12,
            month.unit,
        ),
    )
    check(dataset.manifest()["complete"] is True, "incomplete monthly archive; no gap filling")
    return dataset


def _read(path: Path, limit: int) -> bytes:
    check(not path.is_symlink() and not path.is_junction(), "archive link refused")
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    check(0 < len(raw) <= limit, "archive file size quota")
    return raw


def import_corpus(root: Path) -> ImportedCorpus:
    """All 48 months or refusal. Never execute a partial or imputed corpus."""
    check(not root.is_symlink() and not root.is_junction(), "corpus link refused")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADER)
    manifests = []
    for month in MONTHS:
        path = root / (month.stem + ".zip")
        raw = _read(path, MAX_ZIP_BYTES)
        dataset = month_dataset(
            raw, _read(path.with_suffix(".zip.CHECKSUM"), MAX_CHECKSUM_BYTES), month
        )
        for candle in dataset.series:
            writer.writerow(
                [
                    candle.open_time.isoformat(),
                    candle.close_time.isoformat(),
                    *(str(p.value) for p in (candle.open, candle.high, candle.low, candle.close)),
                    str(candle.volume.value),
                ]
            )
        raw_rows = dataset.raw.splitlines()
        manifests.append(
            dict(
                dataset.manifest(),
                zip_sha256=hashlib.sha256(raw).hexdigest(),
                first_open_utc=dataset.series.candles[0].open_time.isoformat(),
                last_close_exclusive_utc=dataset.series.candles[-1].close_time.isoformat(),
                first_raw_open=raw_rows[0].split(b",")[0].decode("ascii"),
                last_raw_close_inclusive=raw_rows[-1].split(b",")[6].decode("ascii"),
            )
        )
    canonical = Dataset(
        output.getvalue().encode("utf8"),
        DatasetSpec(
            "Binance public Spot monthly BTCUSDT 1h; official SHA256 verified per archive",
            False,
            Timeframe.hours(1),
            MONTHS[0].start,
            MONTHS[-1].end,
            CsvFormat.UTC_V1,
        ),
    )
    check(canonical.manifest()["complete"] is True, "corpus gap/transition refused")
    check(
        len(canonical.series) == (MONTHS[-1].end - MONTHS[0].start) // timedelta(hours=1),
        "corpus count mismatch",
    )
    return ImportedCorpus(canonical, tuple(manifests))
