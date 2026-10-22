from dataclasses import replace
from decimal import localcontext
from fractions import Fraction
from typing import Any, cast

import pytest

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.domain import BTC, USDT, Asset, DomainError, Money, OrderStatus, Qty
from gridbot.paper.accounting import (
    PaperAccount,
    PaperApplySell,
    PaperBook,
    PaperCostStudy,
    PaperError,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSellEvidence,
    PaperSettleBuy,
    paper_transition,
)
from gridbot.strategy import CellCycleRef
from tests.application.economic_fixtures import mandatory_example
from tests.paper.fixtures import (
    bought,
    buy_result,
    commit,
    evidence,
    initial,
    prepare_buy,
    reserve_sell,
    settle_sell,
)


def conservation(book: PaperBook) -> None:
    assert (
        book.initial.initial_quote + book.external_contributions + book.settled_sell_proceeds
        == (
            book.buy_spending
            + book.active_buy_reservations
            + book.available_quote
            + book.external_withdrawals
        )
    )
    buys = [e.finalized for e in book.entries if isinstance(e, PaperSettleBuy)]
    spending = sum(
        (
            Fraction(f.execution_price.value) * Fraction(f.executed_qty.value)
            + (Fraction(f.fee.amount) if f.fee.asset == USDT else 0)
            for b in buys
            for f in b.ledger.fills
        ),
        Fraction(),
    )
    assert Fraction(book.buy_spending.amount) == spending
    n = sum((Fraction(b.net_acquired_base_qty.value) for b in buys), Fraction())
    consumed = Fraction()
    quote = Fraction()
    for event in book.entries:
        if isinstance(event, PaperApplySell):
            observation = book.entries[event.evidence_revision - 1]
            assert isinstance(observation, PaperObserveSell)
            ledger = observation.evidence.reconciliation.ledger
            assert ledger is not None
            consumed += sum(
                (
                    Fraction(f.executed_qty.value)
                    + (Fraction(f.fee.amount) if f.fee.asset == BTC else 0)
                    for f in ledger.fills
                ),
                Fraction(),
            )
            quote += sum(
                (
                    Fraction(f.observed_quote.amount)
                    - (Fraction(f.fee.amount) if f.fee.asset == USDT else 0)
                    for f in ledger.fills
                ),
                Fraction(),
            )
    assert Fraction(book.settled_sell_proceeds.amount) == quote
    assert Fraction(book.remaining_grid_base.value) == n - consumed
    assert book.reserved_grid_base <= book.remaining_grid_base


@pytest.mark.parametrize(
    ("status", "qty"),
    [(OrderStatus.FILLED, None), (OrderStatus.CANCELED, ".015"), (OrderStatus.CANCELED, "0")],
)
def test_terminal_results_and_idempotence(status: OrderStatus, qty: str | None) -> None:
    book, execution = reserve_sell(bought())
    old = book
    source = evidence(book, execution, status=status, qty=qty)
    book = commit(book, PaperObserveSell(source))
    apply = PaperApplySell(execution, book.revision)
    book = commit(book, apply)
    conservation(book)
    assert commit(book, apply) is book
    assert old.initial == book.initial
    if status is OrderStatus.FILLED:
        assert book.grid_state.cells[0].cycle_seq == 1
        assert book.reserved_grid_base.is_zero
        assert book.available_quote == Money.parse("20.045", USDT)
    else:
        assert book.grid_state.cells[0].cycle_seq == 0
        assert not book.reserved_grid_base.is_zero
    if qty == "0":
        assert book.settled_sell_proceeds.amount == 0
        release = PaperReleaseNoFill(execution)
        book = commit(book, release)
        assert commit(book, release) is book
        assert book.reserved_grid_base.is_zero
        assert book.grid_state.cells[0].cycle_seq == 0


