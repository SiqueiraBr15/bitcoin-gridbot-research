from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Symbol,
)
from gridbot.portfolio import (
    AcquisitionOutcome,
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    BuyFinalizationError,
    BuyFinalizationErrorCode,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    finalize_buy,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    GridBuyIntent,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

D = Decimal
E = BuyFinalizationErrorCode
S = BuyExecutionStatus
OUT = AcquisitionOutcome
BNB = Asset("BNB")
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def _pipeline() -> tuple[Any, tuple[GridBuyIntent, ...]]:
    rules = MarketRules(BTCUSDT, PriceRules(p(1)), QuantityRules(q("0.001"), q("0.001")))
    plan = build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(100), p(110), 5), rules)
    state = bootstrap_grid_state(plan, p(105))
    sizing = size_grid_buys(state, rules, Money.parse("10", USDT))
    return state, build_buy_intents(state, sizing).intents


STATE, INTENTS = _pipeline()
INTENT, INTENT_1 = INTENTS[0], INTENTS[1]  # (0,0) 100 x 0.032 ; (1,0) 102 x 0.032
REF = BuyExecutionRef("exec-1")
CTX = BuyExecutionContext(INTENT, REF)


def fill(
    ref: str, qty: str, fee: str = "0", fee_asset: Asset = USDT, price: str = "100"
) -> ObservedBuyFill:
    return ObservedBuyFill(
        fill_ref=ref,
        cycle_ref=INTENT.cycle_ref,
        symbol=BTCUSDT,
        execution_price=p(price),
        executed_qty=q(qty),
        fee=Money.parse(fee, fee_asset),
        liquidity=LiquidityRole.MAKER,
    )


def ledger(*fills: ObservedBuyFill, intent: GridBuyIntent = INTENT) -> BuyFillLedger:
    result = BuyFillLedger(intent)
    for f in fills:
        result = result.record(f)
    return result


def report(
    status: BuyExecutionStatus, qty: str, refs: tuple[str, ...], **overrides: object
) -> ObservedBuyTerminalReport:
    fields: dict[str, object] = {
        "execution_ref": REF,
        "symbol": BTCUSDT,
        "cycle_ref": INTENT.cycle_ref,
        "final_status": status,
        "cumulative_executed_qty": q(qty),
        "fill_refs": refs,
    }
    fields.update(overrides)
    return ObservedBuyTerminalReport(**cast(Any, fields))


def evidence(qty: str, refs: tuple[str, ...], **overrides: object) -> BuyFillReconciliationEvidence:
    fields: dict[str, object] = {
        "execution_ref": REF,
        "symbol": BTCUSDT,
        "cycle_ref": INTENT.cycle_ref,
        "cumulative_executed_qty": q(qty),
        "fill_refs": refs,
    }
    fields.update(overrides)
    return BuyFillReconciliationEvidence(**cast(Any, fields))


def consistent(led: BuyFillLedger, status: BuyExecutionStatus) -> FinalizedBuy:
    """Finaliza com relatório e evidência coerentes com o ledger."""
    refs = tuple(f.fill_ref for f in led.fills)
    gross = str(led.gross_filled_qty.value)
    return finalize_buy(CTX, led, report(status, gross, refs), evidence(gross, refs))


