from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    Candle,
    CandleGap,
    CandleSequenceError,
    CandleSeries,
    DomainError,
    DuplicateCandleError,
    OutOfOrderCandleError,
    OverlappingCandleError,
    Price,
    Qty,
    Symbol,
    Timeframe,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
M1 = Timeframe.minutes(1)
ETHUSDT = Symbol(Asset("ETH"), USDT)


def bar(
    index: int,
    *,
    close: str = "100",
    timeframe: Timeframe = M1,
    symbol: Symbol = BTCUSDT,
    offset: timedelta = timedelta(0),
) -> Candle:
    open_time = T0 + index * timeframe.duration + offset
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe.duration,
        open=Price.parse("100"),
        high=Price.parse("110"),
        low=Price.parse("90"),
        close=Price.parse(close),
        volume=Qty.parse("1"),
    )


def series(*candles: Candle) -> CandleSeries:
    return CandleSeries(BTCUSDT, M1, candles)


# ------------------------------------------------------------------ válidas


def test_contiguous_series() -> None:
    s = series(bar(0), bar(1), bar(2))
    assert len(s) == 3
    assert [c.open_time for c in s] == [T0, T0 + M1.duration, T0 + 2 * M1.duration]
    assert s.start == T0
    assert s.end == T0 + 3 * M1.duration
    assert s.gaps == ()
    assert not s.has_gaps


def test_empty_series_is_valid() -> None:
    empty = CandleSeries(BTCUSDT, M1)
    assert len(empty) == 0
    assert empty.start is None
    assert empty.end is None
    assert empty.gaps == ()


def test_series_is_immutable() -> None:
    s = series(bar(0))
    assert isinstance(s.candles, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.candles = ()  # type: ignore[misc]


def test_list_is_rejected_to_keep_history_immutable() -> None:
    with pytest.raises(TypeError, match="tuple"):
        CandleSeries(BTCUSDT, M1, cast(Any, [bar(0)]))


# ------------------------------------------------------------------ inválidas


def test_duplicate_timestamp_is_rejected() -> None:
    with pytest.raises(DuplicateCandleError):
        series(bar(0), bar(1), bar(1))
    with pytest.raises(DuplicateCandleError):  # mesmo open_time, valores diferentes
        series(bar(0), bar(0, close="105"))


def test_out_of_order_is_rejected_not_sorted() -> None:
    with pytest.raises(OutOfOrderCandleError):
        series(bar(0), bar(2), bar(1))


def test_overlap_is_rejected() -> None:
    with pytest.raises(OverlappingCandleError):
        series(bar(0), bar(0, offset=timedelta(seconds=30)))


def test_misaligned_gap_is_rejected() -> None:
    with pytest.raises(CandleSequenceError) as excinfo:
        series(bar(0), bar(1, offset=timedelta(seconds=30)))
    assert type(excinfo.value) is CandleSequenceError
    assert "desalinhado" in str(excinfo.value)


def test_mixed_market_or_timeframe_is_rejected() -> None:
    with pytest.raises(CandleSequenceError):
        series(bar(0), bar(1, symbol=ETHUSDT))
    with pytest.raises(CandleSequenceError):
        series(bar(0, timeframe=Timeframe.hours(1)))


def test_sequence_errors_are_domain_errors() -> None:
    for error in (DuplicateCandleError, OutOfOrderCandleError, OverlappingCandleError):
        assert issubclass(error, CandleSequenceError)
        assert issubclass(error, DomainError)


# ------------------------------------------------------------------ gaps


def test_gap_is_reported_with_missing_bar_count() -> None:
    s = series(bar(0), bar(1), bar(4), bar(5), bar(7))
    assert s.has_gaps
    assert s.gaps == (
        CandleGap(start=T0 + 2 * M1.duration, end=T0 + 4 * M1.duration, missing_bars=2),
        CandleGap(start=T0 + 6 * M1.duration, end=T0 + 7 * M1.duration, missing_bars=1),
    )


def test_gap_is_never_filled() -> None:
    original = (bar(0), bar(1), bar(4))
    s = series(*original)
    assert s.candles == original  # nada inventado, nada interpolado
    assert len(s) == 3
    window = s.between(T0, T0 + 5 * M1.duration)
    assert [c.open_time for c in window] == [T0, T0 + M1.duration, T0 + 4 * M1.duration]
    assert window.gaps == s.gaps


# ------------------------------------------------------------------ between


def test_between_requires_utc_and_ordered_bounds() -> None:
    s = series(bar(0))
    with pytest.raises(DomainError):
        s.between(T0.replace(tzinfo=None), T0 + M1.duration)
    with pytest.raises(DomainError):
        s.between(T0, T0)
    with pytest.raises(DomainError):
        s.between(T0 + M1.duration, T0)


def test_between_excludes_candle_crossing_end() -> None:
    s = series(bar(0), bar(1))
    window = s.between(T0, T0 + M1.duration + timedelta(seconds=30))
    assert [c.open_time for c in window] == [T0]


# ------------------------------------------------------------------ property-based

indices = st.lists(st.integers(min_value=0, max_value=500), min_size=1, max_size=60, unique=True)


@given(indices)
def test_sorted_unique_bars_form_valid_series_with_exact_gap_accounting(raw: list[int]) -> None:
    ordered = sorted(raw)
    s = series(*(bar(i) for i in ordered))
    missing = sum(g.missing_bars for g in s.gaps)
    assert len(s) + missing == ordered[-1] - ordered[0] + 1
    assert len(s.gaps) == sum(1 for a, b in pairwise(ordered) if b - a > 1)
    for gap in s.gaps:
        assert gap.end - gap.start == gap.missing_bars * M1.duration


@given(indices.filter(lambda xs: xs != sorted(xs)))
def test_unsorted_bars_are_always_rejected(raw: list[int]) -> None:
    with pytest.raises((OutOfOrderCandleError, DuplicateCandleError)):
        series(*(bar(i) for i in raw))