@pytest.mark.parametrize("asset", [BTC, USDT, Asset("BNB")])
def test_real_fee_consumption_and_third_obligation(asset: Asset) -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution, fees=(Money.parse(".00004", asset),))
    book = settle_sell(book, execution, source)
    conservation(book)
    p = source.assessment.projection
    assert p is not None
    assert book.remaining_grid_base == p.projected_origin_remaining
    assert book.settled_sell_proceeds == p.net_observed_quote
    if asset == Asset("BNB"):
        assert book.third_asset_obligations() == (Money.parse(".00004", asset),)
        assert PaperCostStudy(source).hypothetical_pnl is None


def test_source_non_paper_and_real_book_rejected() -> None:
    real = mandatory_example()
    with pytest.raises(DomainError):
        PaperSellEvidence(PaperAccount("PAPER:demo"), 1, real.reconciliation)
    with pytest.raises(DomainError):
        paper_transition(cast(Any, real.reconciliation.book), 0, cast(Any, None))
    with pytest.raises(DomainError):
        GridOperationalBook(cast(Any, initial()))
    with pytest.raises(DomainError):
        PaperAccount("LIVE:demo")


def test_stale_duplicate_and_late_conflict_preserve_applied_history() -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    completed = settle_sell(book, execution, source)
    old_revision = book.revision
    with pytest.raises(PaperError):
        paper_transition(completed, old_revision, PaperApplySell(execution, old_revision + 1))
    repeated = commit(completed, PaperObserveSell(source))
    assert commit(repeated, PaperApplySell(execution, repeated.revision)) is repeated
    conflict = evidence(book, execution, fees=(Money.parse(".02", USDT),))
    quarantined = commit(repeated, PaperObserveSell(conflict))
    assert quarantined.incident_blocked
    assert quarantined.settled_sell_proceeds == completed.settled_sell_proceeds
    with pytest.raises(PaperError):
        commit(quarantined, PaperApplySell(execution, quarantined.revision))
    with pytest.raises(PaperError):
        prepare_buy(quarantined)


def test_incomplete_evidence_cannot_credit_or_release() -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution, status=None)
    recorded = commit(book, PaperObserveSell(source))
    with pytest.raises(PaperError) as error:
        commit(recorded, PaperApplySell(execution, recorded.revision))
    assert error.value.observation is source
    assert recorded.settled_sell_proceeds.amount == 0
    assert recorded.reserved_grid_base == book.reserved_grid_base


def test_second_buy_uses_recycled_proceeds_with_other_virtual_holds() -> None:
    book = initial()
    for cell in (0, 1, 2):
        book = prepare_buy(book, cell, budget="20")
    origin = buy_result(book, fee=".000065")
    book = commit(book, PaperSettleBuy(origin))
    before = book.available_quote
    book, execution = reserve_sell(book)
    book = settle_sell(book, execution)
    after = book.available_quote
    second = prepare_buy(book, budget="20")
    second_context = second.buy_context(CellCycleRef(0, 1))
    cost = Money(second_context.intent.price.notional(second_context.intent.qty), USDT)
    assert cost.amount > before.amount
    assert cost.amount <= after.amount
    assert before + book.settled_sell_proceeds == after
    assert second.remaining_grid_base == book.remaining_grid_base
    conservation(second)
    finalized = buy_result(second, fee=".000065")
    second = commit(second, PaperSettleBuy(finalized))
    conservation(second)
    assert second.buy_spending == Money.parse("13", USDT)


def test_exact_cost_study_and_nonterminating_cost_are_explicit() -> None:
    book, execution = reserve_sell(bought(asset=USDT, fee=".001"), hold="0")
    source = evidence(book, execution)
    study = PaperCostStudy(source)
    assert study.traded_cost == Money.parse("3.201", USDT)
    assert study.base_fee_cost == Money.zero(USDT)
    assert study.residual_cost == Money.zero(USDT)
    assert study.hypothetical_pnl == Money.parse(".149", USDT)
    book, execution = reserve_sell(bought())
    study = PaperCostStudy(evidence(book, execution))
    assert study.traded_cost is None
    assert study.hypothetical_pnl is None


