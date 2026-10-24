"""Exact high-water marks, censored drawdown episodes and risk-only classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from itertools import pairwise
from typing import Any

WITHIN = "WITHIN_20_PERCENT_OBSERVED"
EXCEEDED = "EXCEEDED_20_PERCENT_OBSERVED"
INSUFFICIENT = "INSUFFICIENT_RISK_EVIDENCE"
LIMIT = Fraction(1, 5)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def display(value: Fraction) -> str:
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def quantile(values: list[Fraction], p: Fraction) -> Fraction:
    require(bool(values) and 0 <= p <= 1, "invalid quantile")
    ordered = sorted(values)
    pos = p * (len(values) - 1)
    lo = pos.numerator // pos.denominator
    return ordered[lo] + (ordered[min(lo + 1, len(values) - 1)] - ordered[lo]) * (pos - lo)


def seconds(a: datetime, b: datetime) -> int:
    delta = b - a
    require(delta.microseconds == 0 and delta >= timedelta(0), "invalid duration")
    return delta.days * 86400 + delta.seconds


@dataclass(frozen=True, slots=True)
class Mark:
    time: datetime
    price: Decimal
    cash: Decimal
    btc: Decimal
    nav: Decimal

    def raw(self) -> list[str]:
        return [
            self.time.isoformat(),
            *(str(x) for x in (self.price, self.cash, self.btc, self.nav)),
        ]


@dataclass(frozen=True, slots=True)
class Episode:
    peak: int
    first_below: int
    trough: int
    recovery: int | None
    magnitude: Fraction


def classify(magnitude: Fraction | None) -> str:
    if magnitude is None:
        return INSUFFICIENT
    require(0 <= magnitude < 1, "invalid positive NAV drawdown")
    return WITHIN if magnitude <= LIMIT else EXCEEDED


def profile(points: list[Mark]) -> dict[str, Any]:
    if len(points) < 2:
        return {"risk_class": INSUFFICIENT, "marks": len(points)}
    require(
        all(p.time.utcoffset() == timedelta(0) and p.nav.is_finite() and p.nav > 0 for p in points),
        "invalid risk observation",
    )
    require(all(a.time < b.time for a, b in pairwise(points)), "mark order")
    values = [Fraction(p.nav) for p in points]
    high, high_index = values[0], 0
    peak_index: int | None = None
    first_below = trough = 0
    episodes: list[Episode] = []
    below = 0
    sampled_underwater = 0
    for i, value in enumerate(values):
        if value >= high:
            if peak_index is not None:
                episodes.append(
                    Episode(peak_index, first_below, trough, i, 1 - values[trough] / high)
                )
            high, high_index, peak_index = value, i, None
        else:
            below += 1
            if i < len(points) - 1:
                sampled_underwater += seconds(points[i].time, points[i + 1].time)
            if peak_index is None:
                peak_index, first_below, trough = high_index, i, i
            elif value < values[trough]:
                trough = i
    if peak_index is not None:
        episodes.append(Episode(peak_index, first_below, trough, None, 1 - values[trough] / high))
    worst = max(episodes, key=lambda e: e.magnitude) if episodes else None
    magnitude = worst.magnitude if worst else Fraction(0)
    longest = (
        max(
            episodes,
            key=lambda e: seconds(points[e.peak].time, points[e.recovery or len(points) - 1].time),
        )
        if episodes
        else None
    )
    end = points[-1].time
    recovery = points[worst.recovery].time if worst and worst.recovery is not None else None
    trough_at = points[worst.trough].time if worst else None
    peak_at = points[worst.peak].time if worst else None
    longest_end = points[longest.recovery].time if longest and longest.recovery is not None else end
    longest_peak = points[longest.peak].time if longest else None
    return {
        "risk_class": classify(magnitude),
        "violates_20_percent": magnitude > LIMIT,
        "max_drawdown_fraction": str(magnitude),
        "max_drawdown_magnitude": display(magnitude),
        "worst_signed_drawdown": display(-magnitude),
        "max_drawdown_peak": peak_at.isoformat() if peak_at else None,
        "max_drawdown_trough": trough_at.isoformat() if trough_at else None,
        "peak_nav_usdt": str(points[worst.peak].nav) if worst else None,
        "trough_nav_usdt": str(points[worst.trough].nav) if worst else None,
        "recovery_at": recovery.isoformat() if recovery else None,
        "recovery_censored": bool(worst and recovery is None),
        "recovery_from_trough_seconds": seconds(trough_at, recovery)
        if trough_at and recovery
        else None,
        "peak_to_recovery_seconds": seconds(peak_at, recovery) if peak_at and recovery else None,
        "unrecovered_observed_since_trough_seconds": (
            seconds(trough_at, end) if trough_at and recovery is None else None
        ),
        "longest_episode_seconds": seconds(longest_peak, longest_end) if longest_peak else 0,
        "longest_episode_peak": longest_peak.isoformat() if longest_peak else None,
        "longest_episode_first_below": points[longest.first_below].time.isoformat()
        if longest
        else None,
        "longest_episode_observed_end": longest_end.isoformat() if longest else None,
        "longest_episode_censored": bool(longest and longest.recovery is None),
        "episode_count": len(episodes),
        "underwater_observations": below,
        "sampled_underwater_seconds_left": sampled_underwater,
        "sampled_underwater_fraction_left": display(
            Fraction(sampled_underwater, seconds(points[0].time, end))
        ),
        "marks": len(points),
        "max_mark_interval_seconds": max(seconds(a.time, b.time) for a, b in pairwise(points)),
    }
