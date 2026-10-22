"""PAPER-only event accounting. Production books are structural witnesses, not authority."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Inexact
from enum import StrEnum

from gridbot.application.buy_lifecycle import BuyLifecycleBook
from gridbot.application.buy_quote_capital import (
    BuyQuoteReservation,
    FundedBuyBook,
    bind_funded_buy_execution,
    prepare_funded_buy,
    settle_funded_buy,
)
from gridbot.application.operational_grid import (
    GridOperationalBook,
    _revalidate_finalized_buy,
    bind_external_sell_order,
    bind_sell_execution,
    prepare_sell,
    reserve_operational_sell,
)
from gridbot.application.operational_persistence import require_revision
from gridbot.application.sell_economics import SellEconomicAssessment, _same_economic_event
from gridbot.application.sell_evidence import (
    ObservedSellOrderReport,
    SellOrderIdentity,
    SellTradeCollection,
)
from gridbot.application.sell_fills import ObservedSellFill, SellFillLedger
from gridbot.application.sell_intents import build_sell_intents
from gridbot.application.sell_inventory import SellInventoryBook
from gridbot.application.sell_lifecycle import SellExecutionContext, SellExecutionRef
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.application.sell_terminal import SellTerminalOutcome, SellTerminalReconciliation
from gridbot.domain import BTCUSDT, MarketRules, Money, Qty, Side
from gridbot.domain.decimals import financial
from gridbot.domain.errors import DomainError
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.portfolio.buy_finalization import BuyExecutionContext, BuyExecutionRef, FinalizedBuy
from gridbot.portfolio.sell_sizing import assess_sell_sizing
from gridbot.strategy.buy_intents import BuyIntentPlan, build_buy_intents
from gridbot.strategy.grid_sizing import size_grid_buys
from gridbot.strategy.grid_state import CellCycleRef, CellPhase, CellState, GridState

VENUE = "PAPER_SIMULATOR"
ENVIRONMENT = "PAPER_SIMULATION"


class PaperErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INSUFFICIENT_QUOTE = "INSUFFICIENT_QUOTE"
    STALE_REVISION = "STALE_REVISION"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    SETTLEMENT_CONFLICT = "SETTLEMENT_CONFLICT"
    INCIDENT_BLOCKED = "INCIDENT_BLOCKED"


class PaperError(DomainError):
    def __init__(self, code: PaperErrorCode, detail: str, observation: object = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.observation = observation


def _require(
    condition: bool, detail: str, code: PaperErrorCode = PaperErrorCode.INVALID_INPUT
) -> None:
    if not condition:
        raise PaperError(code, detail)


def _exact(value: object, expected: type) -> None:
    _require(type(value) is expected, f"expected exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class PaperAccount:
    ref: str

    def __post_init__(self) -> None:
        _require(is_valid_external_ref(self.ref) and self.ref.startswith("PAPER:"), "PAPER account")

    def check_ref(self, value: str, kind: str) -> None:
        replace(self)
        _require(
            is_valid_external_ref(value) and value.startswith(self.ref + ":" + kind + ":"),
            "reference outside PAPER namespace",
            PaperErrorCode.IDENTITY_CONFLICT,
        )


@dataclass(frozen=True, slots=True)
class PaperInitialState:
    account: PaperAccount
    grid_state: GridState
    rules: MarketRules
    initial_quote: Money
    third_asset_funding: tuple[Money, ...] = ()

    def __post_init__(self) -> None:
        _exact(self.account, PaperAccount)
        replace(self.account)
        _exact(self.grid_state, GridState)
        _exact(self.rules, MarketRules)
        _exact(self.initial_quote, Money)
        replace(self.grid_state)
        replace(self.rules)
        replace(self.initial_quote)
        replace(self.initial_quote.asset)
        replace(self.rules.symbol.base)
        replace(self.rules.symbol.quote)
        replace(self.rules.symbol)
        replace(self.rules.price)
        replace(self.rules.quantity)
        if self.rules.notional is not None:
            replace(self.rules.notional)
        replace(self.grid_state.plan.spec.lower_price)
        replace(self.grid_state.plan.spec.upper_price)
        replace(self.grid_state.plan.spec)
        for level in self.grid_state.plan.levels:
            replace(level.price)
            replace(level)
        replace(self.grid_state.plan)
        _require(self.rules.symbol == BTCUSDT == self.grid_state.plan.spec.symbol, "BTC/USDT only")
        _require(
            self.initial_quote.asset == BTCUSDT.quote and not self.initial_quote.is_negative,
            "virtual initial quote",
        )
        _require(
            all(
                c.phase is CellPhase.WAITING_BUY and c.cycle_seq == 0 for c in self.grid_state.cells
            ),
            "initial QUOTE_ONLY cycle zero",
        )
        for c in self.grid_state.cells:
            replace(c.cell)
            replace(c)
        _exact(self.third_asset_funding, tuple)
        for funding in self.third_asset_funding:
            _exact(funding, Money)
            replace(funding.asset)
            replace(funding)
            _require(
                funding.asset not in (BTCUSDT.base, BTCUSDT.quote) and not funding.is_negative,
                "explicit third-asset virtual funding only",
            )
        _require(
            len({f.asset for f in self.third_asset_funding}) == len(self.third_asset_funding),
            "duplicate funding asset",
        )


@dataclass(frozen=True, slots=True)
class PaperPrepareBuy:
    plan: BuyIntentPlan
    cycle_ref: CellCycleRef
    quote_fee_hold: Money
    execution_ref: BuyExecutionRef


@dataclass(frozen=True, slots=True)
class PaperSettleBuy:
    finalized: FinalizedBuy


@dataclass(frozen=True, slots=True)
class PaperPrepareSell:
    cycle_ref: CellCycleRef
    base_fee_hold: Qty
    execution_ref: SellExecutionRef
    order_ref: str


@dataclass(frozen=True, slots=True)
class PaperSellEvidence:
    """Supplied simulation evidence, bound to an actual virtual reservation revision."""

    account: PaperAccount
    source_revision: int
    reconciliation: SellTerminalReconciliation

    def __post_init__(self) -> None:
        _exact(self.account, PaperAccount)
        replace(self.account)
        require_revision(self.source_revision)
        _require(self.source_revision > 0, "source revision must be positive")
        _exact(self.reconciliation, SellTerminalReconciliation)
        replace(self.reconciliation)
        _require(
            self.reconciliation.journal_reference is None, "production journal locator forbidden"
        )
        binding = self.reconciliation.book.external_binding_for(self.reconciliation.cycle_ref)
        _require(binding is not None, "PAPER binding required")
        if binding is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "binding absent")
        identity = binding.identity
        _require(
            (identity.venue_ref, identity.environment_ref, identity.account_ref)
            == (VENUE, ENVIRONMENT, self.account.ref),
            "non-PAPER evidence",
            PaperErrorCode.IDENTITY_CONFLICT,
        )
        self.account.check_ref(identity.execution_ref.value, "SELL")
        self.account.check_ref(identity.order_ref, "ORDER")

    @property
    def assessment(self) -> SellEconomicAssessment:
        replace(self)
        return SellEconomicAssessment(self.reconciliation)


@dataclass(frozen=True, slots=True)
class PaperObserveSell:
    evidence: PaperSellEvidence


@dataclass(frozen=True, slots=True)
class PaperApplySell:
    execution_ref: SellExecutionRef
    evidence_revision: int


@dataclass(frozen=True, slots=True)
class PaperReleaseNoFill:
    execution_ref: SellExecutionRef


type PaperCommand = (
    PaperPrepareBuy
    | PaperSettleBuy
    | PaperPrepareSell
    | PaperObserveSell
    | PaperApplySell
    | PaperReleaseNoFill
)
COMMAND_TYPES = (
    PaperPrepareBuy,
    PaperSettleBuy,
    PaperPrepareSell,
    PaperObserveSell,
    PaperApplySell,
    PaperReleaseNoFill,
)


@dataclass(frozen=True, slots=True)
class PaperSellAuthorization:
    """An isolated per-origin witness, never the global PAPER capital authority."""

    account: PaperAccount
    revision: int
    witness: GridOperationalBook

    def __post_init__(self) -> None:
        _exact(self.account, PaperAccount)
        replace(self.account)
        require_revision(self.revision)
        _require(self.revision > 0, "authorization revision")
        _exact(self.witness, GridOperationalBook)
        replace(self.witness)
        _require(len(self.witness.external_sell_bindings) == 1, "one origin witness")
        i = self.witness.external_sell_bindings[0].identity
        _require(
            (i.venue_ref, i.environment_ref, i.account_ref)
            == (VENUE, ENVIRONMENT, self.account.ref),
            "PAPER witness namespace",
        )

    @property
    def context(self) -> SellExecutionContext:
        binding = self.witness.external_sell_bindings[0]
        attempt = self.witness.attempt_for(binding.cycle_ref)
        if attempt is None or attempt.execution is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "missing witness context")
        return attempt.execution

    @property
    def identity(self) -> SellOrderIdentity:
        return self.witness.external_sell_bindings[0].identity


@dataclass(slots=True)
class _Frame:
    """Ephemeral replay accumulators; never stored as an independent authority."""

    state: GridState
    spent: Money
    proceeds: Money
    holds: dict[CellCycleRef, FundedBuyBook] = field(default_factory=dict)
    buys: dict[CellCycleRef, tuple[FundedBuyBook, FinalizedBuy]] = field(default_factory=dict)
    sells: dict[SellExecutionRef, PaperSellAuthorization] = field(default_factory=dict)
    observations: dict[int, PaperSellEvidence] = field(default_factory=dict)
    latest: dict[SellExecutionRef, int] = field(default_factory=dict)
    applied: dict[SellExecutionRef, PaperSellEvidence] = field(default_factory=dict)
    reserved: dict[SellExecutionRef, Qty] = field(default_factory=dict)
    consumed: dict[CellCycleRef, Qty] = field(default_factory=dict)
    released: set[SellExecutionRef] = field(default_factory=set)
    buy_refs: set[BuyExecutionRef] = field(default_factory=set)
    buy_fills: set[str] = field(default_factory=set)
    sell_fills: set[str] = field(default_factory=set)
    incident: bool = False


def _hold_total(frame: _Frame) -> Money:
    return sum(
        (r.reservations[0].total_hold for r in frame.holds.values()), Money.zero(BTCUSDT.quote)
    )


def _available(initial: PaperInitialState, frame: _Frame) -> Money:
    return initial.initial_quote + frame.proceeds - frame.spent - _hold_total(frame)


def _buy_witness(
    initial: PaperInitialState, frame: _Frame, command: PaperPrepareBuy
) -> FundedBuyBook:
    _exact(command.plan, BuyIntentPlan)
    replace(command.plan)
    command.plan.assert_current_for(frame.state, command.plan.sizing)
    _exact(command.cycle_ref, CellCycleRef)
    replace(command.cycle_ref)
    _exact(command.execution_ref, BuyExecutionRef)
    initial.account.check_ref(command.execution_ref.value, "BUY")
    _require(
        command.execution_ref not in frame.buy_refs,
        "BUY execution reused",
        PaperErrorCode.IDENTITY_CONFLICT,
    )
    _require(command.cycle_ref not in frame.holds, "BUY reservation already active")
    intent = next((i for i in command.plan.intents if i.cycle_ref == command.cycle_ref), None)
    _require(intent is not None, "BUY not selected")
    if intent is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "BUY intent absent")
    reservation = BuyQuoteReservation(intent, command.quote_fee_hold)
    _require(
        reservation.total_hold.amount <= _available(initial, frame).amount,
        "insufficient virtual quote",
        PaperErrorCode.INSUFFICIENT_QUOTE,
    )
    # Each A12 witness is funded by THIS recorded hold. It is not recycled global capital.
    state = GridState(
        frame.state.plan,
        tuple(
            CellState(c.cell, CellPhase.WAITING_BUY, c.cycle_ref == command.cycle_ref, c.cycle_seq)
            for c in frame.state.cells
        ),
    )
    plan = build_buy_intents(state, size_grid_buys(state, initial.rules, reservation.notional_hold))
    proof = FundedBuyBook(BuyLifecycleBook(state), reservation.total_hold)
    proof = prepare_funded_buy(proof, plan, command.cycle_ref, command.quote_fee_hold)
    attempt = proof.lifecycle.attempt_for(command.cycle_ref)
    if attempt is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "proof preparation absent")
    _require(attempt.intent == intent, "witness cannot change authorized BUY")
    return bind_funded_buy_execution(
        proof, command.cycle_ref, BuyExecutionContext(intent, command.execution_ref)
    )


def _sell_witness(
    initial: PaperInitialState, frame: _Frame, command: PaperPrepareSell, revision: int
) -> PaperSellAuthorization:
    _exact(command.cycle_ref, CellCycleRef)
    _exact(command.execution_ref, SellExecutionRef)
    initial.account.check_ref(command.execution_ref.value, "SELL")
    initial.account.check_ref(command.order_ref, "ORDER")
    _require(command.execution_ref not in frame.sells, "SELL execution reused")
    _require(
        not any(
            a.identity.cycle_ref == command.cycle_ref or a.identity.order_ref == command.order_ref
            for a in frame.sells.values()
        ),
        "SELL origin/order already committed",
        PaperErrorCode.IDENTITY_CONFLICT,
    )
    _require(
        frame.state.cell(command.cycle_ref.cell_index).cycle_ref == command.cycle_ref
        and frame.state.cell(command.cycle_ref.cell_index).phase is CellPhase.WAITING_SELL,
        "SELL requires current virtual BUY",
    )
    origin = frame.buys.get(command.cycle_ref)
    _require(origin is not None, "no virtual BUY origin")
    if origin is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "BUY absent")
    proof, finalized = origin
    funded = settle_funded_buy(proof, finalized)
    root = GridOperationalBook(SellInventoryBook(funded))
    sizing = assess_sell_sizing(finalized, root.grid_state, initial.rules)
    root = reserve_operational_sell(root, sizing, command.base_fee_hold)
    plan = build_sell_intents(root.inventory_book)
    root = prepare_sell(root, plan, command.cycle_ref)
    attempt = root.attempt_for(command.cycle_ref)
    if attempt is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "SELL witness absent")
    context = SellExecutionContext(attempt.intent, command.execution_ref)
    root = bind_sell_execution(root, command.cycle_ref, context)
    identity = SellOrderIdentity(
        VENUE,
        initial.account.ref,
        ENVIRONMENT,
        command.order_ref,
        context.execution_ref,
        command.cycle_ref,
        context.symbol,
    )
    root = bind_external_sell_order(
        root, command.cycle_ref, ExternalSellOrderBinding(identity, Side.SELL)
    )
    return PaperSellAuthorization(initial.account, revision, root)


def _event_ref(evidence: PaperSellEvidence) -> SellExecutionRef:
    binding = evidence.reconciliation.book.external_sell_bindings[0]
    return binding.identity.execution_ref


def _same(left: PaperSellEvidence, right: PaperSellEvidence) -> bool:
    a, b = left.assessment.projection, right.assessment.projection
    return a is not None and b is not None and _same_economic_event(a, b)


def _apply(initial: PaperInitialState, frame: _Frame, command: PaperCommand, revision: int) -> None:
    _require(type(command) in COMMAND_TYPES, "closed PAPER command set")
    replace(command)
    _require(
        not frame.incident or isinstance(command, PaperObserveSell),
        "late evidence incident",
        PaperErrorCode.INCIDENT_BLOCKED,
    )
    proof: FundedBuyBook | None
    authorization: PaperSellAuthorization | None
    evidence: PaperSellEvidence | None
    if isinstance(command, PaperPrepareBuy):
        proof = _buy_witness(initial, frame, command)
        frame.holds[command.cycle_ref] = proof
        frame.buy_refs.add(command.execution_ref)
    elif isinstance(command, PaperSettleBuy):
        finalized = command.finalized
        _exact(finalized, FinalizedBuy)
        _revalidate_finalized_buy(finalized)
        initial.account.check_ref(finalized.execution_ref.value, "BUY")
        proof = frame.holds.get(finalized.cycle_ref)
        _require(proof is not None, "no active BUY hold")
        if proof is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "BUY proof absent")
        settle_funded_buy(proof, finalized)  # real A12 caps/context checks; witness only
        for buy_fill in finalized.ledger.fills:
            initial.account.check_ref(buy_fill.fill_ref, "TRADE")
            _require(
                buy_fill.fill_ref not in frame.buy_fills
                and buy_fill.fill_ref not in frame.sell_fills,
                "BUY trade reused",
            )
        frame.buy_fills.update(f.fill_ref for f in finalized.ledger.fills)
        frame.spent = frame.spent + finalized.quote_debit_total
        del frame.holds[finalized.cycle_ref]
        frame.buys[finalized.cycle_ref] = (proof, finalized)
        frame.state = (
            frame.state.disarm_buy(finalized.cycle_ref.cell_index)
            if finalized.net_acquired_base_qty.is_zero
            else frame.state.confirm_buy(finalized.cycle_ref.cell_index)
        )
    elif isinstance(command, PaperPrepareSell):
        authorization = _sell_witness(initial, frame, command, revision)
        frame.sells[command.execution_ref] = authorization
        frame.reserved[command.execution_ref] = (
            authorization.context.requested_qty + authorization.context.intent.base_fee_hold
        )
    elif isinstance(command, PaperObserveSell):
        evidence = command.evidence
        _exact(evidence, PaperSellEvidence)
        replace(evidence)
        _require(evidence.account == initial.account, "foreign PAPER account")
        ref = _event_ref(evidence)
        authorization = frame.sells.get(ref)
        _require(authorization is not None, "observation without reservation")
        if authorization is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "SELL absent")
        _require(
            evidence.source_revision == authorization.revision
            and evidence.reconciliation.book == authorization.witness,
            "stale/foreign origin witness",
            PaperErrorCode.IDENTITY_CONFLICT,
        )
        frame.observations[revision] = evidence
        frame.latest[ref] = revision
        if ref in frame.applied and not _same(frame.applied[ref], evidence):
            frame.incident = True
    elif isinstance(command, PaperApplySell):
        require_revision(command.evidence_revision)
        _require(command.evidence_revision in frame.observations, "missing observation")
        evidence = frame.observations[command.evidence_revision]
        ref = _event_ref(evidence)
        _require(
            command.execution_ref == ref and frame.latest[ref] == command.evidence_revision,
            "selection stale",
            PaperErrorCode.STALE_REVISION,
        )
        _require(ref not in frame.applied, "duplicate settlement in history")
        projection = evidence.assessment.projection
        if projection is None:
            raise PaperError(
                PaperErrorCode.EVIDENCE_PENDING, "terminal evidence incomplete", evidence
            )
        ledger = evidence.reconciliation.ledger
        if ledger is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "ledger absent")
        for fill in ledger.fills:
            initial.account.check_ref(fill.fill_ref, "TRADE")
            _require(
                fill.fill_ref not in frame.sell_fills and fill.fill_ref not in frame.buy_fills,
                "trade already economically used",
                PaperErrorCode.IDENTITY_CONFLICT,
            )
        frame.sell_fills.update(f.fill_ref for f in ledger.fills)
        frame.consumed[evidence.reconciliation.cycle_ref] = projection.projected_base_consumption
        frame.proceeds = frame.proceeds + projection.net_observed_quote
        frame.applied[ref] = evidence
        if projection.outcome is SellTerminalOutcome.FULL_EXECUTION:
            frame.reserved[ref] = Qty.zero()
            frame.state = frame.state.confirm_sell(evidence.reconciliation.cycle_ref.cell_index)
        else:
            frame.reserved[ref] = projection.projected_reserved_remainder
    else:
        ref = command.execution_ref
        evidence = frame.applied.get(ref)
        _require(
            evidence is not None and ref not in frame.released, "release without unique settlement"
        )
        if evidence is None:
            raise PaperError(PaperErrorCode.INVALID_INPUT, "settlement absent")
        projection = evidence.assessment.projection
        _require(
            projection is not None and projection.outcome is SellTerminalOutcome.NO_EXECUTION,
            "only terminal no-fill may explicitly release",
        )
        frame.reserved[ref] = Qty.zero()
        frame.released.add(ref)
    _require(not _available(initial, frame).is_negative, "negative virtual available")


def _remaining_grid_base(frame: _Frame) -> Qty:
    total = sum((f.net_acquired_base_qty for _, f in frame.buys.values()), Qty.zero())
    return total - sum(frame.consumed.values(), Qty.zero())


def _buy_context(frame: _Frame, ref: CellCycleRef) -> BuyExecutionContext:
    proof = frame.holds.get(ref)
    _require(proof is not None, "BUY hold absent")
    if proof is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "BUY absent")
    attempt = proof.lifecycle.attempt_for(ref)
    if attempt is None or attempt.execution is None:
        raise PaperError(PaperErrorCode.INVALID_INPUT, "BUY context absent")
    return attempt.execution


def _third_asset_obligations(initial: PaperInitialState, frame: _Frame) -> tuple[Money, ...]:
    """Unfunded virtual fee liabilities, never an invented funding balance."""
    fees = [fee for _, buy in frame.buys.values() for fee in buy.ledger.unvalued_fees]
    for evidence in frame.applied.values():
        projection = evidence.assessment.projection
        if projection is not None:
            fees.extend(projection.third_asset_fees)
    assets = sorted({fee.asset for fee in fees}, key=lambda a: a.code)
    funding = {m.asset: m for m in initial.third_asset_funding}
    obligations = []
    for asset in assets:
        paid = sum((m for m in fees if m.asset == asset), Money.zero(asset))
        difference = paid - funding.get(asset, Money.zero(asset))
        if difference.amount > 0:
            obligations.append(difference)
    return tuple(obligations)


def _third_asset_balances(initial: PaperInitialState, frame: _Frame) -> tuple[Money, ...]:
    """Remaining explicitly supplied virtual funding; obligations never become assets."""
    fees = [fee for _, buy in frame.buys.values() for fee in buy.ledger.unvalued_fees]
    for evidence in frame.applied.values():
        projection = evidence.assessment.projection
        if projection is not None:
            fees.extend(projection.third_asset_fees)
    balances = []
    for funding in initial.third_asset_funding:
        paid = sum((m for m in fees if m.asset == funding.asset), Money.zero(funding.asset))
        difference = funding - paid
        balances.append(difference if difference.amount >= 0 else Money.zero(funding.asset))
    return tuple(balances)


def _is_duplicate(frame: _Frame, command: PaperCommand) -> bool:
    _require(type(command) in COMMAND_TYPES, "non-PAPER command")
    if isinstance(command, (PaperApplySell, PaperReleaseNoFill)):
        _exact(command.execution_ref, SellExecutionRef)
        replace(command.execution_ref)
    if isinstance(command, PaperApplySell):
        require_revision(command.evidence_revision)
    if isinstance(command, PaperSettleBuy):
        _exact(command.finalized, FinalizedBuy)
        _revalidate_finalized_buy(command.finalized)
        previous = frame.buys.get(command.finalized.cycle_ref)
        if previous is not None:
            _require(
                previous[1] == command.finalized,
                "BUY settlement conflict",
                PaperErrorCode.SETTLEMENT_CONFLICT,
            )
            return True
    if isinstance(command, PaperApplySell) and command.execution_ref in frame.applied:
        candidate = frame.observations.get(command.evidence_revision)
        previous_evidence = frame.applied[command.execution_ref]
        _require(
            candidate is not None
            and _event_ref(candidate) == command.execution_ref
            and _same(previous_evidence, candidate),
            "SELL settlement conflict",
            PaperErrorCode.SETTLEMENT_CONFLICT,
        )
        _require(not frame.incident, "unresolved incident", PaperErrorCode.INCIDENT_BLOCKED)
        return True
    if isinstance(command, PaperReleaseNoFill) and command.execution_ref in frame.released:
        _require(not frame.incident, "unresolved incident", PaperErrorCode.INCIDENT_BLOCKED)
        return True
    return False


@dataclass(frozen=True, slots=True)
class PaperBook:
    """Separate authority. Only initial virtual sources and a closed immutable event log."""

    initial: PaperInitialState
    entries: tuple[PaperCommand, ...] = ()

    def __post_init__(self) -> None:
        self._frame()

    def _frame(self) -> _Frame:
        _exact(self.initial, PaperInitialState)
        replace(self.initial)
        _exact(self.entries, tuple)
        require_revision(len(self.entries))
        frame = _Frame(
            self.initial.grid_state, Money.zero(BTCUSDT.quote), Money.zero(BTCUSDT.quote)
        )
        for revision, event in enumerate(self.entries, 1):
            _apply(self.initial, frame, event, revision)
        return frame

    @property
    def revision(self) -> int:
        self._frame()
        return len(self.entries)

    @property
    def grid_state(self) -> GridState:
        return self._frame().state

    @property
    def available_quote(self) -> Money:
        frame = self._frame()
        return _available(self.initial, frame)

    @property
    def buy_spending(self) -> Money:
        return self._frame().spent

    @property
    def settled_sell_proceeds(self) -> Money:
        return self._frame().proceeds

    @property
    def active_buy_reservations(self) -> Money:
        return _hold_total(self._frame())

    @property
    def external_contributions(self) -> Money:
        self._frame()
        return Money.zero(BTCUSDT.quote)

    @property
    def external_withdrawals(self) -> Money:
        self._frame()
        return Money.zero(BTCUSDT.quote)

    @property
    def remaining_grid_base(self) -> Qty:
        return _remaining_grid_base(self._frame())

    @property
    def reserved_grid_base(self) -> Qty:
        return sum(self._frame().reserved.values(), Qty.zero())

    @property
    def incident_blocked(self) -> bool:
        return self._frame().incident

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext:
        return _buy_context(self._frame(), ref)

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization:
        frame = self._frame()
        _require(ref in frame.sells, "SELL authorization absent")
        return frame.sells[ref]

    def third_asset_obligations(self) -> tuple[Money, ...]:
        return _third_asset_obligations(self.initial, self._frame())

    def third_asset_balances(self) -> tuple[Money, ...]:
        return _third_asset_balances(self.initial, self._frame())


def paper_transition(book: PaperBook, expected_revision: int, command: PaperCommand) -> PaperBook:
    """CAS and idempotence within simulation; cannot accept a production root."""
    _exact(book, PaperBook)
    require_revision(expected_revision)
    frame = book._frame()
    _require(
        expected_revision == len(book.entries),
        "stale PAPER revision",
        PaperErrorCode.STALE_REVISION,
    )
    if _is_duplicate(frame, command):
        return book
    return PaperBook(book.initial, (*book.entries, command))


def build_paper_sell_evidence(
    book: PaperBook,
    execution_ref: SellExecutionRef,
    fills: tuple[ObservedSellFill, ...],
    report: ObservedSellOrderReport | None,
    collection: SellTradeCollection | None,
) -> PaperSellEvidence:
    _exact(book, PaperBook)
    authorization = book.sell_authorization(execution_ref)
    ledger = SellFillLedger(authorization.context, fills)
    source = SellTerminalReconciliation(
        authorization.witness, authorization.context.cycle_ref, ledger, report, collection
    )
    return PaperSellEvidence(book.initial.account, authorization.revision, source)


@dataclass(frozen=True, slots=True)
class PaperCostStudy:
    """Hypothesis: proportional net-lot cost, exact Decimal only; no fiscal/production PnL."""

    evidence: PaperSellEvidence

    def __post_init__(self) -> None:
        _exact(self.evidence, PaperSellEvidence)
        replace(self.evidence)
        _require(self.evidence.assessment.projection is not None, "cost needs terminal evidence")

    def _cost(self, quantity: Qty) -> Money | None:
        replace(self)
        projection = self.evidence.assessment.projection
        if projection is None:
            raise PaperError(PaperErrorCode.EVIDENCE_PENDING, "cost source incomplete")
        try:
            with financial():
                return Money(
                    projection.identified_origin_quote_debit.amount
                    * quantity.value
                    / projection.origin_net_base_qty.value,
                    BTCUSDT.quote,
                )
        except Inexact:
            return None

    @property
    def traded_cost(self) -> Money | None:
        projection = self.evidence.assessment.projection
        if projection is None:
            raise PaperError(PaperErrorCode.EVIDENCE_PENDING, "source incomplete")
        return self._cost(projection.executed_qty)

    @property
    def base_fee_cost(self) -> Money | None:
        projection = self.evidence.assessment.projection
        if projection is None:
            raise PaperError(PaperErrorCode.EVIDENCE_PENDING, "source incomplete")
        return self._cost(projection.base_fee_qty)

    @property
    def residual_cost(self) -> Money | None:
        projection = self.evidence.assessment.projection
        if projection is None:
            raise PaperError(PaperErrorCode.EVIDENCE_PENDING, "source incomplete")
        return self._cost(projection.projected_origin_remaining)

    @property
    def hypothetical_pnl(self) -> Money | None:
        projection = self.evidence.assessment.projection
        if projection is None or projection.outcome is SellTerminalOutcome.NO_EXECUTION:
            return None
        if projection.unvalued_third_asset_fees:
            return None
        cost = self._cost(projection.projected_base_consumption)
        return None if cost is None else projection.net_observed_quote - cost

    @property
    def limitations(self) -> tuple[str, ...]:
        replace(self)
        projection = self.evidence.assessment.projection
        if projection is None:
            raise PaperError(PaperErrorCode.EVIDENCE_PENDING, "cost source incomplete")
        result = ["PROPORTIONAL_NET_LOT_HYPOTHESIS_NOT_FISCAL_POLICY"]
        if projection.outcome is SellTerminalOutcome.NO_EXECUTION:
            result.append("NO_SALE")
        if projection.unvalued_third_asset_fees:
            result.append("THIRD_ASSET_COST_UNVALUED")
        if self.traded_cost is None or self.base_fee_cost is None or self.residual_cost is None:
            result.append("NON_TERMINATING_COST_NO_ROUNDING_POLICY")
        return tuple(result)
