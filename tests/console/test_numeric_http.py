"""A valid pack stays HTTP200; internal calculation failures are redacted HTTP500."""

from __future__ import annotations

import json
from typing import Any

import pytest
from research_console.lab import http, numeric
from research_console.server import LocalServer
from tests.console.numeric_cases import coprime_pack, rational
from tests.console.test_lab_http import call
from tests.console.test_lab_http import lab_server as lab_server


@pytest.mark.parametrize("count", [100, 1200, 3000, 9999])
def test_coprime_pack_preview_confirm_analysis_transport(
    lab_server: tuple[LocalServer, str], count: int
) -> None:
    server, cookie = lab_server
    raw, expected = coprime_pack(count)
    status, body, _ = call(
        server, cookie, "/api/lab/preview", raw, extra={"Content-Type": "application/zip"}
    )
    assert status == 200
    token = json.loads(body)["preview_token"]
    status, body, _ = call(
        server,
        cookie,
        "/api/lab/confirm",
        json.dumps({"preview_token": token, "confirmed": True}).encode(),
    )
    assert status == 200
    identity = json.loads(body)["id"]
    for _ in range(2):
        status, body, headers = call(server, cookie, "/api/lab/analysis?id=" + identity)
        assert status == 200
        assert headers["Content-Type"].split(";")[0] == "application/json"
        result = json.loads(body)
        assert rational(result["rows"][0]["metrics"]["exact"]["exposure_mean_left"]) == expected


@pytest.mark.parametrize("fault", ["arithmetic", "serialization", "budget"])
def test_internal_numeric_failure_is_not_invalid_evidence(
    lab_server: tuple[LocalServer, str], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    server, cookie = lab_server
    identity = next(iter(server.service.lab.builtin))

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("SYNTHETIC_PRIVATE_PATH_MUST_NOT_LEAK")

    with monkeypatch.context() as patch:
        if fault == "arithmetic":
            patch.setattr(numeric, "integer_text", fail)
        elif fault == "serialization":
            patch.setattr(http, "canonical", fail)
        else:
            patch.setattr(http, "MAX_ANALYSIS_BYTES", 10)
        status, body, _ = call(server, cookie, "/api/lab/analysis?id=" + identity)
        assert status == 500
        assert json.loads(body)["reason"] == "ANALYSIS_FAILED"
        assert b"DATA_INVALID" not in body
        assert b"PRIVATE_PATH" not in body
        assert b"Traceback" not in body
    assert call(server, cookie, "/api/lab/analysis?id=" + identity)[0] == 200
    assert call(server, cookie, "/api/lab/analysis?id=" + identity + "&accounts=MISSING")[0] == 422
