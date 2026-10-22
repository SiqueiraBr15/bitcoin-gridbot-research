from collections import Counter
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.backtest.engine import run_backtest
from gridbot.backtest.execution import BNB
from gridbot.domain import BTC, USDT, Asset, FeeSchedule, Money, Price
from gridbot.paper.accounting import PaperApplySell, PaperSettleBuy
from gridbot.paper.simulation import PaperSimulation
from tests.backtest.test_data import START
from tests.backtest.test_engine import config, dataset
from tests.paper.simulation_oracle import assert_source_conservation

COUNTS: Counter[str] = Counter()


@settings(max_examples=6, derandomize=True, deadline=None)
@given(
    asset=st.sampled_from([BTC, USDT, BNB]),
    rate=st.sampled_from(["0", ".001", ".002"]),
    volume=st.integers(min_value=1, max_value=1000),
    funding=st.sampled_from(["0", "1"]),
)
def test_generated_pipeline_fee_conservation_and_native_parity(
    asset: Asset, rate: str, volume: int, funding: str
) -> None:
    COUNTS["pipeline_examples"] += 1
    settings_ = config()
    fees = replace(
        settings_.policy.fees,
        buy_asset=asset,
        sell_asset=asset,
        schedule=FeeSchedule.parse(rate, rate),
        bnb_fee_price=Price.parse("100"),
    )
    settings_ = replace(
        settings_,
        policy=replace(settings_.policy, fees=fees),
        third_asset_funding=(Money.parse(funding, BNB),),
        bnb_mark=Price.parse("100"),
    )
    value = str(Decimal(volume) / 100)
    market = dataset(("100,110,90,105,10", f"100,106,89,100,{value}", f"100,111,99,110,{value}"))
    result = run_backtest(market, settings_, code_commit="generated")
    assert_source_conservation(result.sources, result.points[-1].state)
    reference = PaperSimulation.replay(result.sources, run_ref=settings_.run_ref, max_events=1000)
    assert reference.snapshot() == result.points[-1].state
    assert not reference.third_asset_obligations()


@settings(max_examples=6, derandomize=True, deadline=None)
@given(low=st.integers(min_value=1, max_value=89), high=st.integers(min_value=111, max_value=200))
def test_future_bar_mutation_preserves_every_earlier_financial_point(low: int, high: int) -> None:
    COUNTS["causality_examples"] += 1
    original = run_backtest(dataset(), config(), code_commit="generated")
    changed = run_backtest(
        dataset(("100,110,90,105,10", "100,106,89,100,10", f"100,{high},{low},110,10")),
        config(),
        code_commit="generated",
    )
    assert original.points[:2] == changed.points[:2]
    assert original.sources.events[:6] == changed.sources.events[:6]
    cutoff = START + timedelta(minutes=2)
    assert [t for t in original.trades if t.observed_at <= cutoff] == [
        t for t in changed.trades if t.observed_at <= cutoff
    ]


class BacktestSourcesMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        COUNTS["sequences"] += 1
        self.result = run_backtest(dataset(), config(), code_commit="stateful")
        self.sim = PaperSimulation.replay(
            self.result.sources, run_ref=config().run_ref, max_events=1000
        )

    @rule()
    def restart(self) -> None:
        COUNTS["restart_rules"] += 1
        self.sim = PaperSimulation.replay(
            self.sim.source_log(), run_ref=config().run_ref, max_events=1000
        )

    @rule()
    def duplicate_buy(self) -> None:
        COUNTS["duplicate_buy_rules"] += 1
        command = next(
            e.command for e in self.result.sources.events if isinstance(e.command, PaperSettleBuy)
        )
        self.sim.apply(self.sim.revision, command)

    @rule()
    def duplicate_sell(self) -> None:
        COUNTS["duplicate_sell_rules"] += 1
        command = next(
            e.command for e in self.result.sources.events if isinstance(e.command, PaperApplySell)
        )
        self.sim.apply(self.sim.revision, command)

    @invariant()
    def exact_result_and_conservation(self) -> None:
        COUNTS["invariants"] += 1
        assert self.sim.snapshot() == self.result.points[-1].state
        assert_source_conservation(self.sim.source_log(), self.sim.snapshot())


TestBacktestSources = BacktestSourcesMachine.TestCase
TestBacktestSources.settings = settings(
    max_examples=4, stateful_step_count=4, derandomize=True, deadline=None
)
