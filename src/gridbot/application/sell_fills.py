"""Ledger SELL puro A16 (ADR-025): observação não é autorização nem liquidação.

Quote observado e notional derivado permanecem distintos. Recusas preservam o fill
no erro; a camada externa futura deve conservar também o evento bruto da fonte.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, DecimalException
from enum import StrEnum

from gridbot.application.operational_grid import (
    GridOperationalBook,
    _revalidate_finalized_buy,
    validate_operational_sell,
)
from gridbot.application.sell_lifecycle import (
    SellAttemptStatus,
    SellExecutionContext,
    SellExecutionRef,
    same_sell_authorization,
)
from gridbot.domain.assets import Asset, Symbol
from gridbot.domain.decimals import financial
from gridbot.domain.enums import LiquidityRole, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Money, Price, Qty
from gridbot.portfolio.buy_fills import is_valid_external_ref
from gridbot.strategy.grid_state import CellCycleRef


class SellFillErrorCode(StrEnum):
    INVALID_FILL = "INVALID_FILL"
    INVALID_LEDGER = "INVALID_LEDGER"
    INVALID_BOOK = "INVALID_BOOK"
    ATTEMPT_NOT_BOUND = "ATTEMPT_NOT_BOUND"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    EXECUTION_MISMATCH = "EXECUTION_MISMATCH"
    PRICE_BELOW_LIMIT = "PRICE_BELOW_LIMIT"
    OVERFILL = "OVERFILL"
    DUPLICATE_FILL_CONFLICT = "DUPLICATE_FILL_CONFLICT"
    BASE_FEE_EXCEEDS_HOLD = "BASE_FEE_EXCEEDS_HOLD"
    QUOTE_FEE_EXCEEDS_PROCEEDS = "QUOTE_FEE_EXCEEDS_PROCEEDS"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellFillError(DomainError):
    def __init__(
        self,
        code: SellFillErrorCode,
        detail: str,
        observation: ObservedSellFill | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.observation = observation


_E = SellFillErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}")


def _translate(exc: Exception, code: SellFillErrorCode) -> SellFillError:
    if isinstance(exc, DecimalException) or getattr(exc, "code", None) == (
        _E.FINANCIAL_PRECISION_ERROR
    ):
        code = _E.FINANCIAL_PRECISION_ERROR
    return SellFillError(code, str(exc))


def _validate_symbol(symbol: Symbol) -> None:
    _expect(symbol, Symbol, "symbol")
    replace(symbol.base)
    replace(symbol.quote)
    replace(symbol)


@dataclass(frozen=True, slots=True)
class ObservedSellFill:
    """Um trade recebido: IDs externos, quote obrigatório, comissão em seu ativo real.

    Zero quote é literal, nunca marcador de ausência. Divergência com price*qty é
    evidência pendente, não receita corrigida. LiquidityRole só quando observado.
    """

    execution_ref: SellExecutionRef
    fill_ref: str
    cycle_ref: CellCycleRef
    symbol: Symbol
    execution_price: Price
    executed_qty: Qty
    observed_quote: Money
    fee: Money
    liquidity: LiquidityRole | None = None
    side: Side = Side.SELL

    def __post_init__(self) -> None:
        try:
            for value, expected, field in (
                (self.execution_ref, SellExecutionRef, "execution_ref"),
                (self.cycle_ref, CellCycleRef, "cycle_ref"),
                (self.execution_price, Price, "execution_price"),
                (self.executed_qty, Qty, "executed_qty"),
                (self.observed_quote, Money, "observed_quote"),
                (self.fee, Money, "fee"),
            ):
                _expect(value, expected, field)
            replace(self.execution_ref)
            replace(self.cycle_ref)
            replace(self.execution_price)
            replace(self.executed_qty)
            replace(self.observed_quote)
            replace(self.fee)
            _validate_symbol(self.symbol)
            replace(self.observed_quote.asset)
            replace(self.fee.asset)
            if not is_valid_external_ref(self.fill_ref):
                raise DomainError("fill_ref externo inválido")
            if self.side is not Side.SELL:
                raise DomainError("fill exige lado SELL")
            if self.liquidity is not None:
                _expect(self.liquidity, LiquidityRole, "liquidity")
            if self.executed_qty.is_zero:
                raise DomainError("executed_qty deve ser positiva")
            if self.observed_quote.asset != self.symbol.quote:
                raise DomainError("observed_quote deve estar no ativo quote")
            if self.observed_quote.is_negative or self.fee.is_negative:
                raise DomainError("quote e comissão observados devem ser não negativos")
            # Também fecha falhas de precisão antes de aceitar o evento no ledger.
            _ = self.derived_quote_notional
        except (DomainError, TypeError, AttributeError, DecimalException) as exc:
            raise _translate(exc, _E.INVALID_FILL) from exc

    @property
    def trade_key(self) -> tuple[Symbol, SellExecutionRef, str]:
        return self.symbol, self.execution_ref, self.fill_ref

    @property
    def derived_quote_notional(self) -> Money:
        return Money(self.execution_price.notional(self.executed_qty), self.symbol.quote)


def _validate_context(context: SellExecutionContext) -> None:
    _expect(context, SellExecutionContext, "context")
    replace(context.execution_ref)
    _validate_symbol(context.symbol)
    replace(context.cycle_ref)
    replace(context.limit_price)
    replace(context.requested_qty)
    replace(context.intent.base_fee_hold)
    _revalidate_finalized_buy(context.intent.finalized_buy)
    for fill in context.intent.finalized_buy.ledger.fills:
        _validate_symbol(fill.symbol)
        replace(fill.fee.asset)
    replace(context.intent.reservation)
    replace(context.intent)
    replace(context)


@dataclass(frozen=True, slots=True)
class SellFillLedger:
    """Uma execução; contexto A15 como única fonte da autorização econômica.

    Construção direta valida estrutura/proveniência, não autoridade atual da raiz.
    Fills canônicos por fill_ref, sem cache financeiro ou estado terminal.
    """

    context: SellExecutionContext
    fills: tuple[ObservedSellFill, ...] = ()

    def __post_init__(self) -> None:
        try:
            _validate_context(self.context)
            if not isinstance(self.fills, tuple):
                raise TypeError("fills exige tuple imutável")
            for fill in self.fills:
                _expect(fill, ObservedSellFill, "fill")
                replace(fill)
                if fill.symbol != self.context.symbol:
                    raise SellFillError(_E.SYMBOL_MISMATCH, "fill de outro símbolo")
                if fill.cycle_ref != self.context.cycle_ref:
                    raise SellFillError(_E.CYCLE_MISMATCH, "fill de outro ciclo")
                if fill.execution_ref != self.context.execution_ref:
                    raise SellFillError(_E.EXECUTION_MISMATCH, "fill de outra execução")
                if fill.execution_price < self.context.limit_price:
                    raise SellFillError(
                        _E.PRICE_BELOW_LIMIT, "SELL LIMIT executada abaixo do limite"
                    )
            refs = tuple(f.fill_ref for f in self.fills)
            if len(set(refs)) != len(refs):
                raise SellFillError(_E.DUPLICATE_FILL_CONFLICT, "fill_ref repetido no construtor")
            if refs != tuple(sorted(refs)):
                raise SellFillError(_E.INVALID_LEDGER, "fills fora da ordem canônica")
            if self.gross_executed_qty > self.context.requested_qty:
                raise SellFillError(_E.OVERFILL, "execução excede sell_qty; hold não é ordem")
            if self.base_fee_qty > self.context.intent.base_fee_hold:
                raise SellFillError(_E.BASE_FEE_EXCEEDS_HOLD, "fee base excede hold; reconciliar")
            if self.quote_fee.amount > self.gross_observed_quote.amount:
                raise SellFillError(
                    _E.QUOTE_FEE_EXCEEDS_PROCEEDS, "fee quote excede receita observada"
                )
            # Valida também as agregações derivadas, sem substituir quote observado.
            _ = self.gross_derived_quote
            _ = self.fees_by_asset
            _ = self.remaining_qty
            _ = self.net_observed_quote
        except SellFillError:
            raise
        except (DomainError, TypeError, AttributeError, DecimalException) as exc:
            raise _translate(exc, _E.INVALID_LEDGER) from exc

    def _sum(self, values: tuple[Decimal, ...]) -> Decimal:
        try:
            with financial():
                return sum(values, Decimal(0))
        except DecimalException as exc:
            raise _translate(exc, _E.FINANCIAL_PRECISION_ERROR) from exc

    @property
    def gross_executed_qty(self) -> Qty:
        return Qty(self._sum(tuple(f.executed_qty.value for f in self.fills)))

    @property
    def remaining_qty(self) -> Qty:
        try:
            return self.context.requested_qty - self.gross_executed_qty
        except DecimalException as exc:
            raise _translate(exc, _E.FINANCIAL_PRECISION_ERROR) from exc

    @property
    def gross_observed_quote(self) -> Money:
        return Money(
            self._sum(tuple(f.observed_quote.amount for f in self.fills)), self.context.symbol.quote
        )

    @property
    def gross_derived_quote(self) -> Money:
        return Money(
            self._sum(tuple(f.derived_quote_notional.amount for f in self.fills)),
            self.context.symbol.quote,
        )

    def fee_for(self, asset: Asset) -> Money:
        _expect(asset, Asset, "asset")
        replace(asset)
        return Money(
            self._sum(tuple(f.fee.amount for f in self.fills if f.fee.asset == asset)), asset
        )

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        assets = sorted({f.fee.asset for f in self.fills}, key=lambda a: a.code)
        return tuple(self.fee_for(a) for a in assets)

    @property
    def base_fee_qty(self) -> Qty:
        return Qty(self.fee_for(self.context.symbol.base).amount)

    @property
    def quote_fee(self) -> Money:
        return self.fee_for(self.context.symbol.quote)

    @property
    def third_asset_fees(self) -> tuple[Money, ...]:
        return tuple(
            f
            for f in self.fees_by_asset
            if f.asset not in (self.context.symbol.base, self.context.symbol.quote)
        )

    @property
    def has_unvalued_third_asset_fees(self) -> bool:
        return any(f.amount > 0 for f in self.third_asset_fees)

    @property
    def net_observed_quote(self) -> Money:
        try:
            return self.gross_observed_quote - self.quote_fee
        except DecimalException as exc:
            raise _translate(exc, _E.FINANCIAL_PRECISION_ERROR) from exc

    @property
    def quote_discrepancy_refs(self) -> tuple[str, ...]:
        return tuple(f.fill_ref for f in self.fills if f.observed_quote != f.derived_quote_notional)


def _revalidate_ledger(ledger: SellFillLedger) -> None:
    _expect(ledger, SellFillLedger, "ledger")
    replace(ledger)


def build_sell_fill_ledger(book: GridOperationalBook, cycle_ref: CellCycleRef) -> SellFillLedger:
    """Origem legítima BOUND na raiz atual; nenhuma alteração/reserva consumida."""
    try:
        _expect(book, GridOperationalBook, "book")
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        replace(cycle_ref)
        validate_operational_sell(book, cycle_ref)
        attempt = book.attempt_for(cycle_ref)
        if attempt is None or attempt.status is not SellAttemptStatus.EXECUTION_BOUND:
            raise SellFillError(_E.ATTEMPT_NOT_BOUND, "ledger exige tentativa SELL vinculada")
        if attempt.execution is None:
            raise SellFillError(_E.ATTEMPT_NOT_BOUND, "vínculo sem contexto")
        return SellFillLedger(attempt.execution)
    except SellFillError:
        raise
    except (DomainError, TypeError, AttributeError, DecimalException) as exc:
        raise _translate(exc, _E.INVALID_BOOK) from exc


def validate_sell_fill_ledger_against_book(
    ledger: SellFillLedger, book: GridOperationalBook
) -> None:
    """Compatibilidade atual, sem autenticação, continuidade histórica ou liquidação."""
    try:
        _revalidate_ledger(ledger)
        current = build_sell_fill_ledger(book, ledger.context.cycle_ref)
        if (
            ledger.context.execution_ref != current.context.execution_ref
            or not same_sell_authorization(ledger.context.intent, current.context.intent)
        ):
            raise SellFillError(_E.AUTHORIZATION_MISMATCH, "ledger não pertence ao vínculo atual")
    except SellFillError:
        raise
    except (DomainError, TypeError, AttributeError, DecimalException) as exc:
        raise _translate(exc, _E.INVALID_LEDGER) from exc


def record_sell_fill(ledger: SellFillLedger, observed_fill: ObservedSellFill) -> SellFillLedger:
    """Revalida antes do no-op; duplicata conflitante falha sem modificar entradas."""
    try:
        _revalidate_ledger(ledger)
        _expect(observed_fill, ObservedSellFill, "observed_fill")
        replace(observed_fill)
        existing = next((f for f in ledger.fills if f.trade_key == observed_fill.trade_key), None)
        if existing is not None:
            if existing == observed_fill:
                return ledger
            raise SellFillError(_E.DUPLICATE_FILL_CONFLICT, "mesmo trade com conteúdo divergente")
        fills = tuple(sorted((*ledger.fills, observed_fill), key=lambda f: f.fill_ref))
        return SellFillLedger(ledger.context, fills)
    except SellFillError as exc:
        raise SellFillError(exc.code, str(exc), observed_fill) from exc
    except (DomainError, TypeError, AttributeError, DecimalException) as exc:
        translated = _translate(exc, _E.INVALID_FILL)
        raise SellFillError(translated.code, str(translated), observed_fill) from exc
