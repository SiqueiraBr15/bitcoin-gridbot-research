"""Finite-parent A19.4 offline comparison; supplied PAPER sources, no exchange access."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

from scripts.a19_2_study import worker, write

from gridbot.application.sell_terminal import SellTerminalOutcome
from gridbot.backtest import engine
from gridbot.backtest.configuration import configuration as export_configuration
from gridbot.backtest.data import BacktestError, Dataset, check
from gridbot.backtest.export import json_value
from gridbot.backtest.generation_codec import encode_generation
from gridbot.backtest.recenter import RecenterDecision, RecenterRun, run_recenter_backtest
from gridbot.domain import Candle
from gridbot.paper.accounting import PaperApplySell, PaperObserveSell, PaperPrepareBuy
from gridbot.paper.generations import GridGeneration, PaperRecenter
from gridbot.paper.simulation import PaperSimulation


def closed_bar(candle: Candle) -> dict[str, object]:
    return dict(
        open_time=candle.open_time,
        close_time=candle.close_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )


def decision_record(decision: RecenterDecision) -> dict[str, object]:
    a = decision.assessment
    plan = a.plan
    proposed = None
    if plan is not None:
        envelope = encode_generation(PaperRecenter(plan, a.candidate.candle))
        proposed = dict(
            predecessor=plan.previous.generation_ref,
            next_generation=plan.next_generation_ref,
            reference=plan.reference,
            at=plan.at,
            geometry=plan.new_state.plan,
            new_cells=plan.new_state.cells,
            sizing=plan.buy_plan.sizing,
            notional_budget=plan.notional_budget,
            projected_buy_fees=plan.projected_buy_fees,
            required_quote=plan.required_quote,
            configuration_ref=plan.configuration_ref,
            policy=plan.policy,
            context_blockers=plan.context_blockers,
            supplied_plan_envelope=json.loads(envelope),
            supplied_plan_sha256=hashlib.sha256(envelope.encode("utf8")).hexdigest(),
            note="Forecasts and expected pre-state, never a balance import or charged fee",
        )
    return dict(
        candidate_at=a.candidate.candle.close_time,
        closed_signal_bar=closed_bar(a.candidate.candle),
        consecutive=a.candidate.consecutive,
        previous_grid=a.candidate.grid,
        evidence=a.evidence,
        status=a.status,
        blockers=a.blockers,
        mathematically_valid=a.mathematically_valid,
        applicable=a.applicable,
        applied=decision.applied,
        revision_after=decision.revision_after,
        plan=proposed,
    )


def generation_record(g: GridGeneration, run: RecenterRun) -> dict[str, object]:
    upper = (
        g.source_end_revision
        if g.source_end_revision is not None
        else run.result.sources.revision + 1
    )
    revisions = tuple(
        e.revision
        for e in run.result.sources.events
        if g.source_start_revision < e.revision < upper
    )
    buy_cycles = {
        e.command.cycle_ref
        for e in run.result.sources.events
        if e.revision in revisions and isinstance(e.command, PaperPrepareBuy)
    }
    operations = tuple(t for t in run.result.trades if t.cycle_ref in buy_cycles)
    return dict(
        ref=g.ref,
        predecessor=g.predecessor,
        ordinal=g.ordinal,
        configuration_ref=run.configuration_ref,
        original_experiment_configuration=export_configuration(run.result.config),
        source_start_revision=g.source_start_revision,
        source_end_revision=g.source_end_revision,
        created_at=g.created_at,
        closed_at=g.closed_at,
        reason=g.reason,
        signal_at=None if g.transition is None else g.transition.plan.at,
        state_at_creation=g.state_at_creation,
        state_at_closure=g.state_at_closure,
        initial_economics=g.initial_economics,
        final_economics=g.final_economics,
        source_event_revisions=revisions,
        cycle_refs=tuple(sorted(buy_cycles)),
        linked_operations=operations,
        fees=tuple(
            dict(order_ref=t.order_ref, observed_at=t.observed_at, fee=t.fee) for t in operations
        ),
        status="ACTIVE" if g.source_end_revision is None else "ECONOMICALLY_CLOSED",
    )


def transition_oracle(run: RecenterRun) -> list[dict[str, object]]:
    log = run.result.sources
    verified = []
    for e in log.events:
        if not isinstance(e.command, PaperRecenter):
            continue
        prefixes = []
        for end in (e.revision - 1, e.revision):
            events = log.events[:end]
            version = 2 if any(isinstance(v.command, PaperRecenter) for v in events) else 1
            prefix = replace(log, events=events, revision=end, version=version)
            sim = PaperSimulation.replay(
                prefix, run_ref=log.run_ref, max_events=run.result.config.max_events
            )
            prefixes.append(sim.snapshot())
        before, after = prefixes
        check(
            replace(after, grid_state=before.grid_state, revision=before.revision) == before,
            "generation changed economic values",
        )
        check(
            before.remaining_grid_base.is_zero and before.reserved_grid_base.is_zero,
            "generation retained BTC exposure",
        )
        check(before.active_buy_reservations.amount == 0, "generation retained quote hold")
        verified.append(
            dict(
                revision=e.revision,
                predecessor=e.command.plan.previous.generation_ref,
                next_generation=e.command.plan.next_generation_ref,
                economic_state_unchanged=True,
                forced_trades=0,
                reconfiguration_fees="0",
                scope="no order/trade in metadata transition",
            )
        )
    return verified


def diagnostics(market: Dataset, run: RecenterRun) -> dict[str, object]:
    observations = {
        e.revision: e.command.evidence
        for e in run.result.sources.events
        if isinstance(e.command, PaperObserveSell)
    }
    completed_from_sources = sum(
        observations[e.command.evidence_revision].reconciliation.outcome
        is SellTerminalOutcome.FULL_EXECUTION
        for e in run.result.sources.events
        if isinstance(e.command, PaperApplySell)
    )
    check(completed_from_sources == run.result.metrics.cycles, "completed cycle source mismatch")
    cash = holds = btc = nav = Fraction()

    for left, right in pairwise(run.result.points):
        seconds = (right.time - left.time) // timedelta(seconds=1)
        check(seconds > 0, "positive integration interval required")
        cash += Fraction(left.state.available_quote.amount) * seconds
        holds += Fraction(left.state.active_buy_reservations.amount) * seconds
        btc += Fraction(left.btc_mark.amount) * seconds
        nav += Fraction(left.quote_btc_equity.amount) * seconds
    check(cash + holds + btc == nav, "capital-time conservation")
    final = run.result.points[-1]
    return dict(
        classification="EXPLORATORY_IN_SAMPLE",
        lifecycle_policy=run.policy,
        configuration_ref=run.configuration_ref,
        code_commit=run.result.code_commit,
        dataset_sha256=market.sha256,
        candidate_threshold=168,
        candidates=tuple(decision_record(d) for d in run.decisions),
        eligible=sum(d.assessment.applicable for d in run.decisions),
        blocked=sum(not d.assessment.applicable for d in run.decisions),
        reconfigurations=sum(d.applied for d in run.decisions),
        generations=tuple(generation_record(g, run) for g in run.generations),
        transition_oracle=transition_oracle(run),
        completed_cycle_source_oracle=completed_from_sources,
        no_forced_sale=True,
        outside_closed_bar_count=run.outside_closed_bars,
        outside_sample_duration_seconds=run.outside_sample_seconds,
        outside_semantics=(
            "close classified against generation processing bar before recenter; not intrabar dwell"
        ),
        cash_time_fraction=cash / nav if nav else None,
        buy_hold_time_fraction=holds / nav if nav else None,
        btc_time_fraction=btc / nav if nav else None,
        cash_time_integral=cash,
        holds_time_integral=holds,
        btc_time_integral=btc,
        nav_time_integral=nav,
        integration="left-close capital-time samples; initial warmup hour excluded",
        idle_cash_reference=dict(
            initial_quote=run.result.config.initial_quote,
            final_equity=run.result.config.initial_quote,
            return_pct=Fraction(),
            max_drawdown=Fraction(),
            final_grid_btc="0",
            final_btc_equivalent=Fraction(run.result.config.initial_quote.amount)
            / Fraction(final.price.value),
        ),
        trust_boundary=(
            "supplied offline data/configuration; no authenticated exchange state "
            "or durable checkpoint"
        ),
    )


def study(
    dataset: Path,
    configuration: Path,
    output: Path,
    commit: str,
    policy: str,
    configuration_ref: str,
) -> None:
    def execute(
        market: Dataset, cfg: engine.BacktestConfig, *, code_commit: str
    ) -> engine.BacktestResult:
        check(
            not cfg.third_asset_funding,
            "A19.4 economic cash comparison does not admit third-asset funding",
        )
        run = run_recenter_backtest(
            market, cfg, code_commit=code_commit, policy=policy, configuration_ref=configuration_ref
        )
        write(output / "lifecycle.json", json_value(diagnostics(market, run)))
        return run.result

    with patch.object(engine, "run_backtest", execute):
        worker(dataset, configuration, output, commit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--policy", choices=["P0", "P1", "P2"], required=True)
    parser.add_argument("--configuration-ref", required=True)
    args = parser.parse_args()
    try:
        study(
            args.dataset,
            args.configuration,
            args.output,
            args.code_commit,
            args.policy,
            args.configuration_ref,
        )
    except BacktestError as exc:
        write(
            args.output / "measurement.json",
            dict(status="BLOCKED_INVALID_EXPERIMENT", error=str(exc)),
        )
        raise
