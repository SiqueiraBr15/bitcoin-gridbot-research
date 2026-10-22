"""Modelo operacional puro do grid Spot: células e máquina de estados (ADR-011).

Cada intervalo adjacente do plano aritmético é uma célula (ciclo independente):
COMPRAR no nível inferior e, só depois de a compra ser confirmada, VENDER no nível
imediatamente superior. Este módulo não tem quantidade, ordens, fills, saldos nem relógio.

GRID_OWNED_INVENTORY: uma célula só passa a WAITING_SELL depois de uma compra confirmada
pertencente ÀQUELA célula. Inventário de base existente fora do bot (ex.: BTC de longo
prazo do usuário) nunca satisfaz uma obrigação de venda do grid; por isso nenhuma função
daqui recebe saldo.

Estado econômico (``CellPhase``) e elegibilidade operacional (``buy_armed``) são separados:
- WAITING_BUY + armada: pode originar uma intenção de compra (na fase de sizing);
- WAITING_BUY + não armada: ainda não deve originar compra (nível no preço de referência
  ou acima dele);
- WAITING_SELL: há inventário do grid associado à célula/ciclo; nunca armada para compra.

Identidade de ciclo (ADR-013): ECONOMIC STATE MAY REPEAT, OPERATIONAL IDENTITY MUST NOT.
Cada célula tem ``cycle_seq`` (começa em 0 no bootstrap). A compra pertence ao ciclo atual
(``confirm_buy`` não muda ``cycle_seq``); a venda confirmada encerra o ciclo N e a célula
volta a WAITING_BUY no ciclo N + 1. ``CellCycleRef(cell_index, cycle_seq)`` identifica
"esta célula neste ciclo" dentro de um estado; não é um id global nem de exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.grid import GridLevel
from gridbot.domain.values import Price
from gridbot.strategy.arithmetic_grid import ArithmeticGridPlan


class CellPhase(StrEnum):
    WAITING_BUY = "WAITING_BUY"
    """Sem inventário do grid; aguarda compra no ``buy_level``."""
    WAITING_SELL = "WAITING_SELL"
    """Compra confirmada; inventário do grid aguarda venda no ``sell_level``."""


class BootstrapMode(StrEnum):
    QUOTE_ONLY = "QUOTE_ONLY"
    """Bot começa só com o ativo quote: nenhuma célula começa com inventário."""


class GridStateErrorCode(StrEnum):
    UNKNOWN_CELL = "UNKNOWN_CELL"
    NOT_WAITING_BUY = "NOT_WAITING_BUY"
    NOT_WAITING_SELL = "NOT_WAITING_SELL"
    BUY_NOT_ARMED = "BUY_NOT_ARMED"
    INVALID_CELL = "INVALID_CELL"
    INVALID_CYCLE_REF = "INVALID_CYCLE_REF"
    INVALID_STATE = "INVALID_STATE"


class GridStateError(DomainError):
    """Célula/estado inválidos ou transição impossível; ``code`` identifica o motivo."""

    def __init__(self, code: GridStateErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ------------------------------------------------------------------ identidade de ciclo


@dataclass(frozen=True, slots=True, order=True)
class CellCycleRef:
    """ "Esta célula neste ciclo". Identidade local ao estado/plano; não é global."""

    cell_index: int
    cycle_seq: int

    def __post_init__(self) -> None:
        for name in ("cell_index", "cycle_seq"):
            value = getattr(self, name)
            if not _is_index(value) or value < 0:
                raise GridStateError(
                    GridStateErrorCode.INVALID_CYCLE_REF,
                    f"{name} deve ser int >= 0 (recebido {value!r})",
                )

    def __str__(self) -> str:
        return f"cell {self.cell_index} / cycle {self.cycle_seq}"


# ------------------------------------------------------------------ células


@dataclass(frozen=True, slots=True)
class GridCell:
    """Intervalo ``[buy_level, sell_level]`` entre dois níveis adjacentes do plano."""

    index: int
    buy_level: GridLevel
    sell_level: GridLevel

    def __post_init__(self) -> None:
        if not _is_index(self.index) or self.index < 0:
            raise GridStateError(GridStateErrorCode.INVALID_CELL, f"índice {self.index!r}")
        _expect(self.buy_level, GridLevel, "buy_level")
        _expect(self.sell_level, GridLevel, "sell_level")
        if self.buy_level.index != self.index or self.sell_level.index != self.index + 1:
            raise GridStateError(
                GridStateErrorCode.INVALID_CELL,
                f"célula {self.index} exige níveis {self.index} e {self.index + 1}",
            )
        if self.sell_level.price <= self.buy_level.price:
            raise GridStateError(
                GridStateErrorCode.INVALID_CELL,
                f"sell {self.sell_level.price} deve ser > buy {self.buy_level.price}",
            )

    @property
    def buy_price(self) -> Price:
        return self.buy_level.price

    @property
    def sell_price(self) -> Price:
        return self.sell_level.price


def cells_of(plan: ArithmeticGridPlan) -> tuple[GridCell, ...]:
    """N intervalos -> N células; célula i = (levels[i], levels[i + 1])."""
    _expect(plan, ArithmeticGridPlan, "plan")
    levels = plan.levels
    return tuple(GridCell(i, levels[i], levels[i + 1]) for i in range(len(levels) - 1))


# ------------------------------------------------------------------ estado


@dataclass(frozen=True, slots=True)
class CellState:
    """Estado de uma célula: fase econômica, elegibilidade de compra e ciclo. Sem quantidade."""

    cell: GridCell
    phase: CellPhase
    buy_armed: bool
    cycle_seq: int

    def __post_init__(self) -> None:
        _expect(self.cell, GridCell, "cell")
        _expect(self.phase, CellPhase, "phase")
        _expect(self.buy_armed, bool, "buy_armed")
        if not _is_index(self.cycle_seq) or self.cycle_seq < 0:
            raise GridStateError(
                GridStateErrorCode.INVALID_STATE,
                f"cycle_seq deve ser int >= 0 (recebido {self.cycle_seq!r})",
            )
        if self.phase is CellPhase.WAITING_SELL and self.buy_armed:
            raise GridStateError(
                GridStateErrorCode.INVALID_STATE,
                f"célula {self.cell.index} em WAITING_SELL não pode estar armada para compra",
            )

    @property
    def holds_grid_owned_inventory(self) -> bool:
        """Há inventário comprado POR esta célula aguardando venda."""
        return self.phase is CellPhase.WAITING_SELL

    @property
    def can_buy(self) -> bool:
        return self.phase is CellPhase.WAITING_BUY and self.buy_armed

    @property
    def cycle_ref(self) -> CellCycleRef:
        return CellCycleRef(self.cell.index, self.cycle_seq)


@dataclass(frozen=True, slots=True)
class GridState:
    """Estado operacional completo e imutável: uma ``CellState`` por célula do plano.

    Transições devolvem um NOVO ``GridState``; o anterior permanece intacto e as células
    não tocadas são os mesmos objetos (iguais por valor e por identidade).
    """

    plan: ArithmeticGridPlan
    cells: tuple[CellState, ...]

    def __post_init__(self) -> None:
        _expect(self.plan, ArithmeticGridPlan, "plan")
        if not isinstance(self.cells, tuple) or not all(
            isinstance(c, CellState) for c in self.cells
        ):
            raise TypeError("cells deve ser tuple[CellState, ...] (imutável)")
        expected = cells_of(self.plan)
        if tuple(c.cell for c in self.cells) != expected:
            raise GridStateError(
                GridStateErrorCode.INVALID_STATE,
                f"esperadas {len(expected)} células do plano, na ordem 0..N-1",
            )

    def cell(self, index: int) -> CellState:
        if not _is_index(index):
            raise TypeError(f"índice de célula deve ser int (recebido {type(index).__name__})")
        if not 0 <= index < len(self.cells):
            raise GridStateError(
                GridStateErrorCode.UNKNOWN_CELL,
                f"célula {index} não existe (0..{len(self.cells) - 1})",
            )
        return self.cells[index]

    def confirm_buy(self, index: int) -> GridState:
        """WAITING_BUY (armada) -> WAITING_SELL, desarmando a compra. ``cycle_seq`` não muda."""
        current = self.cell(index)
        if current.phase is not CellPhase.WAITING_BUY:
            raise GridStateError(
                GridStateErrorCode.NOT_WAITING_BUY, f"célula {index} está {current.phase}"
            )
        if not current.buy_armed:
            raise GridStateError(
                GridStateErrorCode.BUY_NOT_ARMED, f"célula {index} não está armada para compra"
            )
        return self._with(index, replace(current, phase=CellPhase.WAITING_SELL, buy_armed=False))

    def confirm_sell(self, index: int) -> GridState:
        """WAITING_SELL -> WAITING_BUY rearmada; encerra o ciclo N e abre o ciclo N + 1."""
        current = self.cell(index)
        if current.phase is not CellPhase.WAITING_SELL:
            raise GridStateError(
                GridStateErrorCode.NOT_WAITING_SELL, f"célula {index} está {current.phase}"
            )
        return self._with(
            index,
            replace(
                current,
                phase=CellPhase.WAITING_BUY,
                buy_armed=True,
                cycle_seq=current.cycle_seq + 1,
            ),
        )

    def disarm_buy(self, index: int) -> GridState:
        """WAITING_BUY armada -> WAITING_BUY desarmada, no MESMO ciclo (A11).

        Suspende a célula para decisão explícita futura (ex.: compra terminada sem fill);
        não cria ordens nem faz retry. Célula não armada ou em WAITING_SELL é erro.
        """
        current = self.cell(index)
        if current.phase is not CellPhase.WAITING_BUY:
            raise GridStateError(
                GridStateErrorCode.NOT_WAITING_BUY, f"célula {index} está {current.phase}"
            )
        if not current.buy_armed:
            raise GridStateError(
                GridStateErrorCode.BUY_NOT_ARMED, f"célula {index} já está desarmada"
            )
        return self._with(index, replace(current, buy_armed=False))

    def _with(self, index: int, new_cell: CellState) -> GridState:
        cells = (*self.cells[:index], new_cell, *self.cells[index + 1 :])
        return GridState(self.plan, cells)

    @property
    def armed_buy_indices(self) -> tuple[int, ...]:
        return tuple(c.cell.index for c in self.cells if c.can_buy)

    @property
    def armed_buy_refs(self) -> tuple[CellCycleRef, ...]:
        """Identidade (célula, ciclo) das células ``can_buy``, em ordem de índice."""
        return tuple(c.cycle_ref for c in self.cells if c.can_buy)

    @property
    def waiting_sell_indices(self) -> tuple[int, ...]:
        return tuple(c.cell.index for c in self.cells if c.phase is CellPhase.WAITING_SELL)


def bootstrap_grid_state(
    plan: ArithmeticGridPlan,
    reference_price: Price,
    mode: BootstrapMode = BootstrapMode.QUOTE_ONLY,
) -> GridState:
    """Estado inicial a partir de um preço de referência explícito.

    QUOTE_ONLY: toda célula começa WAITING_BUY (nenhum inventário inicial, nenhuma compra a
    mercado, nenhum saldo externo); fica armada só se ``buy_price < reference_price``
    (estritamente), para nunca criar uma compra limitada no preço de mercado ou acima dele.
    Toda célula começa no ciclo 0: nenhum ciclo anterior é inventado.
    """
    _expect(plan, ArithmeticGridPlan, "plan")
    _expect(reference_price, Price, "reference_price")
    _expect(mode, BootstrapMode, "mode")
    return GridState(
        plan,
        tuple(
            CellState(
                cell,
                CellPhase.WAITING_BUY,
                buy_armed=cell.buy_price < reference_price,
                cycle_seq=0,
            )
            for cell in cells_of(plan)
        ),
    )
