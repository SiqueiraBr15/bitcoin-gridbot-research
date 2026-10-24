"""Independent rational oracles and adversarial Evidence Pack contracts."""

from __future__ import annotations

import io
import json
import random
import stat
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from research_console.lab.analytics import analyze, episodes, metrics, pareto
from research_console.lab.exports import analysis_manifest, export_analysis, replay, safe_cell
from research_console.lab.fixtures import bundled
from research_console.lab.library import Library
from research_console.lab.packs import (
    MAX_UPLOAD,
    canonical,
    read_pack,
    validate_manifest,
    validate_results,
    write_pack,
)


def test_aggregate_is_not_a_curve_and_replays_without_inventing_marks() -> None:
    manifest, _ = sample()
    manifest["source_kind"] = "AGGREGATED_RESEARCH_SUMMARY"
    data = {
        "accounts": [],
        "aggregates": [
            {
                "policy": "SYNTHETIC",
                "cost_scenario": "ZERO",
                "observations": 3,
                "losses": 2,
                "violations": 1,
            }
        ],
    }
    pack = read_pack(write_pack(manifest, data))
    result = analyze(pack)
    assert result["status"] == "AGGREGATE_ONLY_NO_CURVES"
    assert not result["rows"]
    assert result["data_nature"] == "SYNTHETIC"
    assert replay(pack, analysis_manifest(pack))["status"] == "EQUIVALENT"
    data["aggregates"][0]["losses"] = 4
    with pytest.raises(ValueError, match="Contagens"):
        write_pack(manifest, data)


def test_overlapping_windows_are_descriptive_and_not_joined() -> None:
    manifest, data = sample()
    original = deepcopy(data["accounts"])
    for a in original:
        a["account_id"] += "_shifted"
        a["benchmark"] += "_shifted"
        a["window_id"] = "shifted"
        for p in a["points"]:
            p[0] = (datetime.fromisoformat(p[0]) + timedelta(days=1)).isoformat()
        a["start"], a["end"] = a["points"][0][0], a["points"][-1][0]
    data["accounts"].extend(original)
    manifest["end"] = original[0]["end"]
    pack = read_pack(write_pack(manifest, data))
    result = analyze(pack)
    assert len(result["rows"]) == 6
    assert len({r["group_id"] for r in result["rows"]}) == 2
    for group in result["descriptive"]:
        assert group["windows"] == 2
        assert group["overlapping"] is True
        assert group["inference"] == "DESCRIPTIVE_DEPENDENT_WINDOWS_NO_CONFIDENCE_INTERVAL"


@given(
    st.lists(
        st.tuples(st.integers(0, 100), st.integers(0, 100), st.integers(0, 100)),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=60, deadline=None)
def test_pareto_independent_vector_oracle(vectors: list[tuple[int, int, int]]) -> None:
    rows = [
        {
            "account_id": str(i),
            "group_id": "SAME",
            "metrics": {
                "exact": {
                    "nav_final": str(v[0]),
                    "btc_physical": str(v[1]),
                    "max_drawdown": str(Fraction(v[2], 100)),
                }
            },
        }
        for i, v in enumerate(vectors)
    ]
    expected = []
    for i, a in enumerate(vectors):
        if not any(b[0] >= a[0] and b[1] >= a[1] and b[2] <= a[2] and b != a for b in vectors):
            expected.append(str(i))
    assert pareto(rows, ["nav_final", "btc_physical", "max_drawdown"]) == sorted(expected)


def test_zip_duplicates_deep_json_and_decompression_bomb() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = container(
            [("manifest.json", b"{}"), ("results.json", b"{}"), ("results.json", b"{}")]
        )
    with pytest.raises(ValueError, match="duplicatas"):
        read_pack(duplicate)
    with pytest.raises(ValueError, match="aninhado"):
        read_pack(container([("manifest.json", b"[" * 40 + b"]" * 40), ("results.json", b"{}")]))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("results.json", b"0" * 500000)
    with pytest.raises(ValueError, match="compressão"):
        read_pack(stream.getvalue())


def test_preview_expiry_eviction_and_non_owned_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "owned")
    previews = [library.preview(bundled()["favorable"]) for _ in range(3)]
    assert len(library.pending) == 2
    assert previews[0]["preview_token"] not in library.pending
    token = previews[1]["preview_token"]
    created, pack = library.pending[token]
    library.pending[token] = (created - 301, pack)
    with pytest.raises(ValueError, match="expirada"):
        library.confirm(token, True)
    with pytest.raises(ValueError, match="Identidade"):
        library.get("../../secret")
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "owned")
    with pytest.raises(ValueError, match="Links"):
        library.catalog()


