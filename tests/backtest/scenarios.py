"""Explicit synthetic market fixtures, never empirical BTC price histories."""

from dataclasses import replace

from gridbot.backtest.data import Dataset
from gridbot.backtest.engine import BacktestConfig
from gridbot.domain import USDT, Money
from tests.backtest.test_engine import config, dataset

MARKETS: dict[str, tuple[str, ...]] = {
    "sideways": (
        "100,110,90,105,10",
        "100,106,89,100,10",
        "100,111,99,110,10",
        "100,106,89,100,10",
        "100,111,99,110,10",
    ),
    "strong_rise": (
        "100,110,90,105,10",
        "110,120,109,119,10",
        "119,140,118,135,10",
        "135,160,134,155,10",
    ),
    "strong_fall": ("100,110,90,105,10", "100,106,89,90,10", "90,91,69,70,10", "70,71,49,50,10"),
    "high_volatility": (
        "100,110,90,105,10",
        "100,160,40,100,10",
        "100,170,30,110,10",
        "100,180,20,90,10",
    ),
    "low_volatility": ("105,105.1,104.9,105,10",) * 4,
    "price_gap": ("100,110,90,105,10", "80,82,79,81,10", "81,108,80,105,10", "105,120,104,115,10"),
    "exit_range": (
        "100,110,90,105,10",
        "100,106,89,100,10",
        "100,200,99,190,10",
        "190,220,180,210,10",
    ),
    "return_range": (
        "100,110,90,105,10",
        "120,130,119,125,10",
        "125,130,124,129,10",
        "100,110,89,99,10",
    ),
    "multiple_levels": ("100,110,90,105,10", "100,120,80,100,10", "100,120,80,110,10"),
    "insufficient_capital": ("100,110,90,105,10", "100,106,89,100,10", "100,111,99,110,10"),
    "partial": (
        "100,110,90,105,10",
        "100,106,89,100,10",
        "100,111,99,110,.01",
        "110,120,80,100,10",
    ),
    "no_fill": ("100,110,90,105,0", "100,110,80,105,0", "100,110,80,105,0"),
}


def market_case(name: str) -> tuple[Dataset, BacktestConfig]:
    settings = replace(config(), run_ref="SIM:A19_" + name.upper())
    if name == "insufficient_capital":
        settings = replace(settings, initial_quote=Money.parse(".001", USDT))
    return dataset(MARKETS[name]), settings
