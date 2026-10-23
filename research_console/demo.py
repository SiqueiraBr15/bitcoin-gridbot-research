"""Adapt the existing synthetic demo; no new strategy or historical runner."""

from __future__ import annotations

from decimal import Context, localcontext
from fractions import Fraction
from typing import Any

from examples.paper_cycle import PATHS, synthetic_run, verify_conservation

from research_console.data import view
from research_console.risk import display


def demonstration() -> list[dict[str, Any]]:
    with localcontext(Context(prec=50)):
        return _demonstration()


def _demonstration() -> list[dict[str, Any]]:
    accounts = []
    for name in PATHS:
        result = synthetic_run(name)
        verify_conservation(result)
        initial = result.config.initial_quote.amount
        first = result.points[0]
        marks = [
            [
                result.config.effective_start.isoformat(),
                str(first.price.value),
                str(initial),
                "0",
                str(initial),
            ]
        ]
        marks.extend(
            [
                p.time.isoformat(),
                str(p.price.value),
                str(p.state.available_quote.amount + p.state.active_buy_reservations.amount),
                str(p.state.remaining_grid_base.value),
                str(p.quote_btc_equity.amount),
            ]
            for p in result.points
        )
        last = result.points[-1]
        row = {
            "policy": name,
            "cost": "FICTIONAL",
            "months": 0,
            "start": marks[0][0],
            "end": marks[-1][0],
            "initial_usdt": str(initial),
            "nav_usdt": str(last.quote_btc_equity.amount),
            "btc_physical": str(last.state.remaining_grid_base.value),
            "cash_usdt": marks[-1][2],
            "final_mark": marks[-1][1],
            "btc_equivalent": display(Fraction(marks[-1][4]) / Fraction(marks[-1][1])),
            "fees_usdt": str(sum(t.fee.amount for t in result.trades)),
            "max_drawdown_fraction": str(result.metrics.max_drawdown),
            "exposure_mean": display(result.metrics.capital_time_mean_exposure or Fraction(0)),
            "classification": "SYNTHETIC_DEMO",
        }
        account = view(row, marks)
        account["series"][0].update(available_usdt=str(initial), reserved_usdt="0")
        for point, native in zip(account["series"][1:], result.points, strict=True):
            point.update(
                available_usdt=str(native.state.available_quote.amount),
                reserved_usdt=str(native.state.active_buy_reservations.amount),
            )
        account.update(
            {
                "source_kind": "SYNTHETIC_DEMO",
                "conservation": "Fraction residual = 0; replay equal",
                "events": [
                    {"revision": e.revision, "kind": type(e.command).__name__}
                    for e in result.sources.events
                ],
                "fills": [
                    {
                        "order_ref": t.order_ref,
                        "side": t.side.value,
                        "btc": str(t.qty.value),
                        "price": str(t.price.value),
                        "fee_usdt": str(t.fee.amount),
                        "time": t.observed_at.isoformat(),
                    }
                    for t in result.trades
                ],
            }
        )
        accounts.append(account)
    return accounts
