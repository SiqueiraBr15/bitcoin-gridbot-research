"""Conservative suspension gate with retained PAPER sources, never an execution engine."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from gridbot.backtest.data import check
from gridbot.backtest.execution import VirtualOrder
from gridbot.domain import Candle, Price, Side
from gridbot.domain.time import require_utc
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
)
from gridbot.paper.simulation import PaperSimulation, SimulationLog, SimulationSnapshot


class MarketEvent(StrEnum):
    MARKET_TRADING_SUSPENDED = "MARKET_TRADING_SUSPENDED"
    MARKET_TRADING_RESUMED = "MARKET_TRADING_RESUMED"


@dataclass(frozen=True, slots=True)
class InterruptionWindow:
    suspended: datetime
    resumed: datetime
    evidence: str

    def __post_init__(self) -> None:
        require_utc(self.suspended)
        require_utc(self.resumed)
        check(self.suspended < self.resumed, "invalid interruption window")
        check(type(self.evidence) is str and 0 < len(self.evidence) <= 512, "evidence required")

    def overlaps(self, candle: Candle) -> bool:
        check(type(candle) is Candle, "complete candle required")
        replace(candle)
        return candle.open_time < self.resumed and candle.close_time > self.suspended


@dataclass(frozen=True, slots=True)
class FrozenMarketState:
    """Owned read-only capture; recovering requires complete source replay, not this view."""

    sources: SimulationLog
    snapshot: SimulationSnapshot
    orders: tuple[tuple[VirtualOrder, int], ...]
    mark_at: datetime
    mark: Price


def capture(
    sim: PaperSimulation,
    orders: tuple[tuple[VirtualOrder, int], ...],
    mark_at: datetime,
    mark: Price,
) -> FrozenMarketState:
    check(type(sim) is PaperSimulation, "native PAPER runtime required")
    require_utc(mark_at)
    check(type(mark) is Price, "last known mark required")
    replace(mark)
    check(type(orders) is tuple and len(orders) <= 128, "bounded pending order tuple required")
    sources = sim.source_log()
    # A single owned source log binds every subsequent query to the same revision.
    sim = PaperSimulation.replay(sources, run_ref=sources.run_ref, max_events=sim.max_events)
    # Derive complete pending identities from commands, including observed but unapplied SELL.
    active: set[str] = set()
    for event in sources.events:
        command = event.command
        if isinstance(command, (PaperPrepareBuy, PaperPrepareSell)):
            active.add(command.execution_ref.value)
        elif isinstance(command, PaperSettleBuy):
            active.discard(command.finalized.context.execution_ref.value)
        elif isinstance(command, (PaperApplySell, PaperReleaseNoFill)):
            active.discard(command.execution_ref.value)
    seen: set[str] = set()
    for order, age in orders:
        check(type(order) is VirtualOrder, "native pending order required")
        replace(order)
        check(type(age) is int and 0 <= age <= 100_000, "bounded eligible age required")
        check(order.created_at <= mark_at, "order created with future information")
        check(order.ref not in seen, "duplicate pending identity")
        seen.add(order.ref)
        if order.side is Side.BUY:
            context = sim.buy_context(order.cycle_ref)
            check(
                (context.execution_ref.value, context.intent.price, context.intent.qty)
                == (order.ref, order.limit, order.qty),
                "BUY terms differ from retained PAPER sources",
            )
        else:
            prepared = next(
                (
                    e.command
                    for e in sources.events
                    if isinstance(e.command, PaperPrepareSell)
                    and e.command.execution_ref.value == order.ref
                ),
                None,
            )
            check(prepared is not None, "SELL identity absent")
            if prepared is None:
                raise TypeError("SELL identity absent")
            sell = sim.sell_authorization(prepared.execution_ref).context
            check(
                (sell.cycle_ref, sell.limit_price, sell.requested_qty)
                == (order.cycle_ref, order.limit, order.qty),
                "SELL terms differ from retained PAPER sources",
            )
    check(seen == active, "pending orders omitted or fabricated")
    return FrozenMarketState(deepcopy(sources), sim.snapshot(), deepcopy(orders), mark_at, mark)


@dataclass(frozen=True, slots=True)
class SuspensionGate:
    window: InterruptionWindow
    frozen: FrozenMarketState
    events: tuple[MarketEvent, ...] = ()

    def __post_init__(self) -> None:
        check(type(self.window) is InterruptionWindow, "native window required")
        replace(self.window)
        check(type(self.frozen) is FrozenMarketState, "owned capture required")
        check(self.frozen.mark_at <= self.window.suspended, "future mark forbidden")
        check(
            self.events
            in (
                (),
                (MarketEvent.MARKET_TRADING_SUSPENDED,),
                (MarketEvent.MARKET_TRADING_SUSPENDED, MarketEvent.MARKET_TRADING_RESUMED),
            )
            and all(type(e) is MarketEvent for e in self.events),
            "invalid market event history",
        )

    def transition(self, event: MarketEvent, time: datetime) -> SuspensionGate:
        check(type(event) is MarketEvent, "explicit market event required")
        require_utc(time)
        expected = (
            self.window.suspended
            if event is MarketEvent.MARKET_TRADING_SUSPENDED
            else self.window.resumed
        )
        check(time == expected, "event does not match documented window")
        if event in self.events:
            return self
        check(
            event is MarketEvent.MARKET_TRADING_SUSPENDED or len(self.events) == 1,
            "resume requires suspension",
        )
        return replace(self, events=(*self.events, event))

    def permits(self, candle: Candle) -> bool:
        if self.window.overlaps(candle):
            return False
        # Resume notice is not order reconciliation. No executable resume contract yet.
        return not self.events and candle.close_time <= self.window.suspended

    @property
    def execution_state(self) -> str:
        if not self.events:
            return "CAPTURED_PRE_SUSPENSION"
        if self.events[-1] is MarketEvent.MARKET_TRADING_SUSPENDED:
            return "SUSPENDED_ORDER_EXECUTION_UNKNOWN"
        return "RESUMED_RECONCILIATION_REQUIRED"
