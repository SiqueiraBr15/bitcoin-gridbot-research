"""P2L integration uses the native execution/evidence model and exact flow oracle."""

from dataclasses import replace
from fractions import Fraction

import pytest

from gridbot.backtest.partial_grid import run_partial_backtest
from gridbot.domain import BTC, USDT, FeeSchedule, Money, Side
from gridbot.domain.errors import DomainError
from gridbot.paper.simulation import PaperSimulation
from gridbot.paper.two_generation import PartialSourceLog, TwoGenerationPaper
from tests.backtest.test_engine import config, dataset


def legacy_market() -> tuple[str, ...]:
    return (
        "100,110,90,105,10",
        "100,106,89,100,10",
        *(("80,80,80,80,10",) * 168),
        "80,81,69,80,10",
        "80,91,79,90,10",
        "100,111,99,105,10",
    )


def assert_oracle(result: object) -> None:
    from gridbot.backtest.partial_grid import PartialBacktestRun

    assert isinstance(result, PartialBacktestRun)
    cash, btc, fees = Fraction(100), Fraction(0), Fraction(0)
    for point in result.points:
        for trade in result.trades:
            if trade.observed_at != point.time:
                continue
            q, notional, fee = (
                Fraction(trade.qty.value),
                Fraction(trade.price.notional(trade.qty)),
                Fraction(trade.fee.amount),
            )
            if trade.side is Side.BUY:
                cash -= notional + (fee if trade.fee.asset == USDT else 0)
                btc += q - (fee if trade.fee.asset == BTC else 0)
            else:
                cash += notional - (fee if trade.fee.asset == USDT else 0)
                btc -= q + (fee if trade.fee.asset == BTC else 0)
            fees += fee if trade.fee.asset == USDT else 0
        state = point.state
        assert cash == Fraction(state.available_quote.amount) + Fraction(
            state.active_buy_reservations.amount
        )
        assert btc == Fraction(state.remaining_grid_base.value)
        assert cash + btc * Fraction(point.price.value) == Fraction(point.quote_btc_equity.amount)
        assert cash >= 0
        assert btc >= 0


def test_full_runtime_transition_new_buy_and_legacy_sell_conserve_assets() -> None:
    cfg = config()
    cfg = replace(cfg, policy=replace(cfg.policy, ttl_bars=1000))
    result = run_partial_backtest(dataset(legacy_market()), cfg, code_commit="test")
    assert result.new_generations == 1
    assert result.new_buys >= 1
    assert result.legacy_sells >= 1
    assert len(result.base_by_generation) == 2
    assert isinstance(result.sources, PartialSourceLog)
    first = next(c for c in result.candidates if c.applied)
    assert first.plan is not None
    assert first.plan.allocation.source.grid_base.value > 0
    for trade in result.trades:
        if trade.cycle_ref.cycle_seq >= 1:
            assert trade.bar_open >= first.plan.signal[-1].close_time
    rebuilt = TwoGenerationPaper.replay(result.sources, max_events=1000)
    assert rebuilt.snapshot() == result.points[-1].state
    assert rebuilt.base_by_generation() == result.base_by_generation
    assert_oracle(result)


def test_future_bars_cannot_change_candidate_plan_or_prior_finance() -> None:
    one = legacy_market()
    two = (*one[:-3], "80,90,10,85,10", "85,200,20,100,10", "100,200,1,150,10")
    a = run_partial_backtest(dataset(one), config(), code_commit="test")
    b = run_partial_backtest(dataset(two), config(), code_commit="test")
    assert a.candidates[0] == b.candidates[0]
    cutoff = a.candidates[0].at
    assert [p for p in a.points if p.time.isoformat() <= cutoff] == [
        p for p in b.points if p.time.isoformat() <= cutoff
    ]


def test_zero_activity_is_reported_without_invented_return_or_cycle() -> None:
    market = dataset(("80,80,80,80,0",) * 170)
    result = run_partial_backtest(market, config(), code_commit="test")
    assert result.new_generations == 1
    assert result.new_buys == result.legacy_sells == 0
    assert result.metrics.cycles == 0
    assert result.metrics.final_equity == Money.parse("100", USDT)
    assert_oracle(result)


def test_partial_terminal_preserves_residual_and_can_lose_against_cash() -> None:
    market = dataset((*("80,80,80,80,10",) * 168, "80,81,69,80,.02", "80,81,60,65,10"))
    result = run_partial_backtest(market, config(), code_commit="test")
    assert result.new_buys == 1
    assert result.metrics.final_grid_btc.value > 0
    assert result.metrics.final_equity is not None
    assert result.metrics.final_equity.amount < 100
    assert_oracle(result)


def test_btc_commissions_are_funded_by_own_origin_not_core() -> None:
    cfg = config()
    cfg = replace(cfg, policy=replace(cfg.policy, fees=replace(cfg.policy.fees, buy_asset=BTC)))
    result = run_partial_backtest(dataset(legacy_market()), cfg, code_commit="test")
    assert result.new_buys >= 1
    assert_oracle(result)


def test_old_runtime_and_complete_prefix_remain_unchanged() -> None:
    from gridbot.backtest.engine import run_backtest

    market = dataset(("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,10"))
    base = run_backtest(market, config(), code_commit="test")
    result = run_partial_backtest(market, config(), code_commit="test")
    assert result.new_generations == 0
    assert result.points == base.points
    assert result.trades == base.trades
    assert result.metrics == replace(base.metrics, hypothetical_proportional_pnl=None)
    assert isinstance(result.sources, type(base.sources))
    assert (
        PaperSimulation.replay(base.sources, run_ref=config().run_ref, max_events=1000).snapshot()
        == base.points[-1].state
    )


def test_high_fee_does_not_gain_an_exposure_exception() -> None:
    cfg = config()
    cfg = replace(
        cfg,
        policy=replace(
            cfg.policy, fees=replace(cfg.policy.fees, schedule=FeeSchedule.parse(".1", ".1"))
        ),
    )
    result = run_partial_backtest(
        dataset((*("80,80,80,80,10",) * 168, "80,81,69,80,10", "80,91,79,90,10")),
        cfg,
        code_commit="test",
    )
    first = next(c for c in result.candidates if c.applied)
    assert first.plan is not None
    a = first.plan.allocation
    assert Fraction(a.exposure_numerator.amount) <= Fraction(9, 10) * Fraction(
        a.exposure_denominator.amount
    )
    assert_oracle(result)


def test_documented_halt_cannot_be_used_as_new_eligible_interval() -> None:
    from datetime import timedelta

    from gridbot.backtest.data import Dataset
    from gridbot.backtest.recenter import DOCUMENTED_HALT
    from tests.backtest.test_data import raw, spec

    start = DOCUMENTED_HALT.suspended - timedelta(minutes=1)
    end = start + timedelta(minutes=3)
    rows = "".join(
        f"{(start + timedelta(minutes=i)).isoformat()},"
        f"{(start + timedelta(minutes=i + 1)).isoformat()},80,80,80,80,10\n"
        for i in range(3)
    )
    market = Dataset(raw(rows), replace(spec(), start=start, end=end))
    cfg = replace(config(), effective_start=start, effective_end=end)
    with pytest.raises(DomainError, match="suspension"):
        run_partial_backtest(market, cfg, code_commit="test")
