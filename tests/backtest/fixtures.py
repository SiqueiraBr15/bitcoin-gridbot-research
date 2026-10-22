from gridbot.domain import (
    BTCUSDT,
    MarketRules,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
)


def rules() -> MarketRules:
    return MarketRules(
        BTCUSDT,
        PriceRules(Price.parse(".01")),
        QuantityRules(Qty.parse(".001"), Qty.parse(".001")),
        NotionalRules.parse("1"),
    )
