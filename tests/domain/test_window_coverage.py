from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gridbot.domain import (
    BTCUSDT,
    Candle,
    CandleSeries,
    DomainError,
    Price,
    Qty,
    Timeframe,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
M1 = Timeframe.minutes(1)
ZERO = timedelta(0)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def series(*indices: int) -> CandleSeries:
    p = Price.parse("100")
    return CandleSeries(
        BTCUSDT,
        M1,
        tuple(Candle(BTCUSDT, M1, at(i), at(i + 1), p, p, p, p, Qty.parse("1")) for i in indices),
    )


def test_full_coverage() -> None:
    cov = series(0, 1, 2, 3).coverage(at(0), at(4))
    assert cov.is_complete
    assert cov.candle_count == 4
    assert (cov.missing_prefix, cov.missing_suffix, cov.gaps) == (ZERO, ZERO, ())


def test_missing_prefix() -> None:
    cov = series(2, 3).coverage(at(0), at(4))
    assert cov.has_missing_prefix
    assert cov.missing_prefix == timedelta(minutes=2)
    assert not cov.has_missing_suffix
    assert not cov.is_complete


def test_missing_suffix() -> None:
    cov = series(0, 1).coverage(at(0), at(4))
    assert cov.has_missing_suffix
    assert cov.missing_suffix == timedelta(minutes=2)
    assert not cov.has_missing_prefix
    assert not cov.is_complete


def test_internal_gaps_are_reported_unchanged() -> None:
    s = series(0, 1, 3)
    cov = s.coverage(at(0), at(4))
    assert cov.has_gaps
    assert cov.gaps == s.gaps
    assert not cov.has_missing_prefix
    assert not cov.has_missing_suffix
    assert not cov.is_complete


def test_prefix_suffix_and_gap_together() -> None:
    cov = series(2, 4).coverage(at(0), at(8))
    assert (cov.missing_prefix, cov.missing_suffix) == (timedelta(minutes=2), timedelta(minutes=3))
    assert [g.missing_bars for g in cov.gaps] == [1]


def test_empty_window_is_entirely_missing() -> None:
    cov = series(0, 1).coverage(at(10), at(15))
    assert cov.candle_count == 0
    assert cov.missing_prefix == timedelta(minutes=5)
    assert cov.missing_suffix == ZERO
    assert not cov.is_complete


def test_coverage_only_counts_candles_inside_the_window() -> None:
    cov = series(0, 1, 2, 3, 4, 5).coverage(at(2), at(4))
    assert cov.is_complete
    assert cov.candle_count == 2


def test_unaligned_window_cannot_be_complete() -> None:
    cov = series(0, 1, 2).coverage(at(0) + timedelta(seconds=30), at(3))
    assert cov.missing_prefix == timedelta(seconds=30)  # barra parcial não conta
    assert not cov.is_complete


def test_coverage_never_invents_candles() -> None:
    s = series(0, 3)
    s.coverage(at(0), at(4))
    assert len(s) == 2


def test_coverage_validates_window() -> None:
    with pytest.raises(DomainError):
        series(0).coverage(at(1), at(1))
