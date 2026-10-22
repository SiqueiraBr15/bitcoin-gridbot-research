from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    Candle,
    DomainError,
    FloatNotAllowedError,
    InvalidCandleError,
    Price,
    Qty,
    Timeframe,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
M1 = Timeframe.minutes(1)


def make_candle(**overrides: object) -> Candle:
    fields: dict[str, object] = {
        "symbol": BTCUSDT,
        "timeframe": M1,
        "open_time": T0,
        "close_time": T0 + M1.duration,
        "open": Price.parse("82"),
        "high": Price.parse("85"),
        "low": Price.parse("79"),
        "close": Price.parse("84"),
        "volume": Qty.parse("12.5"),
    }
    fields.update(overrides)
    return Candle(**cast(Any, fields))


def p(raw: str) -> Price:
    return Price.parse(raw)


# ------------------------------------------------------------------ válido


def test_valid_candle_keeps_exact_values() -> None:
    candle = make_candle(open=p("65000.123456789012345"), high=p("65000.123456789012346"))
    assert candle.open.value == Decimal("65000.123456789012345")  # sem arredondamento
    assert candle.close_time - candle.open_time == M1.duration


def test_flat_candle_and_zero_volume_are_valid() -> None:
    candle = make_candle(open=p("80"), high=p("80"), low=p("80"), close=p("80"), volume=Qty.zero())
    assert candle.volume.is_zero


def test_candle_is_immutable() -> None:
    candle = make_candle()
    with pytest.raises(dataclasses.FrozenInstanceError):
        candle.high = p("999")  # type: ignore[misc]


# ------------------------------------------------------------------ valores inválidos


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("raw", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_non_positive_or_non_finite_price_cannot_exist(field: str, raw: str) -> None:
    # Price já é > 0 e finito: um candle com esse campo inválido nem chega a ser construído.
    with pytest.raises(DomainError):
        make_candle(**{field: Price.parse(raw)})


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_float_is_rejected_in_every_numeric_field(field: str) -> None:
    with pytest.raises(FloatNotAllowedError):
        make_candle(**{field: 84.0})


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("raw", [Decimal("84"), "84", None])
def test_raw_values_instead_of_value_objects_are_rejected(field: str, raw: object) -> None:
    with pytest.raises(TypeError):
        make_candle(**{field: raw})


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-0.0001"])
def test_invalid_volume_cannot_exist(raw: str) -> None:
    with pytest.raises(DomainError):
        make_candle(volume=Qty.parse(raw))


# ------------------------------------------------------------------ OHLC


@pytest.mark.parametrize(
    ("o", "h", "low", "c", "reason"),
    [
        ("82", "81", "79", "80", "high abaixo de open"),
        ("80", "83", "79", "84", "high abaixo de close"),
        ("82", "85", "83", "84", "low acima de open"),
        ("84", "85", "83", "82", "low acima de close"),
        ("82", "78", "79", "80", "high abaixo de low"),
    ],
)
def test_inconsistent_ohlc_is_rejected(o: str, h: str, low: str, c: str, reason: str) -> None:
    with pytest.raises(InvalidCandleError):
        make_candle(open=p(o), high=p(h), low=p(low), close=p(c))


# ------------------------------------------------------------------ tempo


def test_open_time_must_precede_close_time() -> None:
    with pytest.raises(InvalidCandleError):
        make_candle(close_time=T0)
    with pytest.raises(InvalidCandleError):
        make_candle(close_time=T0 - M1.duration)


def test_duration_must_match_timeframe() -> None:
    with pytest.raises(InvalidCandleError):
        make_candle(close_time=T0 + timedelta(minutes=2))
    with pytest.raises(InvalidCandleError):
        make_candle(timeframe=Timeframe.hours(1))


@pytest.mark.parametrize("field", ["open_time", "close_time"])
def test_naive_timestamps_are_rejected(field: str) -> None:
    naive = (T0 if field == "open_time" else T0 + M1.duration).replace(tzinfo=None)
    with pytest.raises(InvalidCandleError, match="naive"):
        make_candle(**{field: naive})


def test_non_utc_timestamps_are_rejected() -> None:
    brt = timezone(timedelta(hours=-3))
    with pytest.raises(InvalidCandleError, match="UTC"):
        make_candle(open_time=T0.astimezone(brt), close_time=(T0 + M1.duration).astimezone(brt))


def test_non_datetime_timestamp_is_rejected() -> None:
    with pytest.raises(TypeError):
        make_candle(open_time="2026-01-01T00:00:00Z")


def test_symbol_and_timeframe_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        make_candle(symbol="BTCUSDT")
    with pytest.raises(TypeError):
        make_candle(timeframe="1m")


# ------------------------------------------------------------------ property-based

steps = st.decimals(
    min_value=0, max_value=Decimal("1000"), places=8, allow_nan=False, allow_infinity=False
)
lows = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("1000000"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)
positive_steps = steps.filter(lambda d: d > 0)


@given(lows, steps, steps, steps)
def test_any_consistent_ohlc_is_accepted_without_rounding(
    low: Decimal, d_open: Decimal, d_close: Decimal, d_high: Decimal
) -> None:
    o, c = low + d_open, low + d_close
    h = max(o, c) + d_high
    candle = make_candle(open=Price(o), high=Price(h), low=Price(low), close=Price(c))
    assert (candle.open.value, candle.high.value, candle.low.value, candle.close.value) == (
        o,
        h,
        low,
        c,
    )
    assert candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close)
    assert max(candle.open, candle.close) <= candle.high


@given(lows, steps, steps, positive_steps)
def test_high_below_open_or_close_is_always_rejected(
    low: Decimal, d_open: Decimal, d_close: Decimal, deficit: Decimal
) -> None:
    o, c = low + d_open, low + d_close
    h = max(o, c) - deficit
    if h <= 0:
        return  # Price não existe; coberto pelos testes de valor
    with pytest.raises(InvalidCandleError):
        make_candle(open=Price(o), high=Price(h), low=Price(min(low, h)), close=Price(c))


@given(lows, steps, steps, positive_steps)
def test_low_above_open_or_close_is_always_rejected(
    base: Decimal, d_open: Decimal, d_close: Decimal, excess: Decimal
) -> None:
    o, c = base + d_open, base + d_close
    low = min(o, c) + excess
    with pytest.raises(InvalidCandleError):
        make_candle(open=Price(o), high=Price(max(o, c, low)), low=Price(low), close=Price(c))
