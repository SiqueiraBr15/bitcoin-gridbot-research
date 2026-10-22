"""Deterministic offline GRID runner over validated closed bars (ADR-036)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.backtest.data import Dataset, bounded_decimal, check
from gridbot.backtest.execution import (
    BNB,
    CausalClock,
    ExecutionPolicy,
    VirtualOrder,
    executable_quantity,
    selected_orders,
)
from gridbot.backtest.metrics import Decision, EquityPoint, Metrics, Trade, equity_point, summarize
from gridbot.backtest.paper_bridge import proportional_study, settle_buy, settle_sell
from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Candle,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    Qty,
    Side,
)
from gridbot.domain.decimals import financial
from gridbot.domain.time import require_utc
from gridbot.paper.accounting import (
    PaperAccount,
    PaperInitialState,
    PaperPrepareBuy,
    PaperPrepareSell,
)
from gridbot.paper.simulation import (
    MAX_SIMULATION_EVENTS,
    PaperSimulation,
    SimulationLog,
    SimulationSnapshot,
)
from gridbot.portfolio import BuyExecutionRef, FinalizedBuy
from gridbot.portfolio.sell_sizing import assess_sell_sizing
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)
from gridbot.strategy.grid_sizing import GridSizingError


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    grid: ArithmeticGridSpec
    rules: MarketRules
    initial_quote: Money
    notional_budget: Money
    policy: ExecutionPolicy
    run_ref: str
    max_events: int
    assumptions_origin: str
    effective_start: datetime
    effective_end: datetime
    third_asset_funding: tuple[Money, ...] = ()
    bnb_mark: Price | None = None

    def __post_init__(self) -> None:
        check(
            type(self.grid) is ArithmeticGridSpec and type(self.rules) is MarketRules,
            "native grid and rules required",
        )
        replace(self.grid)
        replace(self.rules)
        values = [
            self.grid.lower_price.value,
            self.grid.upper_price.value,
            self.rules.price.tick_size.value,
            self.rules.quantity.step_size.value,
            self.rules.quantity.min_qty.value,
        ]
        values.extend(
            p.value
            for p in (
                self.rules.price.min_price,
                self.rules.price.max_price,
                self.rules.quantity.max_qty,
            )
            if p is not None
        )
        values.extend(
            v
            for v in (self.rules.notional.min_notional, self.rules.notional.max_notional)
            if v is not None
        )
        for amount in values:
            bounded_decimal(amount)
        check(self.grid.symbol == self.rules.symbol == BTCUSDT, "BTC/USDT only")
        check(1 <= self.grid.interval_count <= 64, "at most64 GRID intervals per experiment")
        for value in (self.initial_quote, self.notional_budget):
            check(
                type(value) is Money and value.asset == USDT and not value.is_negative,
                "nonnegative explicit USDT capital/budget required",
            )
            replace(value)
            bounded_decimal(value.amount)
        check(type(self.policy) is ExecutionPolicy, "native execution policy required")
        replace(self.policy)
        check(
            type(self.run_ref) is str
            and self.run_ref.startswith("SIM:")
            and 4 < len(self.run_ref) <= 80
            and all(c.isascii() and (c.isalnum() or c in ":_-") for c in self.run_ref),
            "bounded ASCII simulation identity required",
        )
        check(
            type(self.max_events) is int and 1 <= self.max_events <= MAX_SIMULATION_EVENTS,
            "explicit native event budget required",
        )
        check(
            type(self.assumptions_origin) is str and 0 < len(self.assumptions_origin) <= 256,
            "fee/filter/cost provenance declaration required",
        )
        require_utc(self.effective_start)
        require_utc(self.effective_end)
        check(self.effective_start < self.effective_end, "invalid assumptions validity window")
        check(
            type(self.third_asset_funding) is tuple and len(self.third_asset_funding) <= 1,
            "only one explicit BNB funding lot supported",
        )
        for funding in self.third_asset_funding:
            check(
                type(funding) is Money and funding.asset == BNB and not funding.is_negative,
                "explicit nonnegative BNB funding only",
            )
            replace(funding)
            bounded_decimal(funding.amount)
        check(self.bnb_mark is None or type(self.bnb_mark) is Price, "explicit BNB mark or unknown")
        if self.bnb_mark is not None:
            replace(self.bnb_mark)
            bounded_decimal(self.bnb_mark.value)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    config: BacktestConfig
    dataset_manifest: dict[str, object]
    code_commit: str
    sources: SimulationLog
    benchmark_sources: SimulationLog
    trades: tuple[Trade, ...]
    benchmark_trades: tuple[Trade, ...]
    points: tuple[EquityPoint, ...]
    benchmark_points: tuple[EquityPoint, ...]
    decisions: tuple[Decision, ...]
    metrics: Metrics
    benchmark: Metrics
    cost_limitations: tuple[str, ...]


class _Runner:
    def __init__(self, dataset: Dataset, config: BacktestConfig, code_commit: str) -> None:
        self.dataset = replace(dataset, spec=deepcopy(dataset.spec))
        dataset = self.dataset
        self.config = replace(deepcopy(config))
        config = self.config
        check(type(code_commit) is str and 0 < len(code_commit) <= 128, "code version required")
        self.code_commit = code_commit
        coverage = self.dataset.series.coverage(dataset.spec.start, dataset.spec.end)
        check(coverage.is_complete, "gaps/missing edges are reported but not executable in A19")
        check(len(self.dataset.series) >= 2, "at least two complete candles required")
        check(
            config.effective_start <= dataset.spec.start
            and dataset.spec.end <= config.effective_end,
            "scenario fees/filters not declared valid for this period",
        )
        reference = self.dataset.series.candles[0].close
        state = bootstrap_grid_state(build_arithmetic_grid(config.grid, config.rules), reference)
        account = PaperAccount("PAPER:" + config.run_ref[4:])
        self.sim = PaperSimulation(
            PaperInitialState(
                account, state, config.rules, config.initial_quote, config.third_asset_funding
            ),
            run_ref=config.run_ref,
            max_events=config.max_events,
        )
        # Benchmark starts with the same eligible assets and an inert native grid witness.
        self.bh = PaperSimulation(
            PaperInitialState(
                PaperAccount(account.ref + ":BH"),
                state,
                config.rules,
                config.initial_quote,
                config.third_asset_funding,
            ),
            run_ref=config.run_ref + ":BH",
            max_events=8,
        )
        self.bh_decided = False
        self.last_scheduled_revision = -1
        self.recorded_third_asset_fee = False
        self.pending: dict[str, VirtualOrder] = {}
        self.ages: dict[str, int] = {}
        self.origins: dict[CellCycleRef, FinalizedBuy] = {}
        self.sell_attempts: set[CellCycleRef] = set()
        self.trades: list[Trade] = []
        self.bh_trades: list[Trade] = []
        self.decisions: list[Decision] = []
        self.points: list[EquityPoint] = []
        self.bh_points: list[EquityPoint] = []
        self.studies: list[Money | None] = []
        self.limitations: set[str] = set()
        self.snapshot = self.sim.snapshot()
        self.bh_snapshot = self.bh.snapshot()
        self.initial_equity = equity_point(
            dataset.spec.start, reference, self.snapshot, config.bnb_mark
        ).equity

    def note(self, time: datetime, kind: str, ref: str = "", detail: str = "") -> None:
        # Repeated inactivity is recorded once per identical state, not silently ignored.
        event = Decision(time, kind, ref, detail)
        if not self.decisions or (kind, ref, detail) != (
            self.decisions[-1].kind,
            self.decisions[-1].ref,
            self.decisions[-1].detail,
        ):
            self.decisions.append(event)

    def funded(self, sim: PaperSimulation, fee: Money) -> bool:
        if fee.asset != BNB or fee.amount == 0:
            return True
        return any(m.asset == BNB and m.amount >= fee.amount for m in sim.third_asset_balances())

    def terminal(self, order: VirtualOrder, qty: Qty, candle: Candle) -> None:
        fee = (
            self.config.policy.fees.commission(order.side, order.limit, qty)
            if not qty.is_zero
            else None
        )
        if fee is not None and not self.funded(self.sim, fee):
            self.note(candle.close_time, "BNB_FUNDING_INSUFFICIENT", order.ref)
            return
        if order.side is Side.BUY:
            self.origins[order.cycle_ref] = settle_buy(
                self.sim, order, qty, fee, self.config.policy.fees.buy_role
            )
        else:
            evidence = settle_sell(self.sim, order, qty, fee, self.config.policy.fees.sell_role)
            if not qty.is_zero:
                pnl, limitations = proportional_study(evidence)
                self.studies.append(pnl)
                self.limitations.update(limitations)
        if fee is not None:
            # The exact fee was supplied to and accepted by native PAPER above.
            self.recorded_third_asset_fee |= fee.asset not in (BTC, USDT)
            role = (
                self.config.policy.fees.buy_role
                if order.side is Side.BUY
                else self.config.policy.fees.sell_role
            )
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
                    role,
                )
            )
        self.note(
            candle.close_time,
            "TERMINAL",
            order.ref,
            "FULL" if qty == order.qty else "NO_FILL" if qty.is_zero else "PARTIAL_CANCELED",
        )
        del self.pending[order.ref]
        del self.ages[order.ref]

    def execute(self, candle: Candle) -> None:
        orders = tuple(self.pending.values())
        selected, ambiguous = selected_orders(orders, candle, self.config.policy)
        if ambiguous:
            self.note(candle.close_time, "OHLC_INTRABAR_PATH_UNKNOWN", "", self.config.policy.mixed)
        capacity = self.config.policy.volume(candle, self.config.rules)
        for order in selected:
            qty = executable_quantity(order, capacity, self.config.rules)
            if qty.is_zero:
                continue
            self.terminal(order, qty, candle)
            if order.ref not in self.pending:
                capacity = capacity - qty
        for order in orders:
            if order.ref not in self.pending:
                continue
            if order.active_for(candle):
                self.ages[order.ref] += 1
            if self.ages[order.ref] >= self.config.policy.ttl_bars:
                self.terminal(order, Qty.zero(), candle)

    def schedule(self, candle: Candle) -> None:
        if self.sim.revision == self.last_scheduled_revision:
            return
        state = self.sim.grid_state
        account = self.sim.initial.account.ref
        outstanding = {o.cycle_ref for o in self.pending.values()}
        for ref, origin in self.origins.items():
            if ref in self.sell_attempts or origin.net_acquired_base_qty.is_zero:
                continue
            sizing = assess_sell_sizing(origin, state, self.config.rules)
            quantity = sizing.eligible_sell_qty
            if quantity is None:
                self.note(candle.close_time, "SELL_SIZING_INELIGIBLE", str(ref))
                continue
            fee = self.config.policy.fees.commission(
                Side.SELL, state.cell(ref.cell_index).cell.sell_price, quantity
            )
            hold = Qty(fee.amount) if fee.asset == BTC else Qty.zero()
            if quantity + hold > origin.net_acquired_base_qty:
                self.note(candle.close_time, "SELL_BASE_FEE_HOLD_UNFUNDED", str(ref))
                continue
            execution = SellExecutionRef(f"{account}:SELL:{ref.cell_index}-{ref.cycle_seq}")
            self.sim.apply(
                self.sim.revision,
                PaperPrepareSell(
                    ref, hold, execution, f"{account}:ORDER:{ref.cell_index}-{ref.cycle_seq}"
                ),
            )
            context = self.sim.sell_authorization(execution).context
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
            self.note(candle.close_time, "ORDER_CREATED", execution.value)
        if not any(c.can_buy and c.cycle_ref not in outstanding for c in state.cells):
            self.finish_schedule()
            return
        available = self.sim.available_quote
        budget = Money(min(self.config.notional_budget.amount, available.amount), USDT)
        try:
            plan = build_buy_intents(state, size_grid_buys(state, self.config.rules, budget))
        except GridSizingError as exc:
            self.note(candle.close_time, "BUY_SIZING_INELIGIBLE", "", exc.code)
            self.finish_schedule()
            return
        candidates = tuple(i for i in plan.intents if i.cycle_ref not in outstanding)
        holds = []
        total = Money.zero(USDT)
        for intent in candidates:
            fee = self.config.policy.fees.commission(Side.BUY, intent.price, intent.qty)
            quote_hold = fee if fee.asset == USDT else Money.zero(USDT)
            total = total + Money(intent.price.notional(intent.qty), USDT) + quote_hold
            holds.append(quote_hold)
        if total.amount > available.amount:
            self.note(candle.close_time, "BUY_CAPITAL_INSUFFICIENT")
            self.finish_schedule()
            return
        for intent, quote_hold in zip(candidates, holds, strict=True):
            ref = intent.cycle_ref
            buy_execution = BuyExecutionRef(f"{account}:BUY:{ref.cell_index}-{ref.cycle_seq}")
            self.sim.apply(self.sim.revision, PaperPrepareBuy(plan, ref, quote_hold, buy_execution))
            self.pending[buy_execution.value] = VirtualOrder(
                buy_execution.value,
                ref,
                Side.BUY,
                intent.price,
                intent.qty,
                candle.close_time,
                candle.close_time + self.config.policy.latency,
            )
            self.ages[buy_execution.value] = 0
            self.note(candle.close_time, "ORDER_CREATED", buy_execution.value)
        self.finish_schedule()

    def finish_schedule(self) -> None:
        self.last_scheduled_revision = self.sim.revision

    def reporting_snapshot(self) -> SimulationSnapshot:
        if self.config.third_asset_funding or self.recorded_third_asset_fee:
            return self.sim.snapshot()
        # This closed runner's only fee inputs are the recorded terminal fills.
        # No funding and no third-asset fee proves both third-asset views are empty.
        # All monetary/quantity fields still come directly from native getters;
        # this is a detached report, never an alternate financial authority.
        return SimulationSnapshot(
            self.sim.run_ref,
            self.sim.revision,
            self.sim.grid_state,
            self.sim.available_quote,
            self.sim.buy_spending,
            self.sim.settled_sell_proceeds,
            self.sim.active_buy_reservations,
            self.sim.remaining_grid_base,
            self.sim.reserved_grid_base,
            (),
            (),
            self.sim.incident_blocked,
        )

    def benchmark(self, candle: Candle) -> None:
        first_close = self.dataset.series.candles[0].close_time
        if self.bh_decided or candle.open_time < first_close + self.config.policy.latency:
            return
        self.bh_decided = True
        rules = self.config.rules
        # Hypothetical market acquisition has its own role; GRID BUY LIMIT is unchanged.
        fees = replace(self.config.policy.fees, buy_role=LiquidityRole.TAKER)
        with financial():
            adverse = Price(
                candle.open.value
                * (1 + self.config.policy.spread / Decimal(2) + self.config.policy.slippage)
            )
            price = rules.price.ceil(adverse)
            unit_cost = price.notional(rules.quantity.step_size)
            if fees.buy_asset == USDT:
                unit_cost += fees.commission(Side.BUY, price, rules.quantity.step_size).amount
            units = Fraction(self.config.initial_quote.amount) // Fraction(unit_cost)
            qty = Qty(rules.quantity.step_size.value * units)
        if qty.is_zero or not rules.check(BTCUSDT, price, qty).ok:
            self.note(candle.close_time, "BENCHMARK_FILTER_OR_CAPITAL_INSUFFICIENT")
            return
        # This one-cell witness is a benchmark acquisition, not another GRID policy.
        with financial():
            upper = Price(price.value + rules.price.tick_size.value)
        if rules.price.violations(upper):
            self.note(candle.close_time, "BENCHMARK_NATIVE_WITNESS_GEOMETRY_UNAVAILABLE")
            return
        state = bootstrap_grid_state(
            build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, price, upper, 1), rules), upper
        )
        initial = replace(self.bh.initial, grid_state=state)
        self.bh = PaperSimulation(initial, run_ref=self.bh.run_ref, max_events=8)
        plan = build_buy_intents(
            state, size_grid_buys(state, rules, Money(price.notional(qty), USDT))
        )
        requested = plan.intents[0].qty
        commission = fees.commission(Side.BUY, price, requested)
        hold = commission if commission.asset == USDT else Money.zero(USDT)
        ref = state.cells[0].cycle_ref
        execution = BuyExecutionRef(initial.account.ref + ":BUY:0-0")
        self.bh.apply(self.bh.revision, PaperPrepareBuy(plan, ref, hold, execution))
        filled = rules.quantity.floor(min(requested, self.config.policy.volume(candle, rules)))
        if filled != requested:
            self.note(candle.close_time, "BENCHMARK_PARTIAL_OR_NO_FILL_VOLUME_CAP")
        fee = fees.commission(Side.BUY, price, filled) if not filled.is_zero else None
        if fee is not None and not self.funded(self.bh, fee):
            self.note(candle.close_time, "BENCHMARK_BNB_FUNDING_INSUFFICIENT")
            filled, fee = Qty.zero(), None
        if not filled.is_zero:
            check(
                candle.low <= price <= candle.high,
                "benchmark execution price outside observed OHLC",
            )
        order = VirtualOrder(
            execution.value,
            ref,
            Side.BUY,
            price,
            requested,
            first_close,
            first_close + self.config.policy.latency,
        )
        settle_buy(self.bh, order, filled, fee, fees.buy_role)
        if fee is not None:
            self.bh_trades.append(
                Trade(
                    order.ref,
                    ref,
                    Side.BUY,
                    candle.open_time,
                    candle.close_time,
                    price,
                    filled,
                    fee,
                    fees.buy_role,
                )
            )
        self.bh_snapshot = self.bh.snapshot()

    def run(self) -> BacktestResult:
        clock = CausalClock()
        for candle in self.dataset.series:
            clock.advance(candle)
            self.execute(candle)
            self.benchmark(candle)
            if candle.close_time < self.dataset.spec.end:
                self.schedule(candle)
            else:
                for order in tuple(self.pending.values()):
                    self.terminal(order, Qty.zero(), candle)
            # Every command is validated immediately by PAPER. Only reporting views
            # are coalesced: there is no published intrabar financial sample.
            if self.snapshot.revision != self.sim.revision:
                self.snapshot = self.reporting_snapshot()
            self.points.append(
                equity_point(candle.close_time, candle.close, self.snapshot, self.config.bnb_mark)
            )
            self.bh_points.append(
                equity_point(
                    candle.close_time, candle.close, self.bh_snapshot, self.config.bnb_mark
                )
            )
        points, bh_points = tuple(self.points), tuple(self.bh_points)
        return BacktestResult(
            self.config,
            self.dataset.manifest(),
            self.code_commit,
            self.sim.source_log(),
            self.bh.source_log(),
            tuple(self.trades),
            tuple(self.bh_trades),
            points,
            bh_points,
            tuple(self.decisions),
            summarize(
                self.config.initial_quote,
                self.initial_equity,
                points,
                tuple(self.trades),
                tuple(self.studies),
            ),
            summarize(
                self.config.initial_quote, self.initial_equity, bh_points, tuple(self.bh_trades), ()
            ),
            tuple(sorted(self.limitations)),
        )


def run_backtest(dataset: Dataset, config: BacktestConfig, *, code_commit: str) -> BacktestResult:
    check(type(dataset) is Dataset and type(config) is BacktestConfig, "native experiment inputs")
    return _Runner(dataset, config, code_commit).run()


def compare_scenarios(
    dataset: Dataset, configs: tuple[BacktestConfig, ...], *, code_commit: str
) -> tuple[BacktestResult, ...]:
    check(
        type(configs) is tuple and 1 <= len(configs) <= 8, "bounded explicit sensitivity scenarios"
    )
    check(len({c.run_ref for c in configs}) == len(configs), "scenario identities must be distinct")
    return tuple(run_backtest(dataset, c, code_commit=code_commit) for c in configs)
