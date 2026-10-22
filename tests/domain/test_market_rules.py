from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    DomainError,
    FloatNotAllowedError,
    InvalidMarketRulesError,
    MarketRules,
    MarketRuleViolationError,
    Money,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    RuleViolation,
    RuleViolationCode,
    Symbol,
)

D = Decimal
C = RuleViolationCode


def price(raw: str) -> Price:
    return Price.parse(raw)


def qty(raw: str) -> Qty:
    return Qty.parse(raw)


def btc_rules(**overrides: object) -> MarketRules:
    fields: dict[str, object] = {
        "symbol": BTCUSDT,
        "price": PriceRules(price("0.01"), min_price=price("0.01"), max_price=price("1000000")),
        "quantity": QuantityRules(qty("0.00001"), min_qty=qty("0.00001"), max_qty=qty("9000")),
        "notional": NotionalRules.parse(min_notional="5", max_notional="9000000"),
    }
    fields.update(overrides)
    return MarketRules(**cast(Any, fields))


# ------------------------------------------------------------------ construção


def test_valid_construction_and_optional_limits() -> None:
    rules = MarketRules(BTCUSDT, PriceRules(price("0.10")), QuantityRules(qty("1"), qty("1")))
    assert rules.notional == NotionalRules()
    assert rules.price.min_price is None
    assert rules.check(BTCUSDT, price("1.10"), qty("1000000")).ok  # sem limites máximos


@pytest.mark.parametrize(
    "build",
    [
        lambda: PriceRules(price("1"), min_price=price("10"), max_price=price("9")),
        lambda: QuantityRules(Qty.zero(), qty("1")),
        lambda: QuantityRules(qty("0.1"), Qty.zero()),
        lambda: QuantityRules(qty("0.1"), qty("1"), max_qty=qty("0.5")),
        lambda: NotionalRules.parse(min_notional="-1"),
        lambda: NotionalRules.parse(max_notional="0"),
        lambda: NotionalRules.parse(min_notional="10", max_notional="9"),
    ],
    ids=[
        "max_price<min_price",
        "step_size=0",
        "min_qty=0",
        "max_qty<min_qty",
        "min_notional<0",
        "max_notional=0",
        "max_notional<min_notional",
    ],
)
def test_invalid_rules_fail_at_construction(build: Any) -> None:
    with pytest.raises(InvalidMarketRulesError):
        build()


def test_non_positive_tick_cannot_exist() -> None:
    for raw in ("0", "-0.01"):
        with pytest.raises(DomainError):
            PriceRules(Price.parse(raw))


def test_rule_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        PriceRules(cast(Any, D("0.01")))
    with pytest.raises(TypeError):
        QuantityRules(qty("1"), cast(Any, "1"))
    with pytest.raises(FloatNotAllowedError):
        NotionalRules(min_notional=cast(Any, 5.0))
    with pytest.raises(FloatNotAllowedError):
        NotionalRules.parse(min_notional=cast(Any, 5.0))
    with pytest.raises(TypeError):
        btc_rules(price="0.01")


def test_min_notional_zero_is_allowed() -> None:
    assert NotionalRules.parse(min_notional="0").min_notional == D(0)


def test_rules_are_immutable() -> None:
    rules = btc_rules()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rules.symbol = BTCUSDT  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rules.price.tick_size = price("1")  # type: ignore[misc]


# ------------------------------------------------------------------ alinhamento


@pytest.mark.parametrize(
    ("tick", "raw", "aligned"),
    [
        ("0.10", "65000.10", True),
        ("0.10", "65000.15", False),
        ("0.05", "65000.15", True),
        ("0.05", "65000.07", False),
        ("1", "65000", True),
        ("10", "65005", False),
    ],
)
def test_price_alignment(tick: str, raw: str, aligned: bool) -> None:
    rules = PriceRules(price(tick))
    assert rules.is_aligned(price(raw)) is aligned
    codes = [v.code for v in rules.violations(price(raw))]
    assert (C.PRICE_NOT_ALIGNED in codes) is not aligned


