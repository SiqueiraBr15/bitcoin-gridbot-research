"""Bounded offline CSV ingestion, bound to its exact source bytes (ADR-036)."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from gridbot.domain import BTCUSDT, Candle, CandleSeries, Price, Qty, Timeframe
from gridbot.domain.decimals import require_finite, to_decimal
from gridbot.domain.errors import DomainError
from gridbot.domain.time import require_utc

MAX_BYTES = 64 * 1024 * 1024
MAX_CANDLES = 100_000
HEADER = ("open_time_utc", "close_time_utc", "open", "high", "low", "close", "volume")
_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class BacktestError(DomainError):
    """A refused experiment is never a successful partial historical result."""


def check(condition: bool, detail: str) -> None:
    if not condition:
        raise BacktestError(detail)


def utc(text: str) -> datetime:
    check(type(text) is str and len(text) <= 40, "bounded UTC timestamp required")
    try:
        return require_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except (ValueError, TypeError) as exc:
        raise BacktestError("invalid or ambiguous UTC timestamp") from exc


def number(text: str) -> Decimal:
    check(
        type(text) is str and len(text) <= 80 and _LITERAL.fullmatch(text) is not None,
        "bounded decimal literal required",
    )
    return bounded_decimal(to_decimal(text))


def bounded_decimal(value: Decimal) -> Decimal:
    require_finite(value)
    check(
        len(value.as_tuple().digits) <= 34 and abs(int(value.as_tuple().exponent)) <= 18,
        "experiment input precision exceeds explicit 34 digits / exponent18 contract",
    )
    return value


class CsvFormat(StrEnum):
    UTC_V1 = "UTC_V1"
    BINANCE_KLINES_12 = "BINANCE_KLINES_12"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    origin: str
    synthetic: bool
    timeframe: Timeframe
    start: datetime
    end: datetime
    format: CsvFormat
    epoch_unit: str | None = None
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        check(
            type(self.origin) is str
            and 0 < len(self.origin) <= 256
            and all(ord(c) >= 32 for c in self.origin),
            "declared bounded origin required",
        )
        check(type(self.synthetic) is bool, "synthetic declaration required")
        check(type(self.timeframe) is Timeframe, "native timeframe required")
        replace(self.timeframe)
        require_utc(self.start)
        require_utc(self.end)
        check(self.start < self.end, "dataset start must precede end")
        check(type(self.format) is CsvFormat, "known CSV format required")
        check(
            self.epoch_unit in ("ms", "us")
            if self.format is CsvFormat.BINANCE_KLINES_12
            else self.epoch_unit is None,
            "explicit epoch unit only for klines",
        )
        check(
            self.expected_sha256 is None
            or (
                type(self.expected_sha256) is str
                and re.fullmatch(r"[0-9a-f]{64}", self.expected_sha256) is not None
            ),
            "expected SHA256 must be lowercase hex",
        )


def _epoch(text: str, unit: str | None) -> datetime:
    check(re.fullmatch(r"[0-9]{1,18}", text) is not None, "integer epoch required")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=int(text) * (1000 if unit == "ms" else 1)
    )


def _parse(raw: bytes, spec: DatasetSpec) -> CandleSeries:
    check(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "empty or oversized CSV")
    replace(spec)
    digest = hashlib.sha256(raw).hexdigest()
    check(spec.expected_sha256 is None or digest == spec.expected_sha256, "dataset hash mismatch")
    try:
        rows = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if spec.format is CsvFormat.UTC_V1:
            check(tuple(next(rows, ())) == HEADER, "exact UTC_V1 header required")
        candles: list[Candle] = []
        for row in rows:
            check(len(candles) < MAX_CANDLES, "candle count quota exceeded")
            check(len(row) == (7 if spec.format is CsvFormat.UTC_V1 else 12), "truncated CSV row")
            if spec.format is CsvFormat.UTC_V1:
                opened, closed = utc(row[0]), utc(row[1])
                prices, volume = row[2:6], row[6]
            else:
                opened = _epoch(row[0], spec.epoch_unit)
                closed = _epoch(row[6], spec.epoch_unit) + timedelta(
                    microseconds=1000 if spec.epoch_unit == "ms" else 1
                )
                prices, volume = row[1:5], row[5]
                for column in (7, 9, 10, 11):
                    check(number(row[column]) >= 0, "invalid auxiliary kline volume/value")
                check(re.fullmatch(r"[0-9]{1,18}", row[8]) is not None, "invalid trade count")
            candle = Candle(
                BTCUSDT,
                spec.timeframe,
                opened,
                closed,
                Price(number(prices[0])),
                Price(number(prices[1])),
                Price(number(prices[2])),
                Price(number(prices[3])),
                Qty(number(volume)),
            )
            check(
                spec.start <= candle.open_time and candle.close_time <= spec.end,
                "candle outside declared interval",
            )
            candles.append(candle)
        check(bool(candles), "CSV has no candles")
        return CandleSeries(BTCUSDT, spec.timeframe, tuple(candles))
    except (ValueError, TypeError, OverflowError, UnicodeError, csv.Error) as exc:
        if isinstance(exc, BacktestError):
            raise
        raise BacktestError("invalid CSV, decimal, time or OHLC sequence") from exc


@dataclass(frozen=True, slots=True)
class Dataset:
    raw: bytes
    spec: DatasetSpec
    series: CandleSeries = field(init=False, repr=False)

    def __post_init__(self) -> None:
        check(type(self.spec) is DatasetSpec, "native dataset spec required")
        object.__setattr__(self, "series", _parse(self.raw, self.spec))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def manifest(self) -> dict[str, object]:
        coverage = self.series.coverage(self.spec.start, self.spec.end)
        return dict(
            symbol=BTCUSDT.name,
            origin=self.spec.origin,
            synthetic=self.spec.synthetic,
            format=self.spec.format.value,
            epoch_unit=self.spec.epoch_unit,
            start=self.spec.start.isoformat(),
            end=self.spec.end.isoformat(),
            timeframe_seconds=self.spec.timeframe.duration // timedelta(seconds=1),
            sha256=self.sha256,
            bytes=len(self.raw),
            candles=len(self.series),
            gaps=[
                dict(start=g.start.isoformat(), end=g.end.isoformat(), missing_bars=g.missing_bars)
                for g in coverage.gaps
            ],
            missing_prefix_us=coverage.missing_prefix // timedelta(microseconds=1),
            missing_suffix_us=coverage.missing_suffix // timedelta(microseconds=1),
            complete=coverage.is_complete,
        )


def read_csv(path: Path, spec: DatasetSpec) -> Dataset:
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    return Dataset(raw, spec)


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    start: datetime
    development_end: datetime
    validation_end: datetime
    end: datetime

    def __post_init__(self) -> None:
        for t in (self.start, self.development_end, self.validation_end, self.end):
            require_utc(t)
        check(
            self.start < self.development_end < self.validation_end < self.end,
            "strict chronological development/validation/test boundaries required",
        )

    def segment(self, dataset: Dataset, name: str) -> CandleSeries:
        replace(self)
        check(name in ("development", "validation", "test"), "known split required")
        bounds = {
            "development": (self.start, self.development_end),
            "validation": (self.development_end, self.validation_end),
            "test": (self.validation_end, self.end),
        }
        start, end = bounds[name]
        check(dataset.spec.start <= start and end <= dataset.spec.end, "split outside dataset")
        coverage = dataset.series.coverage(start, end)
        check(coverage.is_complete, "split must contain complete aligned candles")
        return dataset.series.between(start, end)
