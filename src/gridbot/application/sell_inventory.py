"""Reservas puras e exclusivas de inventário do grid (ADR-021).

GRID CANNOT SELL CORE BTC: a autoridade é a compra finalizada e consumida no book
financiado. Uma reserva não vende, debita, realiza fees ou encerra o ciclo.
PERSISTENT_ATOMIC_INVENTORY_RESERVATION_REQUIRED_BEFORE_LIVE: snapshots funcionais
não isolam processos nem provam autenticidade das evidências externas.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import DecimalException
from enum import StrEnum

from gridbot.application.buy_quote_capital import FundedBuyBook, settle_funded_buy
from gridbot.domain.assets import Symbol
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Price, Qty
from gridbot.portfolio.buy_finalization import FinalizedBuy
from gridbot.portfolio.sell_sizing import SellSizingAssessment, SellSizingStatus
from gridbot.strategy.grid_state import CellCycleRef, CellPhase, GridState


class SellInventoryErrorCode(StrEnum):
    INVALID_BOOK = "INVALID_BOOK"
    INVALID_RESERVATION = "INVALID_RESERVATION"
    FINALIZATION_NOT_CONSUMED = "FINALIZATION_NOT_CONSUMED"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    UNKNOWN_CELL = "UNKNOWN_CELL"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    CELL_NOT_WAITING_SELL = "CELL_NOT_WAITING_SELL"
    BUY_PRICE_MISMATCH = "BUY_PRICE_MISMATCH"
    SELL_PRICE_MISMATCH = "SELL_PRICE_MISMATCH"
    SIZING_NOT_ELIGIBLE = "SIZING_NOT_ELIGIBLE"
    RESERVATION_ALREADY_EXISTS = "RESERVATION_ALREADY_EXISTS"
    INSUFFICIENT_BASE_INVENTORY = "INSUFFICIENT_BASE_INVENTORY"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"


class SellInventoryError(DomainError):
    """Reserva recusada sem alterar a entrada; ``code`` identifica o motivo."""

    def __init__(self, code: SellInventoryErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = SellInventoryErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


@contextmanager
def _precision_guard(operation: str) -> Iterator[None]:
    try:
        yield
    except DecimalException as exc:
        raise SellInventoryError(
            _E.FINANCIAL_PRECISION_ERROR,
            f"{operation} excede a precisão financeira; nenhum arredondamento feito",
        ) from exc
    except DomainError as exc:
        if getattr(exc, "code", None) != _E.FINANCIAL_PRECISION_ERROR:
            raise
        if isinstance(exc, SellInventoryError):
            raise
        raise SellInventoryError(_E.FINANCIAL_PRECISION_ERROR, str(exc)) from exc


def _sum_quantities(values: Iterable[Qty]) -> Qty:
    with _precision_guard("soma de quantidades"):
        total = Qty.zero()
        for value in values:
            total = total + value
        return total


def _eligible_qty(assessment: SellSizingAssessment) -> Qty:
    with _precision_guard("elegibilidade do sizing"):
        qty = assessment.eligible_sell_qty
        if (
            assessment.eligibility_status is not SellSizingStatus.ELIGIBLE_FOR_SELL_SIZING
            or qty is None
            or qty.is_zero
        ):
            raise SellInventoryError(_E.SIZING_NOT_ELIGIBLE, "assessment não elegível")
        return qty


@dataclass(frozen=True, slots=True)
class SellBaseInventoryReservation:
    """Fontes de um compromisso de base; isolada, NÃO prova consumo no book.

    O residual do sizing é ``net - sell``; o não comprometido é ``net - sell - fee hold``.
    O hold não é fee realizada, nem estimativa; zero não garante segurança de ordem real.
    """

    assessment: SellSizingAssessment
    base_fee_hold: Qty

    def __post_init__(self) -> None:
        try:
            _validate_reservation(self.assessment, self.base_fee_hold)
        except SellInventoryError as exc:
            if exc.code is _E.FINANCIAL_PRECISION_ERROR:
                raise
            raise SellInventoryError(_E.INVALID_RESERVATION, str(exc)) from exc
        except (DomainError, TypeError) as exc:
            raise SellInventoryError(_E.INVALID_RESERVATION, str(exc)) from exc

    @property
    def finalized_buy(self) -> FinalizedBuy:
        return self.assessment.finalized_buy

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.assessment.cycle_ref

    @property
    def symbol(self) -> Symbol:
        return self.assessment.symbol

    @property
    def target_sell_price(self) -> Price:
        return self.assessment.target_sell_price

    @property
    def confirmed_net_base_qty(self) -> Qty:
        return self.finalized_buy.net_acquired_base_qty

    @property
    def reserved_sell_qty(self) -> Qty:
        return _eligible_qty(self.assessment)

    @property
    def reserved_base_fee_qty(self) -> Qty:
        return self.base_fee_hold

    @property
    def total_reserved_base_qty(self) -> Qty:
        with _precision_guard("hold de inventário"):
            return self.reserved_sell_qty + self.reserved_base_fee_qty

    @property
    def unreserved_base_qty(self) -> Qty:
        with _precision_guard("inventário não comprometido"):
            return self.confirmed_net_base_qty - self.total_reserved_base_qty


def _validate_sources(assessment: SellSizingAssessment) -> None:
    _expect(assessment, SellSizingAssessment, "assessment")
    with _precision_guard("fontes do sizing"):
        replace(assessment)
        replace(assessment.finalized_buy)
        replace(assessment.finalized_buy.ledger)
        replace(assessment.market_rules)
        replace(assessment.grid_state)


def _validate_reservation(assessment: SellSizingAssessment, base_fee_hold: Qty) -> None:
    _expect(base_fee_hold, Qty, "base_fee_hold")
    with _precision_guard("validação da reserva"):
        # Reexecuta os contratos públicos das fontes, inclusive construção direta.
        replace(base_fee_hold)
        _validate_sources(assessment)
        qty = _eligible_qty(assessment)
        # A10 elegível já exige candidata positiva, alinhada e aprovada por MarketRules.
        total = qty + base_fee_hold
        net = assessment.confirmed_net_qty
        if total > net:
            raise SellInventoryError(
                _E.INSUFFICIENT_BASE_INVENTORY,
                f"{assessment.cycle_ref}: venda + fee hold excedem o líquido da compra",
            )
        # A diferença também precisa ser exatamente representável, sem arredondamento.
        _ = net - total


@dataclass(frozen=True, slots=True)
class SellInventoryBook:
    """Book financiado + reservas exclusivas; sem outra cópia de estado ou inventário.

    Consultas globais somam somente compras do ciclo atual em WAITING_SELL. Consumos
    históricos não voltam a ser inventário disponível. A disponibilidade de uma célula
    nunca é financiada pelo total global.
    """

    funded_buy_book: FundedBuyBook
    reservations: tuple[SellBaseInventoryReservation, ...] = ()

    def __post_init__(self) -> None:
        try:
            with _precision_guard("validação do book"):
                _validate_book(self)
        except SellInventoryError as exc:
            if exc.code is _E.FINANCIAL_PRECISION_ERROR:
                raise
            raise SellInventoryError(_E.INVALID_BOOK, str(exc)) from exc
        except (DomainError, TypeError) as exc:
            raise SellInventoryError(_E.INVALID_BOOK, str(exc)) from exc

    @property
    def grid_state(self) -> GridState:
        return self.funded_buy_book.lifecycle.grid_state

    def reservation_for(self, cycle_ref: CellCycleRef) -> SellBaseInventoryReservation | None:
        _expect(cycle_ref, CellCycleRef, "cycle_ref")
        return next((r for r in self.reservations if r.cycle_ref == cycle_ref), None)

    @property
    def confirmed_net_base_qty(self) -> Qty:
        return _sum_quantities(
            f.net_acquired_base_qty
            for f in self.funded_buy_book.lifecycle.consumed
            if self.grid_state.cells[f.cycle_ref.cell_index].cycle_ref == f.cycle_ref
            and self.grid_state.cells[f.cycle_ref.cell_index].phase is CellPhase.WAITING_SELL
        )

    @property
    def reserved_sell_qty(self) -> Qty:
        return _sum_quantities(r.reserved_sell_qty for r in self.reservations)

    @property
    def reserved_base_fee_qty(self) -> Qty:
        return _sum_quantities(r.reserved_base_fee_qty for r in self.reservations)

    @property
    def total_reserved_base_qty(self) -> Qty:
        with _precision_guard("total reservado"):
            return self.reserved_sell_qty + self.reserved_base_fee_qty

    @property
    def unreserved_base_qty(self) -> Qty:
        with _precision_guard("total não comprometido"):
            return self.confirmed_net_base_qty - self.total_reserved_base_qty


def _validate_binding(book: SellInventoryBook, assessment: SellSizingAssessment) -> None:
    state = book.grid_state
    finalized = assessment.finalized_buy
    symbol = state.plan.spec.symbol
    if assessment.symbol != symbol:
        raise SellInventoryError(_E.SYMBOL_MISMATCH, "compra de outro símbolo")
    ref = assessment.cycle_ref
    if ref.cell_index >= len(state.cells):
        raise SellInventoryError(_E.UNKNOWN_CELL, f"{ref}: célula inexistente")
    current = state.cells[ref.cell_index]
    if current.cycle_ref != ref:
        raise SellInventoryError(_E.CYCLE_MISMATCH, f"{ref}: ciclo atual {current.cycle_ref}")
    snapshot_cell = assessment.grid_state.cells[ref.cell_index]
    if (
        current.phase is not CellPhase.WAITING_SELL
        or snapshot_cell.phase is not CellPhase.WAITING_SELL
    ):
        raise SellInventoryError(_E.CELL_NOT_WAITING_SELL, f"{ref}: exige WAITING_SELL")
    if (
        current.cell.buy_price != finalized.ledger.intent.price
        or current.cell.buy_price != snapshot_cell.cell.buy_price
    ):
        raise SellInventoryError(_E.BUY_PRICE_MISMATCH, f"{ref}: preço BUY incompatível")
    if current.cell.sell_price != assessment.target_sell_price:
        raise SellInventoryError(_E.SELL_PRICE_MISMATCH, f"{ref}: preço SELL incompatível")
    consumed = book.funded_buy_book.lifecycle.consumed_for(ref)
    if (
        consumed is None
        or consumed.ledger.intent != finalized.ledger.intent
        or consumed != finalized
    ):
        raise SellInventoryError(_E.FINALIZATION_NOT_CONSUMED, f"{ref}: compra não consumida")
    _eligible_qty(assessment)


def _validate_book(book: SellInventoryBook) -> None:
    _expect(book.funded_buy_book, FundedBuyBook, "funded_buy_book")
    if not isinstance(book.reservations, tuple) or not all(
        isinstance(r, SellBaseInventoryReservation) for r in book.reservations
    ):
        raise TypeError("reservations deve ser tuple[SellBaseInventoryReservation, ...]")
    replace(book.grid_state)
    replace(book.funded_buy_book.lifecycle)
    replace(book.funded_buy_book)
    refs = [r.cycle_ref for r in book.reservations]
    if len(set(refs)) != len(refs):
        raise SellInventoryError(_E.RESERVATION_ALREADY_EXISTS, "reserva duplicada por ciclo")
    for reservation in book.reservations:
        _validate_reservation(reservation.assessment, reservation.base_fee_hold)
        _validate_binding(book, reservation.assessment)
    # Falha fechado também se as somas globais excederem a precisão financeira.
    _ = book.unreserved_base_qty


def reserve_sell_inventory(
    book: SellInventoryBook, assessment: SellSizingAssessment, base_fee_hold: Qty
) -> SellInventoryBook:
    """Reserva UMA venda candidata + hold explícito de fee, sem executar venda.

    Segunda chamada para o ciclo é erro mesmo se idêntica; não substitui nem faz merge.
    Somente o líquido da compra consumida daquele ciclo financia o compromisso.
    """
    _expect(book, SellInventoryBook, "book")
    _expect(assessment, SellSizingAssessment, "assessment")
    _expect(base_fee_hold, Qty, "base_fee_hold")
    replace(book)
    if book.reservation_for(assessment.cycle_ref) is not None:
        raise SellInventoryError(_E.RESERVATION_ALREADY_EXISTS, f"{assessment.cycle_ref}")
    _validate_sources(assessment)
    _validate_binding(book, assessment)
    # Valida antes da construção para preservar os códigos operacionais específicos.
    _validate_reservation(assessment, base_fee_hold)
    reservation = SellBaseInventoryReservation(assessment, base_fee_hold)
    reservations = tuple(sorted((*book.reservations, reservation), key=lambda r: r.cycle_ref))
    return replace(book, reservations=reservations)


def settle_inventory_book_buy(
    book: SellInventoryBook, finalized_buy: FinalizedBuy
) -> SellInventoryBook:
    """Liquida somente uma BUY já vinculada na A12, preservando todas as reservas SELL.

    Não recebe um snapshot substituto arbitrário: a transformação autorizada é a própria
    ``settle_funded_buy``. Todas as origens e os vínculos são revalidados no book resultante.
    Preparação/vínculo de novas compras após encapsular o book exigem integração futura.
    """
    _expect(book, SellInventoryBook, "book")
    replace(book)
    updated = settle_funded_buy(book.funded_buy_book, finalized_buy)
    if updated is book.funded_buy_book:
        return book
    return replace(book, funded_buy_book=updated)
