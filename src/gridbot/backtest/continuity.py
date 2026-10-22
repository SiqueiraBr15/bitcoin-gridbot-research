"""Offline structural eligibility, exact minute aggregation and independent windows.

These reports do not authenticate a venue or authorize execution across a halt.
The existing engine continues to require complete native candles, without gaps.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from gridbot.backtest.archives import _read
from gridbot.backtest.data import HEADER, BacktestError, CsvFormat, Dataset, DatasetSpec, check
from gridbot.domain import BTCUSDT, Candle, Price, Qty, Timeframe
from gridbot.domain.decimals import financial
from gridbot.domain.time import require_utc
from gridbot.marketdata.archive_contract import MAX_CHECKSUM_BYTES, MAX_ZIP_BYTES, MONTHS, unpack


class Eligibility(StrEnum):
    CONTINUOUS_VERIFIED = "CONTINUOUS_VERIFIED"
    DERIVED_VERIFIED = "DERIVED_VERIFIED"
    DOCUMENTED_MARKET_INTERRUPTION = "DOCUMENTED_MARKET_INTERRUPTION"
    INCOMPLETE_OR_UNRESOLVED = "INCOMPLETE_OR_UNRESOLVED"
    NOT_ELIGIBLE_FOR_CONTINUOUS_BACKTEST = "NOT_ELIGIBLE_FOR_CONTINUOUS_BACKTEST"


@dataclass(frozen=True, slots=True)
class Assessment:
    classification: Eligibility
    sha256: str
    reason: str


def assess(raw: bytes, spec: DatasetSpec) -> Assessment:
    """Structural checks only; source authenticity and venue status are separate."""
    check(type(raw) is bytes, "native source bytes required")
    try:
        dataset = Dataset(raw, spec)
    except BacktestError as exc:
        return Assessment(
            Eligibility.INCOMPLETE_OR_UNRESOLVED, hashlib.sha256(raw).hexdigest(), str(exc)
        )
    complete = dataset.manifest()["complete"] is True
    return Assessment(
        Eligibility.CONTINUOUS_VERIFIED
        if complete
        else Eligibility.NOT_ELIGIBLE_FOR_CONTINUOUS_BACKTEST,
        dataset.sha256,
        "native complete interval" if complete else "missing bars or interval edges",
    )


def aggregate_hour(raw: bytes, spec: DatasetSpec) -> Candle:
    """DERIVED from exactly60 aligned, complete native minute bars; never impute."""
    check(type(spec) is DatasetSpec, "native minute specification required")
    check(spec.timeframe == Timeframe.minutes(1), "one-minute source required")
    check(
        spec.start.minute == spec.start.second == spec.start.microsecond == 0
        and spec.end - spec.start == timedelta(hours=1),
        "one aligned UTC hour required",
    )
    source = Dataset(raw, spec)
    check(source.manifest()["complete"] is True and len(source.series) == 60, "60 complete minutes")
    bars = source.series.candles
    with financial():
        volume = Qty(sum((bar.volume.value for bar in bars), start=Qty.zero().value))
    return Candle(
        BTCUSDT,
        Timeframe.hours(1),
        spec.start,
        spec.end,
        bars[0].open,
        Price(max(bar.high.value for bar in bars)),
        Price(min(bar.low.value for bar in bars)),
        bars[-1].close,
        volume,
    )


def verify_derivation(
    minutes: bytes, minute_spec: DatasetSpec, hourly: bytes, hour_spec: DatasetSpec
) -> Candle:
    """Compare independent representations without choosing a profitable version."""
    derived = aggregate_hour(minutes, minute_spec)
    reference = Dataset(hourly, hour_spec)
    check(
        reference.manifest()["complete"] is True and len(reference.series) == 1,
        "one complete reference hour required",
    )
    check(derived == reference.series.candles[0], "granular/hourly source disagreement")
    return derived


@dataclass(frozen=True, slots=True)
class IndependentWindow:
    dataset: Dataset
    sources: tuple[dict[str, object], ...]
    classification: Eligibility = Eligibility.CONTINUOUS_VERIFIED
    reset_initial_state: bool = True


def independent_window(root: Path, start: datetime, end: datetime) -> IndependentWindow:
    """Admit only selected exact source rows within declared aligned calendar bounds.

    Each result is an independent experiment. Never claim state continuity with
    another window. A partial archive outside the requested window is excluded
    explicitly, while every selected row is validated with the native12-column parser.
    """
    require_utc(start)
    require_utc(end)
    check(
        start < end
        and start.minute == start.second == start.microsecond == 0
        and end.minute == end.second == end.microsecond == 0,
        "strict aligned hourly bounds required",
    )
    check(MONTHS[0].start <= start < end <= MONTHS[-1].end, "outside frozen corpus")
    check(not root.is_symlink() and not root.is_junction(), "corpus link refused")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADER)
    manifests = []
    for month in MONTHS:
        if month.end <= start or month.start >= end:
            continue
        path = root / (month.stem + ".zip")
        raw = _read(path, MAX_ZIP_BYTES)
        payload = unpack(raw, _read(path.with_suffix(".zip.CHECKSUM"), MAX_CHECKSUM_BYTES), month)
        lower, upper = max(start, month.start), min(end, month.end)
        selected = []
        for line in payload.splitlines(keepends=True):
            epoch = line.split(b",", 1)[0]
            check(epoch.isascii() and epoch.isdigit() and len(epoch) <= 18, "invalid source epoch")
            # Avoid float timestamp conversion; all row identities remain source epochs.
            try:
                from_epoch = datetime(1970, 1, 1, tzinfo=start.tzinfo) + timedelta(
                    microseconds=int(epoch) * (1000 if month.unit == "ms" else 1)
                )
            except OverflowError as exc:
                raise BacktestError("source epoch outside datetime range") from exc
            check(month.start <= from_epoch < month.end, "source epoch outside declared month")
            if lower <= from_epoch < upper:
                selected.append(line)
        subset = b"".join(selected)
        piece = Dataset(
            subset,
            DatasetSpec(
                month.url,
                False,
                Timeframe.hours(1),
                lower,
                upper,
                CsvFormat.BINANCE_KLINES_12,
                month.unit,
            ),
        )
        check(piece.manifest()["complete"] is True, "window contains gap or missing edge")
        for candle in piece.series:
            writer.writerow(
                [
                    candle.open_time.isoformat(),
                    candle.close_time.isoformat(),
                    *(
                        str(value.value)
                        for value in (candle.open, candle.high, candle.low, candle.close)
                    ),
                    str(candle.volume.value),
                ]
            )
        manifests.append(
            dict(
                source=month.url,
                source_zip_sha256=hashlib.sha256(raw).hexdigest(),
                source_csv_sha256=hashlib.sha256(payload).hexdigest(),
                selected_native_sha256=piece.sha256,
                selected_start=lower.isoformat(),
                selected_end=upper.isoformat(),
                selected_rows=len(piece.series),
                excluded_rows=len(payload.splitlines()) - len(selected),
                source_epoch_unit=month.unit,
            )
        )
    dataset = Dataset(
        output.getvalue().encode("utf8"),
        DatasetSpec(
            "Binance official Spot BTCUSDT1h; independent exact calendar window",
            False,
            Timeframe.hours(1),
            start,
            end,
            CsvFormat.UTC_V1,
        ),
    )
    check(dataset.manifest()["complete"] is True, "window transition gap refused")
    return IndependentWindow(dataset, tuple(manifests))


def continuous_input(windows: tuple[IndependentWindow, ...]) -> Dataset:
    """Reject resets presented as one capital-continuous performance history."""
    check(len(windows) == 1, "independent resets cannot be concatenated as continuous equity")
    return windows[0].dataset
