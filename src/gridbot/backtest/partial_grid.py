"""Experimental partial recenter consumer. Native bootstrap, bounded two-state PAPER.

The native prefix is replayed at the first eligible candidate. It is then retired
as an executor. Benchmark remains a separate control with its original funding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.application.sell_terminal import SellTerminalOutcome
from gridbot.backtest.data import Dataset, check
from gridbot.backtest.engine import BacktestConfig, _Runner
from gridbot.backtest.execution import (
    CausalClock,
    VirtualOrder,
    executable_quantity,
    selected_orders,
)
from gridbot.backtest.lifecycle import RangeObserver
from gridbot.backtest.metrics import Decision, EquityPoint, Metrics, Trade, equity_point, summarize
from gridbot.backtest.paper_bridge import settle_buy, settle_sell
from gridbot.backtest.recenter import DOCUMENTED_HALT
from gridbot.domain import BTC, USDT, Candle, Qty, Side
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperCommand,
    PaperInitialState,
    PaperObserveSell,
    PaperPrepareSell,
    PaperSellAuthorization,
)
from gridbot.paper.partial_allocation import PartialCosts
from gridbot.paper.simulation import SimulationEvent, SimulationLog
from gridbot.paper.two_generation import (
    PartialPublishPlan,
    PartialSourceEvent,
    PartialSourceLog,
    TwoGenerationPaper,
)
from gridbot.portfolio import BuyExecutionContext, FinalizedBuy
from gridbot.portfolio.sell_sizing import assess_sell_sizing
from gridbot.strategy import CellCycleRef


class _Route:
    """An explicit order-owner route, never a second financial authority."""

    def __init__(self, sim: TwoGenerationPaper, generation_ref: str) -> None:
        self.sim = sim
        self.generation_ref = generation_ref

    @property
    def initial(self) -> PaperInitialState:
        return self.sim.initial

    @property
    def revision(self) -> int:
        return self.sim.revision

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext:
        return self.sim.buy_context(ref)

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization:
        return self.sim.sell_authorization(ref)

    def apply(self, expected_revision: int, command: PaperCommand) -> int:
        return self.sim.apply(expected_revision, self.generation_ref, command)


@dataclass(frozen=True, slots=True)
class PartialDecision:
    at: str
    applied: bool
    plan: PartialPublishPlan | None
    blocker: str


@dataclass(frozen=True, slots=True)
class PartialBacktestRun:
    metrics: Metrics
    benchmark: Metrics
    points: tuple[EquityPoint, ...]
    benchmark_points: tuple[EquityPoint, ...]
    trades: tuple[Trade, ...]
    benchmark_trades: tuple[Trade, ...]
    decisions: tuple[Decision, ...]
    candidates: tuple[PartialDecision, ...]
    sources: PartialSourceLog | SimulationLog
    benchmark_sources: SimulationLog
    base_by_generation: tuple[tuple[str, Qty], ...]
    new_buys: int
    legacy_sells: int
    new_generations: int


class _PartialRunner:
    def __init__(self, dataset: Dataset, config: BacktestConfig, code_commit: str) -> None:
        self.native = _Runner(dataset, config, code_commit)
        self.dataset = self.native.dataset
        self.config = self.native.config
        self.sim: TwoGenerationPaper | None = None
        self.observer = RangeObserver(self.native.sim.grid_state.plan, 168)
        self.signal: list[Candle] = []
        self.candidates: list[PartialDecision] = []
        self.pending: dict[str, VirtualOrder] = {}
        self.ages: dict[str, int] = {}
        self.origins: dict[CellCycleRef, FinalizedBuy] = {}
        self.sell_attempts: set[CellCycleRef] = set()
        self.trades: list[Trade] = []
        self.decisions: list[Decision] = []
        self.new_buys = 0
        self.legacy_sells = 0
        fees = config.policy.fees
        self.costs = PartialCosts(fees.schedule.rate_for(fees.buy_role), fees.buy_asset)
        self.account = self.native.sim.initial.account.ref

    def note(self, candle: Candle, kind: str, ref: str = "", detail: str = "") -> None:
        self.decisions.append(Decision(candle.close_time, kind, ref, detail))

    def create_buys(self, plan: PartialPublishPlan, candle: Candle) -> None:
        sim = self.sim
        check(sim is not None, "partial authority missing")
        if sim is None or plan.allocation.plan is None:
            raise TypeError("published orders absent")
        for intent in plan.allocation.plan.intents:
            context = sim.buy_context(intent.cycle_ref)
            order = VirtualOrder(
                context.execution_ref.value,
                intent.cycle_ref,
                Side.BUY,
                intent.price,
                intent.qty,
                candle.close_time,
                candle.close_time + self.config.policy.latency,
            )
            self.pending[order.ref] = order
            self.ages[order.ref] = 0
            self.note(candle, "ORDER_CREATED", order.ref, sim.main_ref)

    def observe(self, candle: Candle, *, allow_transition: bool) -> None:
        self.observer, candidate = self.observer.observe(candle)
        self.signal.append(candle)
        self.signal = self.signal[-168:]
        if candidate is None:
            return
        proposal = None
        applied, blocker = False, ""
        try:
            check(allow_transition, "PERIOD_END")
            check(self.sim is None, "THIRD_GENERATION_FORBIDDEN")
            check(
                not any(o.side is Side.BUY for o in self.native.pending.values()),
                "OLD_BUY_ACTIVE_OR_UNCERTAIN",
            )
            sim = TwoGenerationPaper(
                self.native.sim.source_log(), max_events=self.config.max_events
            )
            proposal = sim.plan(
                mark=candle.close,
                costs=self.costs,
                notional_ceiling=self.config.notional_budget,
                configuration_ref="CFG:A19_6:PARTIAL_NEAREST_EQUAL_BASE_90_V1",
                signal=tuple(self.signal),
            )
            check(proposal.allocation.admissible, ",".join(proposal.allocation.blockers))
            sim.publish(sim.revision, proposal)
            self.sim = sim
            self.pending = self.native.pending.copy()
            self.ages = self.native.ages.copy()
            self.origins = self.native.origins.copy()
            self.sell_attempts = self.native.sell_attempts.copy()
            self.trades = self.native.trades.copy()
            self.decisions = self.native.decisions.copy()
            self.create_buys(proposal, candle)
            self.observer = RangeObserver(sim.grid_state.plan, 168)
            self.signal.clear()
            applied = True
        except DomainError as exc:
            blocker = str(exc)
        self.candidates.append(
            PartialDecision(candle.close_time.isoformat(), applied, proposal, blocker)
        )
        if self.sim is not None:
            self.note(
                candle,
                "PARTIAL_RECENTER_APPLIED" if applied else "PARTIAL_RECENTER_BLOCKED",
                detail=blocker,
            )

    def terminal(self, order: VirtualOrder, qty: Qty, candle: Candle) -> None:
        sim = self.sim
        if sim is None:
            raise TypeError("partial authority absent")
        owner = sim.owner(order.cycle_ref)
        route = _Route(sim, owner)
        fees = self.config.policy.fees
        fee = fees.commission(order.side, order.limit, qty) if not qty.is_zero else None
        if order.side is Side.BUY:
            self.origins[order.cycle_ref] = settle_buy(route, order, qty, fee, fees.buy_role)
            self.new_buys += int(not qty.is_zero)
        else:
            settle_sell(route, order, qty, fee, fees.sell_role)
            self.legacy_sells += int(not qty.is_zero and owner != sim.main_ref)
        if fee is not None:
            self.trades.append(
                Trade(
                    order.ref,
                    order.cycle_ref,
                    order.side,
                    candle.open_time,
                    candle.close_time,
                    order.limit,
                    qty,
                    fee,
                    fees.buy_role if order.side is Side.BUY else fees.sell_role,
                )
            )
        del self.pending[order.ref]
        del self.ages[order.ref]
        self.note(
            candle,
            "TERMINAL",
            order.ref,
            "FULL" if qty == order.qty else "NO_FILL" if qty.is_zero else "PARTIAL_CANCELED",
        )

    def execute(self, candle: Candle) -> None:
        orders = tuple(self.pending.values())
        selected, ambiguous = selected_orders(orders, candle, self.config.policy)
        if ambiguous:
            self.note(candle, "OHLC_INTRABAR_PATH_UNKNOWN", detail=self.config.policy.mixed)
        capacity = self.config.policy.volume(candle, self.config.rules)
        for order in selected:
            qty = executable_quantity(order, capacity, self.config.rules)
            if not qty.is_zero:
                self.terminal(order, qty, candle)
                capacity = capacity - qty
        for order in orders:
            if order.ref not in self.pending:
                continue
            if order.active_for(candle):
                self.ages[order.ref] += 1
            if self.ages[order.ref] >= self.config.policy.ttl_bars:
                self.terminal(order, Qty.zero(), candle)

    def schedule(self, candle: Candle) -> None:
        sim = self.sim
        if sim is None:
            raise TypeError("partial authority absent")
        for ref, origin in self.origins.items():
            if ref in self.sell_attempts or origin.net_acquired_base_qty.is_zero:
                continue
            owner = sim.owner(ref)
            state = sim.state_for(owner)
            sizing = assess_sell_sizing(origin, state, self.config.rules)
            qty = sizing.eligible_sell_qty
            if qty is None:
                self.note(candle, "SELL_SIZING_INELIGIBLE", str(ref))
                continue
            fee = self.config.policy.fees.commission(
                Side.SELL, state.cell(ref.cell_index).cell.sell_price, qty
            )
            hold = Qty(fee.amount) if fee.asset == BTC else Qty.zero()
            if qty + hold > origin.net_acquired_base_qty:
                self.note(candle, "SELL_BASE_FEE_HOLD_UNFUNDED", str(ref))
                continue
            execution = SellExecutionRef(f"{self.account}:SELL:{ref.cell_index}-{ref.cycle_seq}")
            sim.apply(
                sim.revision,
                owner,
                PaperPrepareSell(
                    ref,
                    hold,
                    execution,
                    f"{self.account}:ORDER:{ref.cell_index}-{ref.cycle_seq}",
                ),
            )
            context = sim.sell_authorization(execution).context
            self.pending[execution.value] = VirtualOrder(
                execution.value,
                ref,
                Side.SELL,
                context.limit_price,
                context.requested_qty,
                candle.close_time,
                candle.close_time + self.config.policy.latency,
            )
            self.ages[execution.value] = 0
            self.sell_attempts.add(ref)
        if sim.has_buy_reservations or not sim.grid_state.armed_buy_refs:
            return
        request = sim.plan(
            mark=candle.close,
            costs=self.costs,
            notional_ceiling=self.config.notional_budget,
            configuration_ref="CFG:A19_6:PARTIAL_NEAREST_EQUAL_BASE_90_V1",
        )
        if not request.allocation.admissible:
            self.note(candle, "PARTIAL_BUY_BLOCKED", detail=",".join(request.allocation.blockers))
            return
        sim.publish(sim.revision, request)
        self.create_buys(request, candle)

    def run(self) -> PartialBacktestRun:
        clock = CausalClock()
        points: list[EquityPoint] = []
        bh_points: list[EquityPoint] = []
        snap = self.native.snapshot
        for candle in self.dataset.series:
            clock.advance(candle)
            if self.sim is None:
                self.native.execute(candle)
            else:
                self.execute(candle)
            self.native.benchmark(candle)
            if candle.close_time < self.dataset.spec.end:
                if self.sim is None:
                    self.native.schedule(candle)
                else:
                    self.schedule(candle)
                self.observe(candle, allow_transition=True)
            else:
                if self.sim is None:
                    for order in tuple(self.native.pending.values()):
                        self.native.terminal(order, Qty.zero(), candle)
                else:
                    for order in tuple(self.pending.values()):
                        self.terminal(order, Qty.zero(), candle)
                self.observe(candle, allow_transition=False)
            revision = self.native.sim.revision if self.sim is None else self.sim.revision
            if snap.revision != revision:
                snap = self.native.reporting_snapshot() if self.sim is None else self.sim.snapshot()
            points.append(equity_point(candle.close_time, candle.close, snap, self.config.bnb_mark))
            bh_points.append(
                equity_point(
                    candle.close_time, candle.close, self.native.bh_snapshot, self.config.bnb_mark
                )
            )
        trades = tuple(self.native.trades if self.sim is None else self.trades)
        sources = self.native.sim.source_log() if self.sim is None else self.sim.source_log()
        events: list[SimulationEvent | PartialSourceEvent]
        if isinstance(sources, SimulationLog):
            events = list(sources.events)
        else:
            events = [*sources.prefix.events, *sources.events]
        observations = {
            e.revision: e.command.evidence
            for e in events
            if isinstance(e.command, PaperObserveSell)
        }
        cycles = 0
        for event in events:
            if isinstance(event.command, PaperApplySell):
                projection = observations[event.command.evidence_revision].assessment.projection
                if (
                    projection is not None
                    and projection.outcome is SellTerminalOutcome.FULL_EXECUTION
                ):
                    cycles += 1
        metrics = replace(
            summarize(
                self.config.initial_quote, self.native.initial_equity, tuple(points), trades, ()
            ),
            cycles=cycles,
        )
        return PartialBacktestRun(
            metrics,
            summarize(
                self.config.initial_quote,
                self.native.initial_equity,
                tuple(bh_points),
                tuple(self.native.bh_trades),
                (),
            ),
            tuple(points),
            tuple(bh_points),
            trades,
            tuple(self.native.bh_trades),
            tuple(self.native.decisions if self.sim is None else self.decisions),
            tuple(self.candidates),
            sources,
            self.native.bh.source_log(),
            ((self.account + ":GEN:0", points[-1].state.remaining_grid_base),)
            if self.sim is None
            else self.sim.base_by_generation(),
            self.new_buys,
            self.legacy_sells,
            int(self.sim is not None),
        )


def run_partial_backtest(
    dataset: Dataset, config: BacktestConfig, *, code_commit: str
) -> PartialBacktestRun:
    check(type(dataset) is Dataset and type(config) is BacktestConfig, "native experiment inputs")
    check(
        not any(DOCUMENTED_HALT.overlaps(c) for c in dataset.series),
        "documented market suspension/continuity remains blocked",
    )
    check(
        not config.third_asset_funding
        and config.policy.fees.buy_asset in (BTC, USDT)
        and config.policy.fees.sell_asset in (BTC, USDT),
        "THIRD_ASSET_VALUATION_REQUIRED",
    )
    return _PartialRunner(dataset, config, code_commit).run()
