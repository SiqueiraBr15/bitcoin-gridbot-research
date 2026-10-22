"""Logging estruturado (JSON por linha) com redação de secrets.

Cada registro contém: ``ts`` (UTC, ISO-8601), ``level``, ``component`` (nome do logger),
``run_id`` (quando houver), ``msg`` e campos extras. Chaves sensíveis (api_key, secret,
signature, token, password...) e valores ``SecretStr`` são sempre substituídos por
``***REDACTED***``; padrões como ``signature=...`` e ``X-MBX-APIKEY: ...`` dentro de textos
também são redigidos.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from pydantic import SecretBytes, SecretStr

REDACTED = "***REDACTED***"
ROOT_LOGGER = "gridbot"
LOG_FILENAME = "gridbot.jsonl"

_SENSITIVE_KEY = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret|signature|password|passwd|token|"
    r"x-mbx-apikey|authorization)"
)
_TEXT_PATTERNS = (
    re.compile(r"(?i)(https?://)[^/\s@]+(?=@)"),
    re.compile(
        r"(?i)((?:authorization|proxy-authorization)[\"']?\s*[:=]\s*[\"']?)"
        r"(?:(?:bearer|basic)\s+)?[^\s\"',}&]+"
    ),
    re.compile(r"(?i)(signature=)[^&\s\"']+"),
    re.compile(r"(?i)(x-mbx-apikey[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
    re.compile(
        r"(?i)((?:api[_-]?key|api[_-]?secret|secret|password|token)[\"']?\s*[:=]\s*[\"']?)"
        r"(?:(?:bearer|basic)\s+)?[^\s\"',}&]+"
    ),
)
_LOG_CONTROL = re.compile(r"[\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
_STD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

run_id_var: ContextVar[str | None] = ContextVar("gridbot_run_id", default=None)


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    token = run_id_var.set(run_id)
    try:
        yield
    finally:
        run_id_var.reset(token)


def redact_text(text: str) -> str:
    for pattern in _TEXT_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
    return text


def _sanitize(key: str, value: object) -> object:
    if _SENSITIVE_KEY.search(key) or isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _sanitize(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_sanitize(key, v) for v in value]
    return redact_text(str(value))


def _utc_iso(created: float) -> str:
    stamp = datetime.fromtimestamp(created, tz=UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        run_id = record.__dict__.get("run_id")
        if run_id is None:
            run_id = run_id_var.get()
        payload: dict[str, object] = {
            "ts": _utc_iso(record.created),
            "level": record.levelname,
            "component": redact_text(record.name),
            "run_id": _sanitize("run_id", run_id),
            "msg": redact_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _STD_ATTRS or key in payload:
                continue
            payload[key] = _sanitize(key, value)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        # Mantém texto Unicode comum e uma linha física mesmo para separadores C1/Unicode.
        return _LOG_CONTROL.sub(lambda m: json.dumps(m.group(0))[1:-1], serialized)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{component}")


def configure_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    *,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configura o logger ``gridbot``. ``log_dir`` deve existir (não é criado aqui)."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)
    logger.propagate = False

    formatter = JsonFormatter()
    console = logging.StreamHandler(stream if stream is not None else sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_dir is not None:
        if not log_dir.is_dir():
            raise FileNotFoundError(
                f"diretório de logs não existe: {log_dir} (crie com: gridbot doctor --create-dirs)"
            )
        file_handler = RotatingFileHandler(
            log_dir / LOG_FILENAME, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
