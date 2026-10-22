"""Same native commands through SQLite PAPER and transient PAPER, exact comparisons."""

from pathlib import Path

import pytest

from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus, Qty
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperBook,
    PaperCommand,
    PaperError,
    PaperErrorCode,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSettleBuy,
)
from gridbot.paper.simulation import PaperSimulation, SimulationSnapshot
from gridbot.storage.paper_journal import PaperJournal
from tests.paper.fixtures import initial
from tests.paper.simulation_fixtures import buy_command, buy_fill_result, sell_command, sell_source
from tests.paper.simulation_oracle import assert_source_conservation
from tests.paper.test_realistic_cycle import realistic_initial


def economic_snapshot(book: PaperBook, run_ref: str) -> SimulationSnapshot:
    return SimulationSnapshot(
        run_ref,
        book.revision,
        book.grid_state,
        book.available_quote,
        book.buy_spending,
        book.settled_sell_proceeds,
        book.active_buy_reservations,
        book.remaining_grid_base,
        book.reserved_grid_base,
        book.third_asset_balances(),
        book.third_asset_obligations(),
        book.incident_blocked,
    )


@pytest.mark.parametrize("outcome", ["full", "partial", "no-fill", "unknown", "partial-buy"])
def test_durable_and_fast_match_after_every_identical_command_and_restart(
    tmp_path: Path, outcome: str
) -> None:
    book = initial((Money.parse(".000006", Asset("BNB")),))
    sim = PaperSimulation(book.initial, run_ref="SIM:differential", max_events=50)
    store = PaperJournal.create(tmp_path, book)

    def drive(command: PaperCommand) -> None:
        nonlocal book, store
        expected = book.revision
        result = store.commit(expected, command)
        sim.apply(expected, command)
        store = PaperJournal.open(tmp_path)
        book = store.recover()
        assert book == result
        assert tuple(e.command for e in sim.source_log().events) == book.entries
        assert sim.snapshot() == economic_snapshot(book, sim.run_ref)
        assert_source_conservation(sim.source_log(), sim.snapshot())

    drive(buy_command(book))
    qty = Qty.parse(".015") if outcome == "partial-buy" else None
    finalized = buy_fill_result(book, qty=qty)
    drive(PaperSettleBuy(finalized))
    drive(PaperSettleBuy(finalized))
    prepare = sell_command(book)
    drive(prepare)
    execution = prepare.execution_ref
    assert sim.sell_authorization(execution) == book.sell_authorization(execution)
    quantity = Qty.parse(".030") if outcome == "partial" else None
    status: OrderStatus | None = (
        OrderStatus.CANCELED if outcome in ("partial", "no-fill") else OrderStatus.FILLED
    )
    if outcome == "no-fill":
        quantity = Qty.zero()
    if outcome == "unknown":
        status = None
    fees = (
        (
            Money.parse(".00004", BTC),
            Money.parse(".00105", USDT),
            Money.parse(".00001", Asset("BNB")),
        )
        if outcome == "partial"
        else (Money.zero(USDT),)
    )
    before = sim.available_quote
    drive(PaperObserveSell(sell_source(book, execution, status=status, qty=quantity, fees=fees)))
    assert sim.available_quote == before
    apply = PaperApplySell(execution, sim.revision)
    if outcome == "unknown":
        for call in (
            lambda: sim.apply(sim.revision, apply),
            lambda: store.commit(book.revision, apply),
        ):
            with pytest.raises(PaperError) as error:
                call()
            assert error.value.code is PaperErrorCode.EVIDENCE_PENDING
        assert sim.snapshot() == economic_snapshot(book, sim.run_ref)
        return
    drive(apply)
    drive(apply)
    restored = PaperSimulation.replay(sim.source_log(), run_ref=sim.run_ref, max_events=50)
    assert restored.snapshot() == sim.snapshot()
    if outcome == "no-fill":
        drive(PaperReleaseNoFill(execution))
        drive(PaperReleaseNoFill(execution))
        assert sim.grid_state.cells[0].cycle_seq == 0
    elif outcome == "partial":
        assert sim.reserved_grid_base == Qty.parse(".00106")
        assert sim.third_asset_obligations() == (Money.parse(".000004", Asset("BNB")),)
    else:
        assert sim.grid_state.cells[0].cycle_seq == 1
        drive(buy_command(book))
        drive(PaperSettleBuy(buy_fill_result(book, fee=Money.parse(".001", USDT))))
        drive(apply)


def test_realistic_second_buy_depends_on_applied_proceeds_in_both_runtimes(tmp_path: Path) -> None:
    book = realistic_initial()
    sim = PaperSimulation(book.initial, run_ref="SIM:twenty-usdt", max_events=30)
    store = PaperJournal.create(tmp_path, book)

    def drive(command: PaperCommand) -> None:
        nonlocal book
        expected = book.revision
        book = store.commit(expected, command)
        sim.apply(expected, command)
        assert sim.snapshot() == economic_snapshot(book, sim.run_ref)
        assert_source_conservation(sim.source_log(), sim.snapshot())

    for cell in (0, 1, 2):
        drive(buy_command(book, cell, budget="20"))
    drive(PaperSettleBuy(buy_fill_result(book, fee=Money.parse(".000000102", BTC))))
    prepare = sell_command(book, hold=".0000001")
    drive(prepare)
    source = sell_source(
        book, prepare.execution_ref, price="65500", fees=(Money.parse(".0066155", USDT),)
    )
    drive(PaperObserveSell(source))
    assert sim.available_quote == Money.parse(".0288", USDT)
    drive(PaperApplySell(prepare.execution_ref, book.revision))
    assert sim.available_quote == Money.parse("6.6376845", USDT)
    command = buy_command(book, budget="19.8")
    assert (
        command.plan.intents[0].price.notional(command.plan.intents[0].qty)
        > Money.parse(".0288", USDT).amount
    )
    drive(command)
    drive(PaperSettleBuy(buy_fill_result(book, fee=Money.parse(".000000101", BTC))))
    assert sim.available_quote == Money.parse(".0726845", USDT)
