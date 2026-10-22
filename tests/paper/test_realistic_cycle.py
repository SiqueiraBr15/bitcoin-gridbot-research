"""Synthetic BTC prices at a realistic scale, not current market observations."""

from gridbot.domain import (
    BTCUSDT,
    USDT,
    MarketRules,
    Money,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
)
from gridbot.paper.accounting import PaperAccount, PaperBook, PaperInitialState, PaperSettleBuy
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    bootstrap_grid_state,
    build_arithmetic_grid,
)
from tests.paper.fixtures import (
    buy_result,
    commit,
    evidence,
    prepare_buy,
    reserve_sell,
    settle_sell,
)
from tests.paper.test_accounting import conservation


def realistic_initial() -> PaperBook:
    from decimal import Decimal

    rules = MarketRules(
        BTCUSDT,
        PriceRules(Price.parse(".01")),
        QuantityRules(Qty.parse(".000001"), Qty.parse(".000001")),
        NotionalRules(Decimal("5")),
    )
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse("65000"), Price.parse("66000"), 5), rules
    )
    state = bootstrap_grid_state(plan, Price.parse("65500"))
    return PaperBook(
        PaperInitialState(PaperAccount("PAPER:demo"), state, rules, Money.parse("20", USDT))
    )


def test_realistic_twenty_usdt_cycle_second_buy_requires_actual_proceeds() -> None:
    book = realistic_initial()
    for cell in (0, 1, 2):
        book = prepare_buy(book, cell, budget="20")
    book = commit(book, PaperSettleBuy(buy_result(book, fee=".000000102")))
    assert book.available_quote == Money.parse(".0288", USDT)
    assert book.buy_spending == Money.parse("6.63", USDT)
    book, execution = reserve_sell(book, hold=".0000001")
    source = evidence(
        book, execution, execution_price="65500", fees=(Money.parse(".0066155", USDT),)
    )
    book = settle_sell(book, execution, source)
    assert book.settled_sell_proceeds == Money.parse("6.6088845", USDT)
    assert book.available_quote == Money.parse("6.6376845", USDT)
    assert book.remaining_grid_base == Qty.parse(".000000898")
    assert book.grid_state.cells[0].cycle_seq == 1
    second = prepare_buy(book, budget="19.8")
    context = second.buy_context(CellCycleRef(0, 1))
    assert context.intent.qty == Qty.parse(".000101")
    assert context.intent.price.notional(context.intent.qty) > Money.parse(".0288", USDT).amount
    second = commit(second, PaperSettleBuy(buy_result(second, fee=".000000101")))
    assert second.buy_spending == Money.parse("13.195", USDT)
    assert second.available_quote == Money.parse(".0726845", USDT)
    assert second.remaining_grid_base == Qty.parse(".000101797")
    conservation(second)
