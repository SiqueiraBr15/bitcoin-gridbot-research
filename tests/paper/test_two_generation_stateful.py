"""Finite adversarial state machine; oracle tracks actual fills, never supplied balances."""

from dataclasses import replace
from fractions import Fraction

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from gridbot.domain import USDT, Money
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperObserveSell,
    PaperPrepareSell,
    PaperSettleBuy,
)
from gridbot.paper.two_generation import TwoGenerationPaper
from tests.paper.simulation_fixtures import buy_fill_result, sell_source
from tests.paper.test_two_generation import authority, plan, prepared


class TwoGenerationMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.sim = prepared(active_sell=True)
        snapshot = self.sim.snapshot()
        # Seed independently from the accepted BUY source, not the reporting fields.
        prefix = self.sim.source_log().prefix
        settled = prefix.events[1].command
        assert isinstance(settled, PaperSettleBuy)
        buy = settled.finalized
        self.cash = Fraction(self.sim.initial.initial_quote.amount) - Fraction(
            buy.quote_debit_total.amount
        )
        self.base = Fraction(buy.net_acquired_base_qty.value)
        assert snapshot.remaining_grid_base == buy.net_acquired_base_qty
        self.published = False
        self.filled = False
        self.legacy_applied = False

    @precondition(lambda self: not self.published)
    @rule()
    def publish(self) -> None:
        self.request = plan(self.sim)
        self.sim.publish(self.sim.revision, self.request)
        self.published = True

    @precondition(lambda self: self.published)
    @rule()
    def duplicate_candidate(self) -> None:
        before = authority(self.sim)
        self.sim.publish(self.sim.revision, self.request)
        assert authority(self.sim) == before

    @precondition(lambda self: self.published and not self.filled)
    @rule()
    def main_fill(self) -> None:
        selected = self.request.allocation.plan
        assert selected is not None
        intent = selected.intents[0]
        fee = self.request.costs.fee(intent.price, intent.qty)
        final = buy_fill_result(self.sim, intent.cycle_ref.cell_index, fee=fee)
        self.sim.apply(self.sim.revision, self.sim.main_ref, PaperSettleBuy(final))
        self.cash -= Fraction(final.quote_debit_total.amount)
        self.base += Fraction(final.net_acquired_base_qty.value)
        self.filled = True

    @precondition(lambda self: not self.legacy_applied)
    @rule()
    def legacy_settlement(self) -> None:
        source = self.sim.source_log().prefix.events[-1].command
        assert isinstance(source, PaperPrepareSell)
        old = self.sim.generations[0].ref
        evidence = sell_source(self.sim, source.execution_ref, price="105")
        before = self.sim.snapshot().available_quote
        revision = self.sim.apply(self.sim.revision, old, PaperObserveSell(evidence))
        assert self.sim.snapshot().available_quote == before
        self.sim.apply(self.sim.revision, old, PaperApplySell(source.execution_ref, revision))
        projection = evidence.assessment.projection
        assert projection is not None
        self.cash += Fraction(projection.net_observed_quote.amount)
        self.base -= Fraction(projection.projected_base_consumption.value)
        self.legacy_applied = True

    @rule()
    def stale_plan_or_forged_money(self) -> None:
        candidate = self.request if self.published else plan(self.sim)
        candidate = replace(
            candidate, allocation=replace(candidate.allocation, required_quote=Money.zero(USDT))
        )
        before = authority(self.sim)
        with pytest.raises(DomainError):
            self.sim.publish(self.sim.revision, candidate)
        assert authority(self.sim) == before

    @rule()
    def restart_from_sources(self) -> None:
        before = authority(self.sim)
        self.sim = TwoGenerationPaper.replay(self.sim.source_log(), max_events=1000)
        assert authority(self.sim) == before

    @invariant()
    def exact_global_conservation(self) -> None:
        snapshot = self.sim.snapshot()
        assert self.cash == Fraction(snapshot.available_quote.amount) + Fraction(
            snapshot.active_buy_reservations.amount
        )
        assert self.base == Fraction(snapshot.remaining_grid_base.value)
        assert self.cash >= 0
        assert self.base >= Fraction(snapshot.reserved_grid_base.value)
        assert len(self.sim.generations) <= 2


TestTwoGenerationMachine = TwoGenerationMachine.TestCase
TestTwoGenerationMachine.settings = settings(max_examples=30, stateful_step_count=15, deadline=None)
