"""Print exact grid geometry using synthetic prices; no order or market request."""

from __future__ import annotations

import json

from gridbot.domain import BTCUSDT, MarketRules, Price, PriceRules, Qty, QuantityRules
from gridbot.strategy import ArithmeticGridSpec, build_arithmetic_grid


def main() -> None:
    rules = MarketRules(
        BTCUSDT,
        PriceRules(Price.parse("0.01")),
        QuantityRules(Qty.parse("0.00001"), Qty.parse("0.00001")),
    )
    spec = ArithmeticGridSpec(BTCUSDT, Price.parse("90"), Price.parse("110"), 4)
    plan = build_arithmetic_grid(spec, rules)
    result = {
        "data": "SYNTHETIC_GEOMETRY_ONLY",
        "symbol": BTCUSDT.name,
        "levels": [str(level.price.value) for level in plan.levels],
        "orders": 0,
        "network_requests": 0,
    }
    print(json.dumps(result, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
