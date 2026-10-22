from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from gridbot.backtest.data import BacktestError, Dataset
from gridbot.backtest.engine import BacktestConfig, compare_scenarios, run_backtest
from gridbot.backtest.execution import BNB, MixedPolicy
from gridbot.domain import BTC, BTCUSDT, USDT, Asset, FeeSchedule, Money, Price, Side
from gridbot.paper.accounting import PaperObserveSell
from gridbot.paper.simulation import PaperSimulation, SimulationError
from gridbot.strategy import ArithmeticGridSpec
from tests.backtest.fixtures import rules
from tests.backtest.test_data import START, raw, row, spec
from tests.backtest.test_execution import policy
from tests.paper.simulation_oracle import assert_source_conservation


def config() -> BacktestConfig:
    return BacktestConfig(
        ArithmeticGridSpec(BTCUSDT, Price.parse("90"), Price.parse("110"), 2),
        rules(),
        Money.parse("100", USDT),
        Money.parse("90", USDT),
        policy(),
        "SIM:A19_TEST",
        1000,
        "Synthetic rates and filters, NOT verified Binance history",
        START,
        START + timedelta(days=365),
    )


def dataset(
    values: tuple[str, ...] = ("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,10"),
) -> Dataset:
    return Dataset(raw("".join(row(i, v) for i, v in enumerate(values))), spec(len(values)))


def test_native_economic_roundtrip_exact_metrics_and_replay() -> None:
    result = run_backtest(dataset(), config(), code_commit="unit-test-version")
    assert result.metrics.cycles == 2
    assert result.metrics.fills == 4
    assert result.metrics.final_grid_btc.value == 0
    assert result.metrics.available_quote == Money.parse("109.17147", USDT)
    assert result.metrics.physical_btc_change_pct is None
    assert result.metrics.return_pct == Fraction("9.17147")
    assert result.metrics.realized_pnl is None
    replay = PaperSimulation.replay(result.sources, run_ref=config().run_ref, max_events=1000)
    assert replay.snapshot() == result.points[-1].state
    assert_source_conservation(result.sources, replay.snapshot())
    assert len(result.sources.events) == 10
    assert result.benchmark.bought_btc.value > 0
    assert result.benchmark.final_equity is not None
    assert result.benchmark.final_equity.amount > result.metrics.available_quote.amount
    assert all(t.observed_at >= t.bar_open + timedelta(minutes=1) for t in result.trades)


def test_future_extrema_do_not_fund_or_fill_orders_from_same_close() -> None:
    a = run_backtest(dataset(), config(), code_commit="v")
    different_future = dataset(("100,110,90,105,10", "100,106,89,100,10", "100,200,1,110,10"))
    b = run_backtest(different_future, config(), code_commit="v")
    cutoff = START + timedelta(minutes=2)
    assert [t for t in a.trades if t.observed_at <= cutoff] == [
        t for t in b.trades if t.observed_at <= cutoff
    ]
    assert a.trades[0].bar_open == START + timedelta(minutes=1)
    assert all(t.side is Side.BUY for t in a.trades if t.observed_at == cutoff)
    assert all(t.side is Side.SELL for t in a.trades if t.observed_at > cutoff)
    observations = [e for e in a.sources.events if isinstance(e.command, PaperObserveSell)]
    assert len(observations) == 2


def test_partial_terminal_blocks_residual_without_rearm() -> None:
    market = dataset(
        ("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,.01", "110,120,80,100,10")
    )
    result = run_backtest(market, config(), code_commit="v")
    assert result.points[-1].state.grid_state.cells[0].cycle_seq == 0
    assert result.metrics.cycles == 1  # The other cell completes legitimately on bar4.
    assert result.metrics.reserved_btc.value > 0
    assert sum(t.side is Side.SELL and t.cycle_ref.cell_index == 0 for t in result.trades) == 1
    assert all(t.cycle_ref.cycle_seq == 0 for t in result.trades)
    assert any(e.detail == "PARTIAL_CANCELED" for e in result.decisions)
    assert_source_conservation(result.sources, result.points[-1].state)


def test_zero_volume_no_fill_cancellation_and_no_rearm() -> None:
    result = run_backtest(
        dataset(("100,110,90,105,0", "100,110,80,105,0", "100,110,80,105,0")),
        config(),
        code_commit="v",
    )
    assert not result.trades
    assert result.metrics.available_quote == config().initial_quote
    assert result.metrics.reserved_quote.amount == 0
    assert result.metrics.cycles == 0
    assert all(not c.buy_armed for c in result.points[-1].state.grid_state.cells)
    assert result.benchmark.fills == 0


