from dataclasses import replace
from datetime import timedelta
from fractions import Fraction

import pytest

from gridbot.backtest.engine import BacktestResult, run_backtest
from gridbot.backtest.export import comparison
from gridbot.backtest.metrics import capital_time_average, max_drawdown
from gridbot.domain import BTC, USDT, Money, Side
from tests.backtest.test_data import START
from tests.backtest.test_engine import config, dataset


@pytest.fixture(scope="module")
def result() -> BacktestResult:
    return run_backtest(dataset(), config(), code_commit="metrics-unit")


def test_mark_to_market_conservation_no_double_count(result: BacktestResult) -> None:
    for point in result.points:
        state = point.state
        expected = (
            Fraction(state.available_quote.amount)
            + Fraction(state.active_buy_reservations.amount)
            + Fraction(state.remaining_grid_base.value) * Fraction(point.price.value)
        )
        assert point.equity is not None
        assert Fraction(point.equity.amount) == expected
        assert state.available_quote + state.active_buy_reservations + state.buy_spending == (
            config().initial_quote + state.settled_sell_proceeds
        )
    metrics = result.metrics
    assert metrics.bought_btc.value == metrics.sold_btc.value
    assert metrics.final_grid_btc.value == 0
    assert metrics.final_btc_equivalent == Fraction(metrics.available_quote.amount) / 110
    assert metrics.physical_btc_change_pct is None  # Initial GRID BTC is zero.
    assert metrics.hypothetical_proportional_pnl == Money.parse("9.17147", USDT)
    assert metrics.settled_sell_proceeds != metrics.hypothetical_proportional_pnl
    assert metrics.realized_pnl is None


def test_drawdown_and_time_weighting_exact_known_curve(result: BacktestResult) -> None:
    original = result.points[0]
    points = tuple(
        replace(
            original,
            time=START + timedelta(minutes=i),
            equity=Money.parse(value, USDT),
            btc_mark=Money.parse(str(int(value) * i // 4), USDT),
            exposure=Fraction(i, 4),
        )
        for i, value in enumerate(["100", "80", "120", "90"])
    )
    assert max_drawdown(points, Money.parse("100", USDT)) == Fraction(1, 4)
    assert capital_time_average(points, "exposure") == Fraction(4, 15)
    assert max_drawdown((replace(original, equity=None),), Money.parse("100", USDT)) is None
    assert max_drawdown(points, None) is None
    assert max_drawdown(points, Money.zero(USDT)) is None
    assert capital_time_average((original,), "exposure") is None
    assert capital_time_average((replace(original, equity=None), points[-1]), "exposure") is None


def test_capital_time_integrals_do_not_accumulate_unrelated_denominators(
    result: BacktestResult,
) -> None:
    original = result.points[0]
    amounts = [10_000_001 + i for i in range(1001)]
    points = tuple(
        replace(
            original,
            time=START + timedelta(minutes=i),
            equity=Money.parse(str(value), USDT),
            btc_mark=Money.parse("1", USDT),
            exposure=Fraction(1, value),
        )
        for i, value in enumerate(amounts)
    )
    value = capital_time_average(points, "exposure")
    assert value == Fraction(1000, sum(amounts[:-1]))
    assert value.denominator.bit_length() < 64


def test_benchmark_same_capital_period_fees_and_mark(result: BacktestResult) -> None:
    grid, bh = result.metrics, result.benchmark
    assert grid.initial_quote == bh.initial_quote == config().initial_quote
    assert result.points[-1].time == result.benchmark_points[-1].time
    assert result.points[-1].price == result.benchmark_points[-1].price
    trade = result.benchmark_trades[0]
    assert trade.bar_open == START + timedelta(minutes=1)
    assert trade.price == dataset().series.candles[1].open
    assert trade.observed_at == START + timedelta(minutes=2)
    assert trade.side is Side.BUY
    assert trade.fee.asset == USDT
    assert bh.available_quote.amount >= 0
    assert bh.final_grid_btc.value == bh.bought_btc.value
    assert all(m.asset != BTC or m.amount == 0 for m in grid.fees)


def test_zero_capital_ratios_are_explicitly_undefined() -> None:
    zero = run_backtest(
        dataset(), replace(config(), initial_quote=Money.zero(USDT)), code_commit="v"
    )
    assert zero.metrics.return_pct is None
    assert zero.metrics.max_drawdown is None
    assert zero.metrics.capital_time_mean_exposure is None
    assert zero.metrics.final_equity == Money.zero(USDT)


def test_missing_benchmark_does_not_become_a_claim_of_outperformance(
    result: BacktestResult,
) -> None:
    absent = replace(result.benchmark, fills=0)
    compared = comparison(result.metrics, absent)
    assert compared["status"] == "BENCHMARK_NOT_EXECUTED"
    assert compared["equity_difference"] is None
