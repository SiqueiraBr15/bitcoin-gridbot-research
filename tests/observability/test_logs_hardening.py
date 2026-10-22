from __future__ import annotations

import io
import json
import logging

import pytest
from pydantic import SecretStr

from gridbot.observability.logs import REDACTED, JsonFormatter, bind_run_id, redact_text

MARKER = "AUDIT_SYNTHETIC_CREDENTIAL_NOT_REAL"


@pytest.mark.parametrize(
    "template",
    [
        "Authorization: Bearer {}",
        "authorization=Bearer {}",
        "AUTHORIZATION: Basic {}",
        "{{'Authorization': 'Bearer {}'}}",
        '"Proxy-Authorization": "Basic {}"',
        "token=Bearer {}",
        "token=Basic {}",
        "token=Bearer\n{}",
        "api_secret={}",
        "https://example.test/path?access_token={}&safe=yes",
        "https://audit:{}@example.test/path",
        "Authorization: {}",
        "token=Bearer%20{}",
    ],
)
def test_supported_sensitive_formats_redact_complete_value(template: str) -> None:
    rendered = redact_text(template.format(MARKER))
    assert MARKER not in rendered
    assert REDACTED in rendered


def test_multiple_occurrences_and_harmless_unicode() -> None:
    text = (
        f"ação token=Bearer {MARKER}&symbol=BTCUSDT Authorization: Basic {MARKER} api_key={MARKER}"
    )
    rendered = redact_text(text)
    assert rendered.count(REDACTED) == 3
    assert MARKER not in rendered
    assert "ação" in rendered
    assert "symbol=BTCUSDT" in rendered
    assert redact_text("ação preço 1.23 BTC/USDT") == "ação preço 1.23 BTC/USDT"


@pytest.mark.parametrize(
    "run_id", [f"token={MARKER}", f"Authorization: Bearer {MARKER}", SecretStr(MARKER)]
)
def test_run_id_from_record_or_context_is_sanitized(run_id: object) -> None:
    record = logging.LogRecord("gridbot.audit", logging.INFO, "audit", 1, "ordinary", (), None)
    record.__dict__["run_id"] = run_id
    assert MARKER not in JsonFormatter().format(record)
    with bind_run_id(f"token=Bearer {MARKER}"):
        assert MARKER not in JsonFormatter().format(
            logging.LogRecord("gridbot.audit", logging.INFO, "audit", 1, "ordinary", (), None)
        )


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        " ",
        "normal-id",
        "ação-雪",
        "a/b",
        "a\\b",
        "line\nforged",
        "control\x00id",
        "\x85\u2028\u2029\u202e\u2066",
    ],
)
def test_run_id_preserves_identity_and_json_cannot_forge_lines(run_id: str) -> None:
    record = logging.LogRecord("gridbot.audit", logging.INFO, "audit", 1, "msg " + run_id, (), None)
    record.__dict__["run_id"] = run_id
    with bind_run_id("fallback-must-not-replace-empty-id"):
        formatted = JsonFormatter().format(record)
    assert len(formatted.splitlines()) == 1
    assert json.loads(formatted)["run_id"] == run_id
    assert json.loads(formatted)["msg"] == "msg " + run_id


def test_exceptions_nested_data_component_and_stream_redaction() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.Logger(f"gridbot.Authorization: Bearer {MARKER}")
    logger.addHandler(handler)
    try:
        raise RuntimeError(f"https://audit:{MARKER}@example.test/?token=Bearer {MARKER}\nnext")
    except RuntimeError:
        logger.exception(
            "token=Bearer %s",
            MARKER,
            extra={"nested": [{"safe": f"Authorization: Bearer {MARKER}"}, {"secret": MARKER}]},
        )
    content = stream.getvalue()
    assert MARKER not in content
    assert len(content.splitlines()) == 1
    record = json.loads(content)
    assert "RuntimeError" in record["exc"]
    assert record["nested"][1]["secret"] == REDACTED
