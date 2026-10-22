"""A17.1: propriedades limitadas e máquina de estados sem fonte externa."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from gridbot.application import (
    ExternalSellOrderBinding,
    ObservedSellOrderReport,
    SellBindingVerification,
    SellCollectionVerification,
    SellOrderBindingError,
    SellReconciliationState,
    assess_sell_finalization,
    bind_external_sell_order,
    bind_operational_buy_execution,
    bind_sell_execution,
    build_sell_fill_ledger,
    mark_sell_submission_uncertain,
    record_sell_fill,
    settle_operational_buy,
)
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus
from tests.application.test_external_sell_identity import binding, bound_cells, native_scenario
from tests.application.test_operational_grid import (
    buy_context,
    context,
    prepare_other_buy,
    prepared_root,
    ref,
)
from tests.application.test_sell_fills import fill
from tests.application.test_sell_intents import fingerprint, finish, q
from tests.application.test_sell_reconciliation import C, codes, report, scenario

PS = settings(max_examples=100, deadline=None, derandomize=True)
IDS = st.text(alphabet="abcdef0123456789", min_size=1, max_size=24)


@PS
@given(IDS)
def test_binding_idempotence_preserves_all_sources(order: str) -> None:
    root = bound_cells()
    b = binding(root, order_ref=order)
    result = bind_external_sell_order(root, ref(), b)
    assert bind_external_sell_order(result, ref(), replace(b)) is result
    assert result.inventory_book is root.inventory_book
    assert result.sell_attempts is root.sell_attempts


@PS
@given(IDS, st.sampled_from(["order_ref", "client_order_ref", "account_ref", "environment_ref"]))
def test_conflicts_are_pure(order: str, field: str) -> None:
    root = bound_cells()
    b = binding(root)
    root = bind_external_sell_order(root, ref(), b)
    changes: dict[str, Any] = {field: "other-" + order}
    bad = replace(b, identity=replace(b.identity, **changes))
    before = hash(root), fingerprint(root.inventory_book)
    with pytest.raises(SellOrderBindingError):
        bind_external_sell_order(root, ref(), bad)
    assert before == (hash(root), fingerprint(root.inventory_book))


@PS
@given(IDS, st.sampled_from(["account_ref", "environment_ref", "venue_ref"]))
def test_scoped_unicity_without_client_alias(order: str, field: str) -> None:
    root = bound_cells((0, 1))
    root = bind_external_sell_order(root, ref(), binding(root, order_ref=order))
    with pytest.raises(SellOrderBindingError):
        bind_external_sell_order(
            root, ref(1), binding(root, 1, order_ref=order, client_order_ref=None)
        )
    updated = bind_external_sell_order(
        root, ref(1), binding(root, 1, order_ref=order, **{field: "different"})
    )
    assert len(updated.external_sell_bindings) == 2


@PS
@given(IDS, st.sampled_from(["account_ref", "order_ref", "environment_ref", "client_order_ref"]))
def test_numbers_do_not_override_bound_external_identity(suffix: str, field: str) -> None:
    root, ledger, r, col = native_scenario()
    changes: dict[str, Any] = {field: "different-" + suffix}
    other = replace(r, identity=replace(r.identity, **changes))
    a = assess_sell_finalization(root, ledger, other, col)
    assert a.binding_verification is SellBindingVerification.CONFLICTING
    assert C.EXTERNAL_IDENTITY_UNAUTHENTICATED in codes(a)


@PS
@given(st.integers(1, 31000), st.integers(0, 100), st.sampled_from([BTC, USDT, Asset("BNB")]))
def test_fraction_financial_conservation_with_binding(units: int, fee: int, asset: Asset) -> None:
    root, empty = scenario(None)
    qty = Decimal(units).scaleb(-6)
    charge = Decimal(fee).scaleb(-6)
    ledger = record_sell_fill(
        empty,
        fill(
            empty,
            executed_qty=q(str(qty)),
            observed_quote=Money(qty * Decimal(105), USDT),
            fee=Money(charge, asset),
        ),
    )
    before = fingerprint(root.inventory_book)
    root = bind_external_sell_order(root, ref(), binding(root))
    a = assess_sell_finalization(root, ledger, report(ledger, status=OrderStatus.CANCELED))
    x, b = Fraction(units, 1_000_000), Fraction(fee, 1_000_000) if asset == BTC else Fraction(0)
    assert Fraction((ledger.gross_executed_qty + ledger.base_fee_qty).value) == x + b
    assert x + b <= Fraction(ledger.context.intent.total_base_commitment.value)
    assert Fraction(ledger.context.intent.total_base_commitment.value) <= Fraction(
        ledger.context.intent.confirmed_net_base_qty.value
    )
    u = Fraction(fee, 1_000_000) if asset == USDT else Fraction(0)
    assert Fraction(ledger.net_observed_quote.amount) == x * 105 - u
    assert a.state is SellReconciliationState.PENDING_EVIDENCE
    assert before == fingerprint(root.inventory_book)


@PS
@given(st.integers(1, 100), st.integers(1, 1000000))
def test_native_ids_need_no_gapless_sequence(gap: int, first: int) -> None:
    root, _ = scenario(None)
    empty = build_sell_fill_ledger(root, ref())
    ledger = record_sell_fill(
        empty,
        fill(
            empty,
            fill_ref=str(first),
            executed_qty=q("0.01"),
            observed_quote=Money.parse("1.05", USDT),
        ),
    )
    ledger = record_sell_fill(
        ledger,
        fill(
            ledger,
            fill_ref=str(first + gap),
            executed_qty=q("0.021"),
            observed_quote=Money.parse("2.205", USDT),
        ),
    )
    root = bind_external_sell_order(root, ref(), binding(root))
    _, _, _, col = native_scenario()
    r = report(ledger, collection_ref="capture-1")
    from tests.application.test_sell_reconciliation import trade

    page = replace(
        col.pages[0], trades=(trade(ledger, 1), trade(ledger, 0)), next_cursor=str(first + gap + 1)
    )
    end = replace(col.pages[1], cursor_from=page.next_cursor)
    a = assess_sell_finalization(
        root, ledger, r, replace(col, pages=(page, end), order_before=r, order_after=r)
    )
    assert a.collection_verification is SellCollectionVerification.STRUCTURALLY_COHERENT


@PS
@given(st.integers(103, 10000000))
def test_advancing_but_skipping_cursor_is_not_accepted(cursor: int) -> None:
    root, ledger, r, col = native_scenario()
    bad = replace(col.pages[0], next_cursor=str(cursor))
    a = assess_sell_finalization(
        root, ledger, r, replace(col, pages=(bad, replace(col.pages[1], cursor_from=str(cursor))))
    )
    assert C.CURSOR_ADVANCE_INVALID in codes(a)


@PS
@given(IDS)
def test_cohort_change_never_silently_relabels_evidence(suffix: str) -> None:
    root, ledger, r, col = native_scenario()
    before = hash(root), hash(ledger), hash(col)
    a = assess_sell_finalization(root, ledger, replace(r, collection_ref="old-" + suffix), col)
    assert C.CAPTURE_MISMATCH in codes(a)
    assert before == (hash(root), hash(ledger), hash(col))


@PS
@given(st.sampled_from([1, 10, 50, 100]), st.sampled_from(["duplicate", "missing", "late"]))
def test_collection_changes_exposed_without_financial_effect(n: int, mode: str) -> None:
    root, ledger, r, col = native_scenario(n)
    p = col.pages[0]
    if mode == "duplicate":
        changed = replace(col, pages=(p, p, *col.pages[1:]))
        expected = C.TRADE_ID_CONFLICT
    elif mode == "missing":
        changed = replace(col, pages=(replace(p, trades=p.trades[1:]), *col.pages[1:]))
        expected = C.FILL_SET_INCOMPLETE
    else:
        changed = replace(col, order_after=replace(r, cumulative_quote=Money.parse("999", USDT)))
        expected = C.COLLECTION_CHANGED
    before = fingerprint(root.inventory_book)
    assert expected in codes(assess_sell_finalization(root, ledger, r, changed))
    assert before == fingerprint(root.inventory_book)


@PS
@given(st.integers(1, 1000000))
def test_cycle_changes_cannot_reuse_binding(cycle: int) -> None:
    root = bound_cells()
    b = binding(root)
    bad = replace(b, identity=replace(b.identity, cycle_ref=replace(ref(), cycle_seq=cycle)))
    with pytest.raises(SellOrderBindingError):
        bind_external_sell_order(root, ref(), bad)


class ExternalIdentityMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.root = prepared_root()
        self.bound = False
        self.external: ExternalSellOrderBinding | None = None
        self.uncertain = False
        self.other = False
        self.ledger = build_sell_fill_ledger(bound_cells(), ref())
        self.terminal: ObservedSellOrderReport | None = None
        self.original_reservation = self.root.inventory_book.reservations[0]

    @precondition(lambda self: not self.bound and not self.uncertain)
    @rule()
    def uncertain_submission(self) -> None:
        self.root = mark_sell_submission_uncertain(self.root, ref())
        self.uncertain = True

    @precondition(lambda self: not self.bound)
    @rule()
    def bind_internal(self) -> None:
        self.root = bind_sell_execution(self.root, ref(), context(self.root))
        self.ledger = build_sell_fill_ledger(self.root, ref())
        self.bound = True

    @precondition(lambda self: self.bound and self.external is None)
    @rule()
    def bind_external(self) -> None:
        self.external = binding(self.root)
        self.root = bind_external_sell_order(self.root, ref(), self.external)

    @precondition(lambda self: self.external is not None)
    @rule()
    def replay_and_conflict(self) -> None:
        assert self.external is not None
        assert bind_external_sell_order(self.root, ref(), self.external) is self.root
        bad = replace(self.external, identity=replace(self.external.identity, order_ref="alien"))
        with pytest.raises(SellOrderBindingError):
            bind_external_sell_order(self.root, ref(), bad)

    @precondition(lambda self: self.bound and len(self.ledger.fills) < 3)
    @rule()
    def late_trade(self) -> None:
        idx = len(self.ledger.fills)
        qty = ("0.01", "0.007", "0.014")[idx]
        self.ledger = record_sell_fill(
            self.ledger,
            fill(
                self.ledger,
                fill_ref=str(100 + idx * 3),
                executed_qty=q(qty),
                observed_quote=Money(q(qty).value * Decimal(105), USDT),
            ),
        )

    @rule()
    def terminal_before_or_after_trade(self) -> None:
        self.terminal = report(
            self.ledger,
            cumulative_executed_qty=q("0.031"),
            cumulative_quote=Money.parse("3.255", USDT),
            collection_ref="capture",
        )

    @precondition(lambda self: not self.other)
    @rule()
    def other_cell_buy(self) -> None:
        root = prepare_other_buy(self.root)
        root = bind_operational_buy_execution(root, ref(1), buy_context(root))
        self.root = settle_operational_buy(
            root, finish(root.inventory_book.funded_buy_book, 1, "0.01", "0")
        )
        self.other = True

    @rule()
    def pages_reordered_dropped_and_duplicated(self) -> None:
        from tests.application.test_sell_reconciliation import collection

        col = collection(self.ledger, self.terminal)
        a = assess_sell_finalization(self.root, self.ledger, self.terminal, col)
        assert C.EXTERNAL_COMPLETENESS_UNCONFIRMED in codes(a)
        assert C.EXTERNAL_IDENTITY_UNAUTHENTICATED in codes(a)
        page = col.pages[0]
        repeated = replace(col, pages=(page, page))
        assert C.PAGE_SOURCE_CONFLICT in codes(
            assess_sell_finalization(self.root, self.ledger, self.terminal, repeated)
        )
        dropped = replace(col, pages=())
        assert C.PAGE_CHAIN_INCOMPLETE in codes(
            assess_sell_finalization(self.root, self.ledger, self.terminal, dropped)
        )

    @invariant()
    def preserve_inventory_and_never_authorize(self) -> None:
        assert self.root.inventory_book.reservation_for(ref()) is self.original_reservation
        assert self.root.external_binding_for(ref()) is self.external
        assert self.root.grid_state.cells[0].cycle_seq == 0
        assert self.ledger.gross_executed_qty <= q("0.031")
        a = assess_sell_finalization(self.root, self.ledger, self.terminal)
        assert a.state in (
            SellReconciliationState.PENDING_EVIDENCE,
            SellReconciliationState.CONTRADICTORY_EVIDENCE,
        )


TestExternalIdentityMachine = ExternalIdentityMachine.TestCase
TestExternalIdentityMachine.settings = settings(
    max_examples=40, stateful_step_count=20, deadline=None, derandomize=True
)