def expect_error(code: BuyFinalizationErrorCode, fn: Any) -> BuyFinalizationError:
    with pytest.raises(BuyFinalizationError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ estados terminais aceitos


def test_filled_reconciled() -> None:
    led = ledger(fill("t1", "0.020"), fill("t2", "0.012"))
    fin = consistent(led, S.FILLED)
    assert fin.outcome is OUT.FULLY_ACQUIRED
    assert fin.final_status is S.FILLED
    assert fin.gross_filled_qty == q("0.032")
    assert fin.unexecuted_qty == Qty.zero()
    assert fin.is_sell_sizing_candidate
    assert (fin.execution_ref, fin.symbol, fin.cycle_ref) == (REF, BTCUSDT, INTENT.cycle_ref)


def test_canceled_partial_reconciled_mandatory_example() -> None:
    led = ledger(fill("t1", "0.010", fee="0.00001", fee_asset=BTC))
    fin = finalize_buy(CTX, led, report(S.CANCELED, "0.010", ("t1",)), evidence("0.010", ("t1",)))
    assert fin.final_status.is_terminal
    assert fin.outcome is OUT.PARTIALLY_ACQUIRED
    assert fin.gross_filled_qty == q("0.010")
    assert fin.unexecuted_qty == q("0.022")  # não executado e sem retry
    assert fin.net_acquired_base_qty == q("0.00999")  # fee em base reduz o líquido
    assert fin.inventory.net_qty == q("0.00999")
    assert fin.inventory.fill_refs == ("t1",)
    assert fin.is_sell_sizing_candidate


@pytest.mark.parametrize("status", [S.CANCELED, S.EXPIRED, S.REJECTED])
def test_terminal_without_execution_is_no_fill(status: BuyExecutionStatus) -> None:
    fin = consistent(ledger(), status)
    assert fin.outcome is OUT.NO_FILL
    assert fin.net_acquired_base_qty == Qty.zero()
    assert fin.inventory.net_qty == Qty.zero()
    assert not fin.is_sell_sizing_candidate
    assert fin.unexecuted_qty == q("0.032")


def test_expired_partial() -> None:
    fin = consistent(ledger(fill("t1", "0.005")), S.EXPIRED)
    assert fin.outcome is OUT.PARTIALLY_ACQUIRED
    assert fin.gross_filled_qty == q("0.005")


# ------------------------------------------------------------------ estados terminais recusados


@pytest.mark.parametrize("status", [S.OPEN, S.PARTIALLY_FILLED_OPEN])
def test_non_terminal_status_is_rejected(status: BuyExecutionStatus) -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.NOT_TERMINAL,
        lambda: finalize_buy(
            CTX, led, report(status, "0.010", ("t1",)), evidence("0.010", ("t1",))
        ),
    )


def test_filled_with_incomplete_quantity_is_rejected() -> None:
    led = ledger(fill("t1", "0.020"))
    expect_error(E.INVALID_TERMINAL_STATUS, lambda: consistent(led, S.FILLED))


@pytest.mark.parametrize("status", [S.CANCELED, S.EXPIRED])
def test_canceled_or_expired_with_full_quantity_is_rejected(status: BuyExecutionStatus) -> None:
    led = ledger(fill("t1", "0.032"))
    expect_error(E.INVALID_TERMINAL_STATUS, lambda: consistent(led, status))


def test_rejected_with_fills_is_an_inconsistency() -> None:
    err = expect_error(
        E.INVALID_TERMINAL_STATUS, lambda: consistent(ledger(fill("t1", "0.010")), S.REJECTED)
    )
    assert "reconciliação" in str(err)


# ------------------------------------------------------------------ quantidades e fills


def test_terminal_quantity_above_ledger_is_rejected() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.RECONCILIATION_MISMATCH,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.011", ("t1",)), evidence("0.010", ("t1",))
        ),
    )


def test_terminal_quantity_below_ledger_is_rejected() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.RECONCILIATION_MISMATCH,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.009", ("t1",)), evidence("0.010", ("t1",))
        ),
    )


def test_evidence_quantity_divergent_is_rejected() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.RECONCILIATION_MISMATCH,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.010", ("t1",)), evidence("0.012", ("t1",))
        ),
    )


def test_evidence_lacking_a_ledger_fill_is_rejected() -> None:
    # Ledger tem t1 e t2; a evidência só confirma t1 (com a mesma quantidade total).
    led = ledger(fill("t1", "0.005"), fill("t2", "0.005"))
    err = expect_error(
        E.EXTRA_FILL,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.010", ("t1", "t2")), evidence("0.010", ("t1",))
        ),
    )
    assert "t2" in str(err)


