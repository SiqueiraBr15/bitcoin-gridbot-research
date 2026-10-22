"""Finite adversarial witnesses for the flat-only PAPER migration contract."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from gridbot.backtest import export
from gridbot.backtest.engine import run_backtest
from gridbot.backtest.generation_codec import decode_generation, encode_generation
from gridbot.backtest.lifecycle import RangeCandidate
from gridbot.backtest.recenter import GridRecenterAssessment, assess_recenter, run_recenter_backtest
from gridbot.domain import BTCUSDT, USDT, Candle, Money, Price, Qty, Timeframe
from gridbot.domain.errors import DomainError
from gridbot.paper import simulation
from gridbot.paper.accounting import PaperAccount, PaperCommand, PaperInitialState, PaperSettleBuy
from gridbot.paper.generations import PaperRecenter
from gridbot.paper.simulation import PaperSimulation, SimulationEvent
from gridbot.storage.paper_codec import decode_command, encode_command
from gridbot.strategy import bootstrap_grid_state, build_arithmetic_grid
from tests.backtest.test_data import START
from tests.backtest.test_engine import config, dataset
from tests.paper.simulation_fixtures import buy_command, buy_fill_result
from tests.paper.simulation_oracle import assert_source_conservation


def signal(price: str = "80", *, start: int = 0) -> tuple[Candle, ...]:
    value = Price.parse(price)
    return tuple(
        Candle(
            BTCUSDT,
            Timeframe.minutes(1),
            START + timedelta(minutes=i),
            START + timedelta(minutes=i + 1),
            value,
            value,
            value,
            value,
            Qty.parse("10"),
        )
        for i in range(start, start + 168)
    )


def runtime(*, armed: bool = False, limit: int = 1000) -> PaperSimulation:
    cfg = config()
    state = bootstrap_grid_state(
        build_arithmetic_grid(cfg.grid, cfg.rules), Price.parse("105" if armed else "80")
    )
    return PaperSimulation(
        PaperInitialState(PaperAccount("PAPER:A19_4_UNIT"), state, cfg.rules, cfg.initial_quote),
        run_ref="SIM:A19_4_UNIT",
        max_events=limit,
    )


def assessment(
    sim: PaperSimulation, bars: tuple[Candle, ...] | None = None
) -> GridRecenterAssessment:
    bars = signal() if bars is None else bars
    return assess_recenter(
        sim.generation_evidence(),
        sim.initial.rules,
        RangeCandidate(bars[-1], sim.grid_state.plan, 168),
        bars,
        config().policy.fees,
        config().notional_budget,
        "CFG:A19_4_UNIT",
        pending_orders=(),
        continuity_clear=True,
    )


def command(sim: PaperSimulation, bars: tuple[Candle, ...] | None = None) -> PaperRecenter:
    result = assessment(sim, bars)
    assert result.plan is not None
    return PaperRecenter(result.plan, result.candidate.candle)


def test_one_flat_transition_is_atomic_zero_cost_and_replayable() -> None:
    sim = runtime()
    before = sim.snapshot()
    request = command(sim)
    assert not request.plan.blockers
    assert request.plan.reference == Price.parse("80")
    assert request.plan.new_state.plan.spec.lower_price == Price.parse("70")
    assert request.plan.new_state.plan.spec.upper_price == Price.parse("90")
    assert request.plan.buy_plan.sizing.allocated_quote.amount <= Decimal("90")
    assert sim.recenter(0, request) == 1
    after = sim.snapshot()
    assert after.grid_state == request.plan.new_state
    assert replace(after, grid_state=before.grid_state, revision=before.revision) == before
    assert sim.initial.initial_quote == Money.parse("100", USDT)
    assert sim.generations[0].final_economics == sim.generations[1].initial_economics
    assert sim.generations[1].predecessor == sim.generations[0].ref
    assert sim.source_log().version == 2
    assert all(c.cycle_seq == 1 for c in sim.grid_state.cells)
    replay = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=1000)
    assert replay.snapshot() == after
    assert replay.generations == sim.generations
    assert_source_conservation(sim.source_log(), after)


def test_duplicate_is_noop_and_conflict_never_creates_another_generation() -> None:
    sim = runtime()
    request = command(sim)
    sim.recenter(0, request)
    before = sim.source_log(), sim.snapshot(), sim.generations
    assert sim.apply(1, request) == 1
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before
    conflicting = replace(request, plan=replace(request.plan, configuration_ref="CFG:DIFFERENT"))
    with pytest.raises(DomainError, match="conflicting generation"):
        sim.recenter(1, conflicting)
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before


@pytest.mark.parametrize(
    "damage", ["revision", "generation", "account", "run", "balances", "cycles"]
)
def test_forged_or_stale_evidence_fails_without_mutation(damage: str) -> None:
    sim = runtime()
    request = command(sim)
    evidence = request.plan.previous
    if damage == "revision":
        evidence = replace(evidence, revision=1)
    elif damage == "generation":
        evidence = replace(evidence, generation=1)
    elif damage == "account":
        evidence = replace(evidence, account_ref="PAPER:FOREIGN")
    elif damage == "run":
        evidence = replace(evidence, run_ref="SIM:FOREIGN")
    elif damage == "balances":
        balances = replace(evidence.balances, available_quote=Money.parse("101", USDT))
        evidence = replace(evidence, balances=balances)
    else:
        evidence = replace(evidence, next_cycle_seq=100)
    request = replace(request, plan=replace(request.plan, previous=evidence))
    before = sim.source_log(), sim.snapshot(), sim.generations
    with pytest.raises(DomainError):
        sim.recenter(0, request)
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before


@pytest.mark.parametrize(
    "damage", ["short", "gap", "duplicate", "inside", "stale", "fees", "policy"]
)
def test_invalid_signal_and_plan_are_not_financial_authority(damage: str) -> None:
    sim = runtime()
    request = command(sim)
    before = sim.source_log()

    def corrupt() -> None:
        if damage == "short":
            replace(request.plan, signal=request.plan.signal[:-1])
        elif damage == "gap":
            replace(request.plan, signal=(*request.plan.signal[:-1], signal(start=1)[-1]))
        elif damage == "duplicate":
            replace(request.plan, signal=(*request.plan.signal[:-1], request.plan.signal[-2]))
        elif damage == "inside":
            replace(request.plan, signal=(signal("100")[0], *request.plan.signal[1:]))
        elif damage == "stale":
            replace(request, current_candle=signal(start=1)[-1])
        elif damage == "fees":
            replace(request.plan, projected_buy_fees=())
        else:
            replace(request.plan, policy="UNAPPROVED")

    with pytest.raises(DomainError):
        corrupt()
    assert sim.source_log() == before


@pytest.mark.parametrize("phase", ["buy_hold", "btc_position", "third_fee"])
def test_native_pending_commitments_block_recenter(phase: str) -> None:
    sim = runtime(armed=True)
    sim.apply(0, buy_command(sim, budget="90", hold=".1"))
    if phase != "buy_hold":
        fee = Money.parse("0", USDT) if phase == "btc_position" else Money.parse("1", BTCUSDT.base)
        if phase == "third_fee":
            from gridbot.backtest.execution import BNB

            fee = Money.parse("1", BNB)
        sim.apply(sim.revision, PaperSettleBuy(buy_fill_result(sim, fee=fee)))
    check = assessment(sim)
    assert not check.applicable
    assert check.blockers
    request = command(sim)
    before = sim.source_log(), sim.snapshot(), sim.generations
    with pytest.raises(DomainError, match="RECENTER_BLOCKED"):
        sim.recenter(sim.revision, request)
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before


def test_insufficient_fee_budget_is_a_block_not_a_resize() -> None:
    sim = runtime()
    original = command(sim)
    excessive = replace(original.plan, projected_buy_fees=(Money.parse("11", USDT),))
    assert "CAPITAL_INSUFFICIENT_WITH_FEES" in excessive.blockers
    before = sim.source_log()
    with pytest.raises(DomainError):
        sim.recenter(0, PaperRecenter(excessive, original.current_candle))
    assert sim.source_log() == before
    assert excessive.buy_plan == original.plan.buy_plan


def test_late_publication_failure_preserves_the_entire_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = runtime()
    request = command(sim)
    before = sim.source_log(), sim.snapshot(), sim.generations

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected before head publication")

    with monkeypatch.context() as patch:
        patch.setattr(simulation, "SimulationEvent", fail)
        with pytest.raises(RuntimeError, match="injected"):
            sim.recenter(0, request)
    assert (sim.source_log(), sim.snapshot(), sim.generations) == before


def test_two_concurrent_expected_heads_have_only_one_winner() -> None:
    sim = runtime()
    request = command(sim)

    def attempt(_: int) -> str:
        try:
            sim.recenter(0, request)
            return "APPLIED"
        except DomainError:
            return "STALE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, (0, 1)))
    assert sorted(results) == ["APPLIED", "STALE"]
    assert sim.revision == 1
    assert len(sim.generations) == 2


def test_source_versions_truncation_and_duplicate_events_fail_closed() -> None:
    sim = runtime()
    sim.recenter(0, command(sim))
    log = sim.source_log()
    for bad in (
        replace(log, version=1),
        replace(log, revision=2),
        replace(
            log,
            events=(*log.events, SimulationEvent(log.run_ref, 2, log.events[0].command)),
            revision=2,
        ),
    ):
        with pytest.raises(DomainError):
            PaperSimulation.replay(bad, run_ref=sim.run_ref, max_events=1000)
    assert sim.source_log() == log


def test_new_envelope_roundtrips_and_durable_codecs_reject_it() -> None:
    request = command(runtime())
    encoded = encode_generation(request)
    assert decode_generation(encoded) == request
    assert encode_generation(decode_generation(encoded)) == encoded
    with pytest.raises(DomainError):
        decode_command(encoded)
    with pytest.raises(DomainError):
        encode_command(cast(PaperCommand, request))


@pytest.mark.parametrize(
    "tail", [("80,81,69,80,10", "80,81,79,80,10"), ("80,81,59,60,10", "60,61,49,50,10")]
)
def test_real_native_pipeline_can_gain_or_lose_with_recenter(
    tail: tuple[str, ...],
    tmp_path: Path,
) -> None:
    market = dataset(("80,80,80,80,10",) * 168 + tail)
    cfg = config()
    baseline = run_backtest(market, cfg, code_commit="unit")
    p1 = run_recenter_backtest(
        market, cfg, code_commit="unit", policy="P1", configuration_ref="CFG:UNIT"
    )
    p2 = run_recenter_backtest(
        market, cfg, code_commit="unit", policy="P2", configuration_ref="CFG:UNIT"
    )
    assert p1.result.sources == baseline.sources
    assert p1.result.metrics == baseline.metrics
    assert sum(d.applied for d in p2.decisions) == 1
    assert p2.result.metrics.cycles == sum(t.side.value == "SELL" for t in p2.result.trades)
    assert p2.result.metrics.final_equity is not None
    assert baseline.metrics.final_equity is not None
    if tail[-1].startswith("60"):
        assert p2.result.metrics.final_equity.amount < baseline.metrics.final_equity.amount
    else:
        assert p2.result.metrics.final_equity.amount > baseline.metrics.final_equity.amount
    assert p2.result.trades[0].bar_open >= p2.decisions[0].assessment.candidate.candle.close_time
    final = p2.result.points[-1]
    assert_source_conservation(p2.result.sources, final.state)
    assert Fraction(final.quote_btc_equity.amount) == (
        Fraction(final.state.available_quote.amount)
        + Fraction(final.state.active_buy_reservations.amount)
        + Fraction(final.state.remaining_grid_base.value) * Fraction(final.price.value)
    )
    export.export_run(p2.result, tmp_path / "run", dataset=market)
    recovered = export.replay_sources(tmp_path / "run/paper_sources.jsonl", max_events=1000)
    assert recovered.snapshot() == final.state
    assert recovered.generations == p2.generations


def test_ingress_and_generation_views_cannot_change_owned_sources() -> None:
    sim = runtime()
    request = command(sim)
    sim.recenter(0, request)
    original = deepcopy(sim.source_log())
    object.__setattr__(request.plan, "configuration_ref", "CFG:TAMPERED")
    detached = sim.generations
    object.__setattr__(detached[-1], "ref", "PAPER:FOREIGN:GEN:1")
    assert sim.source_log() == original
    assert sim.generations[-1].ref == "PAPER:A19_4_UNIT:GEN:1"


@pytest.mark.parametrize("condition", ["unknown", "suspension"])
def test_external_order_or_continuity_uncertainty_blocks_pure_assessment(condition: str) -> None:
    sim = runtime()
    bars = signal()
    result = assess_recenter(
        sim.generation_evidence(),
        sim.initial.rules,
        RangeCandidate(bars[-1], sim.grid_state.plan, 168),
        bars,
        config().policy.fees,
        config().notional_budget,
        "CFG:UNIT",
        pending_orders=(),
        continuity_clear=condition != "suspension",
        unknown_orders=("provided-unresolved-order",) if condition == "unknown" else (),
    )
    assert not result.applicable
    assert (
        "ORDER_STATUS_UNKNOWN" if condition == "unknown" else "MARKET_CONTINUITY_UNRESOLVED"
    ) in result.blockers
    assert result.plan is not None
    before = sim.source_log()
    with pytest.raises(DomainError, match="RECENTER_BLOCKED"):
        sim.recenter(0, PaperRecenter(result.plan, bars[-1]))
    assert sim.source_log() == before
