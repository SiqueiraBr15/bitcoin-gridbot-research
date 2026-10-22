"""Contabilidade pura de fills BUY e inventário confirmado do grid (ADR-016).

INTENDED QUANTITY ≠ EXECUTED QUANTITY ≠ NET ACQUIRED QUANTITY.

``GridBuyIntent`` -> fills observados -> ``BuyFillLedger`` -> inventário líquido do ciclo.

- Fills são dados de fora (testes, futuros simuladores/adapters); nada aqui gera fills, lê
  candles, envia ordens, cria SELL ou altera ``GridState``.
- Fee no ativo base reduz o inventário; fee em quote é custo adicional em quote; fee em
  terceiro ativo (ex.: BNB) é só registrada, sem conversão, e marca o custo como não
  valorado.
- O inventário líquido é preservado exato: não é arredondado ao ``step_size``.
  Quantidade vendável, dust e encerramento do ciclo são da próxima fase.
- GRID_OWNED_INVENTORY: o ledger só contém BTC adquirido pelos fills BUY da intenção
  daquele ``cycle_ref``. Nenhuma função recebe saldo de carteira; BTC Core nunca entra
  (GRID CANNOT SELL CORE BTC).
- GRID_OWNED_INVENTORY_IS_A_LEDGER_PROJECTION: a autoridade sobre a quantidade adquirida
  é o ``BuyFillLedger`` validado; um ``GridOwnedInventory`` isolado é só uma projeção.
- Idempotência local: o mesmo ``fill_ref`` com conteúdo idêntico é no-op; com conteúdo
  diferente é erro. Não há garantia entre ledgers nem entre reinicializações
  (GLOBAL_PERSISTENT_FILL_DEDUPLICATION é requisito da futura orquestração).
- Precisão financeira fail-closed: qualquer erro ``Decimal`` (ex.: ``Inexact``) vira
  ``FINANCIAL_PRECISION_ERROR``, com a exceção original encadeada; nada é arredondado.
- Um fill parcial é um evento de execução observado, não uma ordem independente: não se
  exige que cada fill satisfaça min qty, min notional ou step da ordem original.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum

from gridbot.domain.assets import Asset, Symbol
from gridbot.domain.decimals import financial
from gridbot.domain.enums import LiquidityRole, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Money, Price, Qty
from gridbot.strategy.buy_intents import GridBuyIntent
from gridbot.strategy.grid_state import CellCycleRef

_MAX_FILL_REF_LEN = 128


class BuyFillErrorCode(StrEnum):
    INVALID_FILL = "INVALID_FILL"
    INVALID_FEE = "INVALID_FEE"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    PRICE_ABOVE_BUY_LIMIT = "PRICE_ABOVE_BUY_LIMIT"
    OVERFILL = "OVERFILL"
    DUPLICATE_FILL_CONFLICT = "DUPLICATE_FILL_CONFLICT"
    INVALID_LEDGER = "INVALID_LEDGER"
    INVALID_INVENTORY = "INVALID_INVENTORY"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class BuyFillError(DomainError):
    """Fill, ledger ou inventário inválidos; ``code`` identifica o motivo."""

    def __init__(self, code: BuyFillErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def is_valid_external_ref(ref: object) -> bool:
    """Referência externa opaca válida: str não vazia, sem espaços nas pontas, <= 128."""
    return (
        isinstance(ref, str) and bool(ref) and ref == ref.strip() and len(ref) <= _MAX_FILL_REF_LEN
    )


@contextmanager
def _precision_guard(operation: str) -> Iterator[None]:
    """Converte erro de precisão ``Decimal`` em erro de domínio, sem arredondar."""
    try:
        yield
    except DecimalException as exc:
        raise BuyFillError(
            BuyFillErrorCode.FINANCIAL_PRECISION_ERROR,
            f"{operation} excede a precisão financeira; nenhum arredondamento feito",
        ) from exc


@dataclass(frozen=True, slots=True)
class ObservedBuyFill:
    """Execução BUY confirmada, informada de fora. Não é ordem nem fill de exchange.

    ``fill_ref`` é um identificador opaco fornecido externamente (nunca gerado aqui).
    Contrato para o futuro provedor: derivar de uma identidade ESTÁVEL do trade real,
    no escopo de unicidade do provedor (ex.: exchange + conta + símbolo + ordem + trade).
    O mesmo trade reenviado gera o mesmo ``fill_ref``; trades diferentes geram refs
    diferentes. Nunca usar UUID aleatório, relógio, sequência reiniciável ou contador
    local não persistido. O ledger não detecta que dois refs diferentes são o mesmo trade.

    Sem timestamp e sem client order id. ``fee`` é o valor observado, fonte do custo.
    """

    fill_ref: str
    cycle_ref: CellCycleRef
    symbol: Symbol
    execution_price: Price
    executed_qty: Qty
    fee: Money
    liquidity: LiquidityRole
    side: Side = Side.BUY

    def __post_init__(self) -> None:
        ref = self.fill_ref
        if not is_valid_external_ref(ref):
            raise BuyFillError(BuyFillErrorCode.INVALID_FILL, f"fill_ref inválido: {ref!r}")
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.execution_price, Price, "execution_price")
        _expect(self.executed_qty, Qty, "executed_qty")
        _expect(self.fee, Money, "fee")
        _expect(self.liquidity, LiquidityRole, "liquidity")
        _expect(self.side, Side, "side")
        if self.side is not Side.BUY:
            raise BuyFillError(BuyFillErrorCode.INVALID_FILL, f"{ref}: só fills BUY nesta fase")
        if self.executed_qty.is_zero:
            raise BuyFillError(BuyFillErrorCode.INVALID_FILL, f"{ref}: executed_qty deve ser > 0")
        if self.fee.is_negative:
            raise BuyFillError(BuyFillErrorCode.INVALID_FEE, f"{ref}: fee negativa")
        if self.fee.asset == self.symbol.base and self.fee.amount >= self.executed_qty.value:
            # Fee em base >= quantidade bruta deixaria inventário líquido <= 0: falha fechado.
            raise BuyFillError(
                BuyFillErrorCode.INVALID_FEE,
                f"{ref}: fee em base {self.fee} >= executed_qty {self.executed_qty}",
            )

    @property
    def base_fee(self) -> Qty:
        """Fee cobrada no ativo base (reduz o inventário); zero se em outro ativo."""
        return Qty(self.fee.amount) if self.fee.asset == self.symbol.base else Qty.zero()

    @property
    def net_base_qty(self) -> Qty:
        """Base líquida deste fill: ``executed_qty - base_fee`` (exato)."""
        with _precision_guard(f"net_base_qty de {self.fill_ref}"):
            return self.executed_qty - self.base_fee

    @property
    def quote_notional(self) -> Money:
        with _precision_guard(f"notional de {self.fill_ref}"):
            return Money(self.execution_price.notional(self.executed_qty), self.symbol.quote)


@dataclass(frozen=True, slots=True)
class GridOwnedInventory:
    """Inventário de base do grid para uma célula num ciclo.

    GRID_OWNED_INVENTORY_IS_A_LEDGER_PROJECTION: este objeto é uma PROJEÇÃO do
    ``BuyFillLedger``. A validação abaixo garante só consistência estrutural (tipos, refs
    válidas e únicas, ``net_qty > 0`` se e só se houver refs); ela NÃO prova que as refs
    correspondem a fills verdadeiros. A autoridade sobre a quantidade adquirida é o ledger
    validado; uma futura venda deve consumir evidência de execução finalizada e
    reconciliada derivada do ledger, nunca um inventário construído isoladamente.
    """

    symbol: Symbol
    cycle_ref: CellCycleRef
    net_qty: Qty
    fill_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.net_qty, Qty, "net_qty")
        if not isinstance(self.fill_refs, tuple):
            raise TypeError("fill_refs deve ser tuple[str, ...] (imutável)")
        invalid = [ref for ref in self.fill_refs if not is_valid_external_ref(ref)]
        if invalid:
            raise BuyFillError(
                BuyFillErrorCode.INVALID_INVENTORY, f"fill_refs inválidos: {invalid!r}"
            )
        if len(set(self.fill_refs)) != len(self.fill_refs):
            raise BuyFillError(BuyFillErrorCode.INVALID_INVENTORY, "fill_refs repetidos")
        if self.fill_refs and self.net_qty.is_zero:
            raise BuyFillError(
                BuyFillErrorCode.INVALID_INVENTORY, "inventário com fills deve ter net_qty > 0"
            )
        if not self.fill_refs and not self.net_qty.is_zero:
            raise BuyFillError(
                BuyFillErrorCode.INVALID_INVENTORY, "net_qty > 0 exige referências de fills"
            )


@dataclass(frozen=True, slots=True)
class BuyFillLedger:
    """Fills confirmados de UMA intenção BUY (um ``cycle_ref``). Imutável.

    É a AUTORIDADE sobre o inventário adquirido no ciclo. ``record`` devolve um novo
    ledger; o original fica intacto. Invariantes (verificadas também na construção
    direta): cada fill do mesmo símbolo e ciclo da intenção, preço <= limite da compra,
    ``fill_ref`` único e soma das quantidades <= quantidade pretendida.
    """

    intent: GridBuyIntent
    fills: tuple[ObservedBuyFill, ...] = ()

    def __post_init__(self) -> None:
        _expect(self.intent, GridBuyIntent, "intent")
        if not isinstance(self.fills, tuple) or not all(
            isinstance(f, ObservedBuyFill) for f in self.fills
        ):
            raise TypeError("fills deve ser tuple[ObservedBuyFill, ...] (imutável)")
        refs = [f.fill_ref for f in self.fills]
        if len(set(refs)) != len(refs):
            raise BuyFillError(BuyFillErrorCode.INVALID_LEDGER, "fill_ref repetido no ledger")
        for fill in self.fills:
            self._check_against_intent(fill)
        total = self.gross_filled_qty
        if total > self.intent.qty:
            raise BuyFillError(
                BuyFillErrorCode.OVERFILL,
                f"executado {total} > pretendido {self.intent.qty} ({self.intent.cycle_ref})",
            )

    def _check_against_intent(self, fill: ObservedBuyFill) -> None:
        intent = self.intent
        if fill.symbol != intent.symbol:
            raise BuyFillError(
                BuyFillErrorCode.SYMBOL_MISMATCH,
                f"{fill.fill_ref}: fill de {fill.symbol}, intenção de {intent.symbol}",
            )
        if fill.cycle_ref != intent.cycle_ref:
            raise BuyFillError(
                BuyFillErrorCode.CYCLE_MISMATCH,
                f"{fill.fill_ref}: fill de {fill.cycle_ref}, intenção de {intent.cycle_ref}",
            )
        if fill.execution_price > intent.price:
            raise BuyFillError(
                BuyFillErrorCode.PRICE_ABOVE_BUY_LIMIT,
                f"{fill.fill_ref}: executado a {fill.execution_price} > limite {intent.price}",
            )

    def record(self, fill: ObservedBuyFill) -> BuyFillLedger:
        """Registra um fill. Mesmo ``fill_ref`` idêntico: devolve ``self`` (no-op);
        conflitante: ``DUPLICATE_FILL_CONFLICT``. Overfill nunca é ajustado."""
        _expect(fill, ObservedBuyFill, "fill")
        for existing in self.fills:
            if existing.fill_ref == fill.fill_ref:
                if existing == fill:
                    return self
                raise BuyFillError(
                    BuyFillErrorCode.DUPLICATE_FILL_CONFLICT,
                    f"fill_ref {fill.fill_ref} já registrado com outro conteúdo",
                )
        return BuyFillLedger(self.intent, (*self.fills, fill))

    # ---------------------------------------------------------------- derivados

    @property
    def symbol(self) -> Symbol:
        return self.intent.symbol

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref

    @property
    def intended_qty(self) -> Qty:
        return self.intent.qty

    @property
    def gross_filled_qty(self) -> Qty:
        total = Qty.zero()
        with _precision_guard("soma de executed_qty"):
            for fill in self.fills:
                total = total + fill.executed_qty
        return total

    @property
    def remaining_qty(self) -> Qty:
        with _precision_guard("remaining_qty"):
            return self.intended_qty - self.gross_filled_qty

    @property
    def total_base_fee(self) -> Qty:
        total = Qty.zero()
        with _precision_guard("soma de fees em base"):
            for fill in self.fills:
                total = total + fill.base_fee
        return total

    @property
    def net_acquired_base_qty(self) -> Qty:
        """Bruto executado menos fees em base. Exato; nunca quantizado ao step."""
        with _precision_guard("net_acquired_base_qty"):
            return self.gross_filled_qty - self.total_base_fee

    @property
    def gross_quote_notional(self) -> Money:
        total = Money.zero(self.symbol.quote)
        with _precision_guard("soma de notional"):
            for fill in self.fills:
                total = total + fill.quote_notional
        return total

    @property
    def quote_fee_total(self) -> Money:
        total = Money.zero(self.symbol.quote)
        with _precision_guard("soma de fees em quote"):
            for fill in self.fills:
                if fill.fee.asset == self.symbol.quote:
                    total = total + fill.fee
        return total

    @property
    def quote_debit_total(self) -> Money:
        """Notional executado + fees cobradas em quote."""
        with _precision_guard("quote_debit_total"):
            return self.gross_quote_notional + self.quote_fee_total

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        """Total de fees por ativo, ordenado pelo código do ativo (inclui fees zero)."""
        totals: dict[Asset, Decimal] = {}
        with _precision_guard("soma de fees por ativo"), financial():
            for fill in self.fills:
                totals[fill.fee.asset] = totals.get(fill.fee.asset, Decimal(0)) + fill.fee.amount
        return tuple(Money(totals[a], a) for a in sorted(totals, key=lambda a: a.code))

    @property
    def unvalued_fees(self) -> tuple[Money, ...]:
        """Fees positivas em ativos que não são base nem quote (ex.: BNB), sem conversão.

        Enquanto existirem, nenhum PnL líquido em quote pode ser declarado completo.
        """
        own = {self.symbol.base, self.symbol.quote}
        return tuple(m for m in self.fees_by_asset if m.asset not in own and m.amount > 0)

    @property
    def has_unvalued_fees(self) -> bool:
        return bool(self.unvalued_fees)

    @property
    def has_fills(self) -> bool:
        return bool(self.fills)

    @property
    def is_fully_filled(self) -> bool:
        """Quantidade bruta atingiu a pretendida. NÃO é confirmação do estado final da
        ordem na exchange."""
        return self.gross_filled_qty == self.intended_qty

    @property
    def is_partially_filled(self) -> bool:
        return self.has_fills and not self.is_fully_filled

    @property
    def grid_owned_inventory(self) -> GridOwnedInventory:
        """Projeção do inventário (ver GRID_OWNED_INVENTORY_IS_A_LEDGER_PROJECTION)."""
        return GridOwnedInventory(
            symbol=self.symbol,
            cycle_ref=self.cycle_ref,
            net_qty=self.net_acquired_base_qty,
            fill_refs=tuple(f.fill_ref for f in self.fills),
        )
