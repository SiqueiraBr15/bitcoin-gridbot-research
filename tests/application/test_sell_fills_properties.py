"""Oráculos A16 independentes: Fraction, permutação e máquina de estados limitada."""

from __future__ import annotations

import dataclasses
from decimal import Decimal, localcontext
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.application import (
    SellFillLedger,
    build_sell_fill_ledger,
    record_sell_fill,
    validate_sell_fill_ledger_against_book,
)
from gridbot.domain import BTC, USDT, Money, Price, Qty
from tests.application.test_operational_grid import ref
from tests.application.test_sell_fills import BNB, E, bound_root, expect, fill
from tests.application.test_sell_intents import fingerprint, q


def empty() -> SellFillLedger:
    return build_sell_fill_ledger(bound_root(), ref())


def exact(raw: Fraction) -> Decimal:
    # Independente do financial() de produção; todos os denominadores gerados
    # são potências de 2/5, conversão exata possível em 80 dígitos.
    with localcontext() as oracle:
        oracle.prec = 80
        return Decimal(raw.numerator) / Decimal(raw.denominator)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    st.lists(st.integers(1, 250), min_size=1, max_size=12),
    st.integers(102, 100000),
    st.permutations((BTC, USDT, BNB)),
)
def test_fraction_oracle_multicurrency(units: list[int], price: int, assets: list[object]) -> None:
    ledger = empty()
    base = Fraction(0)
    quote = Fraction(0)
    fees: dict[str, Fraction] = {"BTC": Fraction(0), "USDT": Fraction(0), "BNB": Fraction(0)}
    real_assets = (BTC, USDT, BNB)
    # st.permutations provides concrete Asset values; select by observed code.
    codes = tuple(str(a) for a in assets)
    for index, unit in enumerate(units):
        asset = next(a for a in real_assets if a.code == codes[index % 3])
        qty = Fraction(unit, 100000)
        observed = qty * price
        fee = Fraction(1, 1000000) if asset == BTC else Fraction(1, 100000)
        ledger = record_sell_fill(
            ledger,
            fill(
                ledger,
                fill_ref=f"trade-{index:02d}",
                executed_qty=Qty(exact(qty)),
                execution_price=Price.parse(price),
                observed_quote=Money(exact(observed), USDT),
                fee=Money(exact(fee), asset),
            ),
        )
        base += qty
        quote += observed
        fees[asset.code] += fee
    assert Fraction(ledger.gross_executed_qty.value) == base
    assert Fraction(ledger.remaining_qty.value) == Fraction(31, 1000) - base
    assert Fraction(ledger.gross_observed_quote.amount) == quote
    assert Fraction(ledger.gross_derived_quote.amount) == quote
    for asset in real_assets:
        assert Fraction(ledger.fee_for(asset).amount) == fees[asset.code]
    assert Fraction(ledger.net_observed_quote.amount) == quote - fees["USDT"]
    assert base + fees["BTC"] <= Fraction(31968, 1000000)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.permutations(tuple(range(6))), st.integers(1, 400), st.integers(102, 1000))
def test_arrival_permutations_canonical(order: list[int], units: int, price: int) -> None:
    ledger = empty()
    observed = tuple(
        fill(
            ledger,
            fill_ref=str(i),
            executed_qty=Qty(exact(Fraction(units, 100000))),
            execution_price=Price.parse(price),
            observed_quote=Money(exact(Fraction(units * price, 100000)), USDT),
        )
        for i in range(6)
    )
    reference = SellFillLedger(ledger.context, observed)
    for i in order:
        ledger = record_sell_fill(ledger, observed[i])
    assert ledger == reference
    assert Fraction(ledger.gross_observed_quote.amount) == Fraction(units * price * 6, 100000)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(1, 3100), st.text(alphabet="abcdef0123456789", min_size=1, max_size=128))
