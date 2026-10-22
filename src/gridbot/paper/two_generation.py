"""Bounded PAPER experiment: two strategy states, one native financial frame.

No operational/durable registry changes. Retained source replay is in memory only.
The imported pre-transition history is revalidated, never imported as balances.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from typing import cast

from gridbot.application.operational_persistence import require_revision
from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.domain import BTC, BTCUSDT, USDT, Candle, Money, Price, Qty
from gridbot.domain.decimals import financial
from gridbot.paper.accounting import (
    COMMAND_TYPES,
    PaperApplySell,
    PaperCommand,
    PaperError,
    PaperInitialState,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperReleaseNoFill,
    PaperSellAuthorization,
    PaperSettleBuy,
    _apply,
    _available,
    _buy_context,
    _exact,
    _Frame,
    _hold_total,
    _is_duplicate,
    _remaining_grid_base,
    _require,
    _third_asset_balances,
    _third_asset_obligations,
)
from gridbot.paper.generations import GridRecenterPlan, economics, generation_evidence
from gridbot.paper.partial_allocation import (
    BuyCommitment,
    PartialAllocation,
    PartialAllocationInput,
    PartialCosts,
    allocate_partial,
)
from gridbot.paper.simulation import (
    MAX_SIMULATION_EVENTS,
    PaperSimulation,
    SimulationLog,
    SimulationSnapshot,
    _candidate,
)
from gridbot.portfolio import BuyExecutionContext, BuyExecutionRef
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy import (
    ArithmeticGridSpec,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)
from gridbot.strategy.grid_state import CellCycleRef, GridState


@dataclass(frozen=True, slots=True)
class PartialGeneration:
    ref: str
    predecessor: str | None
    state: GridState
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class PartialPublishPlan:
    revision: int
    generation_ref: str
    allocation: PartialAllocation
    costs: PartialCosts
    notional_ceiling: Money
    mark: Price
    signal: tuple[Candle, ...]
    configuration_ref: str


@dataclass(frozen=True, slots=True)
class PartialSourceEvent:
    revision: int
    generation_ref: str
    command: PaperCommand | PartialPublishPlan


@dataclass(frozen=True, slots=True)
class PartialSourceLog:
    prefix: SimulationLog
    events: tuple[PartialSourceEvent, ...]
    revision: int
    version: int = 1


@dataclass(frozen=True, slots=True)
class _PartialHead:
    frame: _Frame
    generations: tuple[PartialGeneration, ...]
    owners: dict[CellCycleRef, str]
    events: tuple[PartialSourceEvent, ...]


def _apply_owned(
    initial: PaperInitialState, frame: _Frame, command: PaperCommand, revision: int
) -> None:
    try:
        _apply(initial, frame, command, revision)
    except PaperError as exc:
        raise PaperError(
            exc.code,
            str(exc).removeprefix(f"{exc.code}: "),
            deepcopy(exc.observation),
        ) from None


class TwoGenerationPaper:
    """Serialized local authority; no API for supplied balances or third generation."""

    def __init__(self, prefix: SimulationLog, *, max_events: int) -> None:
        _exact(prefix, SimulationLog)
        _require(prefix.version == 1, "unmigrated native source prefix required")
        _require(
            type(max_events) is int and 1 <= max_events <= MAX_SIMULATION_EVENTS,
            "bounded event budget required",
        )
        # Full native replay verifies source identity, shape, continuity and commands.
        owned = deepcopy(prefix)
        verified = PaperSimulation.replay(owned, run_ref=owned.run_ref, max_events=max_events)
        self.__prefix = owned
        self.__initial = owned.initial
        self.__limit = max_events
        self.__lock = RLock()
        frame = _Frame(owned.initial.grid_state, Money.zero(USDT), Money.zero(USDT))
        for event in owned.events:
            _require(type(event.command) in COMMAND_TYPES, "native prefix command required")
            # V1 replay above already excludes recenter events.
            _apply(owned.initial, frame, cast(PaperCommand, event.command), event.revision)
        _require(
            economics(owned.initial, frame).available_quote == verified.available_quote,
            "prefix mismatch",
        )
        ref = owned.initial.account.ref + ":GEN:0"
        owners = {cycle: ref for cycle in (*frame.buys, *frame.holds)}
        self.__head = _PartialHead(
            frame, (PartialGeneration(ref, None, frame.state, None),), owners, ()
        )

    @property
    def initial(self) -> PaperInitialState:
        return deepcopy(self.__initial)

    @property
    def run_ref(self) -> str:
        return self.__prefix.run_ref

    @property
    def revision(self) -> int:
        with self.__lock:
            return self.__prefix.revision + len(self.__head.events)

    @property
    def generations(self) -> tuple[PartialGeneration, ...]:
        with self.__lock:
            return deepcopy(self.__head.generations)

    @property
    def main_ref(self) -> str:
        with self.__lock:
            return self.__head.generations[-1].ref

    @property
    def grid_state(self) -> GridState:
        return self.state_for(self.main_ref)

    def state_for(self, generation_ref: str) -> GridState:
        with self.__lock:
            found = next((g for g in self.__head.generations if g.ref == generation_ref), None)
            _require(found is not None, "unknown generation")
            if found is None:
                raise AssertionError("unreachable")
            return deepcopy(found.state)

    def owner(self, cycle: CellCycleRef) -> str:
        with self.__lock:
            _require(cycle in self.__head.owners, "unknown origin")
            return self.__head.owners[cycle]

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext:
        with self.__lock:
            return deepcopy(_buy_context(self.__head.frame, ref))

    @property
    def has_buy_reservations(self) -> bool:
        with self.__lock:
            return bool(self.__head.frame.holds)

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization:
        with self.__lock:
            _require(ref in self.__head.frame.sells, "SELL authorization absent")
            return deepcopy(self.__head.frame.sells[ref])

    def snapshot(self) -> SimulationSnapshot:
        with self.__lock:
            frame = self.__head.frame
            return deepcopy(
                SimulationSnapshot(
                    self.run_ref,
                    self.revision,
                    self.__head.generations[-1].state,
                    _available(self.__initial, frame),
                    frame.spent,
                    frame.proceeds,
                    _hold_total(frame),
                    _remaining_grid_base(frame),
                    sum(frame.reserved.values(), Qty.zero()),
                    _third_asset_balances(self.__initial, frame),
                    _third_asset_obligations(self.__initial, frame),
                    frame.incident,
                )
            )

    def base_by_generation(self) -> tuple[tuple[str, Qty], ...]:
        with self.__lock:
            frame = self.__head.frame
            return tuple(
                (
                    g.ref,
                    sum(
                        (
                            buy.net_acquired_base_qty - frame.consumed.get(ref, Qty.zero())
                            for ref, (_, buy) in frame.buys.items()
                            if self.__head.owners[ref] == g.ref
                        ),
                        Qty.zero(),
                    ),
                )
                for g in self.__head.generations
            )

    def _allocation(
        self, state: GridState, mark: Price, costs: PartialCosts, ceiling: Money
    ) -> PartialAllocation:
        frame = self.__head.frame
        commitments = []
        for proof in frame.holds.values():
            reservation = proof.reservations[0]
            fee = costs.fee(reservation.intent.price, reservation.intent.qty)
            commitments.append(
                BuyCommitment(
                    reservation.intent.price,
                    reservation.intent.qty,
                    reservation.quote_fee_hold,
                    Qty(fee.amount) if fee.asset == BTC else Qty.zero(),
                )
            )
        return allocate_partial(
            PartialAllocationInput(
                state,
                self.__initial.rules,
                _available(self.__initial, frame),
                _hold_total(frame),
                _remaining_grid_base(frame),
                sum(frame.reserved.values(), Qty.zero()),
                mark,
                ceiling,
                costs,
                tuple(commitments),
                bool(
                    self.__initial.third_asset_funding
                    or _third_asset_obligations(self.__initial, frame)
                ),
            )
        )

    def plan(
        self,
        *,
        mark: Price,
        costs: PartialCosts,
        notional_ceiling: Money,
        configuration_ref: str,
        signal: tuple[Candle, ...] = (),
    ) -> PartialPublishPlan:
        with self.__lock:
            for value, expected in (
                (mark, Price),
                (costs, PartialCosts),
                (notional_ceiling, Money),
            ):
                _exact(value, expected)
                replace(value)
            _exact(signal, tuple)
            _require(is_valid_external_ref(configuration_ref), "configuration reference required")
            state = self.grid_state
            frame = self.__head.frame
            _require(not frame.incident, "evidence incident")
            if signal:
                _require(len(self.__head.generations) == 1, "THIRD_GENERATION_FORBIDDEN")
                _require(not frame.holds, "OLD_BUY_ACTIVE_OR_UNCERTAIN")
                evidence = generation_evidence(
                    self.__initial, frame, self.run_ref, self.revision, 0
                )
                # Reuse native signal/geometry/cycle validation; no old flat-only veto bypass
                # is passed to native recenter. Only its proposed strategy state is used.
                with financial():
                    center = self.__initial.rules.price.floor(mark).value
                    lower = center - state.plan.step * (state.plan.spec.interval_count // 2)
                    upper = lower + state.plan.step * state.plan.spec.interval_count
                proposed = bootstrap_grid_state(
                    build_arithmetic_grid(
                        ArithmeticGridSpec(
                            BTCUSDT,
                            Price(lower),
                            Price(upper),
                            state.plan.spec.interval_count,
                        ),
                        self.__initial.rules,
                    ),
                    mark,
                )
                proposed = replace(
                    proposed,
                    cells=tuple(
                        replace(c, cycle_seq=evidence.next_cycle_seq) for c in proposed.cells
                    ),
                )
                native_plan = build_buy_intents(
                    proposed,
                    size_grid_buys(
                        proposed,
                        self.__initial.rules,
                        notional_ceiling,
                    ),
                )
                provisional = GridRecenterPlan(
                    evidence,
                    self.__initial.rules,
                    signal,
                    notional_ceiling,
                    tuple(costs.fee(i.price, i.qty) for i in native_plan.intents),
                    configuration_ref,
                )
                state = provisional.new_state
                _require(mark == signal[-1].close, "signal/mark mismatch")
            else:
                _require(not frame.holds, "BUY_BATCH_STILL_ACTIVE")
            allocation = self._allocation(state, mark, costs, notional_ceiling)
            return deepcopy(
                PartialPublishPlan(
                    self.revision,
                    self.main_ref,
                    allocation,
                    costs,
                    notional_ceiling,
                    mark,
                    signal,
                    configuration_ref,
                )
            )

    def publish(self, expected_revision: int, plan: PartialPublishPlan) -> int:
        require_revision(expected_revision)
        _exact(plan, PartialPublishPlan)
        require_revision(plan.revision)
        with self.__lock:
            _require(expected_revision == self.revision, "stale revision")
            old = self.__head
            owned = deepcopy(plan)
            if any(e.command == owned for e in old.events if type(e.command) is PartialPublishPlan):
                return self.revision
            _require(
                owned.revision == self.revision and owned.generation_ref == self.main_ref,
                "stale plan",
            )
            current = self.plan(
                mark=owned.mark,
                costs=owned.costs,
                notional_ceiling=owned.notional_ceiling,
                configuration_ref=owned.configuration_ref,
                signal=owned.signal,
            )
            _require(current == owned, "forged allocation")
            _require(owned.allocation.admissible, "NO_VALID_FUNDED_ORDERS")
            frame = _candidate(old.frame)
            generations = old.generations
            generation = self.main_ref
            if owned.signal:
                generation = self.__initial.account.ref + ":GEN:1"
                generations = (
                    *generations,
                    PartialGeneration(
                        generation,
                        self.main_ref,
                        owned.allocation.state,
                        owned.signal[-1].close_time,
                    ),
                )
            frame.state = owned.allocation.state
            owners = old.owners.copy()
            buy_plan = owned.allocation.plan
            if buy_plan is None:
                raise AssertionError("validated plan absent")
            revision = self.revision + 1
            for intent, fee in zip(buy_plan.intents, owned.allocation.fees, strict=True):
                _require(intent.cycle_ref not in frame.holds, "BUY already reserved")
                execution = BuyExecutionRef(
                    f"{self.__initial.account.ref}:BUY:{intent.cycle_ref.cell_index}-{intent.cycle_ref.cycle_seq}"
                )
                command = PaperPrepareBuy(
                    buy_plan,
                    intent.cycle_ref,
                    fee if fee.asset == USDT else Money.zero(USDT),
                    execution,
                )
                _apply_owned(self.__initial, frame, command, revision)
                owners[intent.cycle_ref] = generation
            generations = (*generations[:-1], replace(generations[-1], state=frame.state))
            event = PartialSourceEvent(revision, generation, owned)
            self._publish_head(_PartialHead(frame, generations, owners, (*old.events, event)))
            return revision

    def _publish_head(self, head: _PartialHead) -> None:
        _require(self.revision < self.__limit, "event budget exhausted")
        self.__head = head

    def apply(self, expected_revision: int, generation_ref: str, command: PaperCommand) -> int:
        require_revision(expected_revision)
        _require(
            type(command) in COMMAND_TYPES and type(command) is not PaperPrepareBuy,
            "BUY requires admitted batch",
        )
        with self.__lock:
            _require(expected_revision == self.revision, "stale revision")
            old = self.__head
            owned = deepcopy(command)
            if isinstance(owned, PaperSettleBuy):
                cycle = owned.finalized.cycle_ref
                _require(
                    all(f.fee.asset in (BTC, USDT) for f in owned.finalized.ledger.fills),
                    "unexpected third fee",
                )
                admission = next(
                    (
                        event.command
                        for event in reversed(old.events)
                        if isinstance(event.command, PartialPublishPlan)
                        and event.command.allocation.plan is not None
                        and cycle in event.command.allocation.plan.cycle_refs
                    ),
                    None,
                )
                if admission is not None:
                    for fill in owned.finalized.ledger.fills:
                        _require(
                            fill.fee
                            == admission.costs.fee(fill.execution_price, fill.executed_qty),
                            "unexpected BUY commission",
                        )
            elif isinstance(owned, PaperPrepareSell):
                cycle = owned.cycle_ref
            elif isinstance(owned, PaperObserveSell):
                cycle = owned.evidence.reconciliation.cycle_ref
            else:
                authorization = old.frame.sells.get(
                    cast("PaperApplySell | PaperReleaseNoFill", owned).execution_ref
                )
                _require(authorization is not None, "unknown SELL")
                if authorization is None:
                    raise AssertionError("unreachable")
                cycle = authorization.context.cycle_ref
                if isinstance(owned, PaperApplySell):
                    evidence = old.frame.observations.get(owned.evidence_revision)
                    _require(evidence is not None, "missing evidence")
                    if evidence is not None and evidence.assessment.projection is not None:
                        _require(
                            not evidence.assessment.projection.third_asset_fees,
                            "THIRD_ASSET_VALUATION_REQUIRED",
                        )
            _require(self.owner(cycle) == generation_ref, "GENERATION_ORIGIN_MISMATCH")
            if _is_duplicate(old.frame, owned):
                return self.revision
            frame = _candidate(old.frame)
            frame.state = self.state_for(generation_ref)
            revision = self.revision + 1
            _apply_owned(self.__initial, frame, owned, revision)
            generations = tuple(
                replace(g, state=frame.state) if g.ref == generation_ref else g
                for g in old.generations
            )
            frame.state = generations[-1].state
            event = PartialSourceEvent(revision, generation_ref, owned)
            self._publish_head(
                _PartialHead(frame, generations, old.owners.copy(), (*old.events, event))
            )
            return revision

    def source_log(self) -> PartialSourceLog:
        with self.__lock:
            return deepcopy(PartialSourceLog(self.__prefix, self.__head.events, self.revision))

    @classmethod
    def replay(cls, log: PartialSourceLog, *, max_events: int) -> TwoGenerationPaper:
        _exact(log, PartialSourceLog)
        require_revision(log.revision)
        _require(type(log.version) is int and log.version == 1, "unknown partial source version")
        _exact(log.events, tuple)
        _require(
            log.revision == log.prefix.revision + len(log.events), "incomplete partial history"
        )
        runtime = cls(log.prefix, max_events=max_events)
        for event in log.events:
            _exact(event, PartialSourceEvent)
            require_revision(event.revision)
            _require(event.revision == runtime.revision + 1, "noncontiguous partial history")
            actual = (
                runtime.publish(runtime.revision, event.command)
                if type(event.command) is PartialPublishPlan
                else runtime.apply(
                    runtime.revision, event.generation_ref, cast(PaperCommand, event.command)
                )
            )
            _require(actual == event.revision, "duplicate event in source")
            if isinstance(event.command, PartialPublishPlan):
                _require(event.generation_ref == runtime.main_ref, "publish generation mismatch")
        return runtime
