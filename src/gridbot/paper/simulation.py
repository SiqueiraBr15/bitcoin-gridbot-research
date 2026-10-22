"""Transient supplied-event PAPER runtime. No persistence, exchange, or balance import.

Owned sources and one validated incremental head; durable PAPER still replays sources.
See ADR-035 for the induction/ownership contract and deliberately separate authorities.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock

from gridbot.application.operational_persistence import require_revision
from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.domain import BTCUSDT, Money, Qty
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    COMMAND_TYPES,
    PaperCommand,
    PaperError,
    PaperErrorCode,
    PaperInitialState,
    PaperSellAuthorization,
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
from gridbot.paper.generations import (
    GridGeneration,
    GridGenerationEvidence,
    PaperRecenter,
    economics,
    generation_evidence,
    initial_generation,
    validate_recenter,
)
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.portfolio.buy_finalization import BuyExecutionContext
from gridbot.strategy.grid_state import CellCycleRef, GridState

MAX_SIMULATION_EVENTS = 10_000


class SimulationErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
    CONTINUITY_ERROR = "CONTINUITY_ERROR"


class SimulationError(DomainError):
    def __init__(self, code: SimulationErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _check(condition: bool, detail: str, code: SimulationErrorCode) -> None:
    if not condition:
        raise SimulationError(code, detail)


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    run_ref: str
    revision: int
    command: PaperCommand | PaperRecenter


@dataclass(frozen=True, slots=True)
class SimulationLog:
    """Complete retained inputs in memory, never a checkpoint of arbitrary balances."""

    run_ref: str
    initial: PaperInitialState
    events: tuple[SimulationEvent, ...]
    revision: int
    version: int = 1


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    """Detached reporting values. No transition/codec/journal accepts this as authority."""

    run_ref: str
    revision: int
    grid_state: GridState
    available_quote: Money
    buy_spending: Money
    settled_sell_proceeds: Money
    active_buy_reservations: Money
    remaining_grid_base: Qty
    reserved_grid_base: Qty
    third_asset_balances: tuple[Money, ...]
    third_asset_obligations: tuple[Money, ...]
    incident_blocked: bool


@dataclass(frozen=True, slots=True)
class _Head:
    frame: _Frame
    events: tuple[SimulationEvent, ...]
    generations: tuple[GridGeneration, ...]


def _candidate(frame: _Frame) -> _Frame:
    # The reducer only replaces owned immutable values or edits these containers.
    # Copy every container; no historical object is mutated by the native reducer.
    return replace(
        frame,
        holds=frame.holds.copy(),
        buys=frame.buys.copy(),
        sells=frame.sells.copy(),
        observations=frame.observations.copy(),
        latest=frame.latest.copy(),
        applied=frame.applied.copy(),
        reserved=frame.reserved.copy(),
        consumed=frame.consumed.copy(),
        released=frame.released.copy(),
        buy_refs=frame.buy_refs.copy(),
        buy_fills=frame.buy_fills.copy(),
        sell_fills=frame.sell_fills.copy(),
    )


class PaperSimulation:
    """Local serialized simulation, unrelated to journal durability or external authority."""

    __slots__ = ("__head", "__initial", "__limit", "__lock", "__run_ref")

    def __init__(self, initial: PaperInitialState, *, run_ref: str, max_events: int) -> None:
        _exact(initial, PaperInitialState)
        _check(
            type(max_events) is int and 1 <= max_events <= MAX_SIMULATION_EVENTS,
            "explicit bounded event budget required",
            SimulationErrorCode.INVALID_INPUT,
        )
        _check(
            type(run_ref) is str
            and is_valid_external_ref(run_ref)
            and run_ref.startswith("SIM:")
            and len(run_ref) > 4,
            "declared simulation run reference required",
            SimulationErrorCode.INVALID_INPUT,
        )
        owned = deepcopy(initial)
        replace(owned)
        self.__initial = owned
        self.__run_ref = run_ref
        self.__limit = max_events
        self.__lock = RLock()
        frame = _Frame(owned.grid_state, Money.zero(BTCUSDT.quote), Money.zero(BTCUSDT.quote))
        self.__head = _Head(frame, (), (initial_generation(owned, frame),))

    @property
    def initial(self) -> PaperInitialState:
        return deepcopy(self.__initial)

    @property
    def run_ref(self) -> str:
        return self.__run_ref

    @property
    def max_events(self) -> int:
        return self.__limit

    @property
    def revision(self) -> int:
        with self.__lock:
            return len(self.__head.events)

    @property
    def grid_state(self) -> GridState:
        with self.__lock:
            return deepcopy(self.__head.frame.state)

    @property
    def available_quote(self) -> Money:
        with self.__lock:
            return deepcopy(_available(self.__initial, self.__head.frame))

    @property
    def buy_spending(self) -> Money:
        with self.__lock:
            return deepcopy(self.__head.frame.spent)

    @property
    def settled_sell_proceeds(self) -> Money:
        with self.__lock:
            return deepcopy(self.__head.frame.proceeds)

    @property
    def active_buy_reservations(self) -> Money:
        with self.__lock:
            return deepcopy(_hold_total(self.__head.frame))

    @property
    def remaining_grid_base(self) -> Qty:
        with self.__lock:
            return deepcopy(_remaining_grid_base(self.__head.frame))

    @property
    def reserved_grid_base(self) -> Qty:
        with self.__lock:
            return deepcopy(sum(self.__head.frame.reserved.values(), Qty.zero()))

    @property
    def incident_blocked(self) -> bool:
        with self.__lock:
            return self.__head.frame.incident

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext:
        with self.__lock:
            return deepcopy(_buy_context(self.__head.frame, ref))

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization:
        with self.__lock:
            _require(ref in self.__head.frame.sells, "SELL authorization absent")
            return deepcopy(self.__head.frame.sells[ref])

    def third_asset_balances(self) -> tuple[Money, ...]:
        with self.__lock:
            return deepcopy(_third_asset_balances(self.__initial, self.__head.frame))

    def third_asset_obligations(self) -> tuple[Money, ...]:
        with self.__lock:
            return deepcopy(_third_asset_obligations(self.__initial, self.__head.frame))

    def snapshot(self) -> SimulationSnapshot:
        with self.__lock:
            return SimulationSnapshot(
                self.run_ref,
                self.revision,
                self.grid_state,
                self.available_quote,
                self.buy_spending,
                self.settled_sell_proceeds,
                self.active_buy_reservations,
                self.remaining_grid_base,
                self.reserved_grid_base,
                self.third_asset_balances(),
                self.third_asset_obligations(),
                self.incident_blocked,
            )

    @property
    def generations(self) -> tuple[GridGeneration, ...]:
        with self.__lock:
            return deepcopy(self.__head.generations)

    def generation_evidence(self) -> GridGenerationEvidence:
        with self.__lock:
            return deepcopy(
                generation_evidence(
                    self.__initial,
                    self.__head.frame,
                    self.run_ref,
                    self.revision,
                    self.__head.generations[-1].ordinal,
                )
            )

    def recenter(self, expected_revision: int, command: PaperRecenter) -> int:
        """Publish a complete flat generation transition, preserving every finance source."""
        require_revision(expected_revision)
        _exact(command, PaperRecenter)
        with self.__lock:
            old = self.__head
            _require(
                expected_revision == len(old.events),
                "stale simulation revision",
                PaperErrorCode.STALE_REVISION,
            )
            owned = deepcopy(command)
            replace(owned)
            _require(
                not old.frame.incident,
                "unresolved evidence incident",
                PaperErrorCode.INCIDENT_BLOCKED,
            )
            for previous in old.generations:
                if previous.ref == owned.plan.next_generation_ref:
                    _require(
                        previous.transition == owned,
                        "conflicting generation transition",
                        PaperErrorCode.IDENTITY_CONFLICT,
                    )
                    return len(old.events)
            _check(
                len(old.events) < self.__limit,
                "simulation history full; no generation applied",
                SimulationErrorCode.CAPACITY_EXCEEDED,
            )
            evidence = generation_evidence(
                self.__initial,
                old.frame,
                self.run_ref,
                len(old.events),
                old.generations[-1].ordinal,
            )
            state = validate_recenter(
                self.__initial, old.frame, owned, evidence, old.generations[-1]
            )
            revision = len(old.events) + 1
            frame = _candidate(old.frame)
            frame.state = state
            unchanged = economics(self.__initial, frame)
            _require(unchanged == evidence.balances, "recenter changed financial totals")
            closed = replace(
                old.generations[-1],
                source_end_revision=revision,
                closed_at=owned.plan.at,
                state_at_closure=old.frame.state,
                final_economics=unchanged,
            )
            created = GridGeneration(
                owned.plan.next_generation_ref,
                closed.ref,
                closed.ordinal + 1,
                revision,
                owned.plan.at,
                owned.plan.policy,
                state,
                unchanged,
                owned,
            )
            generations = (*old.generations[:-1], closed, created)
            event = SimulationEvent(self.run_ref, revision, owned)
            new_head = _Head(frame, (*old.events, event), generations)
            self.__head = new_head
            return revision

    def apply(self, expected_revision: int, command: PaperCommand | PaperRecenter) -> int:
        """A failed operation publishes nothing. Duplicate settlements consume no slot."""
        require_revision(expected_revision)
        if isinstance(command, PaperRecenter):
            return self.recenter(expected_revision, command)
        _require(type(command) in COMMAND_TYPES, "closed PAPER command set")
        with self.__lock:
            old = self.__head
            _require(
                expected_revision == len(old.events),
                "stale simulation revision",
                PaperErrorCode.STALE_REVISION,
            )
            owned = deepcopy(command)
            try:
                if _is_duplicate(old.frame, owned):
                    return len(old.events)
                _check(
                    len(old.events) < self.__limit,
                    "simulation history full; no event applied",
                    SimulationErrorCode.CAPACITY_EXCEEDED,
                )
                frame = _candidate(old.frame)
                revision = len(old.events) + 1
                _apply(self.__initial, frame, owned, revision)
                event = SimulationEvent(self.run_ref, revision, owned)
                new_head = _Head(frame, (*old.events, event), old.generations)
            except PaperError as exc:
                # Pending evidence can refer to an existing owned observation.
                # Do not expose that alias via the public exception payload.
                raise PaperError(
                    exc.code,
                    str(exc).removeprefix(f"{exc.code}: "),
                    deepcopy(exc.observation),
                ) from None
            self.__head = new_head
            return revision

    def source_log(self) -> SimulationLog:
        with self.__lock:
            return deepcopy(
                SimulationLog(
                    self.run_ref,
                    self.__initial,
                    self.__head.events,
                    self.revision,
                    2 if len(self.__head.generations) > 1 else 1,
                )
            )

    @classmethod
    def replay(cls, log: SimulationLog, *, run_ref: str, max_events: int) -> PaperSimulation:
        """Rebuild all supplied sources. No partial runtime is returned on any failure."""
        _check(
            type(log) is SimulationLog, "simulation log required", SimulationErrorCode.INVALID_INPUT
        )
        _check(
            type(log.version) is int and log.version in (1, 2),
            "unknown simulation log version",
            SimulationErrorCode.INVALID_INPUT,
        )
        _check(
            type(log.events) is tuple and log.run_ref == run_ref,
            "foreign run or non-tuple sources",
            SimulationErrorCode.CONTINUITY_ERROR,
        )
        require_revision(log.revision)
        has_generations = any(
            type(e) is SimulationEvent and type(e.command) is PaperRecenter for e in log.events
        )
        _check(
            has_generations == (log.version == 2),
            "source version/generation mismatch",
            SimulationErrorCode.CONTINUITY_ERROR,
        )
        _check(
            log.revision == len(log.events),
            "incomplete source history",
            SimulationErrorCode.CONTINUITY_ERROR,
        )
        runtime = cls(log.initial, run_ref=run_ref, max_events=max_events)
        _check(
            len(log.events) <= runtime.max_events,
            "source history exceeds declared capacity",
            SimulationErrorCode.CAPACITY_EXCEEDED,
        )
        for expected, event in enumerate(log.events, 1):
            _check(
                type(event) is SimulationEvent,
                "unknown simulation event",
                SimulationErrorCode.INVALID_INPUT,
            )
            require_revision(event.revision)
            _check(
                event.run_ref == run_ref and event.revision == expected,
                "non-contiguous simulation sources",
                SimulationErrorCode.CONTINUITY_ERROR,
            )
            actual = (
                runtime.recenter(expected - 1, event.command)
                if isinstance(event.command, PaperRecenter)
                else runtime.apply(expected - 1, event.command)
            )
            _check(
                actual == expected,
                "idempotent call cannot masquerade as a new historical event",
                SimulationErrorCode.CONTINUITY_ERROR,
            )
        return runtime