def test_duplicate_and_conflict(units: int, ident: str) -> None:
    ledger = empty()
    observed = fill(ledger, fill_ref=ident, executed_qty=Qty(exact(Fraction(units, 100000))))
    updated = record_sell_fill(ledger, observed)
    assert record_sell_fill(updated, dataclasses.replace(observed)) is updated
    conflict = dataclasses.replace(observed, fee=Money.parse("0.00001", BNB))
    expect(E.DUPLICATE_FILL_CONFLICT, lambda: record_sell_fill(updated, conflict))
    assert updated.fills == (observed,)
    assert ledger.fills == ()


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(1, 3100), st.integers(1, 1000))
def test_boundary_overfill_never_rounded(units: int, excess: int) -> None:
    ledger = empty()
    first = fill(ledger, executed_qty=Qty(exact(Fraction(units, 100000))))
    updated = record_sell_fill(ledger, first)
    second = fill(
        ledger,
        fill_ref="trade-2",
        executed_qty=Qty(exact(Fraction(3100 - units, 100000) + Fraction(excess, 10**25))),
    )
    expect(E.OVERFILL, lambda: record_sell_fill(updated, second))
    assert Fraction(updated.gross_executed_qty.value) == Fraction(units, 100000)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(2, 60), st.integers(1, 3000), st.integers(102, 100000))
def test_ambient_precision_exact(precision: int, units: int, price: int) -> None:
    ledger = empty()
    qty = Fraction(units, 100000)
    observed = fill(
        ledger,
        executed_qty=Qty(exact(qty)),
        execution_price=Price.parse(price),
        observed_quote=Money(exact(qty * price), USDT),
    )
    with localcontext() as ambient:
        ambient.prec = precision
        updated = record_sell_fill(ledger, observed)
        assert Fraction(updated.gross_derived_quote.amount) == qty * price
        assert Fraction(updated.remaining_qty.value) == Fraction(31, 1000) - qty


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(0, 10000000))
def test_observed_quote_never_replaced(quote_units: int) -> None:
    ledger = empty()
    raw = exact(Fraction(quote_units, 100000))
    updated = record_sell_fill(ledger, fill(ledger, observed_quote=Money(raw, USDT)))
    assert Fraction(updated.gross_observed_quote.amount) == Fraction(quote_units, 100000)
    assert updated.gross_derived_quote.amount == Decimal("1.05")
    assert bool(updated.quote_discrepancy_refs) == (raw != Decimal("1.05"))


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(1, 3100), st.integers(0, 100))
def test_root_conservation(units: int, base_fee_units: int) -> None:
    root = bound_root()
    before = fingerprint(root.inventory_book)
    ledger = build_sell_fill_ledger(root, ref())
    updated = record_sell_fill(
        ledger,
        fill(
            ledger,
            executed_qty=Qty(exact(Fraction(units, 100000))),
            fee=Money(exact(Fraction(base_fee_units, 1000000)), BTC),
        ),
    )
    validate_sell_fill_ledger_against_book(updated, root)
    assert fingerprint(root.inventory_book) == before
    assert Fraction(updated.gross_executed_qty.value) + Fraction(
        updated.base_fee_qty.value
    ) <= Fraction(root.inventory_book.confirmed_net_base_qty.value)


class SellLedgerMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.root = bound_root()
        self.original = fingerprint(self.root.inventory_book)
        self.ledger = build_sell_fill_ledger(self.root, ref())
        self.quantity = Fraction(0)
        self.count = 0

    @rule(units=st.integers(1, 500))
    def observe(self, units: int) -> None:
        qty = Fraction(units, 100000)
        observed = fill(
            self.ledger, fill_ref=f"trade-{self.count:03d}", executed_qty=Qty(exact(qty))
        )
        if self.quantity + qty > Fraction(31, 1000):
            previous = self.ledger
            expect(E.OVERFILL, lambda: record_sell_fill(self.ledger, observed))
            assert self.ledger is previous
        else:
            self.ledger = record_sell_fill(self.ledger, observed)
            self.quantity += qty
            self.count += 1

    @rule()
    def repeat_and_conflict(self) -> None:
        if self.ledger.fills:
            observed = self.ledger.fills[0]
            assert record_sell_fill(self.ledger, observed) is self.ledger
            conflict = dataclasses.replace(observed, observed_quote=Money.parse("999", USDT))
            expect(E.DUPLICATE_FILL_CONFLICT, lambda: record_sell_fill(self.ledger, conflict))

    @invariant()
    def conserved(self) -> None:
        assert Fraction(self.ledger.gross_executed_qty.value) == self.quantity
        assert self.ledger.gross_executed_qty <= q("0.031")
        assert fingerprint(self.root.inventory_book) == self.original
        validate_sell_fill_ledger_against_book(self.ledger, self.root)


TestSellLedgerMachine = SellLedgerMachine.TestCase
TestSellLedgerMachine.settings = settings(
    max_examples=60, stateful_step_count=30, deadline=None, derandomize=True
)
