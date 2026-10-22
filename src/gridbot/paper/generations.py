"""Flat-only transient PAPER generations; native finance remains the sole ledger.

Plans and detached evidence are proposals. The runtime re-derives the evidence under
its lock before publishing a new head. They cannot import balances or settle funds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from gridbot.application.operational_persistence import require_revision
from gridbot.domain import BTCUSDT, USDT, Candle, MarketRules, Money, Price, Qty
from gridbot.domain.decimals import financial
from gridbot.domain.time import require_utc
from gridbot.paper.accounting import (
    PaperInitialState,
    _available,
    _exact,
    _Frame,
    _hold_total,
    _remaining_grid_base,
    _require,
    _third_asset_balances,
    _third_asset_obligations,
)
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy import (
    ArithmeticGridSpec,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)
from gridbot.strategy.buy_intents import BuyIntentPlan
from gridbot.strategy.grid_state import CellPhase, GridState

RECENTER_POLICY = "PAPER_FLAT_168_SAME_SPACING_V1"
RECENTER_THRESHOLD = 168


@dataclass(frozen=True, slots=True)
class GenerationEconomics:
    available_quote: Money
    buy_spending: Money
    settled_sell_proceeds: Money
    buy_reservations: Money
    grid_base: Qty
    sell_reservations: Qty
    third_asset_balances: tuple[Money, ...]
    third_asset_obligations: tuple[Money, ...]

    def __post_init__(self) -> None:
        for amount in (
            self.available_quote,
            self.buy_spending,
            self.settled_sell_proceeds,
            self.buy_reservations,
        ):
            _exact(amount, Money)
            replace(amount)
            _require(amount.asset == USDT, "quote economics must be USDT")
        for qty in (self.grid_base, self.sell_reservations):
            _exact(qty, Qty)
            replace(qty)
        for collection in (self.third_asset_balances, self.third_asset_obligations):
            _exact(collection, tuple)
            for amount in collection:
                _exact(amount, Money)
                replace(amount)


def economics(initial: PaperInitialState, frame: _Frame) -> GenerationEconomics:
    return GenerationEconomics(
        _available(initial, frame),
        frame.spent,
        frame.proceeds,
        _hold_total(frame),
        _remaining_grid_base(frame),
        sum(frame.reserved.values(), Qty.zero()),
        _third_asset_balances(initial, frame),
        _third_asset_obligations(initial, frame),
    )


@dataclass(frozen=True, slots=True)
class GridGenerationEvidence:
    """Detached expected pre-state, never an authority accepted without comparison."""

    run_ref: str
    account_ref: str
    revision: int
    generation: int
    state: GridState
    balances: GenerationEconomics
    next_cycle_seq: int
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(
            is_valid_external_ref(self.run_ref) and self.run_ref.startswith("SIM:"), "run identity"
        )
        _require(
            is_valid_external_ref(self.account_ref) and self.account_ref.startswith("PAPER:"),
            "PAPER generation account",
        )
        require_revision(self.revision)
        _require(type(self.generation) is int and self.generation >= 0, "generation ordinal")
        _require(
            type(self.next_cycle_seq) is int and self.next_cycle_seq > 0, "cycle high-water mark"
        )
        _exact(self.state, GridState)
        replace(self.state)
        _exact(self.balances, GenerationEconomics)
        replace(self.balances)
        _exact(self.blockers, tuple)
        _require(all(type(s) is str and bool(s) for s in self.blockers), "blocker codes")

    @property
    def generation_ref(self) -> str:
        return f"{self.account_ref}:GEN:{self.generation}"


def generation_evidence(
    initial: PaperInitialState, frame: _Frame, run_ref: str, revision: int, generation: int
) -> GridGenerationEvidence:
    values = economics(initial, frame)
    blockers: list[str] = []
    if frame.holds:
        blockers.extend(("OPEN_BUY_ORDER", "BUY_RESERVATION"))
    if any(ref not in frame.applied and ref not in frame.released for ref in frame.sells):
        blockers.extend(("OPEN_SELL_ORDER_OR_UNKNOWN_STATUS", "SETTLEMENT_PENDING"))
    if not values.sell_reservations.is_zero:
        blockers.append("SELL_RESERVATION")
    if not values.grid_base.is_zero:
        blockers.append("GRID_POSITION_OR_RESIDUAL")
    if any(c.phase is not CellPhase.WAITING_BUY for c in frame.state.cells):
        blockers.append("INCOMPLETE_CELL_CYCLE")
    if frame.incident:
        blockers.append("EVIDENCE_INCIDENT")
    if values.third_asset_obligations:
        blockers.append("THIRD_ASSET_FEE_OBLIGATION")
    if (
        values.available_quote.is_negative
        or initial.initial_quote + frame.proceeds
        != frame.spent + values.buy_reservations + values.available_quote
    ):
        blockers.append("QUOTE_NOT_RECONCILED")
    if any(
        buy.net_acquired_base_qty != frame.consumed.get(ref, Qty.zero())
        for ref, (_, buy) in frame.buys.items()
    ):
        blockers.append("UNCONSUMED_BUY_ORIGIN")
    sequences = [c.cycle_seq for c in frame.state.cells]
    sequences.extend(ref.cycle_seq for ref in (*frame.buys, *frame.holds))
    return GridGenerationEvidence(
        run_ref,
        initial.account.ref,
        revision,
        generation,
        frame.state,
        values,
        max(sequences) + 1,
        tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class GridRecenterPlan:
    """A supplied, immutable PAPER proposal; costs are forecasts, not settlements."""

    previous: GridGenerationEvidence
    rules: MarketRules
    signal: tuple[Candle, ...]
    notional_budget: Money
    projected_buy_fees: tuple[Money, ...]
    configuration_ref: str
    policy: str = RECENTER_POLICY
    context_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _exact(self.previous, GridGenerationEvidence)
        replace(self.previous)
        _exact(self.previous.state, GridState)
        replace(self.previous.state)
        _exact(self.rules, MarketRules)
        replace(self.rules)
        _exact(self.signal, tuple)
        _require(len(self.signal) == RECENTER_THRESHOLD, "complete 168-bar signal required")
        _require(self.policy == RECENTER_POLICY, "unknown recenter policy")
        _exact(self.context_blockers, tuple)
        _require(
            all(type(s) is str and bool(s) for s in self.context_blockers), "context blocker codes"
        )
        _require(is_valid_external_ref(self.configuration_ref), "configuration reference required")
        old = self.previous.state.plan
        _require(old == build_arithmetic_grid(old.spec, self.rules), "old geometry/rules mismatch")
        last = None
        for candle in self.signal:
            _exact(candle, Candle)
            replace(candle)
            _require(candle.symbol == BTCUSDT, "BTC/USDT signal only")
            _require(
                not old.spec.lower_price <= candle.close <= old.spec.upper_price,
                "signal reentered the old range",
            )
            if last is not None:
                _require(
                    candle.open_time == last.close_time and candle.timeframe == last.timeframe,
                    "signal contains gap, overlap or conflicting candle",
                )
            last = candle
        _exact(self.notional_budget, Money)
        replace(self.notional_budget)
        _require(
            self.notional_budget.asset == USDT and not self.notional_budget.is_negative,
            "explicit nonnegative USDT notional budget required",
        )
        _exact(self.projected_buy_fees, tuple)
        for fee in self.projected_buy_fees:
            _exact(fee, Money)
            replace(fee)
            _require(not fee.is_negative, "negative fee forecast")
        _require(
            len(self.projected_buy_fees) == len(self.buy_plan.intents),
            "one explicit fee forecast per prospective BUY required",
        )
        for intent, fee in zip(self.buy_plan.intents, self.projected_buy_fees, strict=True):
            _require(
                fee.asset != BTCUSDT.base or fee.amount < intent.qty.value,
                "projected base fee cannot consume the entire BUY",
            )

    @property
    def at(self) -> datetime:
        return self.signal[-1].close_time

    @property
    def reference(self) -> Price:
        return self.signal[-1].close

    @property
    def next_generation_ref(self) -> str:
        return f"{self.previous.account_ref}:GEN:{self.previous.generation + 1}"

    @property
    def new_state(self) -> GridState:
        old = self.previous.state.plan
        with financial():
            center = self.rules.price.floor(self.reference).value
            lower = center - old.step * (old.spec.interval_count // 2)
            upper = lower + old.step * old.spec.interval_count
        grid = build_arithmetic_grid(
            ArithmeticGridSpec(BTCUSDT, Price(lower), Price(upper), old.spec.interval_count),
            self.rules,
        )
        state = bootstrap_grid_state(grid, self.reference)
        _require(
            type(self.previous.next_cycle_seq) is int
            and self.previous.next_cycle_seq > max(c.cycle_seq for c in self.previous.state.cells),
            "new cycles must not reuse previous identities",
        )
        return replace(
            state,
            cells=tuple(replace(c, cycle_seq=self.previous.next_cycle_seq) for c in state.cells),
        )

    @property
    def buy_plan(self) -> BuyIntentPlan:
        state = self.new_state
        return build_buy_intents(state, size_grid_buys(state, self.rules, self.notional_budget))

    @property
    def required_quote(self) -> Money:
        return self.buy_plan.sizing.allocated_quote + sum(
            (f for f in self.projected_buy_fees if f.asset == USDT), Money.zero(USDT)
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        reasons = [*self.previous.blockers, *self.context_blockers]
        if self.notional_budget.amount > self.previous.balances.available_quote.amount or (
            self.required_quote.amount > self.previous.balances.available_quote.amount
        ):
            reasons.append("CAPITAL_INSUFFICIENT_WITH_FEES")
        forecast_assets = {
            f.asset for f in self.projected_buy_fees if f.asset not in (USDT, BTCUSDT.base)
        }
        for asset in sorted(forecast_assets, key=lambda a: a.code):
            needed = sum(
                (f for f in self.projected_buy_fees if f.asset == asset), Money.zero(asset)
            )
            funding = sum(
                (f for f in self.previous.balances.third_asset_balances if f.asset == asset),
                Money.zero(asset),
            )
            if needed.amount > funding.amount:
                reasons.append("PROJECTED_THIRD_ASSET_FEE_UNFUNDED")
        return tuple(dict.fromkeys(reasons))


@dataclass(frozen=True, slots=True)
class PaperRecenter:
    """Transient V2 event; deliberately absent from durable PAPER/production commands."""

    plan: GridRecenterPlan
    current_candle: Candle

    def __post_init__(self) -> None:
        _exact(self.plan, GridRecenterPlan)
        replace(self.plan)
        _exact(self.current_candle, Candle)
        replace(self.current_candle)
        _require(self.current_candle == self.plan.signal[-1], "stale/look-ahead recenter signal")


@dataclass(frozen=True, slots=True)
class GridGeneration:
    ref: str
    predecessor: str | None
    ordinal: int
    source_start_revision: int
    created_at: datetime | None
    reason: str
    state_at_creation: GridState
    initial_economics: GenerationEconomics
    transition: PaperRecenter | None = None
    source_end_revision: int | None = None
    closed_at: datetime | None = None
    state_at_closure: GridState | None = None
    final_economics: GenerationEconomics | None = None


def initial_generation(initial: PaperInitialState, frame: _Frame) -> GridGeneration:
    return GridGeneration(
        initial.account.ref + ":GEN:0",
        None,
        0,
        0,
        None,
        "INITIAL_PAPER_SOURCE",
        frame.state,
        economics(initial, frame),
    )


def validate_recenter(
    initial: PaperInitialState,
    frame: _Frame,
    command: PaperRecenter,
    evidence: GridGenerationEvidence,
    previous: GridGeneration,
) -> GridState:
    replace(command)
    plan = command.plan
    _require(plan.previous == evidence, "stale/foreign/forged generation evidence")
    _require(plan.rules == initial.rules, "generation cannot change market rules")
    _require(previous.ref == evidence.generation_ref, "generation identity conflict")
    _require(previous.source_end_revision is None, "generation is already closed")
    if previous.created_at is not None:
        require_utc(previous.created_at)
        _require(
            plan.signal[0].open_time >= previous.created_at, "signal belongs to old generation"
        )
    _require(not plan.blockers, "RECENTER_BLOCKED: " + ",".join(plan.blockers))
    _require(economics(initial, frame) == evidence.balances, "economic history changed")
    return plan.new_state
