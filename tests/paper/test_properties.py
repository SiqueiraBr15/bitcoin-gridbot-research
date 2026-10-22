import json
import os
from collections import Counter
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus
from gridbot.paper.accounting import PaperApplySell, PaperObserveSell, PaperReleaseNoFill
from tests.paper.fixtures import bought, commit, evidence, reserve_sell, settle_sell
from tests.paper.test_accounting import conservation

COUNTS: Counter[str] = Counter()


def teardown_module() -> None:
    directory = os.environ.get("A18_1_COUNTER_DIRECTORY")
    if directory:
        Path(directory, "paper_property_counts.json").write_text(
            json.dumps(dict(COUNTS)), encoding="utf8"
        )


@settings(max_examples=12, derandomize=True, deadline=None)
@given(
    asset=st.sampled_from([BTC, USDT, Asset("BNB")]),
    qty=st.sampled_from([".015", ".030", ".031"]),
    zero=st.booleans(),
)
def test_fraction_conservation_and_fees(asset: Asset, qty: str, zero: bool) -> None:
    COUNTS["conservation"] += 1
    book, execution = reserve_sell(bought())
    status = OrderStatus.FILLED if qty == ".031" else OrderStatus.CANCELED
    source = evidence(
        book,
        execution,
        status=status,
        qty=qty,
        fees=(Money.parse("0" if zero else ".00004", asset),),
    )
    final = settle_sell(book, execution, source)
    conservation(final)
    p = source.assessment.projection
    assert p is not None
    assert final.remaining_grid_base == p.projected_origin_remaining
    assert final.settled_sell_proceeds == p.net_observed_quote
    assert final.grid_state.cells[0].cycle_seq == (1 if status is OrderStatus.FILLED else 0)
    assert final.initial == book.initial


@settings(max_examples=6, derandomize=True, deadline=None)
@given(repeats=st.integers(1, 6))
def test_repeats_do_not_credit_debit_or_rearm_again(repeats: int) -> None:
    COUNTS["replay"] += 1
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    book = commit(book, PaperObserveSell(source))
    command = PaperApplySell(execution, book.revision)
    final = commit(book, command)
    for _ in range(repeats):
        assert commit(final, command) is final
    conservation(final)


class PaperMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        COUNTS["sequences"] += 1
        book, self.execution = reserve_sell(bought())
        self.source = evidence(book, self.execution, status=OrderStatus.CANCELED, qty="0")
        self.book = settle_sell(book, self.execution, self.source)
        self.proceeds = self.book.settled_sell_proceeds

    @rule()
    def duplicate(self) -> None:
        COUNTS["duplicate_rule"] += 1
        original = self.book
        self.book = commit(self.book, PaperApplySell(self.execution, 4))
        assert self.book is original

    @rule()
    def release(self) -> None:
        COUNTS["release_rule"] += 1
        self.book = commit(self.book, PaperReleaseNoFill(self.execution))
        assert self.book.reserved_grid_base.is_zero

    @rule()
    def source_replay(self) -> None:
        COUNTS["observation_rule"] += 1
        self.book = commit(self.book, PaperObserveSell(self.source))

    @invariant()
    def money_and_cycle(self) -> None:
        COUNTS["invariant"] += 1
        conservation(self.book)
        assert self.book.settled_sell_proceeds == self.proceeds
        assert self.book.grid_state.cells[0].cycle_seq == 0


TestPaperMachine = PaperMachine.TestCase
TestPaperMachine.settings = settings(
    max_examples=4, stateful_step_count=4, derandomize=True, deadline=None
)
