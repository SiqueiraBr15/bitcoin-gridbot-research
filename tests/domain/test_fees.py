from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any, cast

import pytest

from gridbot.domain import (
    DomainError,
    FeeSchedule,
    FloatNotAllowedError,
    InvalidMarketRulesError,
    LiquidityRole,
    OrderType,
    parse_enum,
)


def test_valid_schedule_and_lookup() -> None:
    fees = FeeSchedule.parse(maker_rate="0.001", taker_rate="0.001")
    assert fees.rate_for(LiquidityRole.MAKER) == Decimal("0.001")
    assert fees.rate_for(LiquidityRole.TAKER) == Decimal("0.001")


def test_maker_and_taker_are_distinct() -> None:
    fees = FeeSchedule.parse(maker_rate="0.00075", taker_rate="0.001")
    assert fees.rate_for(LiquidityRole.MAKER) == Decimal("0.00075")
    assert fees.rate_for(LiquidityRole.TAKER) == Decimal("0.001")


@pytest.mark.parametrize("rate", ["0", "0.000001", "0.999999"])
def test_rate_bounds_accepted(rate: str) -> None:
    assert FeeSchedule.parse(rate, rate).maker_rate == Decimal(rate)


@pytest.mark.parametrize(
    ("maker", "taker"), [("-0.0001", "0.001"), ("0.001", "-0.0001"), ("1", "0.001"), ("0.1", "1.5")]
)
def test_invalid_rates_fail_at_construction(maker: str, taker: str) -> None:
    with pytest.raises(InvalidMarketRulesError):
        FeeSchedule.parse(maker, taker)


def test_float_and_non_finite_rates_are_rejected() -> None:
    with pytest.raises(FloatNotAllowedError):
        FeeSchedule.parse(cast(Any, 0.001), "0.001")
    with pytest.raises(FloatNotAllowedError):
        FeeSchedule(cast(Any, 0.001), Decimal("0.001"))
    with pytest.raises(DomainError):
        FeeSchedule.parse("NaN", "0.001")


def test_lookup_requires_liquidity_role() -> None:
    fees = FeeSchedule.parse("0.001", "0.001")
    with pytest.raises(TypeError):
        fees.rate_for(cast(Any, "MAKER"))
    with pytest.raises(TypeError):
        fees.rate_for(cast(Any, OrderType.LIMIT))  # tipo de ordem não é papel de liquidez


def test_schedule_is_immutable() -> None:
    fees = FeeSchedule.parse("0.001", "0.001")
    with pytest.raises(dataclasses.FrozenInstanceError):
        fees.maker_rate = Decimal(0)  # type: ignore[misc]


def test_liquidity_role_values() -> None:
    assert {r.value for r in LiquidityRole} == {"MAKER", "TAKER"}
    assert parse_enum(LiquidityRole, "TAKER") is LiquidityRole.TAKER
    with pytest.raises(DomainError):
        parse_enum(LiquidityRole, "maker")


def test_schedule_exposes_rates_only_not_amounts_or_assets() -> None:
    # Valor e ativo da fee pertencem ao fill futuro (ADR-009).
    assert {f.name for f in dataclasses.fields(FeeSchedule)} == {"maker_rate", "taker_rate"}