def test_replay_rejects_wrong_code_data_and_unknown_account() -> None:
    pack = read_pack(bundled()["favorable"])
    m = analysis_manifest(pack)
    for key in ("analytics_version", "implementation_sha256", "pack_sha256", "manifest_sha256"):
        invalid = {**m, key: "wrong"}
        with pytest.raises(ValueError, match="incompatív"):
            replay(pack, invalid)
    with pytest.raises(ValueError, match="Seleção"):
        analyze(pack, ["MISSING"])
    with pytest.raises(ValueError, match="Objetivos"):
        analyze(pack, objectives=["score"])
    with pytest.raises(ValueError, match="Objetivos"):
        analyze(pack, objectives=[])


def sample() -> tuple[dict[str, Any], dict[str, Any]]:
    pack = read_pack(bundled()["risk_violation"])
    return deepcopy(pack.manifest), deepcopy(pack.results)


def container(entries: list[tuple[str, bytes]], *, mode: int = stat.S_IFREG) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, raw in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = (mode | 0o600) << 16
            archive.writestr(info, raw)
    return stream.getvalue()


@pytest.mark.parametrize("mode", ["comment", "prefix", "suffix", "nul_name"])
def test_container_rejects_unmanifested_bytes(mode: str) -> None:
    raw = bundled()["favorable"]
    if mode == "comment":
        stream = io.BytesIO(raw)
        with zipfile.ZipFile(stream, "a") as archive:
            archive.comment = b"UNMANIFESTED_TEST_ONLY"
        raw = stream.getvalue()
    elif mode == "prefix":
        raw = b"UNMANIFESTED_TEST_ONLY" + raw
    elif mode == "suffix":
        raw += b"UNMANIFESTED_TEST_ONLY"
    else:
        pack = read_pack(raw)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("manifest.json", canonical(pack.manifest))
            entry = zipfile.ZipInfo("results.json")
            entry.filename = "results.json\x00.py"
            archive.writestr(entry, canonical(pack.results))
        raw = stream.getvalue()
    with pytest.raises(ValueError, match=r".+"):
        read_pack(raw)


@pytest.mark.parametrize("name", ["favorable", "unfavorable", "risk_violation"])
def test_pack_determinism_and_complete_conservation(name: str) -> None:
    raw = bundled()[name]
    assert raw == bundled()[name]
    pack = read_pack(raw)
    result = analyze(pack)
    for account, row in zip(
        sorted(pack.results["accounts"], key=lambda a: a["account_id"]), result["rows"], strict=True
    ):
        for point in account["points"]:
            _, price, cash, btc, nav = point
            assert Fraction(nav) == Fraction(cash) + Fraction(btc) * Fraction(price)
        last = account["points"][-1]
        assert Fraction(row["metrics"]["exact"]["nav_final"]) == Fraction(last[4])
        assert Fraction(row["metrics"]["exact"]["btc_equivalent"]) == Fraction(last[4]) / Fraction(
            last[1]
        )
        assert abs(
            Fraction(row["metrics"]["btc_equivalent"]) - Fraction(last[4]) / Fraction(last[1])
        ) < Fraction(1, 10**45)
    manifest = analysis_manifest(pack)
    assert replay(pack, manifest)["status"] == "EQUIVALENT"
    assert export_analysis(pack) == export_analysis(pack)


@pytest.mark.parametrize("key", sorted(sample()[0]))
def test_every_manifest_field_is_required(key: str) -> None:
    manifest, _ = sample()
    del manifest[key]
    with pytest.raises(ValueError, match=r".+"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("timezone", "local"),
        ("currency", "BTC"),
        ("units", []),
        ("sampling_seconds", True),
        ("sampling_seconds", 0),
        ("source_kind", "REALTIME"),
        ("title", "<script>"),
        ("title", "=SUM(1)"),
        ("title", "C:\\private"),
        ("title", "a\x00b"),
        ("redistribution", "ALLOW_EVERYTHING"),
        ("limitations", []),
        ("created_at", "2020-01-01"),
        ("end", "2019-01-01T00:00:00+00:00"),
    ],
)
def test_metadata_security_and_versions(key: str, value: Any) -> None:
    manifest, _ = sample()
    manifest[key] = value
    with pytest.raises(ValueError, match=r".+"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "path",
    [
        "../results.json",
        "/results.json",
        "C:\\results.json",
        "sub/results.json",
        "results.JSON",
        "résults.json",
        "results.json\x00.py",
        "run.py",
    ],
)
def test_non_allowlisted_container_paths(path: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        read_pack(container([("manifest.json", b"{}"), (path, b"{}")]))


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFDIR, stat.S_IFCHR, stat.S_IFIFO])
def test_special_container_entries(mode: int) -> None:
    with pytest.raises(ValueError, match=r".+"):
        read_pack(container([("manifest.json", b"{}"), ("results.json", b"{}")], mode=mode))


