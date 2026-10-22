"""A18 economic evaluation uses recovered A17.5 sources without writing balances."""

from pathlib import Path

from gridbot.application.sell_economics import (
    SellConsumptionDecision,
    SellEconomicAssessment,
    SellEconomicSettlementPlan,
)
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.storage.journal_oracle import audit_assets, audit_rows
from tests.storage.test_operational_journal import bound_sell


def test_economic_recovery_and_duplicate_witness_revision_are_read_only(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    terminal = store.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    old = SellEconomicAssessment(terminal)
    before = store.recover(state.scope)
    before_bytes = store.policy.database_path().read_bytes()
    reopened = SQLiteOperationalJournal.open(store.policy)
    current_terminal = reopened.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    current = SellEconomicAssessment(current_terminal)
    plan = SellEconomicSettlementPlan(current, state.book, current_terminal.journal_reference)
    assert current == old
    assert plan.potential_effects == old.projection
    assert plan.effects_applied is False
    assert store.policy.database_path().read_bytes() == before_bytes
    assert reopened.recover(state.scope) == before
    state = reopened.append_raw_observation(
        state.scope, state.revision, source.tape.observations[1]
    )
    new_terminal = reopened.reconcile_sell_terminal(state.scope, state.revision, source.plan)
    stale = SellEconomicSettlementPlan(old, state.book, new_terminal.journal_reference)
    assert stale.consumption_decision is SellConsumptionDecision.STALE_FINANCIAL_ROOT
    updated = SellEconomicAssessment(new_terminal)
    repeated = SellEconomicSettlementPlan(
        updated, state.book, new_terminal.journal_reference, (old,)
    )
    assert repeated.consumption_decision is SellConsumptionDecision.SETTLEMENT_ALREADY_APPLIED
    assert repeated.potential_effects is None
    assert state.book == before.state.book
    audit_assets(state)
    audit_rows(store.policy.database_path(), expected_receipts=4)
