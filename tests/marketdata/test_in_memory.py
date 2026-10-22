from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    Candle,
    CandleSequenceError,
    CandleSeries,
    DomainError,
    OutOfOrderCandleError,
    Price,
    Qty,
    Symbol,
    Timeframe,
)
from gridbot.marketdata import InMemoryMarketData, MarketDataPort

T0 = datetime(2026, 1, 1, tzinfo=UTC)
M1 = Timeframe.minutes(1)
H1 = Timeframe.hours(1)
ETHUSDT = Symbol(Asset("ETH"), USDT)


def bar(index: int, *, timeframe: Timeframe = M1, symbol: Symbol = BTCUSDT) -> Candle:
    open_time = T0 + index * timeframe.duration
    price = Price.parse(str(100 + index))
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe.duration,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Qty.parse("1"),
    )


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def source() -> InMemoryMarketData:
    return InMemoryMarketData.from_candles(
        [
            *(bar(i) for i in range(10)),  # BTC 1m: 00:00..00:10
            *(bar(i, symbol=ETHUSDT) for i in range(5)),  # ETH 1m
            *(bar(i, timeframe=H1) for i in range(3)),  # BTC 1h
        ]
    )


def opens(result: CandleSeries) -> list[datetime]:
    return [c.open_time for c in result]


def test_implements_market_data_port() -> None:
    port: MarketDataPort = source()  # checado pelo mypy
    assert isinstance(port.candles(BTCUSDT, M1, at(0), at(1)), CandleSeries)


def test_filters_by_market() -> None:
    btc = source().candles(BTCUSDT, M1, at(0), at(60))
    eth = source().candles(ETHUSDT, M1, at(0), at(60))
    assert len(btc) == 10
    assert len(eth) == 5
    assert all(c.symbol == ETHUSDT for c in eth)
    assert eth.symbol == ETHUSDT


def test_filters_by_timeframe() -> None:
    hourly = source().candles(BTCUSDT, H1, at(0), at(24 * 60))
    assert len(hourly) == 3
    assert all(c.timeframe == H1 for c in hourly)
    assert hourly.timeframe == H1


def test_start_is_inclusive() -> None:
    assert opens(source().candles(BTCUSDT, M1, at(3), at(5))) == [at(3), at(4)]


def test_end_is_exclusive() -> None:
    result = source().candles(BTCUSDT, M1, at(3), at(5))
    assert at(5) not in opens(result)


def test_candle_crossing_end_is_excluded() -> None:
    end = at(5) + timedelta(seconds=30)
    assert opens(source().candles(BTCUSDT, M1, at(3), end)) == [at(3), at(4)]


def test_candle_starting_before_start_is_excluded() -> None:
    start = at(3) + timedelta(seconds=30)
    assert opens(source().candles(BTCUSDT, M1, start, at(6))) == [at(4), at(5)]


@pytest.mark.parametrize(
    ("symbol", "timeframe", "start", "end"),
    [
        (Symbol(Asset("SOL"), USDT), M1, at(0), at(10)),  # mercado desconhecido
        (BTCUSDT, Timeframe.minutes(5), at(0), at(10)),  # timeframe sem dados
        (BTCUSDT, M1, at(100), at(200)),  # janela depois dos dados
        (BTCUSDT, M1, at(-10), at(0)),  # janela antes dos dados
    ],
)
def test_query_without_results_returns_empty_series(
    symbol: Symbol, timeframe: Timeframe, start: datetime, end: datetime
) -> None:
    result = source().candles(symbol, timeframe, start, end)
    assert len(result) == 0
    assert (result.symbol, result.timeframe) == (symbol, timeframe)


def test_results_are_chronological() -> None:
    result = opens(source().candles(BTCUSDT, M1, at(0), at(60)))
    assert result == sorted(result)
    assert result == [at(i) for i in range(10)]


def test_invalid_query_is_rejected() -> None:
    src = source()
    with pytest.raises(DomainError):
        src.candles(BTCUSDT, M1, at(5), at(5))
    with pytest.raises(DomainError):
        src.candles(BTCUSDT, M1, at(0).replace(tzinfo=None), at(5))
    with pytest.raises(DomainError):  # mesmo para mercado sem dados
        src.candles(ETHUSDT, H1, at(5), at(1))


# ------------------------------------------------------------------ imutabilidade


def test_history_cannot_be_altered_through_inputs_or_results() -> None:
    candles = [bar(i) for i in range(5)]
    src = InMemoryMarketData.from_candles(candles)
    candles.clear()  # mutar a lista de entrada não afeta a fonte
    candles.append(bar(99))
    first = src.candles(BTCUSDT, M1, at(0), at(60))
    assert isinstance(first.candles, tuple)
    assert len(first) == 5
    assert src.candles(BTCUSDT, M1, at(0), at(60)) == first


def test_input_is_validated_never_sorted() -> None:
    with pytest.raises(OutOfOrderCandleError):
        InMemoryMarketData.from_candles([bar(1), bar(0)])


def test_duplicate_series_for_same_key_is_rejected() -> None:
    a = CandleSeries(BTCUSDT, M1, (bar(0),))
    b = CandleSeries(BTCUSDT, M1, (bar(5),))
    with pytest.raises(CandleSequenceError):
        InMemoryMarketData([a, b])


def test_non_series_inputs_are_rejected() -> None:
    with pytest.raises(TypeError):
        InMemoryMarketData(cast(Any, [bar(0)]))
    with pytest.raises(TypeError):
        InMemoryMarketData.from_candles(cast(Any, ["not a candle"]))


def test_gaps_survive_queries() -> None:
    src = InMemoryMarketData.from_candles([bar(0), bar(1), bar(5)])
    result = src.candles(BTCUSDT, M1, at(0), at(10))
    assert len(result) == 3
    assert [g.missing_bars for g in result.gaps] == [3]


# ------------------------------------------------------------------ determinismo


def test_same_query_same_result_across_instances() -> None:
    queries = [(at(0), at(10)), (at(2), at(7)), (at(9), at(11))]
    first = [source().candles(BTCUSDT, M1, s, e) for s, e in queries]
    second = [source().candles(BTCUSDT, M1, s, e) for s, e in queries]
    assert first == second


@given(st.integers(min_value=-5, max_value=15), st.integers(min_value=1, max_value=20))
def test_window_matches_naive_containment_filter(start_min: int, length: int) -> None:
    all_bars = [bar(i) for i in range(10)]
    start, end = at(start_min), at(start_min + length)
    expected = [c for c in all_bars if start <= c.open_time and c.close_time <= end]
    result = InMemoryMarketData.from_candles(all_bars).candles(BTCUSDT, M1, start, end)
    assert list(result) == expected


@given(st.integers(min_value=0, max_value=600), st.integers(min_value=1, max_value=600))
def test_unaligned_windows_never_leak_partial_candles(start_s: int, length_s: int) -> None:
    start = T0 + timedelta(seconds=start_s)
    end = start + timedelta(seconds=length_s)
    result = source().candles(BTCUSDT, M1, start, end)
    for candle in result:
        assert start <= candle.open_time
        assert candle.close_time <= end
