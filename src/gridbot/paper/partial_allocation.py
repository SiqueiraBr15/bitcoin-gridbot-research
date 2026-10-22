"""Pure, conservative admission for the experimental partial PAPER grid.

No wallet, fills or reservations are created here. All financial arithmetic uses
the exact native Decimal context; floor division chooses explicit integer steps.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from gridbot.domain import BTC, BTCUSDT, USDT, Asset, MarketRules, Money, Price, Qty
from gridbot.domain.decimals import financial, require_finite
from gridbot.paper.accounting import _exact, _require
from gridbot.strategy import build_buy_intents, size_grid_buys
from gridbot.strategy.buy_intents import BuyIntentPlan
from gridbot.strategy.grid_state import GridState

PARTIAL_POLICY = "PARTIAL_NEAREST_EQUAL_BASE_90_V1"
EXPOSURE_CAP = Decimal("0.90")


@dataclass(frozen=True, slots=True)
class PartialCosts:
    rate: Decimal
    asset: Asset

    def __post_init__(self) -> None:
        require_finite(self.rate, field="partial commission rate")
        _require(Decimal(0) <= self.rate < Decimal(1), "invalid commission rate")
        _exact(self.asset, Asset)
        replace(self.asset)

    def fee(self, price: Price, qty: Qty) -> Money:
        _require(self.asset in (BTC, USDT), "THIRD_ASSET_VALUATION_REQUIRED")
        with financial():
            amount = qty.value if self.asset == BTC else price.notional(qty)
            return Money(amount * self.rate, self.asset)


@dataclass(frozen=True, slots=True)
class BuyCommitment:
    price: Price
    qty: Qty
    quote_fee_hold: Money
    projected_base_fee: Qty

    def __post_init__(self) -> None:
        for value, expected in (
            (self.price, Price),
            (self.qty, Qty),
            (self.quote_fee_hold, Money),
            (self.projected_base_fee, Qty),
        ):
            _exact(value, expected)
            replace(value)
        _require(not self.qty.is_zero, "empty BUY commitment")
        _require(
            self.quote_fee_hold.asset == USDT and not self.quote_fee_hold.is_negative,
            "invalid quote fee hold",
        )
        _require(self.projected_base_fee < self.qty, "base fee consumes BUY")

    @property
    def total_quote(self) -> Money:
        return Money(self.price.notional(self.qty), USDT) + self.quote_fee_hold


@dataclass(frozen=True, slots=True)
class PartialAllocationInput:
    state: GridState
    rules: MarketRules
    available: Money
    buy_reservations: Money
    grid_base: Qty
    sell_reservations: Qty
    mark: Price
    notional_ceiling: Money
    costs: PartialCosts
    commitments: tuple[BuyCommitment, ...] = ()
    third_assets_present: bool = False

    def __post_init__(self) -> None:
        for value, expected in (
            (self.state, GridState),
            (self.rules, MarketRules),
            (self.available, Money),
            (self.buy_reservations, Money),
            (self.grid_base, Qty),
            (self.sell_reservations, Qty),
            (self.mark, Price),
            (self.notional_ceiling, Money),
            (self.costs, PartialCosts),
        ):
            _exact(value, expected)
            replace(value)
        _require(self.state.plan.spec.symbol == self.rules.symbol == BTCUSDT, "BTC/USDT only")
        for amount in (self.available, self.buy_reservations, self.notional_ceiling):
            _require(amount.asset == USDT and not amount.is_negative, "invalid USDT input")
        _require(self.sell_reservations <= self.grid_base, "SELL hold exceeds GRID BTC")
        _exact(self.commitments, tuple)
        for item in self.commitments:
            _exact(item, BuyCommitment)
            replace(item)
        _require(
            sum((c.total_quote for c in self.commitments), Money.zero(USDT))
            == self.buy_reservations,
            "BUY reservation inventory incomplete",
        )
        _exact(self.third_assets_present, bool)


@dataclass(frozen=True, slots=True)
class PartialAllocation:
    source: PartialAllocationInput
    state: GridState
    plan: BuyIntentPlan | None
    fees: tuple[Money, ...]
    required_quote: Money
    residual_quote: Money
    projected_gross_base: Qty
    exposure_numerator: Money
    exposure_denominator: Money
    blockers: tuple[str, ...]
    policy: str = PARTIAL_POLICY

    @property
    def admissible(self) -> bool:
        return self.plan is not None and bool(self.plan.intents) and not self.blockers


def allocate_partial(source: PartialAllocationInput) -> PartialAllocation:
    """Largest nearest-price prefix; then maximum common quantity in integer steps.

    N / D <= .9 is tested without rounded division. N deliberately counts gross
    BUY BTC; D removes every forecast fee and adverse mark-to-limit difference.
    No future SELL credit or favorable mark-to-limit gain is assumed.
    """
    _exact(source, PartialAllocationInput)
    replace(source)
    with financial():
        mark = source.mark.value
        base_mark = source.grid_base.value * mark
        nav = source.available.amount + source.buy_reservations.amount + base_mark
        numerator = base_mark
        denominator = nav
        for commitment in source.commitments:
            numerator += commitment.qty.value * mark
            denominator -= (
                commitment.quote_fee_hold.amount
                + commitment.projected_base_fee.value * mark
                + max(Decimal(0), commitment.price.value - mark) * commitment.qty.value
            )
        empty = PartialAllocation(
            source,
            source.state,
            None,
            (),
            Money.zero(USDT),
            source.available,
            source.grid_base + sum((c.qty for c in source.commitments), Qty.zero()),
            Money(numerator, USDT),
            Money(denominator, USDT),
            (),
        )
        if source.third_assets_present or source.costs.asset not in (BTC, USDT):
            return replace(empty, blockers=("THIRD_ASSET_VALUATION_REQUIRED",))
        if denominator <= 0 or numerator >= EXPOSURE_CAP * denominator:
            return replace(empty, blockers=("GLOBAL_EXPOSURE_HEADROOM_EXHAUSTED",))
        armed = sorted(
            (c for c in source.state.cells if c.can_buy),
            key=lambda c: (-c.cell.buy_price.value, c.cell.index),
        )
        step = source.rules.quantity.step_size.value
        for count in range(len(armed), 0, -1):
            chosen = armed[:count]
            prices = [c.cell.buy_price.value for c in chosen]
            price_sum = sum(prices, Decimal(0))
            quote_fee = price_sum * source.costs.rate if source.costs.asset == USDT else Decimal(0)
            base_fee = (
                Decimal(count) * source.costs.rate if source.costs.asset == BTC else Decimal(0)
            )
            nav_loss = (
                quote_fee
                + base_fee * mark
                + sum((max(Decimal(0), p - mark) for p in prices), Decimal(0))
            )
            units = min(
                source.available.amount // (step * (price_sum + quote_fee)),
                source.notional_ceiling.amount // (step * price_sum),
                (EXPOSURE_CAP * denominator - numerator)
                // (step * (Decimal(count) * mark + EXPOSURE_CAP * nav_loss)),
            )
            for p in prices:
                if source.rules.quantity.max_qty is not None:
                    units = min(units, source.rules.quantity.max_qty.value // step)
                if (
                    source.rules.notional is not None
                    and source.rules.notional.max_notional is not None
                ):
                    units = min(units, source.rules.notional.max_notional // (p * step))
            if units <= 0:
                continue
            qty = Qty(step * units)
            if not all(source.rules.check(BTCUSDT, Price(p), qty).ok for p in prices):
                continue
            selected = {c.cell.index for c in chosen}
            state = replace(
                source.state,
                cells=tuple(
                    replace(c, buy_armed=False) if c.can_buy and c.cell.index not in selected else c
                    for c in source.state.cells
                ),
            )
            budget = Money(qty.value * price_sum, USDT)
            plan = build_buy_intents(state, size_grid_buys(state, source.rules, budget))
            fees = tuple(source.costs.fee(i.price, i.qty) for i in plan.intents)
            required = budget + sum((f for f in fees if f.asset == USDT), Money.zero(USDT))
            projected_n = numerator + Decimal(count) * qty.value * mark
            projected_d = denominator - qty.value * nav_loss
            _require(required.amount <= source.available.amount, "partial funding bound violated")
            _require(projected_n <= EXPOSURE_CAP * projected_d, "partial exposure bound violated")
            return PartialAllocation(
                source,
                state,
                plan,
                fees,
                required,
                source.available - required,
                empty.projected_gross_base + Qty(Decimal(count) * qty.value),
                Money(projected_n, USDT),
                Money(projected_d, USDT),
                (),
            )
        return replace(empty, blockers=("NO_VALID_FUNDED_PREFIX",))
