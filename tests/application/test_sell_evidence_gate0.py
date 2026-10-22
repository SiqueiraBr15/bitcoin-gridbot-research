from dataclasses import replace
from typing import Any, cast

import pytest

from gridbot.application.operational_grid import _revalidate_finalized_buy
from gridbot.application.sell_order_binding import ExternalSellOrderBinding, SellOrderBindingError
from gridbot.application.sell_reconciliation import (
    SellBindingVerification,
    SellCollectionVerification,
    assess_sell_finalization,
)
from gridbot.domain import DomainError, FloatNotAllowedError
from tests.application.test_external_sell_identity import native_scenario
from tests.application.test_sell_intents import forged
from tests.application.test_sell_inventory import finish, prepare


def test_no_sources_only_proves_local_binding() -> None:
    root, ledger, _, _ = native_scenario()
    assert assess_sell_finalization(root, ledger, None).binding_verification is (
        SellBindingVerification.LOCALLY_CONSISTENT
    )


def test_missing_terminal_fields_prevents_positive_collection() -> None:
    root, ledger, report, col = native_scenario()
    report = replace(report, status=None, cumulative_executed_qty=None, cumulative_quote=None)
    assert assess_sell_finalization(root, ledger, report, col).collection_verification is (
        SellCollectionVerification.INSUFFICIENT_METADATA
    )


def test_stale_root_prevents_positive_collection() -> None:
    root, ledger, report, col = native_scenario()
    stale = replace(root, sell_attempts=(), external_sell_bindings=())
    assert assess_sell_finalization(stale, ledger, report, col).collection_verification is (
        SellCollectionVerification.ROOT_UNVERIFIED
    )


@pytest.mark.parametrize("asset", ["base", "quote"])
def test_no_fill_buy_deep_assets_are_validated(asset: str) -> None:
    f = finish(prepare(), qty=None)
    sym = forged(f.symbol, **{asset: forged(getattr(f.symbol, asset), code="invalid")})
    intent = forged(f.context.intent, symbol=sym)
    f = forged(
        f,
        context=forged(f.context, intent=intent),
        ledger=forged(f.ledger, intent=intent),
        terminal_report=forged(f.terminal_report, symbol=sym),
        reconciliation_evidence=forged(f.reconciliation_evidence, symbol=sym),
    )
    with pytest.raises(DomainError):
        _revalidate_finalized_buy(f)


@pytest.mark.parametrize("asset", ["base", "quote"])
def test_invalid_fill_asset_is_diagnosed_before_symbol_comparison(asset: str) -> None:
    f = finish(prepare())
    fill = f.ledger.fills[0]
    sym = forged(fill.symbol, **{asset: forged(getattr(fill.symbol, asset), code="invalid")})
    f = forged(f, ledger=forged(f.ledger, fills=(forged(fill, symbol=sym),)))
    with pytest.raises(DomainError) as error:
        _revalidate_finalized_buy(f)
    assert type(error.value) is DomainError


@pytest.mark.parametrize(("value", "cause"), [("SELL", TypeError), (1.0, FloatNotAllowedError)])
def test_binding_preserves_invalid_type_cause(value: object, cause: type[Exception]) -> None:
    root, _, report, _ = native_scenario()
    with pytest.raises(SellOrderBindingError) as error:
        ExternalSellOrderBinding(report.identity, cast(Any, value))
    assert isinstance(error.value.__cause__, cause)
    assert root.external_binding_for(report.identity.cycle_ref) is not None