@pytest.mark.parametrize(
    "raw",
    [b"", b"not zip", b"PK\x03\x04", b"x" * (MAX_UPLOAD + 1)],
    ids=["empty", "text", "truncated", "over_limit"],
)
def test_invalid_and_oversized_container(raw: bytes) -> None:
    with pytest.raises(ValueError, match=r".+"):
        read_pack(raw)


def test_hash_mismatch_and_duplicate_json_keys() -> None:
    manifest, _ = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        read_pack(container([("manifest.json", canonical(manifest)), ("results.json", b"{}")]))
    with pytest.raises(ValueError, match="duplicado"):
        read_pack(container([("manifest.json", b'{"a":1,"a":2}'), ("results.json", b"{}")]))


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate",
        "order",
        "NAV",
        "price",
        "negative",
        "nan",
        "number_type",
        "timestamp",
        "endpoint",
        "benchmark",
        "cost",
        "market",
        "units",
    ],
)
def test_series_adversaries(change: str) -> None:
    manifest, data = sample()
    a = data["accounts"][0]
    p = a["points"]
    if change == "empty":
        a["points"] = []
    elif change == "duplicate":
        p[1][0] = p[0][0]
    elif change == "order":
        p.reverse()
    elif change == "NAV":
        p[1][4] = "999"
    elif change == "price":
        p[1][1] = "0"
    elif change == "negative":
        p[1][2] = "-1"
    elif change == "nan":
        p[1][4] = "NaN"
    elif change == "number_type":
        p[1][4] = 90
    elif change == "timestamp":
        p[1][0] = "2020-01-02T00:00:00-03:00"
    elif change == "endpoint":
        a["end"] = a["start"]
    elif change == "benchmark":
        a["benchmark"] = "MISSING"
    elif change == "cost":
        a["cost_scenario"] = "OTHER"
    elif change == "market":
        p[1][1] = "8"
        p[1][4] = "80"
    elif change == "units":
        p[0].append("extra")
    with pytest.raises(ValueError, match=r".+"):
        validate_results(manifest, data)


@given(st.lists(st.integers(min_value=0, max_value=100000), min_size=1, max_size=60))
@settings(max_examples=60, deadline=None)
def test_drawdown_quadratic_oracle(values: list[int]) -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    points = [
        [(start + timedelta(days=i)).isoformat(), "1", str(v), "0", str(v)]
        for i, v in enumerate(values)
    ]
    actual = episodes(points, 86400)
    positive = any(values)
    if len(values) < 2 or not positive:
        assert actual["max_drawdown"] is None
    else:
        expected = max(
            [Fraction(0)]
            + [
                1 - Fraction(value, prior)
                for i, value in enumerate(values)
                for prior in values[: i + 1]
                if prior > 0
            ]
        )
        assert Fraction(actual["max_drawdown_fraction"]) == expected


@pytest.mark.parametrize(
    ("values", "violation"),
    [
        ([100, 80, 100], False),
        ([1000000, 799999, 1000000], True),
        ([100, 0, 100], True),
        ([100, 100, 100], False),
    ],
)
def test_risk_boundary_recovery_and_total_loss(values: list[int], violation: bool) -> None:
    points = [
        [f"2020-01-0{i + 1}T00:00:00+00:00", "1", str(v), "0", str(v)] for i, v in enumerate(values)
    ]
    result = episodes(points, 86400)
    assert result["violates_20_percent"] is violation
    for episode in result["episodes"]:
        assert episode["recovery_at"] == points[-1][0]
        assert episode["observed_seconds"] == 172800


