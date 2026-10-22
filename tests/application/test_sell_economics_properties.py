"""Finite A18 properties, independent Fraction oracle and actual execution counters."""

import json
import os
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.application.operational_persistence import OperationalScope
from gridbot.application.sell_economics import SellConsumptionDecision, SellEconomicSettlementPlan
from gridbot.application.sell_terminal import SellJournalReference
from gridbot.domain import BTC, USDT, Asset, OrderStatus
from tests.application.economic_fixtures import economic_sources
from tests.application.test_sell_economics import assert_conservation

COUNTERS: Counter[str] = Counter()


def teardown_module() -> None:
    directory = os.environ.get("A18_COUNTER_DIRECTORY")
    if directory:
        Path(directory, "economic_properties_counters.json").write_text(
            json.dumps(dict(COUNTERS), sort_keys=True), encoding="utf8"
        )


@settings(max_examples=30, derandomize=True, deadline=None)
@given(
    units=st.integers(1, 31000),
    fee_units=st.integers(0, 100),
    asset=st.sampled_from([BTC, USDT, Asset("BNB"), Asset("ETH")]),
)
def test_independent_conservation_multicurrency_purity(
    units: int, fee_units: int, asset: Asset
) -> None:
    COUNTERS["conservation"] += 1
    COUNTERS[asset.code] += 1
    qty = Decimal(units).scaleb(-6)
    status = OrderStatus.FILLED if units == 31000 else OrderStatus.CANCELED
    a = economic_sources(status, str(qty), fee=str(Decimal(fee_units).scaleb(-6)), asset=asset)
    root = a.reconciliation.book
    before = root.inventory_book
    assert_conservation(a)
    assert root.inventory_book is before
    assert a.projection == a.projection
    plan = SellEconomicSettlementPlan(a, root, prior_claims=(a, a))
    assert plan.consumption_decision is SellConsumptionDecision.SETTLEMENT_ALREADY_APPLIED
    assert plan.potential_effects is None
    assert plan.operational_credit is None
    assert not plan.effects_applied
    assert root.inventory_book is before


@settings(max_examples=12, derandomize=True, deadline=None)
@given(
    status=st.sampled_from(
        [
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
            OrderStatus.EXPIRED_IN_MATCH,
            OrderStatus.REJECTED,
        ]
    ),
    asset=st.sampled_from([BTC, USDT, Asset("BNB")]),
)
def test_no_execution_has_no_revenue_or_sale(status: OrderStatus, asset: Asset) -> None:
    COUNTERS["no_fill"] += 1
    a = economic_sources(status, "0", asset=asset)
    assert_conservation(a)
    p = a.projection
    assert p is not None
    assert p.net_observed_quote.amount == 0
    assert p.fees_by_asset == ()
    assert p.projected_base_consumption.is_zero


@settings(max_examples=12, derandomize=True, deadline=None)
@given(missing=st.sampled_from(["ledger", "report", "collection"]), repeat=st.integers(0, 3))
def test_missing_sources_never_offer_plan(missing: str, repeat: int) -> None:
    COUNTERS["missing"] += 1
    a = economic_sources()
    source = a.reconciliation
    for _ in range(repeat + 1):
        changes: dict[str, Any] = {missing: None}
        source = replace(source, **changes)
    a = replace(a, reconciliation=source)
    assert a.projection is None
    plan = SellEconomicSettlementPlan(a, source.book)
    assert plan.potential_effects is None
    assert plan.consumption_decision is SellConsumptionDecision.PENDING_EVIDENCE


@settings(max_examples=12, derandomize=True, deadline=None)
@given(revision=st.integers(1, 1000), repeats=st.integers(1, 3))
def test_witness_revision_and_duplicates_never_create_fresh_credit(
    revision: int, repeats: int
) -> None:
    COUNTERS["stale_duplicate"] += 1
    a = economic_sources()
    report = a.reconciliation.report
    assert report is not None
    i = report.identity
    scope = OperationalScope(i.venue_ref, i.account_ref, i.environment_ref, i.symbol)
    a = replace(
        a,
        reconciliation=replace(
            a.reconciliation, journal_reference=SellJournalReference(scope, revision, (1,))
        ),
    )
    new_ref = SellJournalReference(scope, revision + 1, (1, 2))
    stale = SellEconomicSettlementPlan(a, a.reconciliation.book, new_ref)
    assert stale.consumption_decision is SellConsumptionDecision.STALE_FINANCIAL_ROOT
    current = replace(a, reconciliation=replace(a.reconciliation, journal_reference=new_ref))
    plan = SellEconomicSettlementPlan(current, current.reconciliation.book, new_ref, (a,) * repeats)
    assert plan.consumption_decision is SellConsumptionDecision.SETTLEMENT_ALREADY_APPLIED
    assert plan.potential_effects is None


@settings(max_examples=12, derandomize=True, deadline=None)
@given(fee=st.integers(0, 1000))
def test_conflicting_fee_cannot_offer_credit(fee: int) -> None:
    COUNTERS["conflict"] += 1
    a = economic_sources(fee=str(Decimal(fee).scaleb(-5)))
    conflict = economic_sources(fee=str(Decimal(fee + 1).scaleb(-5)))
    plan = SellEconomicSettlementPlan(a, a.reconciliation.book, prior_claims=(a, conflict))
    assert plan.consumption_decision is SellConsumptionDecision.SETTLEMENT_CONFLICT
    assert plan.potential_effects is None
