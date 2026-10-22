from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest

from gridbot.domain import InvalidTimeframeError, Timeframe


@pytest.mark.parametrize(
    ("timeframe", "duration", "label"),
    [
        (Timeframe.seconds(30), timedelta(seconds=30), "30s"),
        (Timeframe.minutes(1), timedelta(minutes=1), "1m"),
        (Timeframe.minutes(15), timedelta(minutes=15), "15m"),
        (Timeframe.hours(4), timedelta(hours=4), "4h"),
        (Timeframe.days(1), timedelta(days=1), "1d"),
        (Timeframe.days(7), timedelta(days=7), "7d"),
        (Timeframe.seconds(90), timedelta(seconds=90), "90s"),
    ],
)
def test_constructors_and_labels(timeframe: Timeframe, duration: timedelta, label: str) -> None:
    assert timeframe.duration == duration
    assert str(timeframe) == label


def test_equality_is_by_duration_and_hashable() -> None:
    assert Timeframe.minutes(60) == Timeframe.hours(1)
    assert str(Timeframe.minutes(60)) == "1h"
    assert len({Timeframe.minutes(60), Timeframe.hours(1), Timeframe(timedelta(hours=1))}) == 1


def test_ordering() -> None:
    assert Timeframe.minutes(1) < Timeframe.minutes(5) < Timeframe.hours(1) < Timeframe.days(1)


@pytest.mark.parametrize(
    "duration",
    [timedelta(0), timedelta(minutes=-1), timedelta(milliseconds=500), timedelta(seconds=1.5)],
)
def test_invalid_duration_is_rejected(duration: timedelta) -> None:
    with pytest.raises(InvalidTimeframeError):
        Timeframe(duration)


@pytest.mark.parametrize("count", [0, -1, True, 1.0, "1"])
def test_invalid_count_is_rejected(count: object) -> None:
    with pytest.raises(InvalidTimeframeError):
        Timeframe.minutes(cast(Any, count))


def test_non_timedelta_is_rejected() -> None:
    with pytest.raises(InvalidTimeframeError):
        Timeframe(cast(Any, 60))
    with pytest.raises(InvalidTimeframeError):
        Timeframe(cast(Any, "1m"))  # strings de API não pertencem ao domínio
