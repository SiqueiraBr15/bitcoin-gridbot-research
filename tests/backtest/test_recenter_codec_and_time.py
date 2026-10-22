"""Versioned source recovery and explicit causal market boundaries."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from gridbot.backtest.data import Dataset
from gridbot.backtest.generation_codec import MARKER, decode_generation, encode_generation
from gridbot.backtest.recenter import DOCUMENTED_HALT, GridRecenterAssessment, run_recenter_backtest
from gridbot.domain import BTC, Money
from gridbot.domain.errors import DomainError
from gridbot.paper.generations import PaperRecenter
from tests.backtest.test_data import raw, spec
from tests.backtest.test_engine import config, dataset
from tests.backtest.test_safe_recenter import command, runtime


@pytest.mark.parametrize(
    "damage", ["marker", "payload", "extra", "duplicate", "truncated", "unicode"]
)
def test_corrupt_generation_source_is_never_repaired_or_partially_applied(damage: str) -> None:
    sim = runtime()
    original = encode_generation(command(sim))
    data = json.loads(original)
    if damage == "marker":
        encoded = original.replace(MARKER, "UNKNOWN")
    elif damage == "payload":
        encoded = json.dumps(dict(recenter_schema=MARKER, payload=None))
    elif damage == "extra":
        encoded = json.dumps(dict(**data, additional="unapproved"))
    elif damage == "duplicate":
        encoded = '{"recenter_schema":"extra",' + original[1:]
    elif damage == "truncated":
        encoded = original[:-1]
    else:
        encoded = original + chr(0xD800)
    before = sim.source_log()
    with pytest.raises(DomainError):
        decode_generation(encoded)
    assert sim.source_log() == before


def test_direct_assessment_cannot_hide_missing_plan_or_native_blockers() -> None:
    request = command(runtime())
    from gridbot.backtest.lifecycle import RangeCandidate

    candidate = RangeCandidate(request.current_candle, request.plan.previous.state.plan, 168)
    with pytest.raises(DomainError):
        GridRecenterAssessment(candidate, request.plan.previous, None, ())
    costly = replace(
        request.plan, projected_buy_fees=(Money.parse("11", request.plan.notional_budget.asset),)
    )
    with pytest.raises(DomainError):
        GridRecenterAssessment(candidate, costly.previous, costly, ())


def test_base_fee_cannot_be_projected_above_the_acquisition() -> None:
    request = command(runtime())
    with pytest.raises(DomainError):
        replace(request.plan, projected_buy_fees=(Money.parse("2", BTC),))


@pytest.mark.parametrize("policy", ["P0", "P1", "P2"])
def test_even_complete_candles_do_not_authorize_trading_through_documented_halt(
    policy: str,
) -> None:
    start = DOCUMENTED_HALT.suspended - timedelta(minutes=1)
    end = start + timedelta(minutes=3)
    rows = "".join(
        f"{(start + timedelta(minutes=i)).isoformat()},"
        f"{(start + timedelta(minutes=i + 1)).isoformat()},80,80,80,80,10\n"
        for i in range(3)
    )
    market = Dataset(raw(rows), replace(spec(), start=start, end=end))
    cfg = replace(config(), effective_start=start, effective_end=end)
    with pytest.raises(DomainError, match="market suspension"):
        run_recenter_backtest(
            market, cfg, code_commit="unit", policy=policy, configuration_ref="CFG:UNIT"
        )


def test_p2_prefix_is_invariant_to_prices_in_unobserved_future_candles() -> None:
    prefix = ("80,80,80,80,10",) * 168
    one = dataset((*prefix, "80,81,69,80,10", "80,81,79,80,10"))
    two = dataset((*prefix, "80,150,20,120,10", "120,250,10,150,10"))
    first = run_recenter_backtest(
        one, config(), code_commit="unit", policy="P2", configuration_ref="CFG:UNIT"
    )
    second = run_recenter_backtest(
        two, config(), code_commit="unit", policy="P2", configuration_ref="CFG:UNIT"
    )
    assert first.decisions[0].assessment == second.decisions[0].assessment
    assert first.generations[1].state_at_creation == second.generations[1].state_at_creation
    assert first.result.points[167] == second.result.points[167]


def test_raw_pure_plan_is_not_a_paper_command_or_balance_import() -> None:
    sim = runtime()
    plan = command(sim).plan
    before = sim.source_log()
    with pytest.raises(DomainError):
        sim.recenter(0, cast(PaperRecenter, plan))
    assert sim.source_log() == before


@pytest.mark.parametrize("reference", ["CFG:" + chr(0xD800), "CFG:" + chr(0xD83D) + chr(0xDE00)])
def test_source_codec_rejects_raw_surrogates_before_identity_normalization(reference: str) -> None:
    request = command(runtime())
    malformed = replace(request, plan=replace(request.plan, configuration_ref=reference))
    with pytest.raises(DomainError):
        encode_generation(malformed)


def test_valid_unicode_identity_survives_generation_source_roundtrip() -> None:
    request = command(runtime())
    request = replace(request, plan=replace(request.plan, configuration_ref="CFG:ação:😀"))
    assert decode_generation(encode_generation(request)) == request


def test_generation_identity_increments_are_not_completed_trading_cycles() -> None:
    market = dataset(("80,80,80,80,10",) * 170)
    run = run_recenter_backtest(
        market, config(), code_commit="unit", policy="P2", configuration_ref="CFG:UNIT"
    )
    assert len(run.generations) == 2
    assert not run.result.trades
    assert run.result.metrics.cycles == 0
