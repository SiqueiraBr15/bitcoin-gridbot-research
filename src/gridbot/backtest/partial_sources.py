"""Closed transient experiment source envelope; no durable registry or balance import."""

from __future__ import annotations

import hashlib
import json
from typing import cast

from gridbot.backtest.configuration import fields, integer, parse_json, text
from gridbot.backtest.data import MAX_BYTES, check
from gridbot.backtest.export import json_value
from gridbot.backtest.generation_codec import _bar, _candle, _values
from gridbot.paper.accounting import PaperCommand
from gridbot.paper.partial_allocation import PartialCosts
from gridbot.paper.simulation import SimulationEvent, SimulationLog
from gridbot.paper.two_generation import PartialPublishPlan, PartialSourceLog, TwoGenerationPaper
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.paper_codec import (
    _unicode_source,
    decode_command,
    decode_initial,
    encode_command,
    encode_initial,
)

MARKER = "GRIDBOT_A19_6_TRANSIENT_TWO_GENERATION_V1"


def _digest(plan: PartialPublishPlan) -> str:
    return hashlib.sha256(
        json.dumps(
            json_value(plan.allocation),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def encode_partial_sources(log: PartialSourceLog) -> str:
    check(type(log) is PartialSourceLog, "partial source log required")
    TwoGenerationPaper.replay(log, max_events=10_000)
    records: list[dict[str, object]] = []
    for event in log.events:
        if isinstance(event.command, PartialPublishPlan):
            p = event.command
            recipe = (
                p.revision,
                p.generation_ref,
                p.costs.rate,
                p.costs.asset,
                p.notional_ceiling,
                p.mark,
                tuple(_bar(c) for c in p.signal),
                p.configuration_ref,
            )
            _unicode_source(recipe)
            records.append(
                dict(
                    revision=event.revision,
                    generation=event.generation_ref,
                    kind="PUBLISH",
                    payload=encode_contract(recipe),
                    allocation_sha256=_digest(p),
                )
            )
        else:
            records.append(
                dict(
                    revision=event.revision,
                    generation=event.generation_ref,
                    kind="NATIVE",
                    payload=encode_command(event.command),
                    allocation_sha256=None,
                )
            )
    result = json.dumps(
        dict(
            schema=MARKER,
            revision=log.revision,
            prefix=dict(
                run_ref=log.prefix.run_ref,
                revision=log.prefix.revision,
                initial=encode_initial(log.prefix.initial),
                commands=[encode_command(cast(PaperCommand, e.command)) for e in log.prefix.events],
            ),
            events=records,
        ),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    check(len(result.encode("utf8")) <= MAX_BYTES, "partial source envelope quota exceeded")
    return result


def replay_partial_sources(encoded: str, *, max_events: int) -> TwoGenerationPaper:
    check(type(encoded) is str and len(encoded) <= MAX_BYTES, "bounded source text required")
    check(len(encoded.encode("utf8")) <= MAX_BYTES, "partial source envelope quota exceeded")
    data = fields(parse_json(encoded), "schema revision prefix events")
    check(data["schema"] == MARKER, "unknown partial source schema")
    p = fields(data["prefix"], "run_ref revision initial commands")
    commands = p["commands"]
    check(type(commands) is list and len(commands) <= max_events, "bounded native prefix required")
    commands = cast(list[object], commands)
    run_ref = text(p["run_ref"])
    prefix = SimulationLog(
        run_ref,
        decode_initial(text(p["initial"])),
        tuple(
            SimulationEvent(run_ref, i, decode_command(text(c))) for i, c in enumerate(commands, 1)
        ),
        integer(p["revision"]),
    )
    records = data["events"]
    check(type(records) is list, "partial event array required")
    records = cast(list[object], records)
    check(len(records) + prefix.revision <= max_events, "partial event budget exceeded")
    check(integer(data["revision"]) == prefix.revision + len(records), "incomplete source history")
    runtime = TwoGenerationPaper(prefix, max_events=max_events)
    for record in records:
        e = fields(record, "revision generation kind payload allocation_sha256")
        check(integer(e["revision"]) == runtime.revision + 1, "noncontiguous source")
        generation = text(e["generation"])
        if e["kind"] == "PUBLISH":
            recipe = decode_contract(text(e["payload"]))
            _unicode_source(recipe)
            v = _values(recipe, 8)
            check(type(v[6]) is tuple, "signal tuple required")
            signal = tuple(_candle(c) for c in v[6])
            plan = runtime.plan(
                mark=v[5],
                costs=PartialCosts(v[2], v[3]),
                notional_ceiling=v[4],
                configuration_ref=v[7],
                signal=signal,
            )
            check(plan.revision == v[0] and plan.generation_ref == v[1], "stale publication recipe")
            check(_digest(plan) == e["allocation_sha256"], "allocation source mismatch")
            actual = runtime.publish(runtime.revision, plan)
            check(runtime.main_ref == generation, "publication generation mismatch")
        else:
            check(e["kind"] == "NATIVE" and e["allocation_sha256"] is None, "unknown source kind")
            actual = runtime.apply(runtime.revision, generation, decode_command(text(e["payload"])))
        check(actual == e["revision"], "duplicate source cannot be a new event")
    return runtime
