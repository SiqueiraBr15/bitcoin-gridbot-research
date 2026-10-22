"""A18: Fraction oracle, typed uncertainty, anti-replay proposals and purity."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any, cast

import pytest

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.operational_persistence import OperationalScope
from gridbot.application.sell_economics import (
    SellConsumptionDecision,
    SellEconomicAssessment,
    SellEconomicBlocker,
    SellEconomicProjection,
    SellEconomicSettlementPlan,
)
from gridbot.application.sell_fills import SellFillLedger, record_sell_fill
from gridbot.application.sell_terminal import SellJournalReference, SellTerminalOutcome
from gridbot.domain import BTC, USDT, Asset, DomainError, Money, OrderStatus, Qty
from tests.application.economic_fixtures import (
    assessment_from_ledger,
    economic_sources,
    mandatory_example,
    multi_buy_sources,
)
from tests.application.test_operational_grid import prepare_other_buy
from tests.application.test_sell_fills import fill
from tests.application.test_sell_intents import forged

D = SellConsumptionDecision


def assert_conservation(assessment: SellEconomicAssessment) -> None:
    projection = assessment.projection
    assert projection is not None
    source = assessment.reconciliation
    ledger = source.ledger
    assert ledger is not None
    origin = ledger.context.intent.finalized_buy.ledger.fills
    n = sum(
        (
            Fraction(f.executed_qty.value) - (Fraction(f.fee.amount) if f.fee.asset == BTC else 0)
            for f in origin
        ),
        Fraction(),
    )
    x = sum((Fraction(f.executed_qty.value) for f in ledger.fills), Fraction())
    b = sum((Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == BTC), Fraction())
    y = sum((Fraction(f.observed_quote.amount) for f in ledger.fills), Fraction())
    u = sum((Fraction(f.fee.amount) for f in ledger.fills if f.fee.asset == USDT), Fraction())
    q = Fraction(ledger.context.requested_qty.value)
    h = Fraction(ledger.context.intent.base_fee_hold.value)
    assert x <= q
    assert b <= h
    assert x + b <= q + h <= n
    assert Fraction(projection.origin_net_base_qty.value) == n
    assert Fraction(projection.authorized_sell_qty.value) == q
    assert Fraction(projection.base_fee_hold.value) == h
    assert Fraction(projection.executed_qty.value) == x
    assert Fraction(projection.base_fee_qty.value) == b
    assert Fraction(projection.projected_base_consumption.value) == x + b
    assert Fraction(projection.unexecuted_qty.value) == q - x
    assert Fraction(projection.projected_fee_hold_remainder.value) == h - b
    assert Fraction(projection.projected_reserved_remainder.value) == q - x + h - b
    assert Fraction(projection.projected_origin_remaining.value) == n - x - b
    assert Fraction(projection.unreserved_before.value) == n - q - h
    assert projection.unreserved_before + projection.projected_reserved_remainder == (
        projection.projected_origin_remaining
    )
    assert Fraction(projection.gross_observed_quote.amount) == y
    assert Fraction(projection.quote_fee.amount) == u
    assert Fraction(projection.net_observed_quote.amount) == y - u
    assert projection.net_observed_quote + projection.quote_fee == projection.gross_observed_quote
    assert projection.fees_by_asset == ledger.fees_by_asset
    assert projection.third_asset_fees == ledger.third_asset_fees
    assert (
        projection.identified_origin_quote_debit
        == ledger.context.intent.finalized_buy.quote_debit_total
    )
    assert projection.allocated_cost is None
    assert projection.realized_pnl is None
    assert projection.terminal_source_ref == source.report.source_ref if source.report else False


def test_mandatory_example_decimal_fraction_and_no_effects() -> None:
    assessment = mandatory_example()
    root = assessment.reconciliation.book
    before = root.inventory_book
    assert_conservation(assessment)
    p = assessment.projection
    assert p is not None
    assert p.origin_net_base_qty == Qty.parse(".031968")
    assert p.projected_base_consumption == Qty.parse(".03004")
    assert p.projected_reserved_remainder == Qty.parse(".00106")
    assert p.projected_origin_remaining == Qty.parse(".001928")
    assert p.unreserved_before == Qty.parse(".000868")
    assert p.gross_observed_quote == Money.parse("3.17", USDT)
    assert p.net_observed_quote == Money.parse("3.16895", USDT)
    assert p.third_asset_fees == (Money.parse(".00001", Asset("BNB")),)
    assert p.outcome is SellTerminalOutcome.PARTIAL_EXECUTION
    plan = SellEconomicSettlementPlan(assessment, root)
    assert plan.consumption_decision is D.SETTLEMENT_IDENTITY
    assert plan.potential_effects == p
    assert plan.eligible_quote_credit is None
    assert plan.operational_credit is None
    assert plan.effects_applied is False
    assert SellEconomicBlocker.THIRD_ASSET_COST_UNVALUED in plan.settlement_blockers
    assert root.inventory_book is before
    capital = root.inventory_book.funded_buy_book
    assert (
        capital.initial_quote_capital
        == capital.spent_quote + capital.reserved_quote + capital.available_quote
    )
    assert capital.available_quote == Money.parse("16.8", USDT)


@pytest.mark.parametrize(
    ("status", "qty"),
    [(OrderStatus.FILLED, ".031"), (OrderStatus.CANCELED, ".015"), (OrderStatus.EXPIRED, "0")],
)
@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB"), Asset("ETH")])
@pytest.mark.parametrize("fee", ["0", ".00008"])
def test_terminal_asset_matrix(status: OrderStatus, qty: str, asset: Asset, fee: str) -> None:
    assessment = economic_sources(status, qty, fee=fee, asset=asset)
    assert_conservation(assessment)
    p = assessment.projection
    assert p is not None
    if qty == "0":
        assert p.outcome is SellTerminalOutcome.NO_EXECUTION
        assert p.projected_base_consumption.is_zero
        assert p.gross_observed_quote.amount == 0
        assert p.net_observed_quote.amount == 0
        assert p.fees_by_asset == ()
        assert p.projected_reserved_remainder == p.authorized_sell_qty + p.base_fee_hold
        assert p.projected_origin_remaining == p.origin_net_base_qty
    elif status is OrderStatus.FILLED:
        assert p.outcome is SellTerminalOutcome.FULL_EXECUTION
        assert p.projected_origin_remaining.value > 0
    else:
        assert p.outcome is SellTerminalOutcome.PARTIAL_EXECUTION
        assert not p.unexecuted_qty.is_zero


@pytest.mark.parametrize("missing", ["ledger", "report", "collection"])
def test_missing_never_becomes_zero(missing: str) -> None:
    original = economic_sources()
    changes: dict[str, Any] = {missing: None}
    assessment = SellEconomicAssessment(replace(original.reconciliation, **changes))
    assert assessment.projection is None
    assert SellEconomicBlocker.EVIDENCE_NOT_RECONCILED in assessment.settlement_blockers
    plan = SellEconomicSettlementPlan(assessment, original.reconciliation.book)
    assert plan.consumption_decision is D.PENDING_EVIDENCE
    assert plan.potential_effects is None
    with pytest.raises(DomainError):
        SellEconomicProjection(assessment.reconciliation)


@pytest.mark.parametrize(
    "status", [None, OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, OrderStatus.REJECTED]
)
def test_unresolved_status_has_no_financial_projection(status: OrderStatus | None) -> None:
    a = economic_sources(status, ".015")
    assert a.projection is None


@pytest.mark.parametrize("field", ["fee", "observed_quote", "executed_qty"])
def test_missing_trade_field_remains_visible(field: str) -> None:
    a = economic_sources()
    collection = a.reconciliation.collection
    assert collection is not None
    page = collection.pages[0]
    changes: dict[str, Any] = {field: None}
    changed = replace(page, trades=(replace(page.trades[0], **changes),))
    a = SellEconomicAssessment(
        replace(
            a.reconciliation, collection=replace(collection, pages=(changed, *collection.pages[1:]))
        )
    )
    assert a.projection is None
    assert a.reconciliation.findings


@pytest.mark.parametrize("field", ["venue_ref", "account_ref", "environment_ref", "order_ref"])
def test_foreign_identity_never_uses_equal_amounts(field: str) -> None:
    a = economic_sources()
    report = a.reconciliation.report
    assert report is not None
    changes: dict[str, Any] = {field: "foreign"}
    a = SellEconomicAssessment(
        replace(
            a.reconciliation, report=replace(report, identity=replace(report.identity, **changes))
        )
    )
    assert a.projection is None


def test_quote_conflict_not_replaced_by_limit() -> None:
    a = economic_sources()
    report = a.reconciliation.report
    assert report is not None
    a = SellEconomicAssessment(
        replace(
            a.reconciliation, report=replace(report, cumulative_quote=Money.parse("3.162", USDT))
        )
    )
    assert a.projection is None


@pytest.mark.parametrize(
    ("qty", "fee", "asset"), [(".032", "0", BTC), (".031", ".000101", BTC), (".031", "4", USDT)]
)
def test_over_authorization_preserves_observation_and_root(
    qty: str, fee: str, asset: Asset
) -> None:
    a = economic_sources()
    original = a.reconciliation.ledger
    assert original is not None
    observation = fill(
        original,
        executed_qty=Qty.parse(qty),
        observed_quote=Money(Decimal(qty) * Decimal(105), USDT),
        fee=Money.parse(fee, asset),
    )
    from gridbot.application.sell_fills import SellFillError

    before = a.reconciliation.book.inventory_book
    with pytest.raises(SellFillError) as exc:
        record_sell_fill(SellFillLedger(original.context), observation)
    assert exc.value.observation is observation
    assert a.reconciliation.book.inventory_book is before


def test_duplicate_claims_and_new_revision_do_not_offer_second_credit() -> None:
    a = mandatory_example()
    r = a.reconciliation
    assert r.report is not None
    identity = r.report.identity
    scope = OperationalScope(
        identity.venue_ref, identity.account_ref, identity.environment_ref, identity.symbol
    )
    old = replace(r, journal_reference=SellJournalReference(scope, 1, (1,)))
    new = replace(r, journal_reference=SellJournalReference(scope, 2, (1, 2)))
    current = SellEconomicAssessment(new)
    plan = SellEconomicSettlementPlan(
        current, r.book, new.journal_reference, (SellEconomicAssessment(old), a, a)
    )
    assert plan.consumption_decision is D.SETTLEMENT_ALREADY_APPLIED
    assert plan.potential_effects is None
    stale = SellEconomicSettlementPlan(SellEconomicAssessment(old), r.book, new.journal_reference)
    assert stale.consumption_decision is D.STALE_FINANCIAL_ROOT
    assert stale.potential_effects is None


def test_same_order_with_conflicting_economics_blocks_even_after_matching_claim() -> None:
    a = economic_sources(fee=".01")
    conflicting = economic_sources(fee=".02")
    plan = SellEconomicSettlementPlan(a, a.reconciliation.book, prior_claims=(a, conflicting))
    assert plan.consumption_decision is D.SETTLEMENT_CONFLICT
    assert plan.potential_effects is None


def test_unresolved_previous_claim_is_not_proof_of_non_consumption() -> None:
    a = economic_sources()
    unresolved = SellEconomicAssessment(replace(a.reconciliation, report=None))
    plan = SellEconomicSettlementPlan(a, a.reconciliation.book, prior_claims=(unresolved,))
    assert plan.consumption_decision is D.PENDING_EVIDENCE
    assert plan.potential_effects is None


def test_stale_root_and_unrelated_cell() -> None:
    a = mandatory_example()
    root = a.reconciliation.book
    lost = GridOperationalBook(root.inventory_book)
    assert SellEconomicSettlementPlan(a, lost).consumption_decision is D.STALE_FINANCIAL_ROOT
    assert (
        SellEconomicSettlementPlan(a, prepare_other_buy(root)).consumption_decision
        is D.SETTLEMENT_IDENTITY
    )


@pytest.mark.parametrize("target", ["buy", "sell", "report", "reserve"])
def test_nested_tamper_is_revalidated(target: str) -> None:
    a = mandatory_example()
    p = a.projection
    assert p is not None
    ledger = a.reconciliation.ledger
    report = a.reconciliation.report
    assert ledger is not None
    assert report is not None
    if target == "buy":
        object.__setattr__(
            ledger.context.intent.finalized_buy.ledger.fills[0], "fee", Money.parse(".003", BTC)
        )
    elif target == "sell":
        object.__setattr__(ledger.fills[0], "fee", Money.parse(".001", BTC))
    elif target == "reserve":
        object.__setattr__(ledger.context.intent.reservation, "base_fee_hold", Qty.zero())
    else:
        object.__setattr__(report, "cumulative_quote", Money.parse("0", USDT))
    with pytest.raises(DomainError):
        _ = p.net_observed_quote
    if target == "report":
        assert SellEconomicAssessment(a.reconciliation).projection is None
    else:
        with pytest.raises(DomainError):
            SellEconomicAssessment(a.reconciliation)
    assert (
        a.reconciliation.book.inventory_book.funded_buy_book.initial_quote_capital
        == Money.parse("20", USDT)
    )


def test_direct_construction_types_immutability_and_ambient_precision() -> None:
    a = mandatory_example()
    with pytest.raises((DomainError, TypeError)):
        SellEconomicAssessment(cast(Any, None))
    with pytest.raises((DomainError, TypeError)):
        SellEconomicSettlementPlan(a, cast(Any, None))
    with pytest.raises((DomainError, TypeError)):
        SellEconomicSettlementPlan(a, a.reconciliation.book, prior_claims=cast(Any, [a]))
    with pytest.raises(FrozenInstanceError):
        cast(Any, a).reconciliation = None
    with localcontext() as context:
        context.prec = 2
        assert_conservation(a)


def test_forged_quantity_and_wrong_cycle_refused() -> None:
    a = economic_sources()
    ledger = a.reconciliation.ledger
    assert ledger is not None
    invalid = forged(ledger, fills=(forged(ledger.fills[0], executed_qty=Qty.parse(".1")),))
    with pytest.raises(DomainError):
        SellEconomicAssessment(replace(a.reconciliation, ledger=invalid))
    wrong = SellEconomicAssessment(
        replace(a.reconciliation, cycle_ref=replace(a.reconciliation.cycle_ref, cell_index=1))
    )
    assert wrong.projection is None


def test_duplicate_fill_does_not_multiply_proceeds() -> None:
    a = mandatory_example()
    ledger = a.reconciliation.ledger
    assert ledger is not None
    assert record_sell_fill(ledger, ledger.fills[0]) is ledger
    same = assessment_from_ledger(a, ledger, OrderStatus.CANCELED)
    assert same.projection == a.projection
    assert_conservation(same)


@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB")])
def test_multiple_buy_fills_cost_and_fees_stay_unallocated(asset: Asset) -> None:
    a = multi_buy_sources(10, asset)
    assert_conservation(a)
    p = a.projection
    assert p is not None
    assert len(p.origin_buy.ledger.fills) == 10
    expected = "3.200032" if asset == USDT else "3.2"
    assert p.identified_origin_quote_debit == Money.parse(expected, USDT)
    if asset == Asset("BNB"):
        assert len(p.unvalued_third_asset_fees) == 1
        assert SellEconomicBlocker.THIRD_ASSET_COST_UNVALUED in a.settlement_blockers
    assert p.allocated_cost is None


def test_float_nonfinite_and_inexact_source_rejected() -> None:
    a = economic_sources()
    ledger = a.reconciliation.ledger
    assert ledger is not None
    for value in (1.0, Decimal("NaN"), Decimal("Infinity")):
        invalid = forged(ledger.fills[0], executed_qty=forged(Qty.zero(), value=value))
        with pytest.raises((DomainError, TypeError)):
            SellEconomicAssessment(
                replace(a.reconciliation, ledger=forged(ledger, fills=(invalid,)))
            )
    with pytest.raises(DomainError):
        economic_sources(fee=".00000000000000000000000000000000000000001")


def test_terminal_status_conflict_and_external_charge_not_discarded() -> None:
    a = economic_sources(OrderStatus.CANCELED, ".015")
    different_status = economic_sources(OrderStatus.EXPIRED, ".015")
    plan = SellEconomicSettlementPlan(a, a.reconciliation.book, prior_claims=(different_status,))
    assert plan.consumption_decision is D.SETTLEMENT_CONFLICT
    no_fill = economic_sources(OrderStatus.CANCELED, "0")
    report = no_fill.reconciliation.report
    assert report is not None
    changed = replace(report, cumulative_quote=Money.parse(".01", USDT))
    no_fill = replace(no_fill, reconciliation=replace(no_fill.reconciliation, report=changed))
    assert no_fill.projection is None
    assert no_fill.reconciliation.findings


def test_late_incomplete_offline_source_blocks_economic_plan_after_duplicate() -> None:
    from tests.application.test_offline_sell_evidence import edited, wire_scenario

    source = wire_scenario()
    missing = edited(source, "page-0", "commission", None, remove=True).tape.observations[1]
    late = replace(missing, source_ref="late", collection_ref="late-capture")
    tape = source.tape.capture(late).capture(source.tape.observations[1])
    reconciliation = replace(source, tape=tape).terminal_reconciliation
    a = SellEconomicAssessment(reconciliation)
    assert a.projection is None
    assert SellEconomicSettlementPlan(a, source.book).potential_effects is None
    assert len(tape.observations) == 5


def test_missing_optional_terminal_locator_remains_missing() -> None:
    a = economic_sources()
    report = a.reconciliation.report
    assert report is not None
    a = replace(
        a, reconciliation=replace(a.reconciliation, report=replace(report, source_ref=None))
    )
    p = a.projection
    assert p is not None
    assert p.terminal_source_ref is None
    assert SellEconomicBlocker.TERMINAL_SOURCE_REFERENCE_MISSING in a.settlement_blockers
    assert p.net_observed_quote == Money.parse("3.245", USDT)


def test_same_origin_bound_to_another_external_order_conflicts() -> None:
    a = economic_sources()
    r = a.reconciliation
    assert r.report is not None
    assert r.collection is not None
    c = r.collection
    assert c.query is not None
    identity = replace(r.report.identity, order_ref="999")
    report = replace(r.report, identity=identity)
    binding = r.book.external_sell_bindings[0]
    root = replace(r.book, external_sell_bindings=(replace(binding, identity=identity),))
    pages = tuple(
        replace(
            page,
            query_identity=identity,
            trades=tuple(replace(trade, identity=identity) for trade in page.trades),
        )
        for page in c.pages
    )
    collection = replace(
        c,
        identity=identity,
        query=replace(c.query, identity=identity),
        pages=pages,
        order_before=report,
        order_after=report,
    )
    alternative = SellEconomicAssessment(
        replace(r, book=root, report=report, collection=collection)
    )
    assert alternative.projection is not None
    plan = SellEconomicSettlementPlan(a, r.book, prior_claims=(alternative,))
    assert plan.consumption_decision is D.SETTLEMENT_CONFLICT
    assert plan.potential_effects is None
