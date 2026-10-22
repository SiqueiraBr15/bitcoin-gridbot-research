from dataclasses import replace

import pytest

from gridbot.backtest.engine import BacktestResult, run_backtest
from gridbot.backtest.execution import VirtualOrder
from gridbot.backtest.paper_bridge import settle_buy, settle_sell
from gridbot.domain import BTC, USDT, Money, Qty, Side
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperSettleBuy,
)
from gridbot.paper.simulation import PaperSimulation
from gridbot.portfolio import BuyExecutionRef
from gridbot.strategy import build_buy_intents, size_grid_buys
from tests.backtest.test_data import START
from tests.backtest.test_engine import config, dataset
from tests.paper.simulation_oracle import assert_source_conservation


@pytest.fixture(scope="module")
def result() -> BacktestResult:
    return run_backtest(dataset(), config(), code_commit="native-differential")


def test_identical_sources_native_runtime_stepwise_and_duplicate_consumption(
    result: BacktestResult,
) -> None:
    sim = PaperSimulation(result.sources.initial, run_ref=result.sources.run_ref, max_events=1000)
    before_observation = None
    for event in result.sources.events:
        command = event.command
        if isinstance(command, PaperObserveSell):
            before_observation = sim.snapshot()
        sim.apply(event.revision - 1, command)
        for point in result.points:
            if point.state.revision == sim.revision:
                assert sim.snapshot() == point.state
        if isinstance(command, PaperObserveSell):
            assert before_observation is not None
            assert sim.available_quote == before_observation.available_quote
            assert sim.remaining_grid_base == before_observation.remaining_grid_base
        if isinstance(command, PaperApplySell):
            assert before_observation is not None
            assert sim.available_quote.amount > before_observation.available_quote.amount
        assert_source_conservation(sim.source_log(), sim.snapshot())
    assert sim.snapshot() == result.points[-1].state
    for event in result.sources.events:
        if isinstance(event.command, (PaperSettleBuy, PaperApplySell)):
            prior = sim.snapshot()
            sim.apply(sim.revision, event.command)
            assert sim.snapshot() == prior


def test_recycled_quote_is_available_only_after_native_apply(result: BacktestResult) -> None:
    sim = PaperSimulation(result.sources.initial, run_ref=result.sources.run_ref, max_events=1000)
    for event in result.sources.events:
        if isinstance(event.command, PaperApplySell):
            break
        sim.apply(sim.revision, event.command)
    quote_before = sim.available_quote
    sim.apply(sim.revision, event.command)
    ref = sim.grid_state.cells[0].cycle_ref
    plan = build_buy_intents(
        sim.grid_state, size_grid_buys(sim.grid_state, sim.initial.rules, Money.parse("50", USDT))
    )
    intent = plan.intents[0]
    fee = config().policy.fees.commission(Side.BUY, intent.price, intent.qty)
    hold = Money(intent.price.notional(intent.qty), USDT) + fee
    assert quote_before.amount < hold.amount <= sim.available_quote.amount
    sim.apply(
        sim.revision,
        PaperPrepareBuy(plan, ref, fee, BuyExecutionRef(sim.initial.account.ref + ":BUY:RECYCLED")),
    )
    assert_source_conservation(sim.source_log(), sim.snapshot())


def test_bridge_refuses_overfill_foreign_order_missing_fee_and_excess_fee(
    result: BacktestResult,
) -> None:
    sim = PaperSimulation(result.sources.initial, run_ref=result.sources.run_ref, max_events=1000)
    prepare = result.sources.events[0].command
    assert isinstance(prepare, PaperPrepareBuy)
    sim.apply(0, prepare)
    context = sim.buy_context(prepare.cycle_ref)
    order = VirtualOrder(
        context.execution_ref.value,
        context.cycle_ref,
        Side.BUY,
        context.intent.price,
        context.intent.qty,
        START,
        START,
    )
    before = sim.snapshot()
    for quantity, fee in [
        (order.qty + Qty.parse(".001"), Money.zero(USDT)),
        (order.qty, None),
        (order.qty, Money.parse("1000", USDT)),
    ]:
        with pytest.raises((DomainError, ValueError)):
            settle_buy(sim, order, quantity, fee, config().policy.fees.buy_role)
        assert sim.snapshot() == before
    with pytest.raises(DomainError):
        settle_buy(
            sim,
            replace(order, ref="foreign"),
            order.qty,
            Money.zero(USDT),
            config().policy.fees.buy_role,
        )
    assert sim.snapshot() == before

    sell_sim = PaperSimulation(
        result.sources.initial, run_ref=result.sources.run_ref, max_events=1000
    )
    for event in result.sources.events:
        sell_sim.apply(sell_sim.revision, event.command)
        if isinstance(event.command, PaperPrepareSell):
            authorization = sell_sim.sell_authorization(event.command.execution_ref)
            break
    ctx = authorization.context
    sell = VirtualOrder(
        ctx.execution_ref.value,
        ctx.cycle_ref,
        Side.SELL,
        ctx.limit_price,
        ctx.requested_qty,
        START,
        START,
    )
    before = sell_sim.snapshot()
    for quantity, fee in [
        (sell.qty + Qty.parse(".001"), Money.zero(USDT)),
        (sell.qty, Money.parse(".001", BTC)),
        (sell.qty, None),
    ]:
        with pytest.raises((DomainError, ValueError)):
            settle_sell(sell_sim, sell, quantity, fee, config().policy.fees.sell_role)
        assert sell_sim.snapshot() == before
