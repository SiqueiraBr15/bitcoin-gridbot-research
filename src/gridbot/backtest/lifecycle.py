"""Causal read-only lifecycle experiments; no financial transition authority (ADR-039)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from gridbot.backtest.data import check
from gridbot.domain import BTCUSDT, Candle, MarketRules, Price
from gridbot.domain.decimals import financial
from gridbot.strategy import ArithmeticGridPlan, ArithmeticGridSpec, build_arithmetic_grid


@dataclass(frozen=True, slots=True)
class RangeCandidate:
    candle: Candle
    grid: ArithmeticGridPlan
    consecutive: int

    def __post_init__(self) -> None:
        check(
            type(self.candle) is Candle and type(self.grid) is ArithmeticGridPlan, "native inputs"
        )
        replace(self.candle)
        replace(self.grid)
        check(self.candle.symbol == self.grid.spec.symbol == BTCUSDT, "BTC/USDT only")
        check(type(self.consecutive) is int and self.consecutive > 0, "positive streak required")
        check(
            not self.grid.spec.lower_price <= self.candle.close <= self.grid.spec.upper_price,
            "candidate close must be outside original range",
        )


@dataclass(frozen=True, slots=True)
class RangeObserver:
    grid: ArithmeticGridPlan
    threshold: int
    consecutive: int = 0
    last: Candle | None = None

    def __post_init__(self) -> None:
        check(type(self.grid) is ArithmeticGridPlan, "native grid required")
        replace(self.grid)
        check(self.grid.spec.symbol == BTCUSDT, "BTC/USDT only")
        check(type(self.threshold) is int and 1 <= self.threshold <= 100_000, "bounded threshold")
        check(type(self.consecutive) is int and self.consecutive >= 0, "invalid streak")
        check(self.last is None or type(self.last) is Candle, "native closed bar required")
        if self.last is not None:
            replace(self.last)
            check(self.last.symbol == BTCUSDT, "BTC/USDT only")
        else:
            check(self.consecutive == 0, "streak requires history")

    def observe(self, candle: Candle) -> tuple[RangeObserver, RangeCandidate | None]:
        replace(self)
        check(type(candle) is Candle, "complete native candle required")
        replace(candle)
        check(candle.symbol == BTCUSDT, "BTC/USDT only")
        streak = self.consecutive
        if self.last is not None:
            if candle == self.last:
                return self, None
            check(candle.timeframe == self.last.timeframe, "timeframe changed")
            check(candle.open_time >= self.last.close_time, "duplicate/conflicting or past candle")
            if candle.open_time != self.last.close_time:
                streak = 0  # Missing bars cannot prove consecutive closed observations.
        outside = not self.grid.spec.lower_price <= candle.close <= self.grid.spec.upper_price
        streak = streak + 1 if outside else 0
        updated = replace(self, consecutive=streak, last=candle)
        event = RangeCandidate(candle, self.grid, streak) if streak == self.threshold else None
        return updated, event


@dataclass(frozen=True, slots=True)
class RecenterPlan:
    """Informative geometry only. Never accepted as a PAPER command or balance source."""

    candidate: RangeCandidate
    proposed: ArithmeticGridPlan | None
    blockers: tuple[str, ...]

    @property
    def executable(self) -> bool:
        return False


def plan_recenter(candidate: RangeCandidate, rules: MarketRules) -> RecenterPlan:
    check(
        type(candidate) is RangeCandidate and type(rules) is MarketRules, "native planning inputs"
    )
    replace(candidate)
    replace(rules)
    old = candidate.grid
    check(old == build_arithmetic_grid(old.spec, rules), "original grid/rules mismatch")
    with financial():
        spacing = old.levels[1].price.value - old.levels[0].price.value
        # For an odd count the lower half has floor(N/2) intervals, fixed in advance.
        center = rules.price.floor(candidate.candle.close).value
        lower = center - spacing * Decimal(old.spec.interval_count // 2)
        upper = lower + spacing * Decimal(old.spec.interval_count)
    blockers = ("NO_ATOMIC_GEOMETRY_AND_SOURCE_MIGRATION_COMMAND",)
    if lower <= 0 or rules.price.violations(Price(lower)) or rules.price.violations(Price(upper)):
        return RecenterPlan(candidate, None, (*blockers, "PROPOSED_GEOMETRY_INVALID"))
    proposed = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price(lower), Price(upper), old.spec.interval_count), rules
    )
    return RecenterPlan(candidate, proposed, blockers)
