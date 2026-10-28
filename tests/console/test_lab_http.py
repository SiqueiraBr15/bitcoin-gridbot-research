"""Real loopback transport, upload consent, restart and redacted failure paths."""

from __future__ import annotations

import http.client
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path

import pytest
from research_console.lab.fixtures import bundled
from research_console.lab.packs import canonical, read_pack, write_pack
from research_console.server import LocalServer, Service


@pytest.fixture
def lab_server(tmp_path: Path) -> Iterator[tuple[LocalServer, str]]:
    with LocalServer(Service(lab_root=tmp_path / "owned"), 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie", "").split(";")[0]
        connection.close()
        try:
            yield server, cookie
        finally:
            server.shutdown()
            thread.join(timeout=5)


def call(
    server: LocalServer,
    cookie: str,
    path: str,
    body: bytes | None = None,
    *,
    extra: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Cookie": cookie}
    if body is not None:
        headers.update({"X-GridBot-Lab": "1", "Content-Type": "application/json"})
    if extra:
        headers.update(extra)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    try:
        connection.request("POST" if body is not None else "GET", path, body, headers)
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def local_pack() -> bytes:
    pack = read_pack(bundled()["risk_violation"])
    metadata = deepcopy(pack.manifest)
    metadata["pack_id"] = "HTTP_LOCAL"
    return write_pack(metadata, pack.results)


@pytest.mark.parametrize("header", ["Host", "Origin", "Cookie"])
def test_duplicate_security_headers_are_rejected(
    lab_server: tuple[LocalServer, str], header: str
) -> None:
    server, cookie = lab_server
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        connection.putrequest("GET", "/api/lab/library")
        connection.putheader("Cookie", cookie)
        if header == "Origin":
            connection.putheader("Origin", origin)
        connection.putheader(header, "https://other.invalid" if header != "Cookie" else cookie)
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        assert response.status == 403
    finally:
        connection.close()


def test_end_to_end_preview_confirm_replay_export_remove(
    lab_server: tuple[LocalServer, str],
) -> None:
    server, cookie = lab_server
    status, raw, _ = call(server, cookie, "/api/lab/library")
    assert status == 200
    assert len(json.loads(raw)["studies"]) == 3
    status, raw, _ = call(
        server, cookie, "/api/lab/preview", local_pack(), extra={"Content-Type": "application/zip"}
    )
    assert status == 200
    preview = json.loads(raw)
    assert not server.service.lab.owned_paths()
    token = preview["preview_token"]
    status, _, _ = call(
        server, cookie, "/api/lab/confirm", canonical({"preview_token": token, "confirmed": False})
    )
    assert status == 422
    status, raw, _ = call(
        server, cookie, "/api/lab/confirm", canonical({"preview_token": token, "confirmed": True})
    )
    assert status == 200
    identity = json.loads(raw)["id"]
    assert len(server.service.lab.owned_paths()) == 1
    status, raw, _ = call(server, cookie, "/api/lab/analysis?id=" + identity)
    assert status == 200
    analysis = json.loads(raw)
    assert len(analysis["rows"]) == 3
    assert any(r["metrics"]["risk"]["violates_20_percent"] for r in analysis["rows"])
    status, raw, _ = call(
        server,
        cookie,
        "/api/lab/replay",
        canonical({"id": identity, "manifest": analysis["analysis_manifest"]}),
    )
    assert status == 200
    assert json.loads(raw)["status"] == "EQUIVALENT"
    assert call(server, cookie, "/api/lab/export?id=" + identity)[0] == 422
    status, _, _ = call(
        server,
        cookie,
        "/api/lab/authorize-export",
        canonical(
            {"id": identity, "scope": "RAW_AND_DERIVED", "basis": "OWN_DATA", "confirmed": True}
        ),
    )
    assert status == 200
    status, raw, headers = call(server, cookie, "/api/lab/export?id=" + identity)
    assert status == 200
    assert headers["Content-Type"] == "application/zip"
    assert "attachment" in headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("source.gbpack") == local_pack()
        assert json.loads(archive.read("analysis-manifest.json")) == analysis["analysis_manifest"]
    status, _, _ = call(
        server, cookie, "/api/lab/remove", canonical({"id": identity, "confirmed": True})
    )
    assert status == 200
    assert not server.service.lab.owned_paths()


@pytest.mark.parametrize(
    "extra",
    [
        {"Cookie": ""},
        {"Origin": "https://other.invalid"},
        {"Host": "other.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-GridBot-Lab": ""},
    ],
)
def test_mutation_requires_same_origin_and_session(
    lab_server: tuple[LocalServer, str], extra: dict[str, str]
) -> None:
    server, cookie = lab_server
    status, _, _ = call(
        server,
        cookie,
        "/api/lab/preview",
        bundled()["favorable"],
        extra={"Content-Type": "application/zip", **extra},
    )
    assert status == 403
    assert not server.service.lab.pending


@pytest.mark.parametrize(
    "extra",
    [
        {"Content-Type": "text/plain"},
        {"Content-Length": "0"},
        {"Content-Length": "2097153"},
        {"Transfer-Encoding": "chunked"},
    ],
)
def test_body_limits_are_checked_before_read(
    lab_server: tuple[LocalServer, str], extra: dict[str, str]
) -> None:
    server, cookie = lab_server
    status, raw, _ = call(
        server,
        cookie,
        "/api/lab/preview",
        b"bad",
        extra={"Content-Type": "application/zip", **extra},
    )
    assert status == 422
    assert b"DATA_INVALID" in raw
    assert b"Traceback" not in raw


@pytest.mark.parametrize(
    "query",
    [
        "id=../../private",
        "id=C%3A%5Cprivate",
        "path=secret",
        "id=bad",
        "id=x&id=y",
        "id=",
        "id=x&unknown=y",
    ],
)
def test_no_path_or_ambiguous_selection(lab_server: tuple[LocalServer, str], query: str) -> None:
    server, cookie = lab_server
    status, raw, _ = call(server, cookie, "/api/lab/analysis?" + query)
    assert status == 422
    assert b"private" not in raw
    assert b"secret" not in raw
    assert b"Traceback" not in raw


@pytest.mark.parametrize(
    "route", ["/api/lab/confirm", "/api/lab/remove", "/api/lab/replay", "/api/lab/authorize-export"]
)
@pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"path":"C:/private"}', b"{" * 40, b"\xff"])
def test_adversarial_post_json(lab_server: tuple[LocalServer, str], route: str, raw: bytes) -> None:
    server, cookie = lab_server
    status, reply, _ = call(server, cookie, route, raw)
    assert status == 422
    assert b"private" not in reply


def test_restricted_pack_export_cannot_be_enabled_by_query(
    lab_server: tuple[LocalServer, str],
) -> None:
    server, cookie = lab_server
    pack = read_pack(local_pack())
    manifest = deepcopy(pack.manifest)
    manifest["redistribution"] = "RESTRICTED"
    raw = write_pack(manifest, pack.results)
    preview = server.service.lab.preview(raw)
    study = server.service.lab.confirm(preview["preview_token"], True)
    for route in ("source", "export"):
        assert call(server, cookie, "/api/lab/" + route + "?id=" + study["id"])[0] == 422
    assert call(server, cookie, "/api/lab/export?id=" + study["id"] + "&reviewed=1")[0] == 422


def test_actual_paper_fill_before_after_trace(lab_server: tuple[LocalServer, str]) -> None:
    server, cookie = lab_server
    status, raw, _ = call(server, cookie, "/api/lab/paper")
    assert status == 200
    result = json.loads(raw)
    assert result["source_kind"] == "SYNTHETIC_DEMO"
    assert len(result["accounts"]) == 2
    assert all(
        f["reconciliation"] == "FRACTION_EXACT" for a in result["accounts"] for f in a["fills"]
    )


@pytest.mark.parametrize("header", ["X-GridBot-Lab", "Content-Type"])
def test_duplicate_write_headers_are_rejected(
    lab_server: tuple[LocalServer, str], header: str
) -> None:
    server, cookie = lab_server
    body = canonical(
        {"id": "a" * 64, "scope": "RAW_AND_DERIVED", "basis": "OWN_DATA", "confirmed": True}
    )
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.putrequest("POST", "/api/lab/authorize-export")
        values = {
            "Cookie": cookie,
            "X-GridBot-Lab": "1",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        for key, value in values.items():
            connection.putheader(key, value)
        connection.putheader(header, values[header])
        connection.endheaders(body)
        response = connection.getresponse()
        response.read()
        assert response.status == (403 if header == "X-GridBot-Lab" else 422)
    finally:
        connection.close()


def test_authorization_endpoint_requires_local_session_and_cannot_be_forged_in_query(
    lab_server: tuple[LocalServer, str],
) -> None:
    server, cookie = lab_server
    body = canonical(
        {"id": "a" * 64, "scope": "RAW_AND_DERIVED", "basis": "OWN_DATA", "confirmed": True}
    )
    assert call(server, "", "/api/lab/authorize-export", body)[0] == 403
    assert (
        call(
            server,
            cookie,
            "/api/lab/authorize-export",
            body,
            extra={"Origin": "https://outside.invalid"},
        )[0]
        == 403
    )
    assert (
        call(server, cookie, "/api/lab/export?id=" + "a" * 64 + "&scope=RAW_AND_DERIVED")[0] == 422
    )
