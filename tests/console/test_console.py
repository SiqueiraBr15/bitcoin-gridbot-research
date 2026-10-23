"""Synthetic fixtures only: local I/O contracts, financial identity and HTTP boundary."""

from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from research_console.data import Archive, decode, number, public_row, safe_read, view
from research_console.demo import demonstration
from research_console.risk import EXCEEDED, INSUFFICIENT, WITHIN, Mark, classify, profile
from research_console.server import LocalServer, Service


def marks_for(values: list[int]) -> list[Mark]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        Mark(start + timedelta(days=i), Decimal(v), Decimal(0), Decimal(1), Decimal(v))
        for i, v in enumerate(values)
    ]


def fixture_row() -> tuple[dict[str, Any], list[list[str]]]:
    marks = [p.raw() for p in marks_for([100, 80, 100])]
    risk = profile(marks_for([100, 80, 100]))
    return {
        "policy": "B0_BH",
        "cost": "CA",
        "months": 6,
        "status": "VALID",
        "start": marks[0][0],
        "end": marks[-1][0],
        "initial_usdt": "100",
        "nav_usdt": "100",
        "btc_physical": "1",
        "btc_equivalent": "1",
        "cash_usdt": "0",
        "final_mark": "100",
        "fees_usdt": "0",
        "exposure_mean": "1",
        "exposure_max": "1",
        "marks_sha256": hashlib.sha256(
            json.dumps(marks, separators=(",", ":")).encode()
        ).hexdigest(),
        **risk,
    }, marks


@pytest.fixture
def archived(tmp_path: Path) -> Archive:
    folder = tmp_path / "m1_risk"
    folder.mkdir()
    files: dict[str, Any] = {}

    def write(name: str, value: Any) -> None:
        raw = json.dumps(value).encode()
        if name.endswith(".gz"):
            raw = gzip.compress(raw, mtime=0)
        (folder / name).write_bytes(raw)
        files["docs/reviews/m1_risk/" + name] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    wallets = []
    for months in (6, 12, 24):
        for cost in ("CA", "CB", "CX2"):
            row, marks = fixture_row()
            row.update(months=months, cost=cost)
            write(f"M1_RISK_MATRIX_{months}_{cost}.json.gz", {"rows": [row]})
            wallets.append(
                {
                    **{
                        k: row[k]
                        for k in ("start", "end", "cost", "months", "policy", "marks_sha256")
                    },
                    "marks": marks,
                }
            )
    write("M1_RISK_CURVES_0001.json.gz", {"wallets": wallets})
    write(
        "M1_RISK_CURVE_INDEX.json",
        {"wallets": 9, "parts": [{"file": "M1_RISK_CURVES_0001.json.gz", "wallets": 9}]},
    )
    raw = json.dumps({"files": files}).encode()
    (folder / "M1_RISK_ARTIFACT_MANIFEST.json").write_bytes(raw)
    return Archive(tmp_path, pin=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1/5", WITHIN), ("199999/1000000", WITHIN), ("200001/1000000", EXCEEDED)],
)
def test_risk_exact_boundary(value: str, expected: str) -> None:
    assert classify(Fraction(value)) == expected


@given(st.lists(st.integers(min_value=1, max_value=100000), min_size=2, max_size=40))
def test_drawdown_independent_quadratic_oracle(values: list[int]) -> None:
    actual = Fraction(profile(marks_for(values))["max_drawdown_fraction"])
    expected = max(
        Fraction(max(values[: i + 1]) - v, max(values[: i + 1])) for i, v in enumerate(values)
    )
    assert actual == expected


def test_ties_recovery_censor_and_sampled_duration() -> None:
    result = profile(marks_for([100, 100, 80, 80, 100, 90]))
    assert result["max_drawdown_peak"] == "2020-01-02T00:00:00+00:00"
    assert result["max_drawdown_trough"] == "2020-01-03T00:00:00+00:00"
    assert result["recovery_at"] == "2020-01-05T00:00:00+00:00"
    assert result["sampled_underwater_seconds_left"] == 2 * 86400
    assert result["longest_episode_seconds"] == 3 * 86400
    censored = profile(marks_for([100, 80, 90]))
    assert censored["recovery_censored"]
    assert censored["recovery_at"] is None
    assert profile([])["risk_class"] == INSUFFICIENT
    assert profile(marks_for([100, 100]))["max_drawdown_peak"] is None


