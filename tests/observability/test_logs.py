from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from gridbot.config.settings import load_settings
from gridbot.observability.logs import (
    LOG_FILENAME,
    REDACTED,
    bind_run_id,
    configure_logging,
    get_logger,
    redact_text,
)

FAKE_SECRET = hashlib.sha256(b"gridbot-log-test-secret").hexdigest()
FAKE_KEY = hashlib.sha256(b"gridbot-log-test-key").hexdigest()
FAKE_SIG = hashlib.sha256(b"gridbot-log-test-signature").hexdigest()


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    configure_logging("DEBUG", stream=buffer)
    yield buffer
    configure_logging("INFO", stream=io.StringIO())  # fecha handlers de arquivo, se houver


def records(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line]


def test_record_has_structured_utc_fields(stream: io.StringIO) -> None:
    get_logger("execution").info("ordem simulada", extra={"price": Decimal("65000.10")})
    (rec,) = records(stream)
    assert rec["level"] == "INFO"
    assert rec["component"] == "gridbot.execution"
    assert rec["run_id"] is None
    assert rec["msg"] == "ordem simulada"
    assert rec["price"] == "65000.10"  # Decimal serializado sem float
    ts = str(rec["ts"])
    assert ts.endswith("Z")
    parsed = datetime.fromisoformat(ts)
    assert parsed.utcoffset() == timedelta(0)
    assert abs(datetime.now(tz=UTC) - parsed) < timedelta(minutes=5)


def test_run_id_is_bound_and_released(stream: io.StringIO) -> None:
    log = get_logger("backtest")
    with bind_run_id("bt-20260101-001"):
        log.info("dentro")
    log.info("fora")
    inside, outside = records(stream)
    assert inside["run_id"] == "bt-20260101-001"
    assert outside["run_id"] is None


def test_sensitive_extras_are_redacted(stream: io.StringIO) -> None:
    get_logger("exchange").info(
        "request",
        extra={
            "api_key": FAKE_KEY,
            "params": {"symbol": "BTCUSDT", "signature": FAKE_SIG},
            "credential": SecretStr(FAKE_SECRET),
            "headers": {"X-MBX-APIKEY": FAKE_KEY},
        },
    )
    out = stream.getvalue()
    for value in (FAKE_KEY, FAKE_SECRET, FAKE_SIG):
        assert value not in out
    (rec,) = records(stream)
    assert rec["api_key"] == REDACTED
    assert rec["credential"] == REDACTED
    assert rec["params"] == {"symbol": "BTCUSDT", "signature": REDACTED}


def test_secrets_inside_message_text_are_redacted(stream: io.StringIO) -> None:
    log = get_logger("exchange")
    log.info("GET /api/v3/order?symbol=BTCUSDT&timestamp=1&signature=%s", FAKE_SIG)
    log.warning("headers: {'X-MBX-APIKEY': '%s'}", FAKE_KEY)
    log.error("config api_secret=%s", FAKE_SECRET)
    out = stream.getvalue()
    for value in (FAKE_KEY, FAKE_SECRET, FAKE_SIG):
        assert value not in out
    assert "symbol=BTCUSDT" in out


def test_exception_text_is_redacted(stream: io.StringIO) -> None:
    try:
        raise RuntimeError(f"falha assinando signature={FAKE_SIG}")
    except RuntimeError:
        get_logger("exchange").exception("erro")
    assert FAKE_SIG not in stream.getvalue()
    (rec,) = records(stream)
    assert "RuntimeError" in str(rec["exc"])


def test_logging_settings_object_does_not_leak_secrets(stream: io.StringIO) -> None:
    settings = load_settings(
        {"GRIDBOT_BINANCE_API_KEY": FAKE_KEY, "GRIDBOT_BINANCE_API_SECRET": FAKE_SECRET}
    )
    log = get_logger("config")
    log.info("config carregada: %s", settings)
    log.info("config", extra={"settings": settings, "dump": settings.model_dump()})
    out = stream.getvalue()
    assert FAKE_KEY not in out
    assert FAKE_SECRET not in out


def test_redact_text_keeps_harmless_text() -> None:
    assert redact_text("preço 65000 BTCUSDT") == "preço 65000 BTCUSDT"


def test_file_logging_requires_existing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        configure_logging("INFO", tmp_path / "missing", stream=io.StringIO())


def test_file_logging_writes_json_lines(tmp_path: Path, stream: io.StringIO) -> None:
    configure_logging("INFO", tmp_path, stream=stream)
    get_logger("doctor").info("ok", extra={"token": FAKE_KEY})
    logging.getLogger("gridbot").handlers[-1].flush()
    content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
    assert FAKE_KEY not in content
    assert json.loads(content.splitlines()[0])["component"] == "gridbot.doctor"
