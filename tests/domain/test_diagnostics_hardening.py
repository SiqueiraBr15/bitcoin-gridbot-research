from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from tests.domain.test_orders import make_snapshot

from gridbot.domain import DomainError, OrderStatus
from gridbot.domain.market import CandleGap, WindowCoverage

AT = datetime(2026, 1, 1, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


@pytest.mark.parametrize(
    "status", [OrderStatus.NEW, OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.EXPIRED]
)
@pytest.mark.parametrize("quote", ["0.00000001", "10", "1e30"])
def test_no_execution_snapshot_cannot_claim_quote_execution(
    status: OrderStatus, quote: str
) -> None:
    with pytest.raises(DomainError):
        make_snapshot(status, "0", cumulative_quote_qty=Decimal(quote))
    assert make_snapshot(status, "0").cumulative_quote_qty == 0


def test_positive_execution_zero_quote_remains_legacy_contract_pending_decision() -> None:
    assert make_snapshot(OrderStatus.PARTIALLY_FILLED, "0.0005").cumulative_quote_qty == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"start": AT.replace(tzinfo=None)},
        {"end": AT},
        {"missing_bars": 0},
        {"missing_bars": -1},
        {"missing_bars": True},
        {"missing_bars": "1"},
    ],
)
def test_gap_rejects_invalid_direct_construction(overrides: dict[str, object]) -> None:
    fields: dict[str, object] = {"start": AT, "end": AT + MINUTE, "missing_bars": 1}
    fields.update(overrides)
    with pytest.raises((DomainError, TypeError)):
        CandleGap(**cast(Any, fields))


@pytest.mark.parametrize(
    "overrides",
    [
        {"candle_count": True},
        {"candle_count": -1},
        {"candle_count": "1"},
        {"start": AT.replace(tzinfo=None)},
        {"end": AT},
        {"missing_prefix": -MINUTE},
        {"missing_suffix": -MINUTE},
        {"missing_prefix": 0},
        {"gaps": []},
        {"gaps": ("gap",)},
        {"candle_count": 0},
        {"missing_prefix": 4 * MINUTE},
        {"missing_suffix": 4 * MINUTE},
        {"missing_prefix": 2 * MINUTE, "missing_suffix": 2 * MINUTE},
    ],
)
def test_coverage_rejects_contradictory_or_mutable_direct_construction(
    overrides: dict[str, object],
) -> None:
    fields: dict[str, object] = {
        "start": AT,
        "end": AT + 4 * MINUTE,
        "candle_count": 4,
        "missing_prefix": timedelta(0),
        "missing_suffix": timedelta(0),
        "gaps": (),
    }
    fields.update(overrides)
    with pytest.raises((DomainError, TypeError)):
        WindowCoverage(**cast(Any, fields))


def test_empty_coverage_is_entirely_missing() -> None:
    empty = WindowCoverage(AT, AT + MINUTE, 0, MINUTE, timedelta(0), ())
    assert not empty.is_complete
    with pytest.raises(DomainError):
        replace(empty, candle_count=1)


@pytest.mark.parametrize(
    "gap",
    [
        CandleGap(AT, AT + MINUTE, 1),
        CandleGap(AT + 3 * MINUTE, AT + 4 * MINUTE, 1),
    ],
)
def test_gaps_must_be_strictly_internal(gap: CandleGap) -> None:
    with pytest.raises(DomainError):
        WindowCoverage(AT, AT + 4 * MINUTE, 4, timedelta(0), timedelta(0), (gap,))


def test_valid_nested_diagnostic_is_immutable_and_adulteration_is_rejected() -> None:
    gap = CandleGap(AT + MINUTE, AT + 2 * MINUTE, 1)
    valid = WindowCoverage(AT, AT + 4 * MINUTE, 3, timedelta(0), timedelta(0), (gap,))
    assert not valid.is_complete
    object.__setattr__(gap, "missing_bars", -1)
    with pytest.raises(DomainError):
        replace(valid)


def test_gap_count_order_overlap_and_empty_suffix_are_rejected() -> None:
    a = CandleGap(AT + MINUTE, AT + 2 * MINUTE, 1)
    b = CandleGap(AT + 2 * MINUTE, AT + 3 * MINUTE, 1)
    for gaps, count in (((a,), 1), ((b, a), 4), ((a, b), 4)):
        with pytest.raises(DomainError):
            WindowCoverage(AT, AT + 4 * MINUTE, count, timedelta(0), timedelta(0), gaps)
    with pytest.raises(DomainError):
        WindowCoverage(AT, AT + 4 * MINUTE, 0, 4 * MINUTE, MINUTE, ())