@pytest.mark.parametrize("values", [[], ["NaN"], ["-1"], ["1e9999"], ["1/2"], ["1" * 80]])
def test_unexpected_numbers(values: list[str]) -> None:
    with pytest.raises(ValueError, match="inválido"):
        number(values[0] if values else None)


def test_view_identity_btc_equivalent_and_drawdown() -> None:
    row, marks = fixture_row()
    result = view(public_row(row), marks)
    assert result["series"][1]["drawdown"] == "-0.2"
    assert result["series"][1]["btc"] == "1"
    assert result["series"][1]["btc_equivalent"] == "1"
    assert result["series"][1]["cash"] == "0"
    assert result["risk"]["violates_20_percent"] is False


@pytest.mark.parametrize(
    "field",
    [
        "nav_usdt",
        "btc_equivalent",
        "btc_physical",
        "final_mark",
        "cash_usdt",
        "max_drawdown_fraction",
        "violates_20_percent",
        "start",
        "end",
        "policy",
        "cost",
        "marks_sha256",
    ],
)
def test_invalid_row_rejected(field: str) -> None:
    row, _ = fixture_row()
    row[field] = "invalid"
    with pytest.raises((ValueError, TypeError)):
        public_row(row)


def test_no_unexpected_private_metadata_projection() -> None:
    row, _ = fixture_row()
    row["private_path"] = "DO_NOT_DISPLAY"
    assert "DO_NOT_DISPLAY" not in json.dumps(public_row(row))


@pytest.mark.parametrize("mutation", ["identity", "order", "endpoint", "capital", "last", "dd"])
def test_corrupt_curve_rejected(mutation: str) -> None:
    row, marks = fixture_row()
    if mutation == "identity":
        marks[1][4] = "81"
    elif mutation == "order":
        marks[1][0] = marks[0][0]
    elif mutation == "endpoint":
        row["end"] = "2020-01-04T00:00:00+00:00"
    elif mutation == "capital":
        row["initial_usdt"] = "101"
    elif mutation == "last":
        row["cash_usdt"] = "1"
    else:
        row["max_drawdown_fraction"] = "1/4"
    with pytest.raises(ValueError, match=r"divergente|order"):
        view(row, marks)


@pytest.mark.parametrize(
    "path",
    ["../a.json", "a/b.json", "C:\\a.json", "/a.json", "a.json:ads", "a%2f.json", "a.txt", ""],
)
def test_paths_delimited(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="Origem"):
        safe_read(tmp_path, path)


def test_bounded_and_invalid_files(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b" " * (512 * 1024 + 1))
    with pytest.raises(ValueError, match="limite"):
        safe_read(tmp_path, "a.json")
    with pytest.raises(ValueError, match="limite"):
        decode(gzip.compress(b" " * (8 * 1024 * 1024 + 1)), True)
    with pytest.raises(json.JSONDecodeError):
        decode(b"not json")
    with pytest.raises((OSError, EOFError)):
        decode(b"not gzip", True)


def test_origin_link_and_corporate_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="recusada"):
        Archive(tmp_path / "BIMSTRUCT")
    monkeypatch.setattr(Path, "is_symlink", lambda _: True)
    with pytest.raises(ValueError, match="Links"):
        safe_read(tmp_path, "a.json")


def test_archive_readonly_selection_hashes_and_determinism(archived: Archive) -> None:
    before = {p.name: p.read_bytes() for p in archived.root.iterdir()}
    first = archived.selection("2020-01-01", 24, "CA")
    assert first == archived.selection("2020-01-01", 24, "CA")
    assert len(first) == 1
    assert len(archived.summaries) == 9
    assert not archived.selection("1999-01-01", 24, "CA")
    assert before == {p.name: p.read_bytes() for p in archived.root.iterdir()}
    (archived.root / "M1_RISK_CURVES_0001.json.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Integridade"):
        archived.selection("2020-01-01", 24, "CA")


def test_unrecognized_manifest_refused(archived: Archive) -> None:
    with pytest.raises(ValueError, match="Manifesto"):
        Archive(archived.root.parent)


