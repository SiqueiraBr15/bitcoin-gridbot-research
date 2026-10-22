"""Abstração de relógio.

O domínio nunca chama ``datetime.now()``: recebe um ``Clock``. ``SystemClock`` (tempo real)
fica em ``gridbot.infra.clock``; ``ManualClock`` é determinístico e serve de base para
backtest/replay e para testes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from gridbot.domain.errors import DomainError
from gridbot.domain.time import require_utc


class Clock(Protocol):
    def now(self) -> datetime:
        """Instante atual em UTC (timezone-aware)."""
        ...


class ManualClock:
    """Relógio controlado explicitamente; monotônico (nunca volta no tempo)."""

    def __init__(self, start: datetime) -> None:
        self._now = require_utc(start, field="start")

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        if not isinstance(delta, timedelta) or delta < timedelta(0):
            raise DomainError("ManualClock.advance exige timedelta não negativo")
        self._now = self._now + delta
        return self._now

    def set(self, instant: datetime) -> datetime:
        instant = require_utc(instant, field="instant")
        if instant < self._now:
            raise DomainError("ManualClock não pode voltar no tempo")
        self._now = instant
        return self._now