@pytest.mark.parametrize("asset", [BTC, USDT, BNB])
def test_fee_assets_and_fraction_oracle(asset: Asset) -> None:
    settings = config()
    model = replace(
        settings.policy.fees, buy_asset=asset, sell_asset=asset, bnb_fee_price=Price.parse("100")
    )
    settings = replace(
        settings,
        policy=replace(settings.policy, fees=model),
        third_asset_funding=(Money.parse("1", BNB),),
        bnb_mark=Price.parse("100"),
    )
    result = run_backtest(dataset(), settings, code_commit="v")
    assert_source_conservation(result.sources, result.points[-1].state)
    assert all(t.fee.asset == asset for t in result.trades)
    assert not result.points[-1].state.third_asset_obligations
    if asset == BTC:
        assert result.metrics.commission_btc.value > 0
        # Existing sizing may leave too little dust for the explicit SELL BTC hold.
        assert any(d.kind == "SELL_BASE_FEE_HOLD_UNFUNDED" for d in result.decisions)
    if asset == BNB:
        assert result.metrics.hypothetical_proportional_pnl is None


def test_bnb_without_funding_never_invents_assets_and_unvalued_is_incomplete() -> None:
    settings = config()
    model = replace(
        settings.policy.fees, buy_asset=BNB, sell_asset=BNB, bnb_fee_price=Price.parse("100")
    )
    missing = replace(settings, policy=replace(settings.policy, fees=model))
    refused = run_backtest(dataset(), missing, code_commit="v")
    assert not refused.trades
    assert any(d.kind == "BNB_FUNDING_INSUFFICIENT" for d in refused.decisions)
    assert not refused.points[-1].state.third_asset_obligations
    unvalued = run_backtest(
        dataset(), replace(missing, third_asset_funding=(Money.parse("1", BNB),)), code_commit="v"
    )
    assert unvalued.metrics.final_equity is None
    assert unvalued.metrics.return_pct is None
    assert unvalued.benchmark.final_equity is None


def test_capital_filters_gap_and_capacity_fail_closed() -> None:
    small = replace(config(), initial_quote=Money.parse(".001", USDT))
    result = run_backtest(dataset(), small, code_commit="v")
    assert not result.trades
    assert any(d.kind == "BUY_SIZING_INELIGIBLE" for d in result.decisions)
    with pytest.raises(BacktestError, match="gaps"):
        run_backtest(Dataset(raw(row(0) + row(2)), spec()), config(), code_commit="v")
    with pytest.raises(SimulationError):
        run_backtest(dataset(), replace(config(), max_events=1), code_commit="v")
    with pytest.raises(BacktestError, match="valid"):
        run_backtest(
            dataset(),
            replace(config(), effective_end=START + timedelta(minutes=1)),
            code_commit="v",
        )


def test_determinism_and_bounded_explicit_sensitivity() -> None:
    market, settings = dataset(), config()
    first = run_backtest(market, settings, code_commit="v")
    assert run_backtest(market, settings, code_commit="v") == first
    variants = tuple(
        replace(settings, run_ref=f"SIM:VARIANT_{i}", policy=replace(settings.policy, mixed=p))
        for i, p in enumerate(MixedPolicy)
    )
    results = compare_scenarios(market, variants, code_commit="v")
    assert len(results) == 3
    with pytest.raises(BacktestError):
        compare_scenarios(market, (settings, settings), code_commit="v")


def test_sell_btc_fee_is_paid_only_when_the_native_origin_dust_covers_its_hold() -> None:
    settings = config()
    fees = replace(
        settings.policy.fees,
        schedule=FeeSchedule.parse(".001", ".001"),
        buy_asset=BTC,
        sell_asset=BTC,
    )
    result = run_backtest(
        dataset(),
        replace(settings, policy=replace(settings.policy, fees=fees)),
        code_commit="btc-hold-fixture",
    )
    assert result.metrics.cycles == 2
    assert result.metrics.final_grid_btc.value == Decimal(".000110")
    assert result.metrics.commission_btc.value == Decimal(".001890")
    assert result.metrics.reserved_btc.is_zero
    assert_source_conservation(result.sources, result.points[-1].state)
