"""Fraction oracle from retained raw commands, not the runtime's derived totals.

Sizing check here is for the supplied fixtures without maxQty clipping. The existing
geometry/sizing suite remains the independent coverage for the broader rules contract.
"""

from collections import defaultdict
from fractions import Fraction

from gridbot.domain import BTC, USDT, OrderStatus
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
)
from gridbot.paper.simulation import SimulationLog, SimulationSnapshot
from gridbot.strategy.grid_state import CellCycleRef


def assert_source_conservation(
    log: SimulationLog, snapshot: SimulationSnapshot
) -> dict[str, Fraction]:
    spending = Fraction()
    proceeds = Fraction()
    acquired = Fraction()
    buy_base_fee = Fraction()
    sold = Fraction()
    sell_base_fee = Fraction()
    gross_quote = Fraction()
    quote_sell_fee = Fraction()
    holds: dict[CellCycleRef, Fraction] = {}
    origins: dict[CellCycleRef, Fraction] = {}
    commitments = {}
    reserved = {}
    fees: dict[str, Fraction] = defaultdict(Fraction)
    applied = set()
    step = Fraction(log.initial.rules.quantity.step_size.value)
    for event in log.events:
        command = event.command
        if isinstance(command, PaperPrepareBuy):
            intent = next(i for i in command.plan.intents if i.cycle_ref == command.cycle_ref)
            holds[command.cycle_ref] = Fraction(intent.price.value) * Fraction(
                intent.qty.value
            ) + Fraction(command.quote_fee_hold.amount)
        elif isinstance(command, PaperSettleBuy):
            buy = command.finalized
            holds.pop(buy.cycle_ref)
            net = Fraction()
            for fill in buy.ledger.fills:
                quantity = Fraction(fill.executed_qty.value)
                acquired += quantity
                net += quantity
                spending += Fraction(fill.execution_price.value) * quantity
                if fill.fee.asset == BTC:
                    fee = Fraction(fill.fee.amount)
                    buy_base_fee += fee
                    net -= fee
                elif fill.fee.asset == USDT:
                    spending += Fraction(fill.fee.amount)
                else:
                    fees[fill.fee.asset.code] += Fraction(fill.fee.amount)
            origins[buy.cycle_ref] = net
        elif isinstance(command, PaperPrepareSell):
            net = origins[command.cycle_ref]
            quantity = (net // step) * step
            hold = Fraction(command.base_fee_hold.value)
            assert quantity + hold <= net
            commitments[command.execution_ref] = command.cycle_ref, quantity, hold
            reserved[command.execution_ref] = quantity + hold
        elif isinstance(command, PaperApplySell):
            assert command.execution_ref not in applied
            applied.add(command.execution_ref)
            selected = log.events[command.evidence_revision - 1].command
            assert isinstance(selected, PaperObserveSell)
            ledger = selected.evidence.reconciliation.ledger
            assert ledger is not None
            ref, quantity, hold = commitments[command.execution_ref]
            executed = Fraction()
            fee_base = Fraction()
            for sell_fill in ledger.fills:
                executed += Fraction(sell_fill.executed_qty.value)
                gross_quote += Fraction(sell_fill.observed_quote.amount)
                proceeds += Fraction(sell_fill.observed_quote.amount)
                if sell_fill.fee.asset == BTC:
                    fee_base += Fraction(sell_fill.fee.amount)
                elif sell_fill.fee.asset == USDT:
                    quote_sell_fee += Fraction(sell_fill.fee.amount)
                    proceeds -= Fraction(sell_fill.fee.amount)
                else:
                    fees[sell_fill.fee.asset.code] += Fraction(sell_fill.fee.amount)
            assert executed <= quantity
            assert fee_base <= hold
            assert executed + fee_base <= quantity + hold <= origins[ref]
            sold += executed
            sell_base_fee += fee_base
            report = selected.evidence.reconciliation.report
            assert report is not None
            reserved[command.execution_ref] = (
                Fraction()
                if report.status is OrderStatus.FILLED
                else quantity - executed + hold - fee_base
            )
        elif isinstance(command, PaperReleaseNoFill):
            reserved[command.execution_ref] = Fraction()
    held = sum(holds.values(), Fraction())
    remaining = acquired - buy_base_fee - sold - sell_base_fee
    reserve = sum(reserved.values(), Fraction())
    available = Fraction(log.initial.initial_quote.amount) + proceeds - spending - held
    assert available >= 0
    assert remaining >= reserve >= 0
    assert Fraction(snapshot.available_quote.amount) == available
    assert Fraction(snapshot.buy_spending.amount) == spending
    assert Fraction(snapshot.settled_sell_proceeds.amount) == proceeds
    assert Fraction(snapshot.active_buy_reservations.amount) == held
    assert Fraction(snapshot.remaining_grid_base.value) == remaining
    assert Fraction(snapshot.reserved_grid_base.value) == reserve
    assert gross_quote - quote_sell_fee == proceeds
    funding = {m.asset.code: Fraction(m.amount) for m in log.initial.third_asset_funding}
    balances = {m.asset.code: Fraction(m.amount) for m in snapshot.third_asset_balances}
    obligations = {m.asset.code: Fraction(m.amount) for m in snapshot.third_asset_obligations}
    for asset in set(fees) | set(funding):
        assert (
            funding.get(asset, Fraction()) + obligations.get(asset, Fraction())
            == balances.get(asset, Fraction()) + fees[asset]
        )
    return dict(
        acquired=acquired,
        buy_base_fee=buy_base_fee,
        sold=sold,
        sell_base_fee=sell_base_fee,
        remaining=remaining,
        spending=spending,
        proceeds=proceeds,
        held=held,
        available=available,
        reserved=reserve,
    )
