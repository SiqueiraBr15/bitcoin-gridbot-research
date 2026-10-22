"""A16: fixtures A8-A15 reais, evidência observada e falhas sem efeitos econômicos."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from decimal import Decimal, localcontext
from typing import Any, cast

import pytest

from gridbot.application import (
    GridOperationalBook,
    ObservedSellFill,
    SellAttemptStatus,
    SellExecutionRef,
    SellFillError,
    SellFillErrorCode,
    SellFillLedger,
    SellInventoryBook,
    build_sell_fill_ledger,
    record_sell_fill,
    validate_sell_fill_ledger_against_book,
)
from gridbot.domain import BTC, USDT, Asset, LiquidityRole, Money, Price, Side
from gridbot.portfolio import BuyExecutionRef
from gridbot.strategy import CellCycleRef
from tests.application.test_operational_grid import (
    context,
    prepare_other_buy,
    prepared_root,
    ref,
    with_status,
)
from tests.application.test_sell_intents import ETHUSDT, fingerprint, forged, p, q

E = SellFillErrorCode
BNB = Asset("BNB")


def bound_root() -> GridOperationalBook:
    return with_status(prepared_root(), SellAttemptStatus.EXECUTION_BOUND)


@pytest.fixture
def root() -> GridOperationalBook:
    return bound_root()


@pytest.fixture
def ledger(root: GridOperationalBook) -> SellFillLedger:
    return build_sell_fill_ledger(root, ref())


def fill(ledger: SellFillLedger, **changes: Any) -> ObservedSellFill:
    values: dict[str, Any] = {
        "execution_ref": ledger.context.execution_ref,
        "fill_ref": "trade-1",
        "cycle_ref": ledger.context.cycle_ref,
        "symbol": ledger.context.symbol,
        "execution_price": p("105"),
        "executed_qty": q("0.01"),
        "observed_quote": Money.parse("1.05", USDT),
        "fee": Money.parse("0", USDT),
    }
    values.update(changes)
    return ObservedSellFill(**values)


def expect(code: SellFillErrorCode, operation: Callable[[], object]) -> SellFillError:
    with pytest.raises(SellFillError) as info:
        operation()
    assert info.value.code is code
    assert code.value in str(info.value)
    return info.value


def test_valid_empty_build_without_fixture() -> None:
    result = build_sell_fill_ledger(bound_root(), ref())
    assert result.gross_executed_qty == q(0)
    assert result.net_observed_quote == Money.zero(USDT)


def test_empty_ledger_source_and_totals(root: GridOperationalBook, ledger: SellFillLedger) -> None:
    assert ledger.context is root.sell_attempts[0].execution
    assert [f.name for f in dataclasses.fields(ledger)] == ["context", "fills"]
    assert ledger.fills == ()
    assert ledger.gross_executed_qty == q(0)
    assert ledger.remaining_qty == q("0.031")
    assert ledger.gross_observed_quote == Money.zero(USDT)
    assert ledger.gross_derived_quote == Money.zero(USDT)
    assert ledger.net_observed_quote == Money.zero(USDT)
    assert ledger.base_fee_qty == q(0)
    assert ledger.quote_fee == Money.zero(USDT)
    assert ledger.fees_by_asset == ledger.third_asset_fees == ()
    assert ledger.quote_discrepancy_refs == ()
    assert not ledger.has_unvalued_third_asset_fees
    validate_sell_fill_ledger_against_book(ledger, root)


@pytest.mark.parametrize(
    "status", [SellAttemptStatus.PREPARED, SellAttemptStatus.SUBMISSION_UNCERTAIN]
)
def test_unbound_cannot_build(status: SellAttemptStatus) -> None:
    expect(
        E.ATTEMPT_NOT_BOUND,
        lambda: build_sell_fill_ledger(with_status(prepared_root(), status), ref()),
    )


@pytest.mark.parametrize("cycle", [CellCycleRef(0, 1), CellCycleRef(4, 0), CellCycleRef(99, 3)])
def test_missing_attempt(root: GridOperationalBook, cycle: CellCycleRef) -> None:
    expect(E.INVALID_BOOK, lambda: build_sell_fill_ledger(root, cycle))


@pytest.mark.parametrize("value", [None, 1, "root", 1.2, (), object()])
def test_invalid_book_type(value: Any) -> None:
    expect(E.INVALID_BOOK, lambda: build_sell_fill_ledger(value, ref()))


@pytest.mark.parametrize("value", [None, 1, "cycle", 1.2, (), object()])
def test_invalid_cycle_type(root: GridOperationalBook, value: Any) -> None:
    expect(E.INVALID_BOOK, lambda: build_sell_fill_ledger(root, value))


def test_standalone_context_has_no_current_authority(ledger: SellFillLedger) -> None:
    standalone = SellFillLedger(ledger.context)
    other = prepared_root()
    expect(E.ATTEMPT_NOT_BOUND, lambda: validate_sell_fill_ledger_against_book(standalone, other))


def test_lost_reservation_rejected(root: GridOperationalBook, ledger: SellFillLedger) -> None:
    missing = forged(root, inventory_book=SellInventoryBook(root.inventory_book.funded_buy_book))
    expect(E.INVALID_BOOK, lambda: build_sell_fill_ledger(missing, ref()))
    expect(E.INVALID_BOOK, lambda: validate_sell_fill_ledger_against_book(ledger, missing))


def test_buy_not_consumed_rejected(root: GridOperationalBook) -> None:
    funded = root.inventory_book.funded_buy_book
    lifecycle = forged(funded.lifecycle, consumed=())
    broken = forged(
        root,
        inventory_book=forged(
            root.inventory_book, funded_buy_book=forged(funded, lifecycle=lifecycle)
        ),
    )
    expect(E.INVALID_BOOK, lambda: build_sell_fill_ledger(broken, ref()))


def test_other_buy_preserves_authority(root: GridOperationalBook, ledger: SellFillLedger) -> None:
    updated = prepare_other_buy(root)
    validate_sell_fill_ledger_against_book(ledger, updated)


def test_other_execution_not_authorized(root: GridOperationalBook, ledger: SellFillLedger) -> None:
    detached = dataclasses.replace(
        ledger, context=dataclasses.replace(ledger.context, execution_ref=SellExecutionRef("other"))
    )
    expect(E.AUTHORIZATION_MISMATCH, lambda: validate_sell_fill_ledger_against_book(detached, root))


def test_other_authorization_same_execution_rejected(
    root: GridOperationalBook, ledger: SellFillLedger
) -> None:
    reservation = dataclasses.replace(ledger.context.intent.reservation, base_fee_hold=q(0))
    intent = dataclasses.replace(ledger.context.intent, reservation=reservation)
    detached = SellFillLedger(dataclasses.replace(ledger.context, intent=intent))
    expect(E.AUTHORIZATION_MISMATCH, lambda: validate_sell_fill_ledger_against_book(detached, root))


@pytest.mark.parametrize("bad", ["", " id", "id ", "x" * 129, 0, None, True])
def test_trade_identity_invalid(ledger: SellFillLedger, bad: Any) -> None:
    expect(E.INVALID_FILL, lambda: fill(ledger, fill_ref=bad))


@pytest.mark.parametrize("valid", ["0", "1", "x" * 128, "符号-ID", "id with spaces"])
def test_trade_identity_opaque_not_normalized(ledger: SellFillLedger, valid: str) -> None:
    observed = fill(ledger, fill_ref=valid)
    assert observed.fill_ref == valid
    assert observed.trade_key == (ledger.context.symbol, ledger.context.execution_ref, valid)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("execution_ref", BuyExecutionRef("BUY")),
        ("execution_ref", "sell-0"),
        ("execution_ref", None),
        ("cycle_ref", "0:0"),
        ("symbol", "BTCUSDT"),
        ("execution_price", 105.0),
        ("executed_qty", 0.01),
        ("fee", 0.1),
        ("observed_quote", 1.05),
        ("observed_quote", None),
        ("liquidity", "MAKER"),
        ("side", Side.BUY),
        ("side", "SELL"),
        ("executed_qty", q(0)),
        ("observed_quote", Money.parse("-1", USDT)),
        ("observed_quote", Money.parse("1", BTC)),
        ("fee", Money.parse("-0.0001", BTC)),
        ("fee", Money.parse("-1", BNB)),
    ],
)
def test_fill_constructor_rejects_invalid(ledger: SellFillLedger, field: str, bad: Any) -> None:
    expect(E.INVALID_FILL, lambda: fill(ledger, **{field: bad}))


@pytest.mark.parametrize("role", [None, LiquidityRole.MAKER, LiquidityRole.TAKER])
def test_liquidity_is_only_observed(ledger: SellFillLedger, role: LiquidityRole | None) -> None:
    result = record_sell_fill(ledger, fill(ledger, liquidity=role))
    assert result.fills[0].liquidity is role


@pytest.mark.parametrize(
    ("field", "bad", "code"),
    [
        ("execution_ref", SellExecutionRef("other"), E.EXECUTION_MISMATCH),
        ("cycle_ref", CellCycleRef(0, 1), E.CYCLE_MISMATCH),
        ("execution_price", p("101.9999999999999999999999"), E.PRICE_BELOW_LIMIT),
        ("executed_qty", q("0.032"), E.OVERFILL),
        ("executed_qty", q("0.03100000000000000000000000000001"), E.OVERFILL),
        ("executed_qty", q("0.0311"), E.OVERFILL),
        ("fee", Money.parse("0.00010000000000000001", BTC), E.BASE_FEE_EXCEEDS_HOLD),
        ("fee", Money.parse("1.050000000000001", USDT), E.QUOTE_FEE_EXCEEDS_PROCEEDS),
    ],
)
def test_record_rejection_preserves_observation_and_input(
    ledger: SellFillLedger, field: str, bad: Any, code: SellFillErrorCode
) -> None:
    observed = fill(ledger, **{field: bad})
    before = dataclasses.replace(ledger)
    error = expect(code, lambda: record_sell_fill(ledger, observed))
    assert error.observation is observed
    assert ledger == before
    assert ledger.fills == ()


def test_symbol_mismatch(ledger: SellFillLedger) -> None:
    observed = fill(ledger, symbol=ETHUSDT)
    expect(E.SYMBOL_MISMATCH, lambda: record_sell_fill(ledger, observed))


@pytest.mark.parametrize("quantities", [("0.031",), ("0.01", "0.021"), ("0.01", "0.01", "0.011")])
def test_complete_execution_no_terminal_no_economic_changes(
    root: GridOperationalBook, ledger: SellFillLedger, quantities: tuple[str, ...]
) -> None:
    before = fingerprint(root.inventory_book)
    result = ledger
    for index, qty in enumerate(quantities):
        result = record_sell_fill(result, fill(ledger, fill_ref=f"t-{index}", executed_qty=q(qty)))
    assert result.gross_executed_qty == q("0.031")
    assert result.remaining_qty == q(0)
    assert fingerprint(root.inventory_book) == before
    assert ledger.fills == ()
    validate_sell_fill_ledger_against_book(result, root)


def test_partial_substep_is_observation_not_order(ledger: SellFillLedger) -> None:
    result = record_sell_fill(
        ledger,
        fill(ledger, executed_qty=q("0.00000001"), observed_quote=Money.parse("0.00000105", USDT)),
    )
    assert result.remaining_qty == q("0.03099999")


def test_canonical_order_and_varied_real_prices(ledger: SellFillLedger) -> None:
    a = fill(ledger, fill_ref="a", execution_price=p(102), observed_quote=Money.parse("1.02", USDT))
    z = fill(ledger, fill_ref="z", execution_price=p(110), observed_quote=Money.parse("1.10", USDT))
    first = record_sell_fill(record_sell_fill(ledger, z), a)
    second = record_sell_fill(record_sell_fill(ledger, a), z)
    assert first == second
    assert first.fills == (a, z)
    assert first.gross_observed_quote == first.gross_derived_quote == Money.parse("2.12", USDT)
    assert first.context.limit_price == p(102)
    expect(E.INVALID_LEDGER, lambda: SellFillLedger(ledger.context, (z, a)))


def test_duplicate_identical_is_same_object(ledger: SellFillLedger) -> None:
    observed = fill(ledger)
    result = record_sell_fill(ledger, observed)
    assert record_sell_fill(result, dataclasses.replace(observed)) is result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_price", p(106)),
        ("executed_qty", q("0.011")),
        ("observed_quote", Money.parse("1.051", USDT)),
        ("fee", Money.parse("0.000001", BTC)),
        ("liquidity", LiquidityRole.TAKER),
    ],
)
def test_duplicate_conflict_never_changes_totals(
    ledger: SellFillLedger, field: str, value: Any
) -> None:
    observed = fill(ledger)
    populated = record_sell_fill(ledger, observed)
    conflict = dataclasses.replace(observed, **{field: value})
    expect(E.DUPLICATE_FILL_CONFLICT, lambda: record_sell_fill(populated, conflict))
    assert populated.fills == (observed,)
    assert populated.gross_executed_qty == q("0.01")
    assert populated.gross_observed_quote == Money.parse("1.05", USDT)


def test_duplicate_in_direct_constructor_rejected(ledger: SellFillLedger) -> None:
    observed = fill(ledger)
    expect(E.DUPLICATE_FILL_CONFLICT, lambda: SellFillLedger(ledger.context, (observed, observed)))


@pytest.mark.parametrize("quote", ["0", "1.04999999", "1.05000001", "1.2"])
def test_quote_preserved_discrepancy_explicit(ledger: SellFillLedger, quote: str) -> None:
    observed = fill(ledger, observed_quote=Money.parse(quote, USDT))
    result = record_sell_fill(ledger, observed)
    assert result.gross_observed_quote == result.net_observed_quote == Money.parse(quote, USDT)
    assert result.gross_derived_quote == Money.parse("1.05", USDT)
    assert result.quote_discrepancy_refs == (observed.fill_ref,)


@pytest.mark.parametrize(
    ("asset", "amount"),
    [(BTC, "0.0001"), (USDT, "0.01"), (BNB, "0.005"), (Asset("XYZ"), "0.04"), (BNB, "0")],
)
def test_fee_asset_not_converted(ledger: SellFillLedger, asset: Asset, amount: str) -> None:
    fee = Money.parse(amount, asset)
    result = record_sell_fill(ledger, fill(ledger, fee=fee))
    assert result.fees_by_asset == (fee,)
    assert result.fee_for(asset) == fee
    assert result.base_fee_qty == (q(amount) if asset == BTC else q(0))
    assert result.quote_fee == (fee if asset == USDT else Money.zero(USDT))
    assert result.has_unvalued_third_asset_fees == (asset not in (BTC, USDT) and fee.amount > 0)
    assert result.net_observed_quote == Money.parse("1.04" if asset == USDT else "1.05", USDT)


def test_multicurrency_conservation(root: GridOperationalBook, ledger: SellFillLedger) -> None:
    before = fingerprint(root.inventory_book)
    result = ledger
    for ident, fee in (
        ("1", Money.parse("0.0001", BTC)),
        ("2", Money.parse("0.01", USDT)),
        ("3", Money.parse("0.001", BNB)),
    ):
        result = record_sell_fill(result, fill(ledger, fill_ref=ident, fee=fee))
    assert result.gross_executed_qty == q("0.03")
    assert result.base_fee_qty == q("0.0001")
    assert (
        result.gross_executed_qty + result.base_fee_qty
        <= ledger.context.intent.finalized_buy.net_acquired_base_qty
    )
    assert result.gross_observed_quote == Money.parse("3.15", USDT)
    assert result.net_observed_quote + result.quote_fee == result.gross_observed_quote
    assert result.third_asset_fees == (Money.parse("0.001", BNB),)
    assert tuple(f.asset.code for f in result.fees_by_asset) == ("BNB", "BTC", "USDT")
    assert fingerprint(root.inventory_book) == before


def test_cumulative_base_fees_enforce_hold(ledger: SellFillLedger) -> None:
    one = record_sell_fill(ledger, fill(ledger, fee=Money.parse("0.00006", BTC)))
    second = fill(ledger, fill_ref="2", fee=Money.parse("0.00005", BTC))
    error = expect(E.BASE_FEE_EXCEEDS_HOLD, lambda: record_sell_fill(one, second))
    assert error.observation is second
    assert one.base_fee_qty == q("0.00006")


@pytest.mark.parametrize("field", ["observed_quote", "fee", "executed_qty", "execution_price"])
@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), 0.1])
def test_nested_forged_values_revalidated(ledger: SellFillLedger, field: str, bad: Any) -> None:
    observed = fill(ledger)
    value = getattr(observed, field)
    broken = forged(value, **{"amount" if isinstance(value, Money) else "value": bad})
    adulterated = forged(observed, **{field: broken})
    expect(E.INVALID_FILL, lambda: record_sell_fill(ledger, adulterated))


def test_forged_ledger_revalidated_before_duplicate(ledger: SellFillLedger) -> None:
    observed = fill(ledger)
    populated = record_sell_fill(ledger, observed)
    broken = forged(populated, fills=(observed, observed))
    expect(E.DUPLICATE_FILL_CONFLICT, lambda: record_sell_fill(broken, observed))


def test_invalid_duplicate_revalidated_before_conflict(ledger: SellFillLedger) -> None:
    observed = fill(ledger)
    populated = record_sell_fill(ledger, observed)
    broken = forged(observed, executed_qty=q(0))
    expect(E.INVALID_FILL, lambda: record_sell_fill(populated, broken))
    assert populated.fills == (observed,)


def test_invalid_buy_execution_identity_revalidated(ledger: SellFillLedger) -> None:
    buy = ledger.context.intent.finalized_buy
    bad_ref = forged(buy.context.execution_ref, value="")
    context_buy = forged(buy.context, execution_ref=bad_ref)
    bad_buy = forged(
        buy,
        context=context_buy,
        terminal_report=forged(buy.terminal_report, execution_ref=bad_ref),
        reconciliation_evidence=forged(buy.reconciliation_evidence, execution_ref=bad_ref),
    )
    assessment = forged(ledger.context.intent.reservation.assessment, finalized_buy=bad_buy)
    reservation = forged(ledger.context.intent.reservation, assessment=assessment)
    ctx = forged(ledger.context, intent=forged(ledger.context.intent, reservation=reservation))
    expect(E.INVALID_LEDGER, lambda: SellFillLedger(ctx))


@pytest.mark.parametrize("bad", [None, [], "fills", (1,)])
def test_ledger_wrong_fills(ledger: SellFillLedger, bad: Any) -> None:
    expect(E.INVALID_LEDGER, lambda: SellFillLedger(ledger.context, bad))


@pytest.mark.parametrize("bad", [None, 1, 0.2, "context"])
def test_ledger_wrong_context(bad: Any) -> None:
    expect(E.INVALID_LEDGER, lambda: SellFillLedger(bad))


def test_forged_buy_origin_rejected(ledger: SellFillLedger) -> None:
    buy = ledger.context.intent.finalized_buy
    observed = buy.ledger.fills[0]
    nested = forged(observed, executed_qty=forged(observed.executed_qty, value=Decimal("NaN")))
    invalid_buy = forged(buy, ledger=forged(buy.ledger, fills=(nested,)))
    reservation = forged(
        ledger.context.intent.reservation,
        assessment=forged(ledger.context.intent.reservation.assessment, finalized_buy=invalid_buy),
    )
    broken = forged(ledger.context, intent=forged(ledger.context.intent, reservation=reservation))
    expect(E.INVALID_LEDGER, lambda: SellFillLedger(broken))


def test_frozen_objects(ledger: SellFillLedger) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        cast(Any, ledger).fills = ()
    observed = fill(ledger)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cast(Any, observed).fee = Money.zero(BTC)


@pytest.mark.parametrize("precision", [2, 6, 28, 50])
def test_ambient_context_does_not_change_results(ledger: SellFillLedger, precision: int) -> None:
    observed = fill(ledger, executed_qty=q("0.01000000000000000000000000001"))
    expected = record_sell_fill(ledger, observed)
    with localcontext() as ambient:
        ambient.prec = precision
        actual = record_sell_fill(ledger, observed)
        assert actual == expected
        assert actual.gross_derived_quote == expected.gross_derived_quote
        assert actual.net_observed_quote == expected.net_observed_quote


def test_inexact_product_fails_closed(ledger: SellFillLedger) -> None:
    expect(
        E.FINANCIAL_PRECISION_ERROR,
        lambda: fill(
            ledger,
            execution_price=Price.parse("12345678901234567890123456789012345"),
            executed_qty=q("0.00000000000000000000000000000012345"),
        ),
    )


def test_inexact_quote_sum_fails_closed(ledger: SellFillLedger) -> None:
    first = record_sell_fill(
        ledger, fill(ledger, observed_quote=Money.parse("1234567890123456789012345678901234", USDT))
    )
    observed = fill(ledger, fill_ref="2", observed_quote=Money.parse("0.001", USDT))
    expect(E.FINANCIAL_PRECISION_ERROR, lambda: record_sell_fill(first, observed))
    assert first.fills[0].observed_quote.amount == Decimal("1234567890123456789012345678901234")


def test_inexact_remaining_qty_fails_closed(ledger: SellFillLedger) -> None:
    observed = fill(ledger, executed_qty=q("1e-40"), observed_quote=Money.zero(USDT))
    error = expect(E.FINANCIAL_PRECISION_ERROR, lambda: record_sell_fill(ledger, observed))
    assert error.observation is observed
    assert ledger.fills == ()


def test_inexact_net_quote_fails_closed(ledger: SellFillLedger) -> None:
    observed = fill(
        ledger,
        observed_quote=Money.parse("1234567890123456789012345678901234", USDT),
        fee=Money.parse("0.001", USDT),
    )
    error = expect(E.FINANCIAL_PRECISION_ERROR, lambda: record_sell_fill(ledger, observed))
    assert error.observation is observed
    assert ledger.fills == ()


@pytest.mark.parametrize("bad", [None, "ledger", 1.2])
def test_validation_invalid_ledger_type(root: GridOperationalBook, bad: Any) -> None:
    expect(E.INVALID_LEDGER, lambda: validate_sell_fill_ledger_against_book(bad, root))


@pytest.mark.parametrize("bad", [None, 1.1, "ledger"])
def test_record_invalid_ledger_type(bad: Any) -> None:
    valid = build_sell_fill_ledger(bound_root(), ref())
    expect(E.INVALID_FILL, lambda: record_sell_fill(bad, fill(valid)))


@pytest.mark.parametrize("bad", [None, 1.1, "fill"])
def test_record_invalid_fill_type(ledger: SellFillLedger, bad: Any) -> None:
    expect(E.INVALID_FILL, lambda: record_sell_fill(ledger, bad))


def test_invalid_fee_asset_revalidated(ledger: SellFillLedger) -> None:
    observed = fill(ledger)
    broken = forged(observed, fee=forged(observed.fee, asset=forged(USDT, code="usdt")))
    expect(E.INVALID_FILL, lambda: record_sell_fill(ledger, broken))


def test_same_trade_id_in_other_execution_is_not_global(ledger: SellFillLedger) -> None:
    detached = SellFillLedger(
        dataclasses.replace(ledger.context, execution_ref=SellExecutionRef("other"))
    )
    first = record_sell_fill(ledger, fill(ledger))
    second = record_sell_fill(detached, fill(detached))
    assert first.fills[0].fill_ref == second.fills[0].fill_ref
    assert first.fills[0].trade_key != second.fills[0].trade_key


def test_direct_constructor_no_fake_financial_source(ledger: SellFillLedger) -> None:
    assert not hasattr(ledger, "wallet")
    assert not hasattr(ledger, "capital")
    assert not hasattr(ledger, "is_terminal")
    assert not hasattr(ledger, "realized_pnl")
    assert context(bound_root()).requested_qty == ledger.context.requested_qty