def test_evidence_with_unrecorded_fill_is_rejected() -> None:
    led = ledger(fill("t1", "0.010"))
    err = expect_error(
        E.MISSING_FILL,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.010", ("t1",)), evidence("0.010", ("t1", "t9"))
        ),
    )
    assert "t9" in str(err)


def test_terminal_report_refs_are_also_reconciled() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.MISSING_FILL,
        lambda: finalize_buy(
            CTX, led, report(S.CANCELED, "0.010", ("t1", "t9")), evidence("0.010", ("t1",))
        ),
    )


def test_duplicate_refs_in_evidence_or_report_are_rejected() -> None:
    expect_error(E.DUPLICATE_FILL_REF, lambda: evidence("0.010", ("t1", "t1")))
    expect_error(E.DUPLICATE_FILL_REF, lambda: report(S.CANCELED, "0.010", ("t1", "t1")))


def test_ref_order_does_not_matter() -> None:
    led = ledger(fill("t1", "0.010"), fill("t2", "0.012"), fill("t3", "0.010"))
    a = finalize_buy(
        CTX,
        led,
        report(S.FILLED, "0.032", ("t1", "t2", "t3")),
        evidence("0.032", ("t1", "t2", "t3")),
    )
    b = finalize_buy(
        CTX,
        led,
        report(S.FILLED, "0.032", ("t3", "t1", "t2")),
        evidence("0.032", ("t2", "t3", "t1")),
    )
    assert (a.outcome, a.gross_filled_qty, a.net_acquired_base_qty, a.inventory) == (
        b.outcome,
        b.gross_filled_qty,
        b.net_acquired_base_qty,
        b.inventory,
    )


def test_late_fill_blocks_premature_finalization_then_succeeds() -> None:
    # 1) cancelamento confirmado; 2) fill t2 executado antes ainda não chegou ao ledger.
    led = ledger(fill("t1", "0.010"))
    terminal = report(S.CANCELED, "0.015", ("t1", "t2"))
    proof = evidence("0.015", ("t1", "t2"))
    expect_error(E.RECONCILIATION_MISMATCH, lambda: finalize_buy(CTX, led, terminal, proof))
    # 3) o fill atrasado é contabilizado; a nova tentativa é coerente.
    fin = finalize_buy(CTX, led.record(fill("t2", "0.005")), terminal, proof)
    assert fin.outcome is OUT.PARTIALLY_ACQUIRED
    assert fin.gross_filled_qty == q("0.015")


# ------------------------------------------------------------------ identidade e vínculo


def test_execution_ref_mismatch() -> None:
    led = ledger(fill("t1", "0.010"))
    other = BuyExecutionRef("exec-2")
    expect_error(
        E.EXECUTION_REF_MISMATCH,
        lambda: finalize_buy(
            CTX,
            led,
            report(S.CANCELED, "0.010", ("t1",), execution_ref=other),
            evidence("0.010", ("t1",)),
        ),
    )
    expect_error(
        E.EXECUTION_REF_MISMATCH,
        lambda: finalize_buy(
            CTX,
            led,
            report(S.CANCELED, "0.010", ("t1",)),
            evidence("0.010", ("t1",), execution_ref=other),
        ),
    )


def test_symbol_mismatch() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.SYMBOL_MISMATCH,
        lambda: finalize_buy(
            CTX,
            led,
            report(S.CANCELED, "0.010", ("t1",), symbol=ETHUSDT),
            evidence("0.010", ("t1",)),
        ),
    )


def test_cycle_mismatch() -> None:
    led = ledger(fill("t1", "0.010"))
    expect_error(
        E.CYCLE_MISMATCH,
        lambda: finalize_buy(
            CTX,
            led,
            report(S.CANCELED, "0.010", ("t1",)),
            evidence("0.010", ("t1",), cycle_ref=CellCycleRef(0, 1)),
        ),
    )


def test_ledger_of_another_intent_is_rejected() -> None:
    other_ledger = BuyFillLedger(INTENT_1)
    expect_error(
        E.INTENT_MISMATCH,
        lambda: finalize_buy(CTX, other_ledger, report(S.CANCELED, "0", ()), evidence("0", ())),
    )