def test_direct_invalid_history_tamper_and_small_context() -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    completed = settle_sell(book, execution, source)
    with pytest.raises(DomainError):
        PaperBook(completed.initial, (*completed.entries, completed.entries[-1]))
    with pytest.raises(DomainError):
        replace(book.initial, initial_quote=Money.parse("-1", USDT))
    with localcontext() as context:
        context.prec = 2
        conservation(completed)
    object.__setattr__(source.reconciliation.report, "cumulative_quote", Money.zero(USDT))
    with pytest.raises(DomainError):
        _ = completed.available_quote


def test_mixed_fees_partial_and_explicit_third_funding() -> None:
    bnb = Asset("BNB")
    book, execution = reserve_sell(bought(initial((Money.parse(".000006", bnb),))))
    source = evidence(
        book,
        execution,
        status=OrderStatus.CANCELED,
        qty=".030",
        fees=(Money.parse(".00004", BTC), Money.parse(".00105", USDT), Money.parse(".00001", bnb)),
    )
    final = settle_sell(book, execution, source)
    assert final.remaining_grid_base == Qty.parse(".001928")
    assert final.reserved_grid_base == Qty.parse(".00106")
    assert final.settled_sell_proceeds == Money.parse("3.14895", USDT)
    assert final.third_asset_obligations() == (Money.parse(".000004", bnb),)
    assert final.third_asset_balances() == (Money.zero(bnb),)
    assert final.grid_state.cells[0].cycle_seq == 0
    conservation(final)


def test_buy_third_fee_and_unvalued_cost_never_deducted_from_usdt() -> None:
    bnb = Asset("BNB")
    book = bought(initial((Money.parse("1", bnb),)), asset=bnb, fee=".000032")
    book, execution = reserve_sell(book, hold="0")
    source = evidence(book, execution, fees=(Money.parse(".00004", bnb),))
    final = settle_sell(book, execution, source)
    assert final.third_asset_obligations() == ()
    assert final.third_asset_balances() == (Money.parse(".999928", bnb),)
    assert final.buy_spending == Money.parse("3.2", USDT)
    assert final.settled_sell_proceeds == Money.parse("3.36", USDT)
    assert PaperCostStudy(source).hypothetical_pnl is None
    conservation(final)


def test_economic_authority_rejects_foreign_revision_origin_and_insufficient_funding() -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    wrong = replace(source, source_revision=source.source_revision + 1)
    with pytest.raises(DomainError):
        commit(book, PaperObserveSell(wrong))
    with pytest.raises(DomainError):
        reserve_sell(book)
    with pytest.raises(DomainError):
        prepare_buy(
            replace(
                initial(), initial=replace(initial().initial, initial_quote=Money.parse("1", USDT))
            )
        )
    assert book.settled_sell_proceeds.amount == 0


def test_paper_looking_refs_do_not_make_foreign_binding_a_paper_evidence() -> None:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    binding = source.reconciliation.book.external_sell_bindings[0]
    foreign = replace(
        binding,
        identity=replace(binding.identity, venue_ref="BINANCE_SPOT", environment_ref="LIVE"),
    )
    root = replace(source.reconciliation.book, external_sell_bindings=(foreign,))
    inconsistent = replace(source.reconciliation, book=root)
    with pytest.raises(DomainError):
        PaperSellEvidence(book.initial.account, source.source_revision, inconsistent)


def test_invalid_revision_is_rejected_even_on_identical_replay() -> None:
    book, execution = reserve_sell(bought())
    recorded = commit(book, PaperObserveSell(evidence(book, execution)))
    completed = commit(recorded, PaperApplySell(execution, recorded.revision))
    invalid = PaperApplySell(execution, cast(Any, float(recorded.revision)))
    with pytest.raises(DomainError):
        commit(completed, invalid)
