"""Controle fail-closed de modos de execução.

Todo ponto de entrada que inicie um run deve chamar ``ensure_mode_runnable`` antes de
construir qualquer adapter. Na Fase 0 só ``backtest`` é aceito; ``live`` é sempre recusado
com ``LIVE_NOT_IMPLEMENTED``, independentemente de configuração, flags ou credenciais.
"""

from __future__ import annotations

from typing import Final

from gridbot.config.settings import Mode

LIVE_NOT_IMPLEMENTED: Final = "LIVE_NOT_IMPLEMENTED"
MODE_NOT_IMPLEMENTED: Final = "MODE_NOT_IMPLEMENTED"

RUNNABLE_MODES: Final = frozenset({Mode.BACKTEST})


class ModeNotRunnableError(RuntimeError):
    def __init__(self, code: str, mode: Mode, detail: str) -> None:
        super().__init__(f"{code}: modo '{mode}' não pode ser iniciado. {detail}")
        self.code = code
        self.mode = mode


class LiveNotImplementedError(ModeNotRunnableError):
    def __init__(self) -> None:
        super().__init__(
            LIVE_NOT_IMPLEMENTED,
            Mode.LIVE,
            "Execução real não existe nesta versão; nenhuma ordem real pode ser enviada.",
        )


def ensure_mode_runnable(mode: Mode) -> None:
    if not isinstance(mode, Mode):
        raise TypeError(f"modo inválido: {mode!r}")
    if mode is Mode.LIVE:
        raise LiveNotImplementedError
    if mode not in RUNNABLE_MODES:
        raise ModeNotRunnableError(
            MODE_NOT_IMPLEMENTED, mode, "Modo planejado para fase futura do roadmap."
        )
