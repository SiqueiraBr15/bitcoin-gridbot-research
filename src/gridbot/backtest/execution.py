"""Explicit supplied OHLC hypotheses; never evidence of an exchange execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from gridbot.backtest.data import bounded_decimal, check
from gridbot.domain import (
    BTC,
    USDT,
    Asset,
    Candle,
    FeeSchedule,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    Qty,
    Side,
)
from gridbot.domain.decimals import financial, require_finite
from gridbot.domain.time import require_utc
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy import CellCycleRef

BNB = Asset("BNB")


@dataclass(frozen=True, slots=True)
class FeeModel:
    schedule: FeeSchedule
    buy_role: LiquidityRole
    sell_role: LiquidityRole
    buy_asset: Asset
    sell_asset: Asset
    bnb_fee_price: Price | None

    def __post_init__(self) -> None:
        check(type(self.schedule) is FeeSchedule, "native fee schedule required")
        replace(self.schedule)
        bounded_decimal(self.schedule.maker_rate)
        bounded_decimal(self.schedule.taker_rate)
        for role in (self.buy_role, self.sell_role):
            check(type(role) is LiquidityRole, "explicit maker/taker role required")
        for asset in (self.buy_asset, self.sell_asset):
            check(type(asset) is Asset and asset in (BTC, USDT, BNB), "known fee asset required")
        check(
            self.bnb_fee_price is None or type(self.bnb_fee_price) is Price,
            "explicit BNB commission conversion price required",
        )
        if BNB in (self.buy_asset, self.sell_asset):
            check(self.bnb_fee_price is not None, "BNB fees require declared conversion price")
        if self.bnb_fee_price is not None:
            replace(self.bnb_fee_price)
            bounded_decimal(self.bnb_fee_price.value)

    def commission(self, side: Side, price: Price, qty: Qty) -> Money:
        check(type(side) is Side, "known execution side required")
        role = self.buy_role if side is Side.BUY else self.sell_role
        asset = self.buy_asset if side is Side.BUY else self.sell_asset
        with financial():
            rate = self.schedule.rate_for(role)
            if asset == BTC:
                return Money(qty.value * rate, BTC)
            quote_fee = price.notional(qty) * rate
            if asset == USDT:
                return Money(quote_fee, USDT)
            check(self.bnb_fee_price is not None, "BNB fee price absent")
            if self.bnb_fee_price is None:
                raise TypeError("BNB price required")
            return Money(quote_fee / self.bnb_fee_price.value, BNB)


class MixedPolicy(StrEnum):
    DEFER_MIXED = "DEFER_MIXED"
    BUY_PRIORITY = "BUY_PRIORITY"
    SELL_PRIORITY = "SELL_PRIORITY"


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    fees: FeeModel
    spread: Decimal
    slippage: Decimal
    participation: Decimal
    latency: timedelta
    ttl_bars: int
    allow_touch: bool
    mixed: MixedPolicy

    def __post_init__(self) -> None:
        check(type(self.fees) is FeeModel, "native fee model required")
        replace(self.fees)
        for name in ("spread", "slippage", "participation"):
            require_finite(getattr(self, name), field=name)
            bounded_decimal(getattr(self, name))
        with financial():
            check(
                self.spread >= 0
                and self.slippage >= 0
                and self.spread / Decimal(2) + self.slippage < 1,
                "invalid execution buffers",
            )
        check(0 <= self.participation <= 1, "participation must be in [0,1]")
        check(
            type(self.latency) is timedelta and timedelta(0) <= self.latency <= timedelta(days=30),
            "bounded nonnegative latency required",
        )
        check(
            type(self.ttl_bars) is int and 1 <= self.ttl_bars <= 100_000,
            "bounded TTL in eligible candles required",
        )
        check(
            type(self.allow_touch) is bool and type(self.mixed) is MixedPolicy,
            "explicit touch and mixed-side hypotheses required",
        )

    def volume(self, candle: Candle, rules: MarketRules) -> Qty:
        with financial():
            return rules.quantity.floor(Qty(candle.volume.value * self.participation))


@dataclass(frozen=True, slots=True)
class VirtualOrder:
    ref: str
    cycle_ref: CellCycleRef
    side: Side
    limit: Price
    qty: Qty
    created_at: datetime
    activated_at: datetime

    def __post_init__(self) -> None:
        check(is_valid_external_ref(self.ref), "virtual order reference required")
        check(
            type(self.cycle_ref) is CellCycleRef and type(self.side) is Side,
            "native cycle/side required",
        )
        replace(self.cycle_ref)
        check(type(self.limit) is Price and type(self.qty) is Qty, "native limit/quantity required")
        replace(self.limit)
        replace(self.qty)
        check(not self.qty.is_zero, "order quantity must be positive")
        require_utc(self.created_at)
        require_utc(self.activated_at)
        check(self.created_at <= self.activated_at, "activation before creation")

    def active_for(self, candle: Candle) -> bool:
        return self.activated_at <= candle.open_time and self.created_at < candle.close_time


def crossed(order: VirtualOrder, candle: Candle, policy: ExecutionPolicy) -> bool:
    if not order.active_for(candle):
        return False
    # This model reports fills at LIMIT. Never invent a traded price outside the bar.
    # Gap improvement needs a separate explicit execution model; defer instead.
    if not candle.low <= order.limit <= candle.high:
        return False
    with financial():
        buffer = policy.spread / Decimal(2) + policy.slippage
        adverse = (
            candle.low.value * (1 + buffer)
            if order.side is Side.BUY
            else candle.high.value * (1 - buffer)
        )
        if order.side is Side.BUY:
            return (
                adverse <= order.limit.value if policy.allow_touch else adverse < order.limit.value
            )
        return adverse >= order.limit.value if policy.allow_touch else adverse > order.limit.value


def selected_orders(
    orders: tuple[VirtualOrder, ...],
    candle: Candle,
    policy: ExecutionPolicy,
) -> tuple[tuple[VirtualOrder, ...], bool]:
    check(
        type(orders) is tuple and len({o.ref for o in orders}) == len(orders),
        "duplicate virtual order",
    )
    candidates = tuple(o for o in orders if crossed(o, candle, policy))
    mixed = len({o.side for o in candidates}) > 1
    if mixed:
        if policy.mixed is MixedPolicy.DEFER_MIXED:
            return (), True
        side = Side.BUY if policy.mixed is MixedPolicy.BUY_PRIORITY else Side.SELL
        candidates = tuple(o for o in candidates if o.side is side)
    return tuple(sorted(candidates, key=lambda o: o.cycle_ref)), mixed


def executable_quantity(order: VirtualOrder, capacity: Qty, rules: MarketRules) -> Qty:
    check(type(capacity) is Qty, "native nonnegative volume budget required")
    return rules.quantity.floor(min(order.qty, capacity))


class CausalClock:
    """Only a closed bar advances time; no wall clock or future-series query API."""

    def __init__(self) -> None:
        self.now: datetime | None = None

    def advance(self, candle: Candle) -> datetime:
        replace(candle)
        check(self.now is None or self.now == candle.open_time, "non-contiguous causal clock")
        self.now = candle.close_time
        return self.now
