"""Permanent G4.5 regressions; financial oracles do not use production serialization."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from decimal import Context, localcontext
from fractions import Fraction
from pathlib import Path

import pytest
from research_console.lab.analytics import analyze
from research_console.lab.exports import analysis_manifest, export_analysis, replay
from research_console.lab.library import Library
from research_console.lab.numeric import (
    MAX_INTEGER_BITS,
    AnalysisError,
    balanced_sum,
    exact,
    integer_text,
)
from research_console.lab.packs import read_pack
from tests.console.numeric_cases import coprime_pack, primes, rational


@pytest.mark.parametrize(
    ("count", "checksum"),
    [
        (100, "3591b23214a05051fabe632d764fe002981055e0fe252b2dfa9221848ec1f6d1"),
        (1200, "8150d310a5ff6fd04ddbb50ba85a13e80638bc2c67f3ea1b57d818631b04cede"),
    ],
)
def test_original_g45_bytes_exactly_analyze(count: int, checksum: str) -> None:
    raw = (Path(__file__).parents[1] / "fixtures" / f"g45_prime_{count}.gbpack").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == checksum
    parsed = read_pack(raw)
    a = analyze(parsed)
    expected = 1 - sum((Fraction(1, p) for p in primes(count)[:-1]), Fraction()) / (count - 1)
    assert rational(a["rows"][0]["metrics"]["exact"]["exposure_mean_left"]) == expected
    assert replay(parsed, analysis_manifest(parsed))["status"] == "EQUIVALENT"


@pytest.mark.parametrize("count", [100, 1200, 3000, 9999])
def test_coprime_growth_keeps_exact_transport_and_export(count: int) -> None:
    raw, expected = coprime_pack(count)
    parsed = read_pack(raw)
    result = analyze(parsed)
    encoded = json.dumps(result, allow_nan=False)
    decoded = json.loads(encoded)
    values = decoded["rows"][0]["metrics"]["exact"]
    assert rational(values["exposure_mean_left"]) == expected
    last = primes(count)[-1]
    assert rational(values["nav_initial"]) == 1009
    assert rational(values["nav_final"]) == last
    assert rational(values["btc_physical"]) == rational(values["cash_usdt"]) == 1
    assert rational(values["btc_equivalent"]) == Fraction(last, last - 1)
    assert rational(values["return_ratio"]) == Fraction(last - 1009, 1009)
    assert rational(values["max_drawdown"]) == rational(values["fees_usdt"]) == 0
    assert result["pareto"]["non_dominated"] == ["HOLD"]
    with zipfile.ZipFile(io.BytesIO(export_analysis(parsed, permission="RAW_AND_DERIVED"))) as z:
        exported = json.loads(z.read("metrics.json"))
        assert exported == result
        assert z.read("source.gbpack") == raw
        checks = json.loads(z.read("checksums.json"))
        assert all(hashlib.sha256(z.read(n)).hexdigest() == v["sha256"] for n, v in checks.items())


@pytest.mark.parametrize("scale", [-100, 15])
def test_extreme_valid_magnitudes_do_not_change_exposure(scale: int) -> None:
    raw, expected = coprime_pack(123, scale)
    parsed = read_pack(raw)
    values = analyze(parsed)["rows"][0]["metrics"]["exact"]
    assert rational(values["exposure_mean_left"]) == expected
    assert rational(values["nav_final"]) == Fraction(parsed.results["accounts"][0]["points"][-1][4])


def test_exact_serializer_is_context_independent_without_disabling_int_safety() -> None:
    limit = sys.get_int_max_str_digits()
    value = Fraction(-(10**5001 + 7), 10**5101 + 3)
    with localcontext(Context(prec=1)):
        serialized = exact(value)
    assert rational(serialized) == value
    assert sys.get_int_max_str_digits() == limit
    assert exact(Fraction(0)) == "0"
    assert exact(Fraction(-2)) == "-2"


def test_impossible_out_of_contract_integer_is_internal_error() -> None:
    with pytest.raises(AnalysisError, match="numeric contract"):
        integer_text(1 << (MAX_INTEGER_BITS + 1))


def test_balanced_sum_does_not_change_inputs_or_cancellation() -> None:
    values = [Fraction(1, 11), Fraction(-1, 11), Fraction(2, 7)]
    before = values[:]
    assert balanced_sum(values) == Fraction(2, 7)
    assert values == before
    assert balanced_sum([]) == 0


def test_long_exposure_cold_warm_cache_is_exact_and_isolated(tmp_path: Path) -> None:
    lib = Library(tmp_path / "numeric-library")
    ids = []
    for n in [100, 1200]:
        raw, _ = coprime_pack(n)
        preview = lib.preview(raw)
        ids.append(lib.confirm(preview["preview_token"], True)["id"])
    first = lib.analysis(ids[0])
    second = lib.analysis(ids[1])
    assert first == lib.analysis(ids[0])
    assert second == lib.analysis(ids[1])
    assert first != second
    assert rational(first["rows"][0]["metrics"]["exact"]["exposure_mean_left"]) != rational(
        second["rows"][0]["metrics"]["exact"]["exposure_mean_left"]
    )
