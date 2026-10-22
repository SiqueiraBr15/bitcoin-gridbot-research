from __future__ import annotations

import dataclasses
from decimal import Decimal
from itertools import pairwise
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    FloatNotAllowedError,
    GridLevel,
    MarketRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Symbol,
    is_multiple_of,
)
from gridbot.strategy import (
    ArithmeticGridPlan,
    ArithmeticGridSpec,
    GridError,
    GridErrorCode,
    build_arithmetic_grid,
)

D = Decimal
E = GridErrorCode
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str) -> Price:
    return Price.parse(raw)


def rules(
    tick: str,
    *,
    min_price: str | None = None,
    max_price: str | None = None,
    symbol: Symbol = BTCUSDT,
) -> MarketRules:
    return MarketRules(
        symbol,
        PriceRules(
            p(tick),
            min_price=None if min_price is None else p(min_price),
            max_price=None if max_price is None else p(max_price),
        ),
        QuantityRules(Qty.parse("0.00001"), Qty.parse("0.00001")),
    )


def spec(lower: str, upper: str, intervals: int, symbol: Symbol = BTCUSDT) -> ArithmeticGridSpec:
    return ArithmeticGridSpec(symbol, p(lower), p(upper), intervals)


def build(tick: str, lower: str, upper: str, intervals: int) -> ArithmeticGridPlan:
    return build_arithmetic_grid(spec(lower, upper, intervals), rules(tick))