def test_demo_no_network_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)
    first = demonstration()
    assert first == demonstration()
    assert Fraction(first[0]["summary"]["nav_usdt"]) > 100
    assert Fraction(first[1]["summary"]["nav_usdt"]) < 100
    assert all(a["source_kind"] == "SYNTHETIC_DEMO" and a["events"] and a["fills"] for a in first)
    for account in first:
        assert all(fill["order_ref"] for fill in account["fills"])
        for point in account["series"]:
            assert Fraction(point["cash"]) == (
                Fraction(point["available_usdt"]) + Fraction(point["reserved_usdt"])
            )


@pytest.fixture
def server(archived: Archive) -> Iterator[LocalServer]:
    instance = LocalServer(Service(archived), 0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def request(
    server: LocalServer, path: str, *, headers: dict[str, str] | None = None, method: str = "GET"
) -> tuple[int, bytes, dict[str, str]]:
    with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)) as conn:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read(), dict(response.getheaders())


def test_http_menus_catalog_and_selection(server: LocalServer) -> None:
    status, body, headers = request(server, "/")
    assert status == 200
    assert b"127.0.0.1" not in body
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "SameSite=Strict" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    for path in (
        "/app.js",
        "/style.css",
        "/api/catalog",
        "/api/selection?start=2020-01-01&months=24&cost=CA",
        "/api/export?start=2020-01-01&months=24&cost=CA",
        "/api/demo",
    ):
        status, body, headers = request(server, path, headers={"Cookie": cookie})
        assert status == 200
        assert body
        assert b"DO_NOT_DISPLAY" not in body
        if path.startswith("/api/export"):
            assert "attachment" in headers["Content-Disposition"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_http_rebinding_csrf_rejected(server: LocalServer, headers: dict[str, str]) -> None:
    assert request(server, "/", headers=headers)[0] == 403


def test_http_no_session_traversal_mutation_and_missing(server: LocalServer) -> None:
    assert request(server, "/api/catalog")[0] == 403
    cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
    headers = {"Cookie": cookie}
    for path in ("/../LICENSE", "/.env", "/api/unknown"):
        assert request(server, path, headers=headers)[0] == 404
    assert request(server, "/api/selection?start=x&months=24&cost=CA", headers=headers)[0] == 422
    assert (
        request(server, "/api/selection?start=a&start=b&months=24&cost=CA", headers=headers)[0]
        == 422
    )
    assert request(server, "/api/demo", headers=headers, method="POST")[0] == 405
    server.service = Service(archive_error=True)
    assert (
        json.loads(request(server, "/api/catalog", headers=headers)[1])["archive_status"]
        == "UNAVAILABLE"
    )
    assert json.loads(request(server, "/api/selection", headers=headers)[1])["accounts"] == []
    assert Service().catalog()["research_date"] is None


def test_selection_comparison_uses_same_endpoint(archived: Archive) -> None:
    service = Service(archived)
    query = {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    result = service.selection(query)
    assert result["accounts"][0]["benchmark_gaps"]["B0_BH"]["return_pp"] == "0"


def test_demo_decimal_context_isolation() -> None:
    expected = demonstration()
    with localcontext() as context:
        context.prec = 6
        assert demonstration() == expected


def test_archive_does_not_execute_a_strategy(
    archived: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import research_console.demo as demo

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("No new historical run")

    monkeypatch.setattr(demo, "synthetic_run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert archived.selection("2020-01-01", 6, "CA")


@pytest.mark.parametrize("argv", [["console", "--port", "80"], ["console", "--help"]])
def test_cli_help_and_invalid_port(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from research_console.__main__ import main

    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == (0 if "--help" in argv else 2)


@pytest.mark.parametrize("archive", [False, True])
def test_cli_bind_failure_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    archive: bool,
) -> None:
    import research_console.__main__ as cli

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Do not expose this path")

    monkeypatch.setattr(cli, "LocalServer", unavailable)
    argv = ["console"] + (["--archive-root", str(tmp_path)] if archive else [])
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    errors = capsys.readouterr().err
    assert "Do not expose" not in errors
    assert str(tmp_path) not in errors
