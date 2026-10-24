"""G3 characterization and adversarial contracts; fixtures are synthetic only."""

from __future__ import annotations

import csv
import io
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from research_console.analysis import export_csv
from research_console.data import MAX_ITEMS, Archive, decode, public_row, safe_read, view
from research_console.demo import demonstration
from research_console.server import LocalServer, Service
from tests.console.test_console import archived as archived
from tests.console.test_console import fixture_row, request
from tests.console.test_console import server as server


@pytest.mark.parametrize("suffix", ["&unexpected=", "&policies=", "&cost=", "&reference="])
def test_blank_or_unknown_query_is_not_silently_dropped(server: LocalServer, suffix: str) -> None:
    cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
    status, body, _ = request(
        server,
        "/api/selection?start=2020-01-01&months=24&cost=CA" + suffix,
        headers={"Cookie": cookie},
    )
    assert status == 422
    assert json.loads(body)["source_kind"] == "UNAVAILABLE"


def test_export_carries_dataset_schema_and_focus(archived: Archive) -> None:
    result = Service(archived).selection(
        {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    )
    exported = next(csv.DictReader(io.StringIO(export_csv(result).decode("utf-8-sig"))))
    assert exported["dataset_id"] == "M1_R_DAILY_MARKS_V1"
    assert exported["schema"] == result["schema"]
    assert exported["focused_policy"] == "B0_BH"
    assert exported["reference"] == "B0_BH"
    assert Fraction(exported["nav_usdt"]) == Fraction(result["accounts"][0]["summary"]["nav_usdt"])


def test_nested_json_is_rejected_before_resource_growth() -> None:
    with pytest.raises(ValueError, match="JSON"):
        decode(b"[" * 1500 + b"0" + b"]" * 1500)


@pytest.mark.parametrize("raw", [b"NaN", b"Infinity", b"-Infinity"])
def test_nonstandard_json_constants_are_refused(raw: bytes) -> None:
    with pytest.raises(ValueError, match="JSON"):
        decode(raw)


def test_subset_response_does_not_mutate_nested_cache(archived: Archive) -> None:
    service = Service(archived)
    query = {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    expected = deepcopy(service.selection(query))
    changed = service.selection({**query, "policies": ["B0_BH"]})
    changed["accounts"][0]["series"][0]["nav"] = "FORGED"
    assert service.selection(query) == expected


@pytest.mark.parametrize("field", ["policy", "months", "marks_sha256", "nav_usdt"])
def test_csv_formula_payload_refused(archived: Archive, field: str) -> None:
    result: dict[str, Any] = Service(archived).selection(
        {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    )
    result["accounts"][0]["summary"][field] = '=HYPERLINK("https://invalid.example")'
    with pytest.raises(ValueError, match="Export"):
        export_csv(result)


@pytest.mark.parametrize(
    "raw", [b'{"x":', b"\xff", b"[1,2,", b'{"a":1,"a":2}', "{}".encode("utf-16")]
)
def test_invalid_encoding_truncated_json_and_duplicates(raw: bytes) -> None:
    with pytest.raises(ValueError, match=r"JSON|Expecting|codec"):
        decode(raw)


def test_json_string_brackets_are_not_structural() -> None:
    value = {"literal": '["' * 100 + r"\"quoted\\" + "}]" * 100}
    assert decode(json.dumps(value).encode()) == value
    with pytest.raises(ValueError, match="JSON"):
        decode(b"[" + b"0," * (MAX_ITEMS + 1) + b"0]")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_usdt", "-1"),
        ("nav_usdt", "0"),
        ("final_mark", "0"),
        ("initial_usdt", "0"),
        ("fees_usdt", "NaN"),
        ("btc_physical", None),
        ("policy", "UNKNOWN"),
        ("months", 9),
        ("cost", "UNKNOWN"),
    ],
)
def test_invalid_financial_schema_refused(field: str, value: Any) -> None:
    row, _ = fixture_row()
    row[field] = value
    with pytest.raises((ValueError, TypeError)):
        public_row(row)


@pytest.mark.parametrize("length", [0, 1])
def test_insufficient_marks_do_not_become_a_valid_wallet(length: int) -> None:
    row, marks = fixture_row()
    with pytest.raises(ValueError, match="Série"):
        view(public_row(row), marks[:length])


def test_constant_and_gapped_cash_wallet_is_valid() -> None:
    row, marks = fixture_row()
    for mark in marks:
        mark[2:5] = ["100", "0", "100"]
    marks[1][0] = "2020-01-03T00:00:00+00:00"
    marks[2][0] = "2020-01-05T00:00:00+00:00"
    row.update(end=marks[-1][0], cash_usdt="100", btc_physical="0", max_drawdown_fraction="0")
    result = view(row, marks)
    assert result["risk"]["max_drawdown_fraction"] == "0"
    assert result["risk"]["max_mark_interval_seconds"] == 172800


def test_csv_is_not_an_admitted_archive_format(tmp_path: Path) -> None:
    (tmp_path / "truncated.csv").write_text('nav,btc\n"100', encoding="utf-8")
    with pytest.raises(ValueError, match="Origem"):
        safe_read(tmp_path, "truncated.csv")


@pytest.mark.parametrize(
    "target",
    [
        "//[",
        "http://invalid.example/",
        "/api/selection?bad",
        "/api/selection?start=a&months=24&cost=CA&focus=UNKNOWN",
        "/api/demo?unknown=",
        "/api/demo?focus=UNKNOWN",
        "/api/demo?focus=a&focus=b",
    ],
)
def test_malformed_targets_have_defined_responses(server: LocalServer, target: str) -> None:
    cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
    status, body, _ = request(server, target, headers={"Cookie": cookie})
    assert status in (400, 403, 404, 422)
    assert b"Traceback" not in body


def test_missing_static_file_is_sanitized(
    server: LocalServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("research_console.server.STATIC", tmp_path)
    status, body, _ = request(server, "/app.js")
    assert status == 503
    assert str(tmp_path).encode() not in body


def test_moderate_simultaneous_reads_and_disconnect(server: LocalServer) -> None:
    cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
    path = "/api/selection?start=2020-01-01&months=24&cost=CA"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: request(server, path, headers={"Cookie": cookie}), range(8))
        )
    assert all(code == 200 for code, _, _ in results)
    assert all(body == results[0][1] for _, body, _ in results)
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as conn:
        conn.sendall(
            (
                f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{server.server_port}\r\n"
                f"Cookie: {cookie}\r\n\r\n"
            ).encode()
        )
    assert request(server, path, headers={"Cookie": cookie})[0] == 200


