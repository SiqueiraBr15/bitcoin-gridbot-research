from dataclasses import replace

import pytest
from scripts.a19_3_study import lifecycle_diagnostics

from gridbot.backtest.data import BacktestError
from gridbot.backtest.engine import run_backtest
from gridbot.backtest.execution import BNB
from gridbot.domain import Money, Price
from tests.backtest.test_engine import config, dataset


@pytest.mark.parametrize("mark", [Price.parse("100"), None], ids=["valued", "unvalued"])
def test_bnb_funded_portfolio_cannot_receive_incomplete_cash_reference(mark: Price | None) -> None:
    settings = replace(config(), third_asset_funding=(Money.parse("1", BNB),), bnb_mark=mark)
    market = dataset()
    result = run_backtest(market, settings, code_commit="diagnostic-admission")
    if mark is not None:
        assert result.metrics.initial_equity != settings.initial_quote
    else:
        assert result.metrics.initial_equity is None
    with pytest.raises(BacktestError, match="third-asset funding"):
        lifecycle_diagnostics(market, result, "P0")
