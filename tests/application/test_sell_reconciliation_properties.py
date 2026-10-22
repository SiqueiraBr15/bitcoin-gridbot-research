"""Hypothesis A17 limitado; apenas evidências sintéticas, sem adapter/exchange."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from gridbot.application import (
    ObservedSellOrderReport,
    SellEvidenceError,
    SellExecutionRef,
    SellFillError,
    SellFillLedger,
    SellFindingKind,
    SellReconciliationState,
    SellTradePage,
    assess_sell_finalization,
    bind_operational_buy_execution,
    bind_sell_execution,
    build_sell_fill_ledger,
    mark_sell_submission_uncertain,
    record_sell_fill,
    settle_operational_buy,
)
from gridbot.domain import USDT, Asset, Money, OrderStatus
from tests.application.test_operational_grid import (
    buy_context,
    context,
    prepare_other_buy,
    prepared_root,
    ref,
)
from tests.application.test_sell_fills import fill
from tests.application.test_sell_intents import fingerprint, finish, p, q
from tests.application.test_sell_reconciliation import (
    C,
    assess,
    codes,
    collection,
    identity,
    report,
    scenario,
    trade,
)

PS = settings(max_examples=100, deadline=None, derandomize=True)


@PS
@given(st.integers(1, 31000), st.integers(105, 1000), st.integers(0, 100))
def test_fraction_oracle_conservation_and_no_effects(units: int, price: int, fee: int) -> None:
    root, empty = scenario(None)
    quantity = Decimal(units).scaleb(-6)
    gross = Fraction(units, 1_000_000) * price
    quote = Decimal(gross.numerator) / Decimal(gross.denominator)
    f = fill(
        empty,
        executed_qty=q(str(quantity)),
        execution_price=p(price),
        observed_quote=Money(quote, USDT),
        fee=Money(Decimal(fee).scaleb(-6), USDT),
    )
    ledger = record_sell_fill(empty, f)
    before = fingerprint(root.inventory_book)
    a = assess(root, ledger, report=report(ledger, status=OrderStatus.CANCELED))
    assert Fraction(ledger.gross_observed_quote.amount) == gross
    assert Fraction(ledger.net_observed_quote.amount) == gross - Fraction(fee, 1_000_000)
    assert Fraction(ledger.gross_executed_qty.value) <= Fraction(31, 1000)
    assert a.state is SellReconciliationState.PENDING_EVIDENCE
    assert before == fingerprint(root.inventory_book)


@PS
@given(
    st.sampled_from([OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, None]), st.integers(1, 31000)
)
def test_nonterminal_and_unknown_never_authenticate(status: OrderStatus | None, units: int) -> None:
    root, ledger = scenario(str(Decimal(units).scaleb(-6)))
    a = assess(root, ledger, report=report(ledger, status=status))
    assert C.FULL_TERMINAL_EXECUTION not in codes(a)
    assert C.PARTIAL_TERMINAL_EXECUTION not in codes(a)
    assert C.ORDER_TERMINAL_NO_FILL not in codes(a)
    assert C.EXTERNAL_COMPLETENESS_UNCONFIRMED in codes(a)


@PS
@given(st.text(alphabet="abcdef0123456789", min_size=1, max_size=30))
def test_different_order_cannot_be_hidden_by_equal_numbers(suffix: str) -> None:
    root, ledger = scenario()
    r = report(ledger, identity=identity(ledger, order_ref="other-" + suffix))
    a = assess_sell_finalization(root, ledger, r, collection(ledger))
    assert C.ORDER_IDENTITY_MISMATCH in codes(a)
    assert a.state is SellReconciliationState.CONTRADICTORY_EVIDENCE


@PS
@given(st.integers(1, 100000))
def test_altering_quote_cannot_be_tolerated(units: int) -> None:
    root, ledger = scenario()
    r = report(
        ledger,
        cumulative_quote=Money.parse(str(Decimal("3.255") + Decimal(units).scaleb(-12)), USDT),
    )
    a = assess(root, ledger, report=r)
    assert C.CUMULATIVE_QUOTE_MISMATCH in codes(a)
    assert a.state is SellReconciliationState.CONTRADICTORY_EVIDENCE


@PS
@given(st.sampled_from([USDT, Asset("BTC"), Asset("BNB"), Asset("XYZ")]), st.integers(1, 100))
def test_changed_fee_keeps_asset_and_amount(asset: Asset, units: int) -> None:
    root, ledger = scenario()
    fee = Money(Decimal(units).scaleb(-6), asset)
    t = trade(ledger, fee=fee)
    col = collection(ledger, pages=(SellTradePage("p", None, None, (t,)),))
    a = assess(root, ledger, collection=col)
    assert C.FEE_MISMATCH in codes(a)
    assert any(f.code is C.FEE_MISMATCH and f.observed == fee for f in a.findings)


@PS
@given(st.permutations((0, 1, 2)), st.integers(1, 100))
def test_permutation_and_duplicate_do_not_create_execution(order: list[int], fee: int) -> None:
    root, empty = scenario(None)
    amounts = ("0.01", "0.007", "0.014")
    assets = (USDT, Asset("BTC"), Asset("BNB"))
    fills = tuple(
        fill(
            empty,
            fill_ref=f"t{i}",
            executed_qty=q(amounts[i]),
            observed_quote=Money(p(105).notional(q(amounts[i])), USDT),
            fee=Money(Decimal(fee).scaleb(-6), assets[i]),
        )
        for i in range(3)
    )
    ledger = empty
    for i in order:
        ledger = record_sell_fill(ledger, fills[i])
        assert record_sell_fill(ledger, fills[i]) is ledger
    assert ledger == SellFillLedger(empty.context, fills)
    a = assess(root, ledger)
    r = report(ledger)
    col = collection(
        ledger, pages=(SellTradePage("p", None, None, tuple(trade(ledger, i) for i in order)),)
    )
    b = assess_sell_finalization(root, ledger, r, col)
    assert a.findings == b.findings
    assert Fraction(ledger.gross_executed_qty.value) == Fraction(31, 1000)


@PS
@given(st.integers(1, 24), st.integers(0, 99))
def test_independent_buy_does_not_change_sell_binding_or_holds(units: int, fee: int) -> None:
    root, ledger = scenario()
    current = prepare_other_buy(root)
    current = bind_operational_buy_execution(current, ref(1), buy_context(current))
    current = settle_operational_buy(
        current,
        finish(
            current.inventory_book.funded_buy_book,
            1,
            str(Decimal(units).scaleb(-3)),
            str(Decimal(fee).scaleb(-6)),
        ),
    )
    a = assess(current, ledger)
    assert C.STALE_OPERATIONAL_BOOK not in codes(a)
    assert current.inventory_book.reservations is root.inventory_book.reservations
    assert current.sell_attempts is root.sell_attempts


@PS
@given(st.integers(1, 100000))
def test_error_is_pure_and_assessment_deterministic(units: int) -> None:
    root, ledger = scenario()
    before = hash(root), hash(ledger), fingerprint(root.inventory_book)
    r = report(ledger)
    col = collection(ledger)
    assert assess_sell_finalization(root, ledger, r, col) == (
        assess_sell_finalization(root, ledger, r, col)
    )
    bad = dataclasses.replace(
        r, identity=identity(ledger, execution_ref=SellExecutionRef(f"wrong-{units}"))
    )
    assert C.EXECUTION_REF_MISMATCH in codes(assess(root, ledger, report=bad))
    assert before == (hash(root), hash(ledger), fingerprint(root.inventory_book))


class SellEvidenceMachine(RuleBasedStateMachine):
    """Snapshots synthétiques; nenhuma evidência deste teste vem da Binance."""

    def __init__(self) -> None:
        super().__init__()
        self.root = prepared_root()
        self.bound = False
        self.uncertain = False
        self.empty = SellFillLedger(context(self.root))
        self.ledger = self.empty
        self.terminal: ObservedSellOrderReport | None = None
        self.other_updated = False
        self.original_holds = self.root.inventory_book.reservations

    @precondition(lambda self: not self.bound and not self.uncertain)
    @rule()
    def submission_uncertain(self) -> None:
        self.root = mark_sell_submission_uncertain(self.root, ref())
        self.uncertain = True

    @precondition(lambda self: not self.bound)
    @rule()
    def bind(self) -> None:
        self.root = bind_sell_execution(self.root, ref(), context(self.root))
        self.ledger = build_sell_fill_ledger(self.root, ref())
        self.bound = True

    @precondition(lambda self: self.bound and len(self.ledger.fills) < 3)
    @rule()
    def receive_synthetic_fill(self) -> None:
        index = len(self.ledger.fills)
        quantity = ("0.01", "0.007", "0.014")[index]
        self.ledger = record_sell_fill(
            self.ledger,
            fill(
                self.ledger,
                fill_ref=f"t{index}",
                executed_qty=q(quantity),
                observed_quote=Money(p(105).notional(q(quantity)), USDT),
            ),
        )

    @rule()
    def receive_terminal_before_or_after_last_fill(self) -> None:
        # Declara execução integral; fica contraditório até todos os fills estarem presentes.
        self.terminal = report(
            self.ledger,
            cumulative_executed_qty=q("0.031"),
            cumulative_quote=Money.parse("3.255", USDT),
        )

    @precondition(lambda self: bool(self.ledger.fills))
    @rule()
    def repeat_and_conflict(self) -> None:
        f = self.ledger.fills[0]
        assert record_sell_fill(self.ledger, f) is self.ledger
        with pytest.raises(SellFillError):
            record_sell_fill(self.ledger, dataclasses.replace(f, fee=Money.parse("0.001", USDT)))

    @precondition(lambda self: not self.other_updated)
    @rule()
    def independent_other_buy(self) -> None:
        current = prepare_other_buy(self.root)
        current = bind_operational_buy_execution(current, ref(1), buy_context(current))
        self.root = settle_operational_buy(
            current, finish(current.inventory_book.funded_buy_book, 1, "0.01", "0")
        )
        self.other_updated = True

    @rule()
    def reconcile_repeat_and_conflicting_context(self) -> None:
        a = assess_sell_finalization(self.root, self.ledger, self.terminal)
        assert a == dataclasses.replace(a)
        if not self.bound:
            assert C.STALE_OPERATIONAL_BOOK in codes(a)
        r = report(
            self.ledger, identity=identity(self.ledger, execution_ref=SellExecutionRef("alien"))
        )
        assert C.EXECUTION_REF_MISMATCH in codes(assess(self.root, self.ledger, report=r))
        with pytest.raises(SellEvidenceError):
            assess_sell_finalization(self.root, self.ledger, "bad")  # type: ignore[arg-type]

    @invariant()
    def no_transition_releases_or_credits_or_advances(self) -> None:
        assert self.root.inventory_book.reservations is self.original_holds
        assert self.root.grid_state.cells[0].cycle_seq == 0
        assert self.root.inventory_book.reserved_base_fee_qty == q("0.0001")
        assert self.ledger.gross_executed_qty <= q("0.031")
        a = assess_sell_finalization(self.root, self.ledger, self.terminal)
        assert a.state in (
            SellReconciliationState.PENDING_EVIDENCE,
            SellReconciliationState.CONTRADICTORY_EVIDENCE,
        )
        assert (
            not any(
                f.kind is SellFindingKind.INFORMATION and f.code is C.FULL_TERMINAL_EXECUTION
                for f in a.findings
            )
            if self.ledger.remaining_qty > q(0)
            else True
        )


TestSellEvidenceMachine = SellEvidenceMachine.TestCase
TestSellEvidenceMachine.settings = settings(
    max_examples=40, stateful_step_count=20, deadline=None, derandomize=True
)