def test_gap_censors_and_never_claims_complete_risk() -> None:
    points = [
        ["2020-01-01T00:00:00+00:00", "1", "100", "0", "100"],
        ["2020-01-02T00:00:00+00:00", "1", "80", "0", "80"],
        ["2020-01-04T00:00:00+00:00", "1", "100", "0", "100"],
    ]
    risk = episodes(points, 86400)
    assert risk["episodes"][0]["reason"] == "GAP_CENSORED"
    assert risk["episodes"][0]["recovery_at"] is None
    assert risk["risk_complete"] is False
    assert risk["gaps"]


def test_zero_and_single_observation_are_not_divided_by_zero() -> None:
    _, data = sample()
    a = data["accounts"][0]
    a["points"] = [[a["start"], "1", "0", "0", "0"]]
    m = metrics(a, 86400)
    assert m["return_ratio"] is m["exposure_final"] is None
    assert m["risk"]["status"] == "INSUFFICIENT_RISK_EVIDENCE"


def test_pareto_uses_exact_values_not_display_rounding() -> None:
    a = Fraction(1)
    b = a + Fraction(1, 10**70)
    rows = [
        {"account_id": name, "group_id": "same", "metrics": {"exact": {"nav_final": str(v)}}}
        for name, v in [("A", a), ("B", b)]
    ]
    assert pareto(rows, ["nav_final"]) == ["B"]
    rows[1]["group_id"] = "different"
    assert pareto(rows, ["nav_final"]) == ["A", "B"]


def test_decimal_context_and_export_rights_and_replay() -> None:
    raw = bundled()["favorable"]
    pack = read_pack(raw)
    expected = analyze(pack)
    with localcontext() as context:
        context.prec = 3
        assert analyze(pack) == expected
    manifest, data = sample()
    manifest["redistribution"] = "RESTRICTED"
    restricted = read_pack(write_pack(manifest, data))
    with pytest.raises(ValueError, match="bloqueado"):
        export_analysis(restricted)
    manifest["redistribution"] = "AGGREGATES_ONLY"
    aggregate = read_pack(write_pack(manifest, data))
    with pytest.raises(ValueError, match="Revisão"):
        export_analysis(aggregate)
    with zipfile.ZipFile(io.BytesIO(export_analysis(aggregate, reviewed=True))) as archive:
        assert "source.gbpack" not in archive.namelist()
        projected = json.loads(archive.read("metrics.json"))
        assert all(
            "risk" not in row["metrics"] and "points" not in row for row in projected["rows"]
        )
    m = analysis_manifest(pack)
    m["expected_result_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="equivalente"):
        replay(pack, m)


@pytest.mark.parametrize("value", ["=cmd()", "+1", "-1", "@SUM", "  =cmd()"])
def test_csv_injection(value: str) -> None:
    assert safe_cell(value).startswith("'")


def test_explicit_persistence_restart_tamper_and_remove(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    library = Library(root)
    manifest, data = sample()
    manifest["pack_id"] = "local_copy"
    raw = write_pack(manifest, data)
    preview = library.preview(raw)
    assert not list(root.glob("*.gbpack"))
    with pytest.raises(ValueError, match=r".+"):
        library.confirm(preview["preview_token"], False)
    study = library.confirm(preview["preview_token"], True)
    restarted = Library(root)
    assert restarted.get(study["id"]).raw == raw
    first = restarted.analysis(study["id"])
    first["rows"].clear()
    assert restarted.analysis(study["id"])["rows"]
    path = root / (study["id"] + ".gbpack")
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match=r".+"):
        restarted.analysis(study["id"])
    assert any(r["source_kind"] == "DATA_INVALID" for r in restarted.catalog()["studies"])
    restarted.remove(study["id"], True)
    assert not path.exists()


def test_disabled_persistence_and_existing_directory_refusal(tmp_path: Path) -> None:
    library = Library()
    preview = library.preview(bundled()["favorable"])
    with pytest.raises(ValueError, match="desativada"):
        library.confirm(preview["preview_token"], True)
    (tmp_path / "unrelated.txt").write_text("do not touch")
    with pytest.raises(ValueError, match="vazia"):
        Library(tmp_path)
    assert (tmp_path / "unrelated.txt").read_text() == "do not touch"


def test_bounded_seeded_zip_fuzz() -> None:
    rng = random.Random(4001)  # noqa: S311 - deterministic parser fixtures
    seed = bundled()["favorable"]
    for _ in range(80):
        raw = bytearray(seed)
        for _ in range(3):
            raw[rng.randrange(len(raw))] = rng.randrange(256)
        try:
            pack = read_pack(bytes(raw))
        except ValueError:
            continue
        assert analyze(pack)["source_kind"] == "SYNTHETIC_DEMO"