def test_occupied_port_and_expired_session(server: LocalServer) -> None:
    with (
        pytest.raises(OSError, match=r"10048|Address already|endereço|address"),
        LocalServer(Service(), server.server_port),
    ):
        pass
    headers = {"Cookie": "console=" + "a" * 64}
    assert request(server, "/api/catalog", headers=headers)[0] == 403


def test_sessions_for_two_ports_do_not_overwrite_each_other(server: LocalServer) -> None:
    with LocalServer(Service(), 0) as second:
        thread = threading.Thread(target=second.serve_forever, daemon=True)
        thread.start()
        try:
            first_cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
            second_cookie = request(second, "/")[2]["Set-Cookie"].split(";")[0]
            assert first_cookie.split("=")[0] != second_cookie.split("=")[0]
            headers = {"Cookie": first_cookie + "; " + second_cookie}
            assert request(server, "/api/catalog", headers=headers)[0] == 200
            assert request(second, "/api/catalog", headers=headers)[0] == 200
        finally:
            second.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_explicit_demo_rerun_executes_native_path_and_is_equal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_console.server as module

    original = demonstration
    calls = []

    def observed() -> list[dict[str, Any]]:
        calls.append(True)
        return original()

    monkeypatch.setattr(module, "demonstration", observed)
    service = Service()
    first = service.demonstration("falling_mark")
    assert service.demonstration("falling_mark") == first
    assert len(calls) == 1
    assert service.demonstration("falling_mark", rerun=True) == first
    assert len(calls) == 2


def test_real_symlink_outside_archive_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "a.json"
    target.write_text("{}", encoding="utf-8")
    inside = tmp_path / "inside"
    inside.mkdir()
    try:
        (inside / "a.json").symlink_to(target)
    except OSError:
        pytest.skip("Windows does not permit symlink creation in this account")
    with pytest.raises(ValueError, match="Links"):
        safe_read(inside, "a.json")