@pytest.mark.parametrize(
    ("step", "raw", "aligned"),
    [
        ("0.00001", "0.12345", True),
        ("0.00001", "0.000015", False),
        ("0.05", "0.10", True),
        ("0.05", "0.07", False),
        ("1", "3", True),
    ],
)
def test_qty_alignment(step: str, raw: str, aligned: bool) -> None:
    rules = QuantityRules(qty(step), qty(step))
    assert rules.is_aligned(qty(raw)) is aligned


def test_validation_never_changes_values() -> None:
    rules = btc_rules()
    p, q = price("65000.155"), qty("0.000015")
    check = rules.check(BTCUSDT, p, q)
    assert check.price is p
    assert check.qty is q
    assert check.price.value == D("65000.155")
    assert {C.PRICE_NOT_ALIGNED, C.QTY_NOT_ALIGNED} <= set(check.codes)


# ------------------------------------------------------------------ quantização tipada


def test_price_floor_and_ceil() -> None:
    rules = PriceRules(price("0.10"))
    assert rules.floor(price("100.19")) == price("100.10")
    assert rules.ceil(price("100.19")) == price("100.20")
    assert rules.floor(price("100.20")) == price("100.20")
    assert rules.ceil(price("100.20")) == price("100.20")


def test_price_floor_to_zero_is_an_error_not_a_price() -> None:
    with pytest.raises(DomainError, match="resulta em 0"):
        PriceRules(price("0.10")).floor(price("0.05"))


def test_qty_floor_and_ceil() -> None:
    rules = QuantityRules(qty("0.00001"), qty("0.00001"))
    assert rules.floor(qty("0.001239")) == qty("0.00123")
    assert rules.ceil(qty("0.001239")) == qty("0.00124")
    assert rules.floor(qty("0.000009")) == Qty.zero()  # Qty pode ser 0


def test_quantized_value_may_still_violate_limits() -> None:
    # Quantizar só alinha; limites são verificados separadamente.
    rules = btc_rules()
    floored = rules.quantity.floor(qty("0.000009"))
    codes = rules.check(BTCUSDT, price("65000"), floored).codes
    assert C.QTY_BELOW_MIN in codes
    assert C.QTY_NOT_ALIGNED not in codes


# ------------------------------------------------------------------ limites (inclusivos)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.01", ()),  # == min: ok (inclusivo)
        ("1000000", ()),  # == max: ok (inclusivo)
        ("1000000.01", (C.PRICE_ABOVE_MAX,)),
    ],
)
def test_price_limits_are_inclusive(raw: str, expected: tuple[RuleViolationCode, ...]) -> None:
    rules = PriceRules(price("0.01"), min_price=price("0.01"), max_price=price("1000000"))
    assert tuple(v.code for v in rules.violations(price(raw))) == expected


def test_price_below_min() -> None:
    rules = PriceRules(price("0.01"), min_price=price("1"))
    assert [v.code for v in rules.violations(price("0.99"))] == [C.PRICE_BELOW_MIN]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.00001", ()),
        ("9000", ()),
        ("0.000009", (C.QTY_NOT_ALIGNED, C.QTY_BELOW_MIN)),
        ("9000.00001", (C.QTY_ABOVE_MAX,)),
    ],
)
def test_qty_limits_are_inclusive(raw: str, expected: tuple[RuleViolationCode, ...]) -> None:
    rules = QuantityRules(qty("0.00001"), min_qty=qty("0.00001"), max_qty=qty("9000"))
    assert tuple(v.code for v in rules.violations(qty(raw))) == expected


@pytest.mark.parametrize(
    ("p", "q", "expected"),
    [
        ("50000", "0.0001", ()),  # notional 5 == min: ok
        ("50000", "0.00009", (C.NOTIONAL_BELOW_MIN,)),  # 4.5
        ("100000", "90", ()),  # 9.000.000 == max: ok
        ("100000", "90.00001", (C.NOTIONAL_ABOVE_MAX,)),
    ],
)
def test_notional_limits_are_inclusive(
    p: str, q: str, expected: tuple[RuleViolationCode, ...]
) -> None:
    assert btc_rules().check(BTCUSDT, price(p), qty(q)).codes == expected


