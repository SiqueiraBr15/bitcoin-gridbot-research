"""Propriedades finitas com oráculos Fraction e contadores efetivos."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.application.sell_terminal import (
    ReconciledSellEvidence,
    SellNoFillOutcome,
    SellStructuralState,
    SellTerminalOutcome,
    reconcile_sell_terminal,
)
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus
from tests.application.terminal_fixtures import terminal_sources
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.application.test_operational_grid import ref

COUNTS: dict[str, int] = {}
FINITE = settings(max_examples=30, deadline=None, derandomize=True)


def count(name: str) -> None:
    COUNTS[name] = COUNTS.get(name, 0) + 1


@pytest.fixture(scope="module", autouse=True)
def actual_examples() -> Iterator[None]:
    yield
    sys.stdout.write("\nA17_5_PROPERTY_COUNTS=" + json.dumps(COUNTS, sort_keys=True) + "\n")


@FINITE
@given(st.integers(0, 31000), st.sampled_from([*OrderStatus, None]))
def test_terminal_quantity_policy(units: int, status: OrderStatus | None) -> None:
    count("terminal_examples")
    qty = Decimal(units).scaleb(-6)
    root, ledger, report, collection = terminal_sources(status, str(qty), fee="0")
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    assert root == result.book
    if status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, None):
        assert result.evidence is None
    elif status is OrderStatus.FILLED:
        if units == 31000:
            assert result.outcome is SellTerminalOutcome.FULL_EXECUTION
        else:
            assert result.state is SellStructuralState.CONTRADICTORY_EVIDENCE
    elif status is OrderStatus.REJECTED:
        assert (result.outcome is SellTerminalOutcome.NO_EXECUTION) == (units == 0)
    elif units == 0:
        assert isinstance(result.evidence, SellNoFillOutcome)
    elif units < 31000:
        assert result.outcome is SellTerminalOutcome.PARTIAL_EXECUTION
        evidence = result.evidence
        assert isinstance(evidence, ReconciledSellEvidence)
        assert Fraction(evidence.unexecuted_qty.value) == Fraction(31000 - units, 10**6)
    else:
        assert result.evidence is None


@FINITE
@given(
    st.integers(1, 31000),
    st.integers(0, 99),
    st.sampled_from([BTC, USDT, Asset("BNB"), Asset("ETH")]),
)
def test_financial_oracles_and_no_capital_credit(units: int, fee_units: int, asset: Asset) -> None:
    count("financial_examples")
    count("fee_" + asset.code)
    qty = Decimal(units).scaleb(-6)
    fee = Decimal(fee_units).scaleb(-6)
    root, ledger, report, collection = terminal_sources(
        OrderStatus.CANCELED if units < 31000 else OrderStatus.FILLED,
        str(qty),
        fee=str(fee),
        asset=asset,
    )
    capital = root.inventory_book.funded_buy_book
    holds = root.inventory_book.reservations
    result = reconcile_sell_terminal(root, ref(), ledger, report, collection)
    evidence = result.evidence
    assert isinstance(evidence, ReconciledSellEvidence)
    x = Fraction(units, 10**6)
    b = Fraction(fee_units, 10**6) if asset == BTC else Fraction()
    y = x * 105
    u = Fraction(fee_units, 10**6) if asset == USDT else Fraction()
    q = Fraction(31, 1000)
    h = Fraction(1, 10000)
    n = Fraction(31968, 10**6)
    assert x <= q
    assert b <= h
    assert x + b <= q + h <= n
    assert Fraction(evidence.executed_qty.value) == x
    assert Fraction(evidence.base_fee_qty.value) == b
    assert Fraction(evidence.gross_quote.amount) == y
    assert Fraction(evidence.net_observed_quote.amount) == y - u
    assert root.inventory_book.reservations == holds
    assert root.inventory_book.funded_buy_book == capital
    assert Fraction(capital.initial_quote_capital.amount) == (
        Fraction(capital.spent_quote.amount)
        + Fraction(capital.reserved_quote.amount)
        + Fraction(capital.available_quote.amount)
    )


@FINITE
@given(st.integers(1, 100), st.booleans())
def test_quote_or_fee_alteration_detected(delta_units: int, change_fee: bool) -> None:
    count("alteration_examples")
    root, ledger, report, collection = terminal_sources()
    delta = Decimal(delta_units).scaleb(-6)
    first = collection.pages[0]
    observed = first.trades[0]
    assert observed.observed_quote is not None
    assert observed.fee is not None
    trade = (
        replace(observed, fee=Money(observed.fee.amount + delta, USDT))
        if change_fee
        else replace(observed, observed_quote=Money(observed.observed_quote.amount + delta, USDT))
    )
    changed = replace(collection, pages=(replace(first, trades=(trade,)), *collection.pages[1:]))
    result = reconcile_sell_terminal(root, ref(), ledger, report, changed)
    assert result.evidence is None
    assert result.state is SellStructuralState.CONTRADICTORY_EVIDENCE


@settings(max_examples=12, deadline=None, derandomize=True)
@given(st.permutations((0, 1, 2)), st.integers(0, 2))
def test_replay_permutation_and_repeat_preserve_execution(
    permutation: list[int], repeated: int
) -> None:
    count("replay_examples")
    source = wire_scenario()
    tape = replace(
        source.tape, observations=tuple(source.tape.observations[i] for i in permutation)
    )
    tape = tape.capture(source.tape.observations[repeated])
    result = replace(source, tape=tape).terminal_reconciliation
    evidence = result.evidence
    assert isinstance(evidence, ReconciledSellEvidence)
    assert evidence.executed_qty.value == Decimal(".031")
    assert evidence.net_observed_quote.amount == Decimal("3.255")


@settings(max_examples=12, deadline=None, derandomize=True)
@given(st.lists(st.integers(0, 2), min_size=1, max_size=6))
def test_repeats_cannot_renew_a_selection_past_incomplete_evidence(indices: list[int]) -> None:
    count("late_duplicate_examples")
    source = wire_scenario()
    missing = edited(source, "page-0", "commission", None, remove=True).tape.observations[1]
    tape = source.tape.capture(
        replace(missing, source_ref="late-missing", collection_ref="capture-late")
    )
    for index in indices:
        tape = tape.capture(source.tape.observations[index])
    result = replace(source, tape=tape).terminal_reconciliation
    assert result.evidence is None
    assert result.state is SellStructuralState.PENDING_EVIDENCE
    assert result.book == source.book
