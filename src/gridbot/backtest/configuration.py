"""Closed, offline, versioned experiment configuration. Financial literals are strings."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from gridbot.backtest.data import (
    BacktestError,
    CsvFormat,
    DatasetSpec,
    check,
    number,
    utc,
)
from gridbot.backtest.engine import BacktestConfig
from gridbot.backtest.execution import BNB, ExecutionPolicy, FeeModel, MixedPolicy
from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    FeeSchedule,
    LiquidityRole,
    MarketRules,
    Money,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Timeframe,
)
from gridbot.strategy import ArithmeticGridSpec


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        check(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _no_float(value: str) -> None:
    raise BacktestError("JSON numeric fractions/constants forbidden; financial values use strings")


def _integer(value: str) -> int:
    check(len(value) <= 18, "bounded JSON integer required")
    return int(value)


def parse_json(text: str) -> object:
    check(type(text) is str and len(text) <= 64 * 1024 * 1024, "bounded JSON text required")
    try:
        result = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_pairs,
                parse_float=_no_float,
                parse_constant=_no_float,
                parse_int=_integer,
            ),
        )
    except (ValueError, RecursionError) as exc:
        raise BacktestError("malformed, duplicate, numeric or excessively nested JSON") from exc
    stack = [(result, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        check(depth <= 128 and nodes <= 600_000, "JSON depth/node quota exceeded")
        if isinstance(node, dict):
            stack.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
    return result


def read_json(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(1_048_577)
    check(len(raw) <= 1_048_576, "configuration file exceeds1MiB")
    return parse_json(raw.decode("utf8"))


def fields(value: object, names: str) -> dict[str, object]:
    check(type(value) is dict, "JSON object required")
    result = cast(dict[str, object], value)
    check(set(result) == set(names.split()), "unknown or missing configuration fields")
    return result


def text(value: object) -> str:
    check(type(value) is str, "text required; financial literals must be strings")
    return cast(str, value)


def integer(value: object) -> int:
    check(type(value) is int, "native JSON integer required")
    return cast(int, value)


def boolean(value: object) -> bool:
    check(type(value) is bool, "native JSON boolean required")
    return cast(bool, value)


def optional_price(value: object) -> Price | None:
    return None if value is None else Price(number(text(value)))


def optional_qty(value: object) -> Qty | None:
    return None if value is None else Qty(number(text(value)))


def optional_decimal(value: object) -> Decimal | None:
    return None if value is None else number(text(value))


def dataset_spec(value: object) -> tuple[str, DatasetSpec]:
    data = fields(
        value,
        "version csv_path origin synthetic timeframe_seconds start end format epoch_unit sha256",
    )
    check(integer(data["version"]) == 1, "unknown dataset manifest version")
    return text(data["csv_path"]), DatasetSpec(
        text(data["origin"]),
        boolean(data["synthetic"]),
        Timeframe.seconds(integer(data["timeframe_seconds"])),
        utc(text(data["start"])),
        utc(text(data["end"])),
        CsvFormat(text(data["format"])),
        None if data["epoch_unit"] is None else text(data["epoch_unit"]),
        None if data["sha256"] is None else text(data["sha256"]),
    )


def scenario(value: object) -> BacktestConfig:
    data = fields(
        value,
        "version run_ref max_events capital_usdt notional_budget_usdt grid rules "
        "execution assumptions third_asset_funding_bnb bnb_mark",
    )
    check(integer(data["version"]) == 1, "unknown scenario version")
    grid = fields(data["grid"], "lower upper intervals")
    rules = fields(
        data["rules"], "tick step min_qty max_qty min_price max_price min_notional max_notional"
    )
    execution = fields(
        data["execution"],
        "maker_rate taker_rate buy_role sell_role buy_fee_asset "
        "sell_fee_asset bnb_fee_price spread slippage participation latency_us "
        "ttl_bars allow_touch mixed",
    )
    assumptions = fields(data["assumptions"], "origin effective_start effective_end")
    funding = data["third_asset_funding_bnb"]
    check(
        type(funding) is list and len(cast(list[object], funding)) <= 1, "bounded BNB funding list"
    )
    market_rules = MarketRules(
        BTCUSDT,
        PriceRules(
            Price(number(text(rules["tick"]))),
            optional_price(rules["min_price"]),
            optional_price(rules["max_price"]),
        ),
        QuantityRules(
            Qty(number(text(rules["step"]))),
            Qty(number(text(rules["min_qty"]))),
            optional_qty(rules["max_qty"]),
        ),
        NotionalRules(
            optional_decimal(rules["min_notional"]), optional_decimal(rules["max_notional"])
        ),
    )
    fees = FeeModel(
        FeeSchedule.parse(text(execution["maker_rate"]), text(execution["taker_rate"])),
        LiquidityRole(text(execution["buy_role"])),
        LiquidityRole(text(execution["sell_role"])),
        Asset(text(execution["buy_fee_asset"])),
        Asset(text(execution["sell_fee_asset"])),
        optional_price(execution["bnb_fee_price"]),
    )
    policy = ExecutionPolicy(
        fees,
        number(text(execution["spread"])),
        number(text(execution["slippage"])),
        number(text(execution["participation"])),
        timedelta(microseconds=integer(execution["latency_us"])),
        integer(execution["ttl_bars"]),
        boolean(execution["allow_touch"]),
        MixedPolicy(text(execution["mixed"])),
    )
    return BacktestConfig(
        ArithmeticGridSpec(
            BTCUSDT,
            Price(number(text(grid["lower"]))),
            Price(number(text(grid["upper"]))),
            integer(grid["intervals"]),
        ),
        market_rules,
        Money(number(text(data["capital_usdt"])), USDT),
        Money(number(text(data["notional_budget_usdt"])), USDT),
        policy,
        text(data["run_ref"]),
        integer(data["max_events"]),
        text(assumptions["origin"]),
        utc(text(assumptions["effective_start"])),
        utc(text(assumptions["effective_end"])),
        tuple(Money(number(text(f)), BNB) for f in cast(list[object], funding)),
        optional_price(data["bnb_mark"]),
    )


def configuration(config: BacktestConfig) -> dict[str, object]:
    rules, policy = config.rules, config.policy
    fees = policy.fees

    def value(v: Price | Qty | Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v if isinstance(v, Decimal) else v.value)

    return dict(
        version=1,
        run_ref=config.run_ref,
        max_events=config.max_events,
        capital_usdt=str(config.initial_quote.amount),
        notional_budget_usdt=str(config.notional_budget.amount),
        grid=dict(
            lower=str(config.grid.lower_price.value),
            upper=str(config.grid.upper_price.value),
            intervals=config.grid.interval_count,
        ),
        rules=dict(
            tick=value(rules.price.tick_size),
            step=value(rules.quantity.step_size),
            min_qty=value(rules.quantity.min_qty),
            max_qty=value(rules.quantity.max_qty),
            min_price=value(rules.price.min_price),
            max_price=value(rules.price.max_price),
            min_notional=value(rules.notional.min_notional),
            max_notional=value(rules.notional.max_notional),
        ),
        execution=dict(
            maker_rate=str(fees.schedule.maker_rate),
            taker_rate=str(fees.schedule.taker_rate),
            buy_role=fees.buy_role.value,
            sell_role=fees.sell_role.value,
            buy_fee_asset=fees.buy_asset.code,
            sell_fee_asset=fees.sell_asset.code,
            bnb_fee_price=value(fees.bnb_fee_price),
            spread=str(policy.spread),
            slippage=str(policy.slippage),
            participation=str(policy.participation),
            latency_us=policy.latency // timedelta(microseconds=1),
            ttl_bars=policy.ttl_bars,
            allow_touch=policy.allow_touch,
            mixed=policy.mixed.value,
        ),
        assumptions=dict(
            origin=config.assumptions_origin,
            effective_start=config.effective_start.isoformat(),
            effective_end=config.effective_end.isoformat(),
        ),
        third_asset_funding_bnb=[str(f.amount) for f in config.third_asset_funding],
        bnb_mark=value(config.bnb_mark),
    )
