"""G2 regressions: exact comparisons, source integrity, exports and bounded cache."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from fractions import Fraction
from typing import Any

import pytest
from research_console.analysis import compare, distributions, export_csv
from research_console.data import Archive, decode, number, public_row, view
from research_console.server import LocalServer, Service
from tests.console.test_console import archived as archived
from tests.console.test_console import fixture_row, request
from tests.console.test_console import server as server


def peers() -> list[dict[str, Any]]:
    row, _ = fixture_row()
    row = public_row(row)
    first = {**row, "nav_usdt": "100", "btc_physical": "0.5", "cash_usdt": "50", "return": "0"}
    second = {
        **row,
        "policy": "P_BANDS",
        "nav_usdt": "80",
        "btc_physical": "0.6",
        "cash_usdt": "20",
        "return": "-0.2",
    }
    return [{"summary": first}, {"summary": second}]


def test_exact_more_btc_less_nav_decomposition() -> None:
    result = compare(peers(), "B0_BH")
    row = result["rows"][1]
    assert row["more_btc_less_nav"]
    assert Fraction(row["delta_btc"]) == Fraction(1, 10)
    assert row["delta_cash_usdt"] == "-30"
    assert row["btc_mark_component_usdt"] == "10"
    assert row["delta_nav_usdt"] == "-20"
    assert row["delta_return_pp"] == "-20"
    assert "winner" not in result
    assert result["extrema"]["nav_usdt"]["maximum"] == ["B0_BH"]
    assert result["extrema"]["btc_physical"]["maximum"] == ["P_BANDS"]


@pytest.mark.parametrize("field", ["start", "end", "cost", "months", "initial_usdt", "final_mark"])
def test_incompatible_comparison_refused(field: str) -> None:
    accounts = peers()
    accounts[1]["summary"][field] = (
        "200" if field in ("initial_usdt", "final_mark") else "different"
    )
    with pytest.raises(ValueError, match="incompatível"):
        compare(accounts, "B0_BH")


def test_comparison_duplicate_empty_and_absent_reference() -> None:
    with pytest.raises(ValueError, match="indisponível"):
        compare([], "B0_BH")
    with pytest.raises(ValueError, match="Referência"):
        compare(peers(), "UNKNOWN")
    p = peers()
    p[1]["summary"]["policy"] = "B0_BH"
    with pytest.raises(ValueError, match="Referência"):
        compare(p, "B0_BH")


def test_ties_and_reference_reversal() -> None:
    accounts = peers()
    result = compare(accounts, "P_BANDS")
    assert result["rows"][0]["delta_return_pp"] == "20"
    assert result["extrema"]["fees_usdt"]["maximum"] == ["B0_BH", "P_BANDS"]


def test_internal_distributions_not_promoted_to_public() -> None:
    assert distributions([], "LOCAL_AUTHORIZED_ARCHIVE")["status"] == "UNAVAILABLE"
    assert distributions([], "ARCHIVED_RESEARCH_RESULT")["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("values", [["0", "0"], ["-0.2", "0.2"], ["0.000000001"]])
def test_synthetic_distributions_count_every_result(values: list[str]) -> None:
    rows = [{"return": v, "max_drawdown": "0.2"} for v in values]
    result = distributions(rows, "SYNTHETIC_DEMO")
    assert sum(b["count"] for b in result["return"]["bins"]) == len(values)
    assert sum(result["return"][k] for k in ("positive", "negative", "zero")) == len(values)
    assert result["status"] == "SYNTHETIC_DEMO"


def test_synthetic_empty_distribution_is_explicit() -> None:
    assert distributions([], "SYNTHETIC_DEMO")["return"]["bins"] == []


@pytest.mark.parametrize(
    "query",
    [
        {"reference": ["UNKNOWN"]},
        {"policies": ["B0_BH,B0_BH"]},
        {"policies": ["P_BANDS"], "reference": ["B0_BH"]},
        {"policies": ["../private"]},
        {"unknown": ["x"]},
        {"start": ["a", "b"]},
    ],
)
def test_api_selection_parameters_rejected(archived: Archive, query: dict[str, list[str]]) -> None:
    base = {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    base.update(query)
    with pytest.raises(ValueError, match="Seleção"):
        Service(archived).selection(base)


def test_cache_isolated_by_cost_horizon_and_source(archived: Archive) -> None:
    service = Service(archived)
    query = {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    first = service.selection(query)
    assert service.selection(query) == first
    assert service.cache_hits == 1
    mutated = service.selection(query)
    mutated["accounts"][0]["summary"]["nav_usdt"] = "FORGED"
    assert service.selection(query)["accounts"][0]["summary"]["nav_usdt"] == "100"
    for months in ("6", "12", "24"):
        for cost in ("CA", "CX2", "CB"):
            result = service.selection({**query, "months": [months], "cost": [cost]})
            assert result["accounts"][0]["summary"]["cost"] == cost
            assert result["accounts"][0]["summary"]["months"] == int(months)
    assert len(service.cache) == 4


@pytest.mark.parametrize(
    "name",
    [
        "M1_RISK_CURVES_0001.json.gz",
        "M1_RISK_MATRIX_24_CA.json.gz",
        "M1_RISK_CURVE_INDEX.json",
        "M1_RISK_ARTIFACT_MANIFEST.json",
    ],
)
def test_cache_never_hides_corruption(archived: Archive, name: str) -> None:
    service = Service(archived)
    query = {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    service.selection(query)
    path = archived.root / name
    raw = path.read_bytes()
    # Same length; mtime is deliberately irrelevant to the hash key.
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match=r"Integridade|Manifesto"):
        service.selection(query)


def test_no_future_or_incomplete_marks_admitted() -> None:
    row, marks = fixture_row()
    with pytest.raises(ValueError, match="Endpoint"):
        view(row, marks[:-1])
    future = deepcopy(marks[-1])
    future[0] = "2020-01-04T00:00:00+00:00"
    with pytest.raises(ValueError, match="Endpoint"):
        view(row, [*marks, future])
    bad = deepcopy(marks)
    bad[1][1] = "-1"
    with pytest.raises(ValueError, match="Saldo"):
        view(row, bad)


@pytest.mark.parametrize("value", ["1e999", "\uff11", "\u0661", "1e-999"])
def test_plot_unsafe_financial_encodings_refused(value: str) -> None:
    with pytest.raises(ValueError, match="inválid"):
        number(value)


def test_duplicate_json_fields_refused() -> None:
    with pytest.raises(ValueError, match="duplicado"):
        decode(b'{"policy":"B0_BH","policy":"P_BANDS"}')


def test_exact_csv_projection_and_units(archived: Archive) -> None:
    payload = Service(archived).selection(
        {"start": ["2020-01-01"], "months": ["24"], "cost": ["CA"]}
    )
    payload["accounts"][0]["summary"]["private_path"] = "DO_NOT_EXPORT"
    raw = export_csv(payload)
    assert b"DO_NOT_EXPORT" not in raw
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0]["nav_usdt"] == "100"
    assert rows[0]["source_kind"] == "ARCHIVED_RESEARCH_RESULT"
    assert "UTC" in rows[0]["units"]
    assert rows[0]["manifest_sha256"] == archived.pin
    assert rows[0]["reference"] == "B0_BH"
    assert rows[0]["delta_nav_usdt"] == "0"
    assert rows[0]["delta_return_pp"] == "0"
    assert rows[0]["delta_btc"] == "0"


def test_synthetic_export_and_cache_identification() -> None:
    service = Service()
    result = service.demonstration()
    assert result == service.demonstration()
    assert result["comparison"] is None
    assert result["distributions"]["observations"] == 2
    assert b"SYNTHETIC_DEMO" in export_csv(result)
    assert all("return" in a["summary"] for a in result["accounts"])


def test_external_navigation_shell_only_and_strict_api(server: LocalServer) -> None:
    headers = {
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    assert request(server, "/", headers=headers)[0] == 200
    assert request(server, "/api/catalog", headers=headers)[0] == 403
    assert request(server, "/", headers={**headers, "Sec-Fetch-Dest": "iframe"})[0] == 403
    assert request(server, "/", headers={**headers, "Host": "evil.example"})[0] == 403


def test_new_exports_assets_and_public_errors(server: LocalServer) -> None:
    cookie = request(server, "/")[2]["Set-Cookie"].split(";")[0]
    headers = {"Cookie": cookie, "X-GridBot-Reviewed": "1"}
    for name in ("/state.js", "/charts.js", "/api/export.csv?start=2020-01-01&months=24&cost=CA"):
        status, body, response_headers = request(server, name, headers=headers)
        assert status == 200
        assert body
        if name.startswith("/api/export"):
            assert "csv" in response_headers["Content-Type"]
    assert server.service.archive is not None
    server.service.archive.root.joinpath("M1_RISK_CURVES_0001.json.gz").write_bytes(b"invalid")
    status, body, _ = request(
        server, "/api/selection?start=2020-01-01&months=24&cost=CA", headers=headers
    )
    assert status == 422
    assert json.loads(body)["reason"] == "INTEGRITY_MISMATCH"
    assert b"C:\\" not in body
