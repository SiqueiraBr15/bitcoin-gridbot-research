"""Orquestração pura do ciclo de vida das compras do grid (ADR-019).

BUY INTENT CURRENT -> PREPARED -> EXECUTION_BOUND -> FINALIZED (consumida) -> GRID STATE.

``BuyLifecycleBook`` é um snapshot lógico imutável: o ``GridState`` corrente, as tentativas
de compra ativas e as compras finalizadas já consumidas. Toda operação devolve um NOVO
book; o original nunca muda, inclusive quando a operação falha.

Garantias (locais ao book, em memória):
- no máximo UMA tentativa ativa por célula/ciclo, bloqueada já em PREPARED (antes de
  qualquer submissão futura), inclusive em SUBMISSION_UNCERTAIN;
- uma ``FinalizedBuy`` é consumida economicamente uma única vez: a repetição idêntica é
  no-op; uma divergente é erro;
- ``execution_ref`` e ``fill_ref`` nunca são reutilizados entre registros do book.

NÃO são garantias: idempotência de execução real, resistência a crash/concorrência ou
deduplicação global de trades (dependem de persistência transacional futura). Nada aqui
envia ordens, reserva/debita saldo, cria SELL, faz retry ou toca BTC Core.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.portfolio.buy_finalization import BuyExecutionContext, FinalizedBuy
from gridbot.strategy.buy_intents import BuyIntentPlan, GridBuyIntent
from gridbot.strategy.grid_state import CellCycleRef, CellPhase, GridState


class BuyAttemptStatus(StrEnum):
    PREPARED = "PREPARED"
    """Intenção registrada logicamente para eventual execução. Nenhuma ordem enviada."""
    EXECUTION_BOUND = "EXECUTION_BOUND"
    """Contexto de execução externa associado. Não significa que houve fill."""
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    """Resultado de uma submissão futura desconhecido: bloqueia novo envio até reconciliação."""


class BuyLifecycleErrorCode(StrEnum):
    STALE_INTENT_PLAN = "STALE_INTENT_PLAN"
    INTENT_NOT_IN_PLAN = "INTENT_NOT_IN_PLAN"
    UNKNOWN_CELL = "UNKNOWN_CELL"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    CELL_NOT_BUYABLE = "CELL_NOT_BUYABLE"
    ATTEMPT_ALREADY_ACTIVE = "ATTEMPT_ALREADY_ACTIVE"
    CYCLE_ALREADY_CONSUMED = "CYCLE_ALREADY_CONSUMED"
    ATTEMPT_NOT_FOUND = "ATTEMPT_NOT_FOUND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    INTENT_MISMATCH = "INTENT_MISMATCH"
    EXECUTION_REF_IN_USE = "EXECUTION_REF_IN_USE"
    EXECUTION_ALREADY_BOUND = "EXECUTION_ALREADY_BOUND"
    EXECUTION_NOT_BOUND = "EXECUTION_NOT_BOUND"
    EXECUTION_REF_MISMATCH = "EXECUTION_REF_MISMATCH"
    STATE_MISMATCH = "STATE_MISMATCH"
    FINALIZATION_CONFLICT = "FINALIZATION_CONFLICT"
    FILL_REF_ALREADY_CONSUMED = "FILL_REF_ALREADY_CONSUMED"
    INVALID_BOOK = "INVALID_BOOK"


class BuyLifecycleError(DomainError):
    """Operação de ciclo de vida recusada (fail-closed); ``code`` identifica o motivo."""

    def __init__(self, code: BuyLifecycleErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = BuyLifecycleErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _invalid(detail: str) -> BuyLifecycleError:
    return BuyLifecycleError(_E.INVALID_BOOK, detail)


# ------------------------------------------------------------------ tentativa


@dataclass(frozen=True, slots=True)
class BuyAttempt:
    """Tentativa de compra de UMA célula/ciclo. ``execution`` só existe em EXECUTION_BOUND."""

    intent: GridBuyIntent
    status: BuyAttemptStatus
    execution: BuyExecutionContext | None = None

    def __post_init__(self) -> None:
        _expect(self.intent, GridBuyIntent, "intent")
        _expect(self.status, BuyAttemptStatus, "status")
        if self.status is BuyAttemptStatus.EXECUTION_BOUND:
            if not isinstance(self.execution, BuyExecutionContext):
                raise _invalid(f"{self.cycle_ref}: EXECUTION_BOUND exige BuyExecutionContext")
            if self.execution.intent != self.intent:
                raise _invalid(f"{self.cycle_ref}: contexto de execução de outra intenção")
        elif self.execution is not None:
            raise _invalid(f"{self.cycle_ref}: {self.status} não pode ter execução vinculada")

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref


# ------------------------------------------------------------------ aggregate


@dataclass(frozen=True, slots=True)
class BuyLifecycleBook:
    """Snapshot lógico e imutável do ciclo de vida das compras (sem persistência).

    Invariantes revalidadas na construção (direta ou por operação), com ``INVALID_BOOK``:
    tipos e tuplas; símbolos iguais ao do grid; uma tentativa por célula, sempre no ciclo
    atual de uma célula WAITING_BUY armada com o mesmo buy; ``execution_ref`` únicos entre
    tentativas e consumos; um consumo por ciclo; nenhuma tentativa em ciclo consumido;
    ``fill_ref`` únicos entre consumos; consumo do ciclo atual coerente com a fase da
    célula; e toda célula WAITING_SELL comprovada por um consumo com inventário positivo.
    Frozen dataclasses não provam autenticidade de evidência nem isolam contra código
    malicioso no mesmo processo.
    """

    grid_state: GridState
    attempts: tuple[BuyAttempt, ...] = ()
    consumed: tuple[FinalizedBuy, ...] = ()

    def __post_init__(self) -> None:
        _expect(self.grid_state, GridState, "grid_state")
        for name, item_type in (("attempts", BuyAttempt), ("consumed", FinalizedBuy)):
            items = getattr(self, name)
            if not isinstance(items, tuple) or not all(isinstance(i, item_type) for i in items):
                raise TypeError(f"{name} deve ser tuple[{item_type.__name__}, ...] (imutável)")
        _validate_book(self)

    # ---------------------------------------------------------------- consultas

    def attempt_for(self, cycle_ref: CellCycleRef) -> BuyAttempt | None:
        return next((a for a in self.attempts if a.cycle_ref == cycle_ref), None)

    def consumed_for(self, cycle_ref: CellCycleRef) -> FinalizedBuy | None:
        return next((f for f in self.consumed if f.cycle_ref == cycle_ref), None)

    @property
    def active_cycle_refs(self) -> tuple[CellCycleRef, ...]:
        return tuple(a.cycle_ref for a in self.attempts)


def _validate_book(book: BuyLifecycleBook) -> None:
    state = book.grid_state
    symbol = state.plan.spec.symbol

    attempt_cells = [a.cycle_ref.cell_index for a in book.attempts]
    if len(set(attempt_cells)) != len(attempt_cells):
        raise _invalid("mais de uma tentativa ativa para a mesma célula")
    consumed_cycles = [f.cycle_ref for f in book.consumed]
    if len(set(consumed_cycles)) != len(consumed_cycles):
        raise _invalid("mais de um consumo para o mesmo ciclo")

    execution_refs = [a.execution.execution_ref for a in book.attempts if a.execution] + [
        f.execution_ref for f in book.consumed
    ]
    if len(set(execution_refs)) != len(execution_refs):
        raise _invalid("execution_ref associado a mais de um registro")

    fill_refs = [fill.fill_ref for f in book.consumed for fill in f.ledger.fills]
    if len(set(fill_refs)) != len(fill_refs):
        raise _invalid("fill_ref presente em mais de uma compra consumida")

    for attempt in book.attempts:
        ref = attempt.cycle_ref
        if attempt.intent.symbol != symbol:
            raise _invalid(f"{ref}: tentativa de {attempt.intent.symbol}, grid de {symbol}")
        if ref in consumed_cycles:
            raise _invalid(f"{ref}: tentativa ativa em ciclo já consumido")
        if ref.cell_index >= len(state.cells):
            raise _invalid(f"{ref}: célula inexistente")
        cell_state = state.cells[ref.cell_index]
        if cell_state.cycle_seq != ref.cycle_seq or not cell_state.can_buy:
            raise _invalid(f"{ref}: tentativa exige célula WAITING_BUY armada no ciclo atual")
        if cell_state.cell.buy_price != attempt.intent.price:
            raise _invalid(f"{ref}: preço da tentativa difere do buy da célula")

    for finalized in book.consumed:
        ref = finalized.cycle_ref
        if finalized.symbol != symbol:
            raise _invalid(f"{ref}: consumo de {finalized.symbol}, grid de {symbol}")
        if ref.cell_index >= len(state.cells):
            raise _invalid(f"{ref}: célula inexistente")
        cell_state = state.cells[ref.cell_index]
        if ref.cycle_seq > cell_state.cycle_seq:
            raise _invalid(f"{ref}: consumo de ciclo futuro")
        if ref.cycle_seq == cell_state.cycle_seq:
            positive = not finalized.net_acquired_base_qty.is_zero
            expected_phase = CellPhase.WAITING_SELL if positive else CellPhase.WAITING_BUY
            if cell_state.phase is not expected_phase or cell_state.buy_armed:
                raise _invalid(f"{ref}: fase da célula incoerente com o consumo")

    for cell_state in state.cells:
        if cell_state.phase is CellPhase.WAITING_SELL:
            proof = book.consumed_for(cell_state.cycle_ref)
            if proof is None or proof.net_acquired_base_qty.is_zero:
                raise _invalid(
                    f"{cell_state.cycle_ref}: WAITING_SELL sem compra consumida com inventário"
                )


def _attempt_or_fail(book: BuyLifecycleBook, cycle_ref: CellCycleRef) -> BuyAttempt:
    _expect(cycle_ref, CellCycleRef, "cycle_ref")
    attempt = book.attempt_for(cycle_ref)
    if attempt is None:
        raise BuyLifecycleError(_E.ATTEMPT_NOT_FOUND, f"nenhuma tentativa ativa para {cycle_ref}")
    return attempt


def _replace_attempt(book: BuyLifecycleBook, new: BuyAttempt) -> BuyLifecycleBook:
    attempts = tuple(new if a.cycle_ref == new.cycle_ref else a for a in book.attempts)
    return replace(book, attempts=attempts)


# ------------------------------------------------------------------ operações


def prepare_buy(
    book: BuyLifecycleBook, buy_intent_plan: BuyIntentPlan, cycle_ref: CellCycleRef
) -> BuyLifecycleBook:
    """Registra uma tentativa PREPARED para ``cycle_ref``. Não altera o ``GridState``.

    Ordem das verificações: plano CURRENT para o estado do book e seu sizing de origem;
    célula existente; mesmo ciclo; WAITING_BUY armada; intenção presente no plano; nenhuma
    tentativa ativa na célula; ciclo ainda não consumido.
    """
    _expect(book, BuyLifecycleBook, "book")
    _expect(buy_intent_plan, BuyIntentPlan, "buy_intent_plan")
    _expect(cycle_ref, CellCycleRef, "cycle_ref")
    state = book.grid_state
    if not buy_intent_plan.is_current_for(state, buy_intent_plan.sizing):
        reasons = buy_intent_plan.freshness_for(state, buy_intent_plan.sizing).reasons
        raise BuyLifecycleError(_E.STALE_INTENT_PLAN, f"plano não é current: {list(reasons)}")
    if cycle_ref.cell_index >= len(state.cells):
        raise BuyLifecycleError(_E.UNKNOWN_CELL, f"célula {cycle_ref.cell_index} não existe")
    cell_state = state.cells[cycle_ref.cell_index]
    if cell_state.cycle_seq != cycle_ref.cycle_seq:
        raise BuyLifecycleError(
            _E.CYCLE_MISMATCH, f"{cycle_ref}; célula está no ciclo {cell_state.cycle_seq}"
        )
    if not cell_state.can_buy:
        raise BuyLifecycleError(_E.CELL_NOT_BUYABLE, f"{cycle_ref} não está WAITING_BUY armada")
    intent = next((i for i in buy_intent_plan.intents if i.cycle_ref == cycle_ref), None)
    if intent is None:  # defensivo: um plano current contém todas as células can_buy
        raise BuyLifecycleError(_E.INTENT_NOT_IN_PLAN, f"{cycle_ref} não está no plano")
    existing = next(
        (a for a in book.attempts if a.cycle_ref.cell_index == cycle_ref.cell_index), None
    )
    if existing is not None:
        raise BuyLifecycleError(
            _E.ATTEMPT_ALREADY_ACTIVE,
            f"{existing.cycle_ref} já tem tentativa {existing.status}",
        )
    if book.consumed_for(cycle_ref) is not None:
        raise BuyLifecycleError(_E.CYCLE_ALREADY_CONSUMED, f"{cycle_ref} já foi consumido")
    attempt = BuyAttempt(intent, BuyAttemptStatus.PREPARED)
    attempts = tuple(sorted((*book.attempts, attempt), key=lambda a: a.cycle_ref))
    return replace(book, attempts=attempts)


def mark_submission_uncertain(book: BuyLifecycleBook, cycle_ref: CellCycleRef) -> BuyLifecycleBook:
    """PREPARED -> SUBMISSION_UNCERTAIN. A tentativa continua ocupando o ciclo; nada é
    descartado, reenviado ou liberado automaticamente."""
    _expect(book, BuyLifecycleBook, "book")
    attempt = _attempt_or_fail(book, cycle_ref)
    if attempt.status is not BuyAttemptStatus.PREPARED:
        raise BuyLifecycleError(
            _E.INVALID_TRANSITION, f"{cycle_ref}: {attempt.status} -> SUBMISSION_UNCERTAIN"
        )
    return _replace_attempt(book, replace(attempt, status=BuyAttemptStatus.SUBMISSION_UNCERTAIN))


def bind_buy_execution(
    book: BuyLifecycleBook, cycle_ref: CellCycleRef, execution_context: BuyExecutionContext
) -> BuyLifecycleBook:
    """PREPARED ou SUBMISSION_UNCERTAIN -> EXECUTION_BOUND com o contexto informado.

    O contexto deve ser da exata intenção preparada; o ``execution_ref`` não pode estar em
    uso no book. Repetir o mesmo vínculo é no-op; substituir por outro é erro. A existência
    de um ``execution_ref`` não prova que não há outras ordens desconhecidas na exchange.
    """
    _expect(book, BuyLifecycleBook, "book")
    _expect(execution_context, BuyExecutionContext, "execution_context")
    attempt = _attempt_or_fail(book, cycle_ref)
    if execution_context.cycle_ref != cycle_ref:
        raise BuyLifecycleError(
            _E.CYCLE_MISMATCH, f"contexto de {execution_context.cycle_ref}, tentativa {cycle_ref}"
        )
    if execution_context.intent != attempt.intent:
        raise BuyLifecycleError(_E.INTENT_MISMATCH, f"{cycle_ref}: contexto de outra intenção")
    if attempt.status is BuyAttemptStatus.EXECUTION_BOUND:
        if attempt.execution == execution_context:
            return book
        raise BuyLifecycleError(
            _E.EXECUTION_ALREADY_BOUND,
            f"{cycle_ref} já vinculado a outra execução; não substituído",
        )
    ref = execution_context.execution_ref
    in_use = any(a.execution and a.execution.execution_ref == ref for a in book.attempts) or any(
        f.execution_ref == ref for f in book.consumed
    )
    if in_use:
        raise BuyLifecycleError(_E.EXECUTION_REF_IN_USE, f"execution_ref {ref} já está em uso")
    bound = BuyAttempt(attempt.intent, BuyAttemptStatus.EXECUTION_BOUND, execution_context)
    return _replace_attempt(book, bound)


def consume_finalized_buy(book: BuyLifecycleBook, finalized_buy: FinalizedBuy) -> BuyLifecycleBook:
    """Consome uma compra finalizada uma única vez e aplica a transição econômica.

    - mesma ``FinalizedBuy`` já consumida (conteúdo idêntico): no-op;
    - outra finalização para o mesmo ciclo ou ``execution_ref``: ``FINALIZATION_CONFLICT``;
    - exige tentativa EXECUTION_BOUND com o mesmo contexto, célula no mesmo ciclo e
      WAITING_BUY armada, e ``fill_ref`` ainda não consumidos;
    - inventário líquido > 0: ``confirm_buy`` (WAITING_SELL, mesmo ciclo);
    - NO_FILL: ``disarm_buy`` (WAITING_BUY desarmada, mesmo ciclo), sem retry.
    """
    _expect(book, BuyLifecycleBook, "book")
    _expect(finalized_buy, FinalizedBuy, "finalized_buy")
    ref = finalized_buy.cycle_ref
    if finalized_buy in book.consumed:
        return book
    for previous in book.consumed:
        if previous.cycle_ref == ref or previous.execution_ref == finalized_buy.execution_ref:
            raise BuyLifecycleError(
                _E.FINALIZATION_CONFLICT,
                f"{ref}/{finalized_buy.execution_ref} conflita com consumo de "
                f"{previous.cycle_ref}/{previous.execution_ref}",
            )
    attempt = _attempt_or_fail(book, ref)
    if attempt.status is not BuyAttemptStatus.EXECUTION_BOUND or attempt.execution is None:
        raise BuyLifecycleError(_E.EXECUTION_NOT_BOUND, f"{ref} está {attempt.status}")
    if attempt.execution.execution_ref != finalized_buy.execution_ref:
        raise BuyLifecycleError(
            _E.EXECUTION_REF_MISMATCH,
            f"{ref}: tentativa vinculada a {attempt.execution.execution_ref}, "
            f"finalização de {finalized_buy.execution_ref}",
        )
    if attempt.execution != finalized_buy.context:
        raise BuyLifecycleError(_E.INTENT_MISMATCH, f"{ref}: finalização de outra intenção")
    cell_state = book.grid_state.cells[ref.cell_index]
    if cell_state.cycle_seq != ref.cycle_seq or not cell_state.can_buy:
        raise BuyLifecycleError(
            _E.STATE_MISMATCH, f"{ref}: célula não está WAITING_BUY armada no mesmo ciclo"
        )
    consumed_fill_refs = {fill.fill_ref for f in book.consumed for fill in f.ledger.fills}
    repeated = sorted(
        fill.fill_ref for fill in finalized_buy.ledger.fills if fill.fill_ref in consumed_fill_refs
    )
    if repeated:
        raise BuyLifecycleError(
            _E.FILL_REF_ALREADY_CONSUMED, f"{ref}: fills já consumidos em outra compra: {repeated}"
        )
    if finalized_buy.net_acquired_base_qty.is_zero:
        new_state = book.grid_state.disarm_buy(ref.cell_index)
    else:
        new_state = book.grid_state.confirm_buy(ref.cell_index)
    return BuyLifecycleBook(
        grid_state=new_state,
        attempts=tuple(a for a in book.attempts if a.cycle_ref != ref),
        consumed=(*book.consumed, finalized_buy),
    )
