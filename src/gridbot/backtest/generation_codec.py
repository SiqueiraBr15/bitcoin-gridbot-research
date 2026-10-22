"""Explicit transient generation envelope. Durable/operational registries stay closed."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import datetime, timedelta
from typing import Any, cast

from gridbot.backtest.configuration import fields as object_fields
from gridbot.backtest.configuration import parse_json
from gridbot.backtest.data import BacktestError, check
from gridbot.domain import BTCUSDT, Candle, Timeframe
from gridbot.domain.errors import DomainError
from gridbot.paper.generations import (
    GenerationEconomics,
    GridGenerationEvidence,
    GridRecenterPlan,
    PaperRecenter,
)
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.paper_codec import _unicode_source, text_bytes

MARKER = "GRIDBOT_TRANSIENT_RECENTER_A19_4_V1"


def _values(value: object, size: int) -> tuple[Any, ...]:
    check(type(value) is tuple and len(value) == size, "invalid generation tuple fields")
    return cast(tuple[Any, ...], value)


def _bar(candle: Candle) -> tuple[object, ...]:
    return (
        candle.open_time.isoformat(),
        candle.close_time.isoformat(),
        candle.timeframe.duration // timedelta(seconds=1),
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
    )


def _candle(value: object) -> Candle:
    values = _values(value, 8)
    return Candle(
        BTCUSDT,
        Timeframe.seconds(values[2]),
        datetime.fromisoformat(values[0]),
        datetime.fromisoformat(values[1]),
        *values[3:],
    )


def encode_generation(command: PaperRecenter) -> str:
    check(type(command) is PaperRecenter, "transient generation command required")
    replace(command)
    p = command.plan
    e = p.previous
    balances = tuple(getattr(e.balances, f.name) for f in fields(e.balances))
    previous = (
        e.run_ref,
        e.account_ref,
        e.revision,
        e.generation,
        e.state,
        balances,
        e.next_cycle_seq,
        e.blockers,
    )
    payload = (
        previous,
        p.rules,
        tuple(_bar(c) for c in p.signal),
        p.notional_budget,
        p.projected_buy_fees,
        p.configuration_ref,
        p.policy,
        p.context_blockers,
        _bar(command.current_candle),
    )
    encoded_payload = encode_contract(payload)
    _unicode_source(payload)
    encoded = json.dumps(
        dict(recenter_schema=MARKER, payload=encoded_payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    text_bytes(encoded)
    return encoded


def decode_generation(text: str) -> PaperRecenter:
    text_bytes(text)
    envelope = object_fields(parse_json(text), "recenter_schema payload")
    check(envelope["recenter_schema"] == MARKER, "unknown transient generation schema")
    try:
        check(type(envelope["payload"]) is str, "encoded financial tuple required")
        decoded = decode_contract(cast(str, envelope["payload"]))
        _unicode_source(decoded)
        p = _values(decoded, 9)
        e = _values(p[0], 8)
        economics = GenerationEconomics(*_values(e[5], 8))
        evidence = GridGenerationEvidence(e[0], e[1], e[2], e[3], e[4], economics, e[6], e[7])
        check(type(p[2]) is tuple and len(p[2]) == 168, "generation signal must have 168 bars")
        signal = tuple(_candle(c) for c in p[2])
        plan = GridRecenterPlan(evidence, p[1], signal, *p[3:8])
        return PaperRecenter(plan, _candle(p[8]))
    except (DomainError, TypeError, ValueError, OverflowError) as exc:
        raise BacktestError("invalid transient generation source") from exc