# ------------------------------------------------------------------ notional


def test_notional_is_exact_money_in_quote_asset() -> None:
    check = btc_rules().check(BTCUSDT, price("65000.10"), qty("0.00015"))
    assert check.notional == Money(D("9.750015"), USDT)
    assert btc_rules().notional_of(price("0.01"), qty("0.00001")) == Money(D("1E-7"), USDT)


# ------------------------------------------------------------------ múltiplas violações


def test_multiple_violations_are_all_reported_in_fixed_order() -> None:
    check = btc_rules().check(BTCUSDT, price("1000000.005"), qty("0.000004"))  # notional ~4.0
    assert check.codes == (
        C.PRICE_NOT_ALIGNED,
        C.PRICE_ABOVE_MAX,
        C.QTY_NOT_ALIGNED,
        C.QTY_BELOW_MIN,
        C.NOTIONAL_BELOW_MIN,
    )
    assert not check.ok


def test_qty_below_min_and_notional_below_min_together() -> None:
    rules = btc_rules(quantity=QuantityRules(qty("0.00001"), min_qty=qty("0.001")))
    check = rules.check(BTCUSDT, price("1000"), qty("0.0001"))  # notional 0.1
    assert check.codes == (C.QTY_BELOW_MIN, C.NOTIONAL_BELOW_MIN)
    assert check.violations[0] == RuleViolation(C.QTY_BELOW_MIN, D("0.0001"), D("0.001"))
    assert check.violations[1] == RuleViolation(C.NOTIONAL_BELOW_MIN, D("0.1000"), D("5"))


def test_raise_if_invalid_carries_every_violation() -> None:
    check = btc_rules().check(BTCUSDT, price("65000.001"), qty("0.000001"))
    with pytest.raises(MarketRuleViolationError) as excinfo:
        check.raise_if_invalid()
    assert excinfo.value.check is check
    message = str(excinfo.value)
    for code in check.codes:
        assert code in message


def test_valid_proposal() -> None:
    check = btc_rules().check(BTCUSDT, price("65000.10"), qty("0.001"))
    assert check.ok
    assert check.codes == ()
    check.raise_if_invalid()  # não levanta


def test_other_market_is_a_programming_error() -> None:
    eth = Symbol(Asset("ETH"), USDT)
    with pytest.raises(DomainError):
        btc_rules().check(eth, price("3000"), qty("1"))


def test_check_rejects_raw_types() -> None:
    with pytest.raises(TypeError):
        btc_rules().check(BTCUSDT, cast(Any, D("65000")), qty("1"))
    with pytest.raises(TypeError):
        btc_rules().check(BTCUSDT, price("65000"), cast(Any, "1"))


# ------------------------------------------------------------------ determinismo / propriedades


def test_check_is_deterministic() -> None:
    args = (BTCUSDT, price("65000.155"), qty("0.000015"))
    assert btc_rules().check(*args) == btc_rules().check(*args)


raw_prices = st.decimals(
    min_value=D("0.01"), max_value=D("2000000"), places=4, allow_nan=False, allow_infinity=False
)
raw_qtys = st.decimals(
    min_value=D("0.00001"), max_value=D("20000"), places=7, allow_nan=False, allow_infinity=False
)


@given(raw_prices, raw_qtys)
def test_floored_proposal_never_has_alignment_violations(p: Decimal, q: Decimal) -> None:
    rules = btc_rules()
    aligned_price = rules.price.floor(Price(p))
    aligned_qty = rules.quantity.floor(Qty(q))
    codes = rules.check(BTCUSDT, aligned_price, aligned_qty).codes
    assert C.PRICE_NOT_ALIGNED not in codes
    assert C.QTY_NOT_ALIGNED not in codes
