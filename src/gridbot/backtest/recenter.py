"""Causal experimental P0/P1/P2 over the native runner; one flat PAPER generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from gridbot.backtest.data import Dataset, check
from gridbot.backtest.engine import BacktestConfig, BacktestResult, _Runner
from gridbot.backtest.execution import FeeModel, VirtualOrder
from gridbot.backtest.interruption import InterruptionWindow
from gridbot.backtest.lifecycle import RangeCandidate, RangeObserver, plan_recenter
from gridbot.domain import Candle, MarketRules, Money, Side
from gridbot.domain.errors import DomainError
from gridbot.paper.generations import (
    RECENTER_THRESHOLD,
    GridGeneration,
    GridGenerationEvidence,
    GridRecenterPlan,
    PaperRecenter,
)
from gridbot.strategy import bootstrap_grid_state, build_buy_intents, size_grid_buys

DOCUMENTED_HALT = InterruptionWindow(
    datetime(2023, 3, 24, 11, 27, tzinfo=UTC),
    datetime(2023, 3, 24, 14, tzinfo=UTC),
    "A19.2/A19.3 documented Spot halt; continuation remains unreleased",
)


@dataclass(frozen=True, slots=True)
class GridRecenterAssessment:
    candidate: RangeCandidate
    evidence: GridGenerationEvidence
    plan: GridRecenterPlan | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        check(type(self.candidate) is RangeCandidate, "native candidate assessment required")
        replace(self.candidate)
        check(type(self.evidence) is GridGenerationEvidence, "native evidence assessment required")
        replace(self.evidence)
        check(
            type(self.blockers) is tuple and all(type(s) is str and s for s in self.blockers),
            "immutable blocker codes required",
        )
        if self.plan is None:
            check(bool(self.blockers), "missing plan cannot be applicable")
        else:
            check(type(self.plan) is GridRecenterPlan, "native pure plan required")
            replace(self.plan)
            check(self.plan.previous == self.evidence, "assessment evidence mismatch")
            check(self.plan.signal[-1] == self.candidate.candle, "assessment signal mismatch")
            check(set(self.plan.blockers).issubset(self.blockers), "cannot hide plan blockers")

    @property
    def status(self) -> str:
        return "RECENTER_BLOCKED" if self.blockers else "PAPER_ONLY_APPLICABLE"

    @property
    def mathematically_valid(self) -> bool:
        return self.plan is not None

    @property
    def applicable(self) -> bool:
        return self.plan is not None and not self.blockers


def assess_recenter(
    evidence: GridGenerationEvidence,
    rules: MarketRules,
    candidate: RangeCandidate,
    signal: tuple[Candle, ...],
    fees: FeeModel,
    notional_budget: Money,
    configuration_ref: str,
    *,
    pending_orders: tuple[VirtualOrder, ...],
    continuity_clear: bool,
    unknown_orders: tuple[str, ...] = (),
) -> GridRecenterAssessment:
    """Pure assessment. Neither a detached pre-state nor this return value moves funds."""
    check(type(evidence) is GridGenerationEvidence, "native generation evidence required")
    replace(evidence)
    check(type(candidate) is RangeCandidate, "native range candidate required")
    replace(candidate)
    check(type(fees) is FeeModel, "native declared fee model required")
    replace(fees)
    check(type(pending_orders) is tuple, "complete virtual order tuple required")
    check(
        type(unknown_orders) is tuple and all(type(s) is str for s in unknown_orders),
        "explicit unknown order set required",
    )
    check(type(continuity_clear) is bool, "explicit market continuity decision required")
    reasons = list(evidence.blockers)
    if not continuity_clear or any(DOCUMENTED_HALT.overlaps(c) for c in signal):
        reasons.append("MARKET_CONTINUITY_UNRESOLVED")
    if unknown_orders:
        reasons.append("ORDER_STATUS_UNKNOWN")
    for order in pending_orders:
        check(type(order) is VirtualOrder, "native virtual order required")
        replace(order)
        reasons.append("OPEN_BUY_ORDER" if order.side is Side.BUY else "OPEN_SELL_ORDER")
    if candidate.grid != evidence.state.plan:
        reasons.append("STALE_GRID_OR_GENERATION")
    if candidate.consecutive != RECENTER_THRESHOLD or not signal or candidate.candle != signal[-1]:
        reasons.append("STALE_OR_INELIGIBLE_SIGNAL")
    proposal = None
    if "STALE_GRID_OR_GENERATION" not in reasons and "STALE_OR_INELIGIBLE_SIGNAL" not in reasons:
        try:
            geometry = plan_recenter(candidate, rules).proposed
            check(geometry is not None, "invalid proposed geometry")
            if geometry is None:
                raise TypeError("geometry absent")
            state = bootstrap_grid_state(geometry, candidate.candle.close)
            state = replace(
                state,
                cells=tuple(replace(c, cycle_seq=evidence.next_cycle_seq) for c in state.cells),
            )
            plan = build_buy_intents(state, size_grid_buys(state, rules, notional_budget))
            projected = tuple(fees.commission(Side.BUY, i.price, i.qty) for i in plan.intents)
            proposal = GridRecenterPlan(
                evidence,
                rules,
                signal,
                notional_budget,
                projected,
                configuration_ref,
                context_blockers=tuple(dict.fromkeys(reasons)),
            )
            check(
                proposal.new_state == state and proposal.buy_plan == plan,
                "native proposal reconstruction mismatch",
            )
            reasons.extend(proposal.blockers)
        except DomainError as exc:
            reasons.append("GEOMETRY_SIZING_OR_EVIDENCE_INVALID:" + type(exc).__name__)
    return GridRecenterAssessment(candidate, evidence, proposal, tuple(dict.fromkeys(reasons)))


@dataclass(frozen=True, slots=True)
class RecenterDecision:
    assessment: GridRecenterAssessment
    applied: bool
    revision_after: int


@dataclass(frozen=True, slots=True)
class RecenterRun:
    result: BacktestResult
    policy: str
    configuration_ref: str
    decisions: tuple[RecenterDecision, ...]
    generations: tuple[GridGeneration, ...]
    outside_closed_bars: int
    outside_sample_seconds: int


class _RecenterRunner(_Runner):
    def __init__(
        self,
        dataset: Dataset,
        config: BacktestConfig,
        code_commit: str,
        policy: str,
        configuration_ref: str,
    ) -> None:
        super().__init__(dataset, config, code_commit)
        self.lifecycle_policy = policy
        self.configuration_ref = configuration_ref
        self.observer = RangeObserver(self.sim.grid_state.plan, RECENTER_THRESHOLD)
        self.signal: list[Candle] = []
        self.assessments: list[RecenterDecision] = []
        self.outside_closed_bars = 0
        self.outside_sample_seconds = 0

    def observe_lifecycle(self, candle: Candle, *, allow_transition: bool) -> None:
        grid = self.observer.grid
        if not grid.spec.lower_price <= candle.close <= grid.spec.upper_price:
            self.outside_closed_bars += 1
            self.outside_sample_seconds += candle.timeframe.duration // timedelta(seconds=1)
        if self.lifecycle_policy == "P0":
            return
        self.observer, candidate = self.observer.observe(candle)
        self.signal.append(candle)
        if len(self.signal) > RECENTER_THRESHOLD:
            del self.signal[0]
        if candidate is None:
            return
        evidence = self.sim.generation_evidence()
        budget = Money(
            min(self.config.notional_budget.amount, evidence.balances.available_quote.amount),
            self.config.notional_budget.asset,
        )
        assessment = assess_recenter(
            evidence,
            self.config.rules,
            candidate,
            tuple(self.signal),
            self.config.policy.fees,
            budget,
            self.configuration_ref,
            pending_orders=tuple(self.pending.values()),
            continuity_clear=True,
        )
        if not allow_transition:
            assessment = replace(assessment, blockers=(*assessment.blockers, "PERIOD_END"))
        applied = False
        if self.lifecycle_policy == "P2" and assessment.applicable:
            plan = assessment.plan
            if plan is None:
                raise TypeError("applicable recenter plan absent")
            self.sim.recenter(self.sim.revision, PaperRecenter(plan, candle))
            applied = True
            self.note(candle.close_time, "RECENTER_APPLIED", plan.next_generation_ref, plan.policy)
            self.observer = RangeObserver(self.sim.grid_state.plan, RECENTER_THRESHOLD)
            self.signal.clear()
            # Reuses native holds/fees/identities. New orders cannot fill in this candle.
            super().schedule(candle)
        elif assessment.blockers:
            self.note(
                candle.close_time,
                "RECENTER_BLOCKED",
                evidence.generation_ref,
                ",".join(assessment.blockers),
            )
        self.assessments.append(RecenterDecision(assessment, applied, self.sim.revision))

    def schedule(self, candle: Candle) -> None:
        super().schedule(candle)
        self.observe_lifecycle(candle, allow_transition=True)


def run_recenter_backtest(
    dataset: Dataset,
    config: BacktestConfig,
    *,
    code_commit: str,
    policy: str,
    configuration_ref: str,
) -> RecenterRun:
    check(type(dataset) is Dataset and type(config) is BacktestConfig, "native experiment inputs")
    check(policy in ("P0", "P1", "P2"), "unknown lifecycle policy")
    check(
        not any(DOCUMENTED_HALT.overlaps(c) for c in dataset.series),
        "documented market suspension/continuity remains blocked",
    )
    runner = _RecenterRunner(dataset, config, code_commit, policy, configuration_ref)
    result = runner.run()
    runner.observe_lifecycle(dataset.series.candles[-1], allow_transition=False)
    generations = runner.sim.generations
    # Sequence high-water marks namespace identities; only advances *within* a
    # generation represent completed cycles. Geometry migrations execute no SELL.
    completed = sum(
        sum(c.cycle_seq for c in (g.state_at_closure or result.points[-1].state.grid_state).cells)
        - sum(c.cycle_seq for c in g.state_at_creation.cells)
        for g in generations
    )
    check(completed >= 0, "generation cycle counter regressed")
    result = replace(result, metrics=replace(result.metrics, cycles=completed))
    return RecenterRun(
        result,
        policy,
        configuration_ref,
        tuple(runner.assessments),
        generations,
        runner.outside_closed_bars,
        runner.outside_sample_seconds,
    )
