"""History, residuals and asset conservation across native PAPER generations."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.backtest.execution import BNB
from gridbot.backtest.lifecycle import RangeCandidate
from gridbot.backtest.recenter import assess_recenter
from gridbot.domain import BTC, BTCUSDT, USDT, Money, OrderStatus, Price, Qty
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    PaperAccount,
    PaperApplySell,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
)
from gridbot.paper.generations import PaperRecenter
from gridbot.paper.simulation import PaperSimulation
from gridbot.storage.financial_codec import encode_contract
from gridbot.strategy import ArithmeticGridSpec, bootstrap_grid_state, build_arithmetic_grid
from tests.backtest.test_engine import config
from tests.backtest.test_safe_recenter import assessment, command, runtime, signal
from tests.paper.simulation_fixtures import buy_command, buy_fill_result, sell_command, sell_source
from tests.paper.simulation_oracle import assert_source_conservation


def supplied_cycle(
    sim: PaperSimulation,
    *,
    buy_fee: Money | None = None,
    sell_fee: Money | None = None,
) -> PaperSettleBuy:
    buy_fee = Money.parse(".01", USDT) if buy_fee is None else buy_fee
    sell_fee = Money.parse(".02", USDT) if sell_fee is None else sell_fee
    sim.apply(sim.revision, buy_command(sim, budget="90", hold="1"))
    bought = PaperSettleBuy(buy_fill_result(sim, fee=buy_fee))
    sim.apply(sim.revision, bought)
    sale = sell_command(sim, hold="0")
    sim.apply(sim.revision, sale)
    target = sim.sell_authorization(sale.execution_ref).context.limit_price
    observed = sell_source(sim, sale.execution_ref, fees=(sell_fee,), price=str(target.value))
    sim.apply(sim.revision, PaperObserveSell(observed))
    sim.apply(sim.revision, PaperApplySell(sale.execution_ref, sim.revision))
    return bought


def test_two_generations_keep_costs_proceeds_and_old_idempotency() -> None:
    sim = runtime(armed=True)
    bought = supplied_cycle(sim)
    first = sim.snapshot()
    assert first.buy_spending.amount > 0
    assert first.settled_sell_proceeds.amount > 0
    request = command(sim)
    sim.recenter(sim.revision, request)
    second_buy = supplied_cycle(sim)
    after = sim.snapshot()
    assert after.buy_spending.amount > first.buy_spending.amount
    assert after.settled_sell_proceeds.amount > first.settled_sell_proceeds.amount
    assert after.buy_spending.amount > sim.initial.initial_quote.amount
    next_request = command(sim, signal("100", start=168))
    sim.recenter(sim.revision, next_request)
    assert len(sim.generations) == 3
    assert sim.generations[0].final_economics == sim.generations[1].initial_economics
    assert sim.generations[1].final_economics == sim.generations[2].initial_economics
    sequences = {bought.finalized.cycle_ref.cycle_seq, second_buy.finalized.cycle_ref.cycle_seq}
    assert len(sequences) == 2
    assert min(c.cycle_seq for c in sim.grid_state.cells) > max(sequences)
    current = sim.snapshot(), sim.source_log(), sim.generations
    for duplicate in (bought, second_buy, request, next_request):
        assert sim.apply(sim.revision, duplicate) == sim.revision
    assert (sim.snapshot(), sim.source_log(), sim.generations) == current
    replay = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=1000)
    assert replay.snapshot() == sim.snapshot()
    assert replay.generations == sim.generations
    assert_source_conservation(sim.source_log(), sim.snapshot())


@pytest.mark.parametrize(
    "case", ["sell_open", "unknown", "unapplied", "partial", "released", "dust", "third_fee"]
)
def test_native_source_closure_cannot_be_replaced_by_a_flat_looking_view(case: str) -> None:
    sim = runtime(armed=True)
    fee = Money.parse(".000032", BTC) if case == "dust" else Money.parse("0", USDT)
    if case == "third_fee":
        fee = Money.parse("1", BNB)
    sim.apply(0, buy_command(sim, budget="90", hold="1"))
    sim.apply(sim.revision, PaperSettleBuy(buy_fill_result(sim, fee=fee)))
    sale = sell_command(sim, hold="0")
    sim.apply(sim.revision, sale)
    target = str(sim.sell_authorization(sale.execution_ref).context.limit_price.value)
    if case != "sell_open":
        status = (
            None
            if case == "unknown"
            else OrderStatus.CANCELED
            if case in ("partial", "released")
            else OrderStatus.FILLED
        )
        quantity = (
            Qty.parse(".1") if case == "partial" else Qty.zero() if case == "released" else None
        )
        source = sell_source(
            sim,
            sale.execution_ref,
            status=status,
            qty=quantity,
            fees=(Money.parse(".01", USDT),),
            price=target,
        )
        sim.apply(sim.revision, PaperObserveSell(source))
        if case not in ("unknown", "unapplied"):
            sim.apply(sim.revision, PaperApplySell(sale.execution_ref, sim.revision))
        if case == "released":
            sim.apply(sim.revision, PaperReleaseNoFill(sale.execution_ref))
    result = assessment(sim)
    assert not result.applicable
    assert result.plan is not None
    if case == "third_fee":
        assert sim.remaining_grid_base.is_zero
        assert "THIRD_ASSET_FEE_OBLIGATION" in result.blockers
    if case == "dust":
        assert sim.remaining_grid_base > Qty.zero()
        assert all(c.phase.value == "WAITING_BUY" for c in sim.grid_state.cells)
        assert "UNCONSUMED_BUY_ORIGIN" in result.blockers
    before = sim.source_log(), sim.snapshot(), sim.generations
    with pytest.raises(DomainError):
        sim.recenter(sim.revision, PaperRecenter(result.plan, result.candidate.candle))
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before


def test_generation_cannot_consume_core_or_import_a_numeric_balance() -> None:
    sim = runtime()
    original = command(sim)
    fake_balances = replace(original.plan.previous.balances, grid_base=Qty.parse("100"))
    fake = replace(original.plan.previous, balances=fake_balances)
    proposal = replace(original.plan, previous=fake)
    before = sim.source_log()
    with pytest.raises(DomainError):
        sim.recenter(0, PaperRecenter(proposal, original.current_candle))
    assert sim.source_log() == before
    with pytest.raises(DomainError):
        encode_contract(original.plan)
    with pytest.raises(DomainError):
        sim.apply(0, cast(PaperRecenter, original.plan))
    assert sim.remaining_grid_base == Qty.zero()


def test_past_generation_signal_does_not_become_current_after_geometry_changes() -> None:
    sim = runtime()
    sim.recenter(0, command(sim))
    old_time_signal = command(sim, signal("120"))
    before = sim.source_log()
    with pytest.raises(DomainError, match="old generation"):
        sim.recenter(sim.revision, old_time_signal)
    assert sim.source_log() == before


def test_recenter_quota_and_foreign_initial_preserve_complete_history() -> None:
    sim = runtime(limit=1)
    request = command(sim)
    sim.recenter(0, request)
    before = sim.source_log()
    with pytest.raises(DomainError, match="history full"):
        sim.recenter(1, command(sim, signal("120", start=168)))
    assert sim.recenter(1, request) == 1
    assert sim.source_log() == before
    foreign = replace(
        before, initial=replace(before.initial, initial_quote=Money.parse("101", USDT))
    )
    with pytest.raises(DomainError):
        PaperSimulation.replay(foreign, run_ref=sim.run_ref, max_events=1000)


@pytest.mark.parametrize(("price", "budget"), [("5", "90"), ("80", ".00001")])
def test_invalid_geometry_or_unfundable_sizing_has_no_generation(price: str, budget: str) -> None:
    sim = runtime()
    from gridbot.backtest.lifecycle import RangeCandidate
    from gridbot.backtest.recenter import assess_recenter
    from tests.backtest.test_engine import config

    bars = signal(price)
    result = assess_recenter(
        sim.generation_evidence(),
        sim.initial.rules,
        RangeCandidate(bars[-1], sim.grid_state.plan, 168),
        bars,
        config().policy.fees,
        Money.parse(budget, USDT),
        "CFG:UNIT",
        pending_orders=(),
        continuity_clear=True,
    )
    assert not result.applicable
    assert result.plan is None
    assert len(sim.generations) == 1


@given(st.integers(1, 3), st.integers(0, 100), st.integers(0, 100))
@settings(max_examples=20, deadline=None, derandomize=True)
def test_fraction_oracle_conserves_btc_quote_and_history_across_generations(
    count: int,
    buy_cents: int,
    sell_cents: int,
) -> None:
    sim = runtime()
    for generation in range(count):
        request = command(
            sim, signal("80" if generation % 2 == 0 else "120", start=168 * generation)
        )
        sim.recenter(sim.revision, request)
        bought = supplied_cycle(
            sim,
            buy_fee=Money(Decimal(buy_cents) / 100, USDT),
            sell_fee=Money(Decimal(sell_cents) / 100, USDT),
        )
        values = assert_source_conservation(sim.source_log(), sim.snapshot())
        assert values["remaining"] == 0
        assert values["available"] == Fraction(100) + values["proceeds"] - values["spending"]
        original = sim.snapshot()
        sim.apply(sim.revision, bought)
        assert sim.snapshot() == original
    replay = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=1000)
    assert replay.snapshot() == sim.snapshot()
    assert replay.generations == sim.generations


@given(st.integers(1, 9), st.integers(20001, 22099))
@settings(max_examples=25, deadline=None, derandomize=True)
def test_integer_tick_and_rational_bundle_oracles(intervals: int, reference_ticks: int) -> None:
    cfg = config()
    geometry = build_arithmetic_grid(
        ArithmeticGridSpec(
            BTCUSDT,
            Price.parse("100"),
            Price(Decimal(100 + intervals * 10)),
            intervals,
        ),
        cfg.rules,
    )
    initial = replace(
        runtime().initial,
        account=PaperAccount("PAPER:GEOMETRY"),
        grid_state=bootstrap_grid_state(geometry, Price.parse("80")),
    )
    sim = PaperSimulation(initial, run_ref="SIM:GEOMETRY", max_events=1000)
    reference = Decimal(reference_ticks) / 100
    bars = signal(str(reference))
    result = assess_recenter(
        sim.generation_evidence(),
        cfg.rules,
        RangeCandidate(bars[-1], geometry, 168),
        bars,
        cfg.policy.fees,
        cfg.notional_budget,
        "CFG:GEOMETRY",
        pending_orders=(),
        continuity_clear=True,
    )
    assert result.applicable
    assert result.plan is not None
    plan = result.plan
    first_tick = reference_ticks - (intervals // 2) * 1000
    expected = tuple(Fraction(first_tick + i * 1000, 100) for i in range(intervals + 1))
    assert tuple(Fraction(p.value) for p in plan.new_state.plan.prices) == expected
    intents = plan.buy_plan.intents
    if intents:
        prices = tuple(Fraction(i.price.value) for i in intents)
        step = Fraction(cfg.rules.quantity.step_size.value)
        expected_quantity = (Fraction(90) // (sum(prices) * step)) * step
        assert all(Fraction(i.qty.value) == expected_quantity for i in intents)
        cost = sum(prices) * expected_quantity
        assert cost <= Fraction(90) < cost + sum(prices) * step
        quote_fee = cost * Fraction(cfg.policy.fees.schedule.maker_rate)
        assert Fraction(plan.required_quote.amount) == cost + quote_fee
    before = sim.snapshot()
    sim.recenter(0, PaperRecenter(plan, bars[-1]))
    after = sim.snapshot()
    assert replace(after, grid_state=before.grid_state, revision=0) == before
