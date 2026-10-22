"""A17.5: resultados distintos, matemática externa e ausência de efeitos."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from typing import Any, cast

import pytest

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.operational_persistence import OperationalScope
from gridbot.application.sell_evidence import SellEvidenceError
from gridbot.application.sell_reconciliation import (
    SellFindingKind,
    SellReconciliationCode,
    SellReconciliationFinding,
)
from gridbot.application.sell_terminal import (
    ReconciledSellEvidence,
    SellJournalReference,
    SellNoFillOutcome,
    SellProvenanceLimit,
    SellStructuralState,
    SellTerminalOutcome,
    reconcile_sell_terminal,
    validate_terminal_reconciliation_against_current,
)
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus
from tests.application.terminal_fixtures import terminal_sources
from tests.application.test_operational_grid import prepare_other_buy, prepared_root, ref
from tests.application.test_sell_intents import forged

S = SellStructuralState
Outcome = SellTerminalOutcome


@pytest.mark.parametrize(
    ("status", "qty", "expected_state", "outcome"),
    [
        (OrderStatus.FILLED, ".031", S.STRUCTURALLY_RECONCILED, Outcome.FULL_EXECUTION),
        (OrderStatus.FILLED, ".01", S.CONTRADICTORY_EVIDENCE, None),
        (OrderStatus.FILLED, "0", S.CONTRADICTORY_EVIDENCE, None),
        *[
            (status, ".01", S.STRUCTURALLY_RECONCILED, Outcome.PARTIAL_EXECUTION)
            for status in (OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.EXPIRED_IN_MATCH)
        ],
        *[
            (status, "0", S.STRUCTURALLY_RECONCILED, Outcome.NO_EXECUTION)
            for status in (
                OrderStatus.CANCELED,
                OrderStatus.EXPIRED,
                OrderStatus.EXPIRED_IN_MATCH,
                OrderStatus.REJECTED,
            )
        ],
        *[
            (status, ".031", S.PENDING_EVIDENCE, None)
            for status in (OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.EXPIRED_IN_MATCH)
        ],
        (OrderStatus.REJECTED, ".01", S.CONTRADICTORY_EVIDENCE, None),
        *[
            (status, ".01", S.PENDING_EVIDENCE, None)
            for status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, None)
        ],
    ],
)
def test_terminal_matrix(
    status: OrderStatus | None,
    qty: str,
    expected_state: SellStructuralState,
    outcome: SellTerminalOutcome | None,
) -> None:
    root, ledger, report, collection = terminal_sources(status, qty)
    before = root.inventory_book
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    assert result.state is expected_state
    assert result.outcome is outcome
    assert result.observed_status is status
    assert result.provenance_limit is SellProvenanceLimit.PROVIDED_EVIDENCE_EXTERNALLY_UNVERIFIED
    assert root.inventory_book is before
    if outcome is Outcome.NO_EXECUTION:
        assert type(result.evidence) is SellNoFillOutcome
        with pytest.raises(SellEvidenceError):
            ReconciledSellEvidence(result)
    elif outcome is not None:
        assert type(result.evidence) is ReconciledSellEvidence
        with pytest.raises(SellEvidenceError):
            SellNoFillOutcome(result)
    else:
        assert result.evidence is None
        with pytest.raises(SellEvidenceError):
            ReconciledSellEvidence(result)


@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB"), Asset("ETH")])
def test_fraction_oracle_and_third_asset_preservation(asset: Asset) -> None:
    root, ledger, report, collection = terminal_sources(fee=".00008", asset=asset)
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    evidence = result.evidence
    assert isinstance(evidence, ReconciledSellEvidence)
    fills = ledger.fills
    x = sum((Fraction(f.executed_qty.value) for f in fills), Fraction())
    b = sum((Fraction(f.fee.amount) for f in fills if f.fee.asset == BTC), Fraction())
    y = sum((Fraction(f.observed_quote.amount) for f in fills), Fraction())
    u = sum((Fraction(f.fee.amount) for f in fills if f.fee.asset == USDT), Fraction())
    origin = ledger.context.intent.finalized_buy.ledger.fills
    net = sum(
        (
            Fraction(f.executed_qty.value) - (Fraction(f.fee.amount) if f.fee.asset == BTC else 0)
            for f in origin
        ),
        Fraction(),
    )
    q = Fraction(ledger.context.requested_qty.value)
    h = Fraction(ledger.context.intent.base_fee_hold.value)
    assert x <= q
    assert b <= h
    assert x + b <= q + h <= net
    assert Fraction(evidence.executed_qty.value) == x
    assert Fraction(evidence.base_fee_qty.value) == b
    assert Fraction(evidence.net_observed_quote.amount) == y - u
    assert evidence.fees_by_asset == (Money.parse(".00008", asset),)
    assert evidence.third_asset_fees == (() if asset in (BTC, USDT) else evidence.fees_by_asset)
    assert evidence.binding == root.external_sell_bindings[0]
    assert evidence.outcome is Outcome.FULL_EXECUTION
    assert evidence.unexecuted_qty.is_zero
    assert evidence.gross_quote == ledger.gross_observed_quote
    assert evidence.quote_fee == ledger.quote_fee


@pytest.mark.parametrize("missing", ["report", "collection", "ledger"])
def test_missing_sources_never_conclude(missing: str) -> None:
    root, ledger, report, collection = terminal_sources()
    result = reconcile_sell_terminal(
        root,
        ref(),
        None if missing == "ledger" else ledger,
        None if missing == "report" else report,
        None if missing == "collection" else collection,
    )
    assert result.state is S.PENDING_EVIDENCE
    assert result.evidence is None


@pytest.mark.parametrize(
    "field",
    [
        "original_qty",
        "cumulative_executed_qty",
        "cumulative_quote",
        "limit_price",
        "collection_ref",
    ],
)
def test_missing_report_field_cannot_be_zero_or_default(field: str) -> None:
    root, ledger, report, collection = terminal_sources()
    changes: dict[str, Any] = {field: None}
    report = replace(report, **changes)
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    assert result.state is S.PENDING_EVIDENCE
    assert result.evidence is None


@pytest.mark.parametrize(
    "field", ["account_ref", "environment_ref", "order_ref", "venue_ref", "client_order_ref"]
)
def test_foreign_identity_is_contradictory(field: str) -> None:
    root, ledger, report, collection = terminal_sources()
    changes: dict[str, Any] = {field: "other"}
    report = replace(report, identity=replace(report.identity, **changes))
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    assert result.state is S.CONTRADICTORY_EVIDENCE
    assert result.evidence is None


@pytest.mark.parametrize("quote", ["0", "3.254", "3.256"])
def test_report_quote_divergence_is_visible(quote: str) -> None:
    root, ledger, report, collection = terminal_sources()
    result = reconcile_sell_terminal(
        root, ref(), ledger, replace(report, cumulative_quote=Money.parse(quote, USDT)), collection
    )
    assert result.state is S.CONTRADICTORY_EVIDENCE
    assert result.evidence is None


def test_uncertain_attempt_without_ledger_remains_pending() -> None:
    from gridbot.application.operational_grid import mark_sell_submission_uncertain

    root = mark_sell_submission_uncertain(prepared_root(), ref())
    result = reconcile_sell_terminal(root, ref(), None, None, None)
    assert result.state is S.PENDING_EVIDENCE
    assert result.outcome is None
    assert result.assessment is None


def test_unrelated_cell_keeps_economic_conclusion_valid() -> None:
    root, ledger, report, collection = terminal_sources()
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    current = prepare_other_buy(root)
    validate_terminal_reconciliation_against_current(result, current)
    updated = replace(result, book=current)
    assert updated.outcome == result.outcome
    assert updated.evidence is not None
    assert updated.assessment is not None


def test_stale_root_cannot_authorize_old_result() -> None:
    root, ledger, report, collection = terminal_sources()
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    lost = GridOperationalBook(root.inventory_book)
    with pytest.raises(SellEvidenceError):
        validate_terminal_reconciliation_against_current(result, lost)
    wrong_cycle = replace(result, cycle_ref=replace(ref(), cycle_seq=1))
    assert wrong_cycle.state is S.CONTRADICTORY_EVIDENCE


def test_direct_build_and_nested_tamper_are_revalidated() -> None:
    root, ledger, report, collection = terminal_sources()
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    evidence = result.evidence
    assert isinstance(evidence, ReconciledSellEvidence)
    with pytest.raises(FrozenInstanceError):
        cast(Any, evidence).reconciliation = result
    object.__setattr__(report, "cumulative_quote", Money.parse("1", USDT))
    with pytest.raises(SellEvidenceError):
        _ = evidence.executed_qty


@pytest.mark.parametrize("field", ["fee", "observed_quote", "executed_qty"])
def test_missing_trade_field_blocks_closure(field: str) -> None:
    root, ledger, report, collection = terminal_sources()
    first = collection.pages[0]
    changes: dict[str, Any] = {field: None}
    trade = replace(first.trades[0], **changes)
    collection = replace(collection, pages=(replace(first, trades=(trade,)), *collection.pages[1:]))
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    assert result.evidence is None


def test_adulterated_ledger_cannot_release_or_complete() -> None:
    root, ledger, report, collection = terminal_sources()
    invalid = forged(ledger.fills[0], fee=Money.parse(".001", BTC))
    hacked = forged(ledger, fills=(invalid,))
    with pytest.raises(SellEvidenceError):
        reconcile_sell_terminal(root, ref(), hacked, report, collection)
    assert root.inventory_book.reservations


@pytest.mark.parametrize(
    ("revision", "sequences"),
    [(True, (1,)), (-1, (1,)), (2**63, (1,)), (1, (0,)), (1, (2, 1)), (1, (1, 1)), (1, (True,))],
)
def test_invalid_journal_reference_direct_construction(
    revision: int, sequences: tuple[int, ...]
) -> None:
    root, _ledger, report, _collection = terminal_sources()
    identity = report.identity
    scope = OperationalScope(
        identity.venue_ref,
        identity.account_ref,
        identity.environment_ref,
        root.grid_state.plan.spec.symbol,
    )
    with pytest.raises(SellEvidenceError):
        SellJournalReference(scope, revision, sequences)


def test_journal_reference_is_required_and_foreign_scope_rejected() -> None:
    root, ledger, report, collection = terminal_sources()
    identity = report.identity
    scope = OperationalScope(
        identity.venue_ref, identity.account_ref, identity.environment_ref, identity.symbol
    )
    reference = SellJournalReference(scope, 1, (1, 2))
    result = reconcile_sell_terminal(
        root, ref(), ledger, report, collection, journal_reference=reference
    )
    with pytest.raises(SellEvidenceError):
        validate_terminal_reconciliation_against_current(result, root)
    with pytest.raises(SellEvidenceError):
        replace(
            result, journal_reference=replace(reference, scope=replace(scope, account_ref="other"))
        )


def test_provenance_residual_never_hides_an_explicit_contradiction() -> None:
    root, ledger, report, collection = terminal_sources()
    finding = SellReconciliationFinding(
        SellReconciliationCode.EXTERNAL_IDENTITY_UNAUTHENTICATED,
        SellFindingKind.CONTRADICTORY,
        "provided-contradiction",
    )
    result = reconcile_sell_terminal(
        root, ref(), ledger, report, collection, source_findings=(finding,)
    )
    assert result.state is S.CONTRADICTORY_EVIDENCE
    assert result.evidence is None
