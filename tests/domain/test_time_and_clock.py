from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from gridbot.domain import DomainError, ManualClock, require_utc
from gridbot.infra.clock import SystemClock

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_utc_datetime_is_accepted() -> None:
    assert require_utc(T0) is T0
    assert require_utc(datetime(2026, 1, 1, tzinfo=timezone(timedelta(0)))) is not None


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(DomainError, match="naive"):
        require_utc(T0.replace(tzinfo=None))


def test_non_utc_offset_is_rejected() -> None:
    brt = timezone(timedelta(hours=-3))
    with pytest.raises(DomainError, match="UTC"):
        require_utc(T0.astimezone(brt))


@pytest.mark.parametrize("value", [date(2026, 1, 1), "2026-01-01T00:00:00Z", 1767225600])
def test_non_datetime_is_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        require_utc(cast(Any, value))


def test_manual_clock_is_deterministic() -> None:
    def run() -> list[datetime]:
        clock = ManualClock(T0)
        out = [clock.now()]
        for seconds in (1, 59, 3600):
            out.append(clock.advance(timedelta(seconds=seconds)))
        out.append(clock.set(T0 + timedelta(days=1)))
        return out

    first, second = run(), run()
    assert first == second
    assert first[-2] == T0 + timedelta(seconds=3660)
    assert all(t.utcoffset() == timedelta(0) for t in first)


def test_manual_clock_does_not_move_on_its_own() -> None:
    clock = ManualClock(T0)
    assert clock.now() == clock.now() == T0


def test_manual_clock_never_goes_back() -> None:
    clock = ManualClock(T0)
    with pytest.raises(DomainError):
        clock.advance(timedelta(seconds=-1))
    with pytest.raises(DomainError):
        clock.set(T0 - timedelta(microseconds=1))


def test_manual_clock_requires_utc() -> None:
    with pytest.raises(DomainError):
        ManualClock(T0.replace(tzinfo=None))
    clock = ManualClock(T0)
    with pytest.raises(DomainError):
        clock.set((T0 + timedelta(hours=1)).astimezone(timezone(timedelta(hours=2))))


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.utcoffset() == timedelta(0)
    assert require_utc(now) is now