@pytest.mark.parametrize("raw", ["", " exec", "exec ", "x" * 129])
def test_invalid_execution_ref(raw: str) -> None:
    expect_error(E.INVALID_INPUT, lambda: BuyExecutionRef(raw))


def test_input_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        BuyExecutionContext(INTENT, cast(Any, "exec-1"))
    with pytest.raises(TypeError):
        report(cast(Any, "FILLED"), "0", ())
    with pytest.raises(TypeError):
        evidence("0", cast(Any, ["t1"]))
    expect_error(E.INVALID_INPUT, lambda: evidence("0.010", ("",)))
    with pytest.raises(TypeError):
        finalize_buy(CTX, cast(Any, "ledger"), report(S.CANCELED, "0", ()), evidence("0", ()))


# ------------------------------------------------------------------ fees e inventário


def test_quote_and_third_asset_fees_are_preserved_unconverted() -> None:
    led = ledger(
        fill("t1", "0.010", fee="0.001", fee_asset=USDT),
        fill("t2", "0.010", fee="0.00002", fee_asset=BNB),
    )
    fin = consistent(led, S.CANCELED)
    assert fin.net_acquired_base_qty == q("0.020")
    assert fin.quote_debit_total == Money.parse("2.001", USDT)
    assert fin.fees_by_asset == (Money.parse("0.00002", BNB), Money.parse("0.001", USDT))
    assert fin.has_unvalued_fees


def test_inventory_is_derived_from_ledger_and_exact() -> None:
    led = ledger(fill("t1", "0.032", fee="0.000032", fee_asset=BTC))
    fin = consistent(led, S.FILLED)
    assert fin.net_acquired_base_qty == led.net_acquired_base_qty == q("0.031968")
    assert fin.inventory == led.grid_owned_inventory
    assert "inventory" not in {f.name for f in dataclasses.fields(FinalizedBuy)}


# ------------------------------------------------------------------ construção direta / pureza


def test_tampered_direct_construction_is_rejected() -> None:
    fin = consistent(ledger(fill("t1", "0.010")), S.CANCELED)
    tampered: list[dict[str, object]] = [
        {"ledger": ledger(fill("t1", "0.010"), fill("t2", "0.001"))},  # fill extra
        {"terminal_report": report(S.OPEN, "0.010", ("t1",))},  # não terminal
        {"terminal_report": report(S.FILLED, "0.010", ("t1",))},  # FILLED incompleto
        {"reconciliation_evidence": evidence("0.009", ("t1",))},  # qty divergente
        {"context": BuyExecutionContext(INTENT, BuyExecutionRef("exec-x"))},
        {"context": BuyExecutionContext(INTENT_1, REF)},
        {"ledger": cast(Any, "ledger")},
    ]
    for changes in tampered:
        with pytest.raises(BuyFinalizationError) as excinfo:
            dataclasses.replace(fin, **cast(Any, changes))
        assert excinfo.value.code is E.INVALID_FINALIZED_BUY
        assert excinfo.value.__cause__ is not None


def test_valid_direct_construction_equals_finalize() -> None:
    led = ledger(fill("t1", "0.010"))
    args = (CTX, led, report(S.CANCELED, "0.010", ("t1",)), evidence("0.010", ("t1",)))
    assert FinalizedBuy(*args) == finalize_buy(*args)


def test_finalization_is_deterministic_and_immutable() -> None:
    led = ledger(fill("t1", "0.010"))
    a, b = consistent(led, S.CANCELED), consistent(led, S.CANCELED)
    assert a == b
    assert hash(a) == hash(b)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.ledger = BuyFillLedger(INTENT)  # type: ignore[misc]


def test_failed_finalization_changes_nothing() -> None:
    led = ledger(fill("t1", "0.010"))
    before = dataclasses.astuple(led)
    with pytest.raises(BuyFinalizationError):
        finalize_buy(CTX, led, report(S.CANCELED, "0.011", ("t1",)), evidence("0.011", ("t1",)))
    assert dataclasses.astuple(led) == before