def expect_error(code: GridErrorCode, fn: Any) -> GridError:
    with pytest.raises(GridError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ exemplos obrigatórios


def test_case_a_tick_1() -> None:
    plan = build("1", "100", "110", 5)
    assert plan.prices == tuple(p(x) for x in ("100", "102", "104", "106", "108", "110"))
    assert [level.index for level in plan.levels] == [0, 1, 2, 3, 4, 5]
    assert plan.step == D(2)
    assert plan.step_ticks == 2


def test_case_b_tick_010() -> None:
    plan = build("0.10", "100", "101", 5)
    expected = ("100.00", "100.20", "100.40", "100.60", "100.80", "101.00")
    assert plan.prices == tuple(p(x) for x in expected)
    assert plan.step == D("0.20")
    assert plan.step_ticks == 2


def test_case_c_tick_001_eleven_levels() -> None:
    plan = build("0.01", "65000", "70000", 10)
    assert len(plan.levels) == 11
    assert plan.prices == tuple(p(str(65000 + 500 * i)) for i in range(11))
    assert plan.step_ticks == 50_000


def test_case_d_spacing_not_divisible_is_rejected() -> None:
    err = expect_error(E.GRID_SPACING_NOT_REPRESENTABLE, lambda: build("1", "100", "110", 3))
    assert "10 ticks" in str(err)


def test_case_e_unaligned_lower_is_rejected_not_quantized() -> None:
    expect_error(E.LOWER_PRICE_NOT_ALIGNED, lambda: build("0.10", "100.05", "110", 5))


def test_case_f_single_interval() -> None:
    plan = build("1", "100", "110", 1)
    assert plan.prices == (p("100"), p("110"))
    assert plan.step == D(10)


# ------------------------------------------------------------------ spec


def test_valid_spec() -> None:
    s = spec("100", "110", 5)
    assert s.interval_count == 5
    assert s.level_count == 6


@pytest.mark.parametrize(("lower", "upper"), [("100", "100"), ("110", "100")])
def test_lower_must_be_below_upper(lower: str, upper: str) -> None:
    expect_error(E.LOWER_NOT_BELOW_UPPER, lambda: spec(lower, upper, 5))


@pytest.mark.parametrize("count", [0, -1, True, False, 5.0, "5", None])
def test_invalid_interval_count(count: object) -> None:
    expect_error(
        E.INVALID_INTERVAL_COUNT,
        lambda: ArithmeticGridSpec(BTCUSDT, p("100"), p("110"), cast(Any, count)),
    )


@pytest.mark.parametrize("field", ["lower_price", "upper_price"])
def test_float_prices_are_rejected(field: str) -> None:
    fields: dict[str, object] = {
        "symbol": BTCUSDT,
        "lower_price": p("100"),
        "upper_price": p("110"),
        "interval_count": 5,
        field: 105.0,
    }
    with pytest.raises(FloatNotAllowedError):
        ArithmeticGridSpec(**cast(Any, fields))


def test_raw_types_are_rejected() -> None:
    with pytest.raises(TypeError):
        ArithmeticGridSpec(BTCUSDT, cast(Any, D("100")), p("110"), 5)
    with pytest.raises(TypeError):
        ArithmeticGridSpec(cast(Any, "BTCUSDT"), p("100"), p("110"), 5)
    with pytest.raises(TypeError):
        build_arithmetic_grid(spec("100", "110", 5), cast(Any, PriceRules(p("1"))))


# ------------------------------------------------------------------ regras de preço


def test_symbol_mismatch() -> None:
    expect_error(
        E.SYMBOL_MISMATCH,
        lambda: build_arithmetic_grid(spec("100", "110", 5), rules("1", symbol=ETHUSDT)),
    )


def test_unaligned_upper_is_rejected() -> None:
    expect_error(E.UPPER_PRICE_NOT_ALIGNED, lambda: build("0.10", "100", "110.05", 5))


@pytest.mark.parametrize(
    ("lower", "upper", "code"),
    [
        ("99", "110", E.LOWER_PRICE_OUT_OF_RANGE),
        ("100", "201", E.UPPER_PRICE_OUT_OF_RANGE),
        ("250", "260", E.LOWER_PRICE_OUT_OF_RANGE),  # lower acima do max
    ],
)
def test_bounds_outside_price_rules(lower: str, upper: str, code: GridErrorCode) -> None:
    r = rules("1", min_price="100", max_price="200")
    expect_error(code, lambda: build_arithmetic_grid(spec(lower, upper, 2), r))


def test_bounds_exactly_on_price_limits_are_valid() -> None:
    r = rules("1", min_price="100", max_price="200")
    plan = build_arithmetic_grid(spec("100", "200", 4), r)
    assert plan.prices[0] == p("100")
    assert plan.prices[-1] == p("200")


def test_more_intervals_than_ticks_is_not_representable() -> None:
    expect_error(E.GRID_SPACING_NOT_REPRESENTABLE, lambda: build("1", "100", "103", 4))


def test_tick_005_example() -> None:
    plan = build("0.05", "100", "101", 4)  # 20 ticks / 4 = 5 ticks
    assert plan.prices == tuple(p(x) for x in ("100", "100.25", "100.50", "100.75", "101"))


def test_large_but_reasonable_interval_count() -> None:
    plan = build("0.01", "10000", "20000", 10_000)  # 1.000.000 ticks / 10.000 = 100 ticks
    assert len(plan.levels) == 10_001
    assert plan.step == D("1.00")
    assert plan.levels[5_000].price == p("15000")


def test_error_precedence_is_fixed() -> None:
    # Desalinhado E fora da faixa E indivisível: o primeiro da ordem documentada vence.
    r = rules("1", min_price="200")
    s = ArithmeticGridSpec(BTCUSDT, p("100.5"), p("110"), 3)
    expect_error(E.LOWER_PRICE_NOT_ALIGNED, lambda: build_arithmetic_grid(s, r))


# ------------------------------------------------------------------ plano / imutabilidade


def test_plan_and_parts_are_immutable() -> None:
    plan = build("1", "100", "110", 5)
    assert isinstance(plan.levels, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.levels = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.spec.interval_count = 3  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.levels[0].price = p("1")  # type: ignore[misc]


def test_level_has_no_side() -> None:
    assert {f.name for f in dataclasses.fields(GridLevel)} == {"index", "price"}


def test_build_is_deterministic() -> None:
    first = build("0.01", "65000", "70000", 10)
    second = build("0.01", "65000", "70000", 10)
    assert first == second
    assert hash(first) == hash(second)


def _levels(*prices: str) -> tuple[GridLevel, ...]:
    return tuple(GridLevel(i, p(x)) for i, x in enumerate(prices))


@pytest.mark.parametrize(
    "levels",
    [
        _levels("100", "102", "104", "106", "108"),  # nível faltando
        _levels("100", "103", "104", "106", "108", "110"),  # espaçamento irregular
        _levels("100", "102", "104", "106", "108", "111"),  # último != upper
        _levels("100", "102", "104", "104", "108", "110"),  # duplicado
        tuple(
            GridLevel(i + 1, p(x)) for i, x in enumerate(("100", "102", "104", "106", "108", "110"))
        ),
    ],
    ids=["missing", "irregular", "wrong-upper", "duplicate", "bad-index"],
)
def test_plan_rejects_arbitrary_levels(levels: tuple[GridLevel, ...]) -> None:
    expect_error(
        E.PLAN_INVARIANT_VIOLATED,
        lambda: ArithmeticGridPlan(spec("100", "110", 5), p("1"), levels),
    )


def test_plan_rejects_levels_off_tick_grid() -> None:
    levels = _levels("100", "100.5", "101")
    expect_error(
        E.PLAN_INVARIANT_VIOLATED,
        lambda: ArithmeticGridPlan(spec("100", "101", 2), p("1"), levels),
    )


def test_plan_rejects_list_of_levels() -> None:
    plan = build("1", "100", "110", 5)
    with pytest.raises(TypeError):
        ArithmeticGridPlan(plan.spec, plan.tick_size, cast(Any, list(plan.levels)))


# ------------------------------------------------------------------ propriedades

ticks = st.sampled_from(["0.01", "0.05", "0.10", "0.25", "1", "10", "0.00001"])


@given(
    ticks,
    st.integers(min_value=1, max_value=10_000_000),
    st.integers(min_value=1, max_value=200),
    st.integers(min_value=1, max_value=5_000),
)
def test_valid_grids_satisfy_all_invariants(
    tick: str, lower_ticks: int, intervals: int, step_ticks: int
) -> None:
    t = D(tick)
    lower = t * lower_ticks
    upper = lower + t * intervals * step_ticks
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price(lower), Price(upper), intervals), rules(tick)
    )
    values = [level.price.value for level in plan.levels]
    assert len(values) == intervals + 1
    assert values[0] == lower
    assert values[-1] == upper
    assert all(b > a for a, b in pairwise(values))
    assert len(set(values)) == len(values)
    assert all(is_multiple_of(v, t) for v in values)
    assert {b - a for a, b in pairwise(values)} == {t * step_ticks}
    assert plan.step_ticks == step_ticks
    assert plan == build_arithmetic_grid(plan.spec, rules(tick))


@given(
    ticks,
    st.integers(min_value=1, max_value=10_000_000),
    st.integers(min_value=2, max_value=200),
    st.integers(min_value=1, max_value=100_000),
)
def test_indivisible_spans_are_always_rejected(
    tick: str, lower_ticks: int, intervals: int, span_ticks: int
) -> None:
    if span_ticks % intervals == 0:
        span_ticks += 1  # força indivisível
    t = D(tick)
    lower = t * lower_ticks
    s = ArithmeticGridSpec(BTCUSDT, Price(lower), Price(lower + t * span_ticks), intervals)
    expect_error(E.GRID_SPACING_NOT_REPRESENTABLE, lambda: build_arithmetic_grid(s, rules(tick)))
