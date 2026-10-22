"""Informational MTM and exact dimensionless ratios; no financial authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from itertools import pairwise

from gridbot.backtest.execution import BNB
from gridbot.domain import BTC, USDT, LiquidityRole, Money, Price, Qty, Side
from gridbot.paper.simulation import SimulationSnapshot
from gridbot.strategy import CellCycleRef


@dataclass(frozen=True, slots=True)
class Trade:
    order_ref: str
    cycle_ref: CellCycleRef
    side: Side
    bar_open: datetime
    observed_at: datetime
    price: Price
    qty: Qty
    fee: Money
    liquidity: LiquidityRole


@dataclass(frozen=True, slots=True)
class Decision:
    time: datetime
    kind: str
    ref: str
    detail: str


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time: datetime
    price: Price
    state: SimulationSnapshot
    quote_btc_equity: Money
    equity: Money | None
    btc_mark: Money
    exposure: Fraction | None
    utilization: Fraction | None


def equity_point(
    time: datetime, price: Price, state: SimulationSnapshot, bnb_mark: Price | None
) -> EquityPoint:
    btc = Money(price.notional(state.remaining_grid_base), USDT)
    component = state.available_quote + state.active_buy_reservations + btc
    complete: Money | None = component
    for balance in state.third_asset_balances:
        if not balance.amount:
            continue
        if balance.asset != BNB or bnb_mark is None:
            complete = None
        elif complete is not None:
            complete = complete + Money(bnb_mark.notional(Qty(balance.amount)), USDT)
    if state.third_asset_obligations:
        complete = None
    exposure = (
        Fraction(btc.amount) / Fraction(complete.amount)
        if complete is not None and complete.amount > 0
        else None
    )
    utilization = (
        Fraction((btc + state.active_buy_reservations).amount) / Fraction(component.amount)
        if component.amount > 0
        else None
    )
    return EquityPoint(time, price, state, component, complete, btc, exposure, utilization)


def max_drawdown(points: tuple[EquityPoint, ...], initial: Money | None) -> Fraction | None:
    if initial is None or initial.amount <= 0 or any(p.equity is None for p in points):
        return None
    peak = initial.amount
    result = Fraction(0)
    for point in points:
        if point.equity is None:
            return None
        current = point.equity.amount
        peak = max(peak, current)
        if peak > 0:
            result = max(result, (Fraction(peak) - Fraction(current)) / Fraction(peak))
    return result


def capital_time_average(points: tuple[EquityPoint, ...], field: str) -> Fraction | None:
    """Integral of employed value / integral of equity, using left-closed samples.

    This is capital-time weighting, not the arithmetic mean of per-bar ratios.
    Monetary integrals have power-of-ten denominators, avoiding unbounded LCM growth.
    """
    numerator = Fraction(0)
    denominator = Fraction(0)
    for left, right in pairwise(points):
        duration = (right.time - left.time) // timedelta(microseconds=1)
        if field == "exposure":
            if left.equity is None:
                return None
            employed, equity = left.btc_mark, left.equity
        else:
            employed = left.btc_mark + left.state.active_buy_reservations
            equity = left.quote_btc_equity
        numerator += Fraction(employed.amount) * duration
        denominator += Fraction(equity.amount) * duration
    return numerator / denominator if denominator > 0 else None


def fee_totals(trades: tuple[Trade, ...]) -> tuple[Money, ...]:
    totals: dict[str, Money] = {}
    for trade in trades:
        asset = trade.fee.asset
        totals[asset.code] = totals.get(asset.code, Money.zero(asset)) + trade.fee
    return tuple(totals[a] for a in sorted(totals))


@dataclass(frozen=True, slots=True)
class Metrics:
    initial_quote: Money
    available_quote: Money
    reserved_quote: Money
    buy_spending: Money
    settled_sell_proceeds: Money
    initial_grid_btc: Qty
    bought_btc: Qty
    sold_btc: Qty
    commission_btc: Qty
    final_grid_btc: Qty
    reserved_btc: Qty
    available_btc: Qty
    physical_btc_change: Qty
    physical_btc_change_pct: Fraction | None
    final_btc_equivalent: Fraction | None
    initial_equity: Money | None
    final_equity: Money | None
    return_pct: Fraction | None
    max_drawdown: Fraction | None
    capital_time_mean_exposure: Fraction | None
    capital_time_mean_quote_btc_utilization: Fraction | None
    final_capital_employed_mtm: Money
    fills: int
    cycles: int
    fees: tuple[Money, ...]
    hypothetical_proportional_pnl: Money | None
    realized_pnl: None = None


def summarize(
    initial_quote: Money,
    initial_equity: Money | None,
    points: tuple[EquityPoint, ...],
    trades: tuple[Trade, ...],
    studies: tuple[Money | None, ...],
) -> Metrics:
    last = points[-1]
    state = last.state
    bought = sum((t.qty for t in trades if t.side is Side.BUY), Qty.zero())
    sold = sum((t.qty for t in trades if t.side is Side.SELL), Qty.zero())
    base_fees = Qty(sum((m for m in fee_totals(trades) if m.asset == BTC), Money.zero(BTC)).amount)
    equivalent = (
        Fraction(last.equity.amount) / Fraction(last.price.value)
        if last.equity is not None
        else None
    )
    pct = (
        100 * (Fraction(last.equity.amount) / Fraction(initial_equity.amount) - 1)
        if last.equity is not None and initial_equity is not None and initial_equity.amount > 0
        else None
    )
    pnl: Money | None = None
    if studies and all(s is not None for s in studies):
        pnl = sum((s for s in studies if s is not None), Money.zero(USDT))
    return Metrics(
        initial_quote,
        state.available_quote,
        state.active_buy_reservations,
        state.buy_spending,
        state.settled_sell_proceeds,
        Qty.zero(),
        bought,
        sold,
        base_fees,
        state.remaining_grid_base,
        state.reserved_grid_base,
        state.remaining_grid_base - state.reserved_grid_base,
        state.remaining_grid_base,
        None,
        equivalent,
        initial_equity,
        last.equity,
        pct,
        max_drawdown(points, initial_equity),
        capital_time_average(points, "exposure"),
        capital_time_average(points, "utilization"),
        last.btc_mark + state.active_buy_reservations,
        len(trades),
        sum(c.cycle_seq for c in state.grid_state.cells),
        fee_totals(trades),
        pnl,
    )