def test_no_grid_state_transition_no_sell_and_no_retry() -> None:
    before = dataclasses.astuple(STATE)
    fin = consistent(ledger(), S.CANCELED)  # terminal sem execução
    assert dataclasses.astuple(STATE) == before  # GridState intacto (célula segue WAITING_BUY)
    assert STATE.cell(0).can_buy  # nada desarmou nem rearmou a célula
    public = {n for n in dir(fin) if not n.startswith("_")}
    assert not {n for n in public if "sell" in n.lower() and n != "is_sell_sizing_candidate"}
    assert not {n for n in public if "retry" in n.lower() or "intent" in n.lower()}
    assert list(inspect.signature(finalize_buy).parameters) == [
        "execution_context",
        "ledger",
        "terminal_report",
        "reconciliation_evidence",
    ]


def test_status_terminality() -> None:
    assert {s for s in S if s.is_terminal} == {S.FILLED, S.CANCELED, S.REJECTED, S.EXPIRED}


# ------------------------------------------------------------------ propriedades


@st.composite
def ledgers(draw: Any) -> BuyFillLedger:
    units = draw(st.lists(st.integers(min_value=1, max_value=8), min_size=1, max_size=6))
    led = BuyFillLedger(INTENT)
    total = 0
    for i, n in enumerate(units):
        if total + n > 32:
            break
        total += n
        asset = draw(st.sampled_from([BTC, USDT, BNB]))
        fee = str(D("0.000001") * n) if asset is BTC else "0.0001"
        led = led.record(fill(f"t{i}", str(D("0.001") * n), fee=fee, fee_asset=asset))
    return led


def _status_for(led: BuyFillLedger) -> BuyExecutionStatus:
    return S.FILLED if led.is_fully_filled else S.CANCELED


@given(ledgers(), st.randoms(use_true_random=False))
def test_consistent_evidence_finalizes_and_preserves_net(led: BuyFillLedger, rnd: Any) -> None:
    refs = [f.fill_ref for f in led.fills]
    rnd.shuffle(refs)
    gross = str(led.gross_filled_qty.value)
    status = _status_for(led)
    fin = finalize_buy(
        CTX, led, report(status, gross, tuple(refs)), evidence(gross, tuple(reversed(refs)))
    )
    assert fin.net_acquired_base_qty == led.net_acquired_base_qty
    assert fin == finalize_buy(
        CTX, led, report(status, gross, tuple(refs)), evidence(gross, tuple(reversed(refs)))
    )
    assert fin.outcome is (OUT.FULLY_ACQUIRED if led.is_fully_filled else OUT.PARTIALLY_ACQUIRED)


@given(ledgers(), st.integers(min_value=1, max_value=5))
def test_divergent_quantity_never_finalizes(led: BuyFillLedger, delta_units: int) -> None:
    refs = tuple(f.fill_ref for f in led.fills)
    wrong = str(led.gross_filled_qty.value + D("0.001") * delta_units)
    gross = str(led.gross_filled_qty.value)
    status = _status_for(led)
    expect_error(
        E.RECONCILIATION_MISMATCH,
        lambda: finalize_buy(CTX, led, report(status, gross, refs), evidence(wrong, refs)),
    )


@given(ledgers())
def test_removing_or_adding_a_ref_never_finalizes(led: BuyFillLedger) -> None:
    refs = tuple(f.fill_ref for f in led.fills)
    gross = str(led.gross_filled_qty.value)
    status = _status_for(led)
    expect_error(
        E.EXTRA_FILL,
        lambda: finalize_buy(CTX, led, report(status, gross, refs), evidence(gross, refs[1:])),
    )
    expect_error(
        E.MISSING_FILL,
        lambda: finalize_buy(
            CTX, led, report(status, gross, refs), evidence(gross, (*refs, "unknown"))
        ),
    )
