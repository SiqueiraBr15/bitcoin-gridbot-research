"""Relógio real. Único lugar do projeto que lê a hora do sistema."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)
