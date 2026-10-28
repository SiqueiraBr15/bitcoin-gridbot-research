"""G4.1 adversarial contracts; inputs and failures stay in disposable fixtures."""

from __future__ import annotations

import io
import json
import os
import stat
import struct
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from research_console.lab import http
from research_console.lab import library as library_module
from research_console.lab.analytics import analyze, episodes, pareto
from research_console.lab.exports import export_analysis
from research_console.lab.fixtures import bundled
from research_console.lab.library import Library
from research_console.lab.packs import canonical, read_pack, write_pack
from research_console.lab.storage import no_links, writer_lock


def local_raw(label: str = "external") -> bytes:
    pack = read_pack(bundled()["risk_violation"])
    manifest = deepcopy(pack.manifest)
    manifest["pack_id"] = label
    return write_pack(manifest, pack.results)


def forged_stream(kind: str) -> bytes:
    """Construct independent local/central ZIP headers which lie about inflation."""
    pack = read_pack(bundled()["favorable"])
    local, central = bytearray(), bytearray()
    for name, data in [
        (b"manifest.json", canonical(pack.manifest)),
        (b"results.json", canonical(pack.results)),
    ]:
        inflated = data
        if name == b"results.json" and kind in ("underreported", "bomb"):
            inflated += b"UNMANIFESTED_SYNTHETIC_ONLY" * 2000
            if kind == "bomb":
                inflated += b"x" * (8 * 1024 * 1024)
        compressor = zlib.compressobj(wbits=-15)
        payload = compressor.compress(inflated) + compressor.flush()
        if name == b"results.json" and kind == "trailing":
            payload += b"UNMANIFESTED_SYNTHETIC_ONLY"
        crc = zlib.crc32(data)
        offset = len(local)
        local.extend(
            struct.pack(
                "<4s5H3I2H",
                b"PK\x03\x04",
                20,
                0,
                8,
                0,
                0,
                crc,
                len(payload),
                len(data),
                len(name),
                0,
            )
        )
        local.extend(name + payload)
        central.extend(
            struct.pack(
                "<4s6H3I5H2I",
                b"PK\x01\x02",
                788,
                20,
                0,
                8,
                0,
                0,
                crc,
                len(payload),
                len(data),
                len(name),
                0,
                0,
                0,
                0,
                (stat.S_IFREG | 0o600) << 16,
                offset,
            )
        )
        central.extend(name)
    footer = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 2, 2, len(central), len(local), 0)
    return bytes(local + central + footer)


@pytest.mark.parametrize("kind", ["underreported", "trailing", "bomb"])
def test_actual_inflated_bytes_not_only_zip_declared_size(kind: str) -> None:
    # zipfile alone returns the plausible prefix; the evidence reader must reject it.
    raw = forged_stream(kind)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read("results.json"))["accounts"]
    with pytest.raises(ValueError, match=r".+"):
        read_pack(raw)


def test_self_declared_public_pack_does_not_authorize_export() -> None:
    pack = read_pack(local_raw())
    assert pack.manifest["source_kind"] == "SYNTHETIC_DEMO"
    assert pack.manifest["redistribution"] == "PUBLIC"
    with pytest.raises(ValueError, match="autoriza"):
        export_analysis(pack)


def imported(library: Library, raw: bytes) -> dict[str, Any]:
    preview = library.preview(raw)
    return library.confirm(preview["preview_token"], True)


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "NUL.txt",
        "results.json:ads",
        "results.json.",
        "RESULTS.JSON",
        "\uff4danifest.json",
        "\\\\host\\results.json",
    ],
)
def test_windows_container_aliases_never_become_paths(name: str) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr(name, b"{}")
    with pytest.raises(ValueError, match=r".+"):
        read_pack(stream.getvalue())


def test_zip_entry_order_changes_identity_not_math() -> None:
    original = read_pack(bundled()["favorable"])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("results.json", canonical(original.results))
        archive.writestr("manifest.json", canonical(original.manifest))
    reordered = read_pack(stream.getvalue())
    assert original.sha256 != reordered.sha256
    assert [r["metrics"] for r in analyze(original)["rows"]] == [
        r["metrics"] for r in analyze(reordered)["rows"]
    ]


@pytest.mark.parametrize("stage", ["write", "flush", "fsync", "replace"])
def test_failed_commit_preserves_existing_study_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    library = Library(tmp_path / "owned")
    first = imported(library, local_raw("first"))
    preview = library.preview(local_raw("second"))
    prior = library.get(first["id"]).raw
    before = {p.name: p.read_bytes() for p in library.owned_paths()}
    with monkeypatch.context() as patch:
        if stage in ("fsync", "replace"):

            def fail(*args: Any) -> None:
                raise OSError(28, "SYNTHETIC disk full")

            patch.setattr(os, stage, fail)
        else:
            original_open = Path.open

            class BrokenWrite:
                def __init__(self, stream: Any) -> None:
                    self.stream = stream

                def __enter__(self) -> BrokenWrite:
                    return self

                def __exit__(self, *args: Any) -> None:
                    self.stream.close()

                def write(self, raw: bytes) -> None:
                    self.stream.write(raw[:17])
                    if stage == "write":
                        raise OSError(28, "SYNTHETIC partial write")

                def flush(self) -> None:
                    raise OSError(5, "SYNTHETIC flush failure")

            def opening(path: Path, *args: Any, **kwargs: Any) -> Any:
                stream = original_open(path, *args, **kwargs)
                return BrokenWrite(stream) if path.name.startswith(".pending-") else stream

            patch.setattr(Path, "open", opening)
        with pytest.raises(OSError, match="SYNTHETIC"):
            library.confirm(preview["preview_token"], True)
    assert {p.name: p.read_bytes() for p in library.owned_paths()} == before
    assert not list((tmp_path / "owned").glob(".pending-*"))
    assert Library(tmp_path / "owned").get(first["id"]).raw == prior
    study = library.confirm(preview["preview_token"], True)
    assert library.get(study["id"]).raw == local_raw("second")


def test_multiple_instances_cannot_race_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "owned"
    a, b = Library(root), Library(root)
    previews = [a.preview(local_raw("a")), b.preview(local_raw("b"))]
    monkeypatch.setattr(library_module, "MAX_PACKS", 1)
    original_replace = os.replace

    def slower(*args: Any) -> None:
        time.sleep(0.04)
        original_replace(*args)

    monkeypatch.setattr(os, "replace", slower)
    barrier = threading.Barrier(2)

    def confirm(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            [a, b][index].confirm(previews[index]["preview_token"], True)
            return "COMMITTED"
        except ValueError:
            return "REJECTED_RETRY_OR_QUOTA"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(confirm, range(2)))
    assert outcomes.count("COMMITTED") == 1
    assert len(Library(root).owned_paths()) == 1


def test_lock_excludes_other_process_and_releases_after_crash(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    Library(root)
    code = (
        "from pathlib import Path; from research_console.lab.storage import writer_lock; "
        "import sys,time; "
        "\nwith writer_lock(Path(sys.argv[1])):\n print('LOCKED',flush=True); time.sleep(10)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "LOCKED"
        with pytest.raises(ValueError, match="ocupada"), writer_lock(root):
            pytest.fail("concurrent process acquired exclusive lock")
    finally:
        process.kill()
        process.communicate(timeout=5)
    with writer_lock(root):
        assert root.is_dir()


def test_abrupt_partial_import_never_appears_as_valid(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    Library(root)
    orphan = root / ".pending-SYNTHETIC_CRASH_ONLY"
    orphan.write_bytes(local_raw()[:17])
    restarted = Library(root)
    assert len(restarted.catalog()["studies"]) == 3
    assert orphan.read_bytes() == local_raw()[:17]


def test_real_process_exit_after_partial_write_and_safe_retry(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    library = Library(root)
    previous = imported(library, local_raw("before_crash"))
    source = tmp_path / "input.gbpack"
    raw = local_raw("crashed")
    source.write_bytes(raw)
    code = """
import os,sys
from pathlib import Path
from research_console.lab.library import Library
library=Library(Path(sys.argv[1]))
preview=library.preview(Path(sys.argv[2]).read_bytes())
original=Path.open
class Interrupted:
    def __init__(self,stream):self.stream=stream
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def write(self,raw):
        self.stream.write(raw[:17]);self.stream.flush();os._exit(17)
def opening(path,*args,**kwargs):
    stream=original(path,*args,**kwargs)
    return Interrupted(stream) if path.name.startswith('.pending-') else stream
Path.open=opening
library.confirm(preview['preview_token'],True)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(root), str(source)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    restarted = Library(root)
    assert len(restarted.owned_paths()) == 1
    assert restarted.get(previous["id"]).raw == local_raw("before_crash")
    assert len(list(root.glob(".pending-*"))) == 1
    assert imported(restarted, raw)["integrity"] == "VALIDATED"
    assert len(restarted.owned_paths()) == 2
    assert source.read_bytes() == raw


def test_catalog_during_staging_sees_only_committed_complete_studies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "owned"
    writer, reader = Library(root), Library(root)
    original = os.replace
    staged, release = threading.Event(), threading.Event()

    def pause(*args: Any) -> None:
        staged.set()
        assert release.wait(timeout=5)
        original(*args)

    monkeypatch.setattr(os, "replace", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(imported, writer, local_raw())
        try:
            assert staged.wait(timeout=5)
            assert len(reader.catalog()["studies"]) == 3
        finally:
            release.set()
        study = future.result(timeout=5)
    assert reader.get(study["id"]).raw == local_raw()


def test_double_confirmation_commits_exactly_one_copy(tmp_path: Path) -> None:
    library = Library(tmp_path / "owned")
    preview = library.preview(local_raw())
    barrier = threading.Barrier(2)

    def confirm(_: int) -> str:
        barrier.wait(timeout=5)
        try:
            library.confirm(preview["preview_token"], True)
            return "COMMITTED"
        except ValueError:
            return "TOKEN_CONSUMED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, range(2))) == ["COMMITTED", "TOKEN_CONSUMED"]
    assert len(library.owned_paths()) == 1


def test_writer_lock_rejects_hardlink_without_modifying_other_file(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    Library(root)
    outside = tmp_path / "outside-empty.txt"
    outside.write_bytes(b"")
    link = root / ".gridbot-writer-lock-v1"
    os.link(outside, link)
    with pytest.raises(ValueError, match="Lock local inválido"), writer_lock(root):
        pytest.fail("hardlink acquired")
    assert outside.read_bytes() == b""


def test_unconfirmed_import_has_no_persistent_side_effect(tmp_path: Path) -> None:
    library = Library(tmp_path / "owned")
    before = {p.name: p.read_bytes() for p in (tmp_path / "owned").iterdir()}
    preview = library.preview(local_raw())
    with pytest.raises(ValueError, match="Confirmação"):
        library.confirm(preview["preview_token"], False)
    assert {p.name: p.read_bytes() for p in (tmp_path / "owned").iterdir()} == before


@pytest.mark.parametrize("name", ["NUL", "con.txt", "LPT9", "data:ads", "trailing.", "trail "])
def test_nonportable_operator_paths_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="portátil"):
        no_links(tmp_path / name)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_real_windows_junction_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("SYNTHETIC untouched")
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
        timeout=5,
    )
    try:
        with pytest.raises(ValueError, match="reparse"):
            Library(junction / "owned")
        assert sentinel.read_text() == "SYNTHETIC untouched"
    finally:
        junction.rmdir()


@pytest.mark.parametrize("rights", ["PUBLIC", "AGGREGATES_ONLY", "RESTRICTED"])
def test_independent_export_consent_all_formats_and_restart(tmp_path: Path, rights: str) -> None:
    original = read_pack(local_raw())
    manifest = deepcopy(original.manifest)
    manifest["redistribution"] = rights
    library = Library(tmp_path / "owned")
    study = imported(library, write_pack(manifest, original.results))
    identity = study["id"]
    assert study["export_scope"] is None
    for route in ("source", "export"):
        with pytest.raises(ValueError, match=r".+"):
            http.get(
                library,
                "/api/lab/" + route,
                {"id": [identity], **({"reviewed": ["1"]} if route == "export" else {})},
            )
    with pytest.raises(ValueError, match="Confirmação"):
        library.authorize_export(identity, "DERIVED_ONLY", "OWN_DATA", False)
    if rights == "RESTRICTED":
        with pytest.raises(ValueError, match="bloqueado"):
            library.authorize_export(identity, "DERIVED_ONLY", "OWN_DATA", True)
        return
    library.authorize_export(identity, "DERIVED_ONLY", "OWN_DATA", True)
    raw = http.get(library, "/api/lab/export", {"id": [identity], "reviewed": ["1"]})[0]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "source.gbpack" not in archive.namelist()
        projection = json.loads(archive.read("metrics.json"))
        assert all("risk" not in r["metrics"] for r in projection["rows"])
        assert all(b'"points"' not in archive.read(n) for n in archive.namelist())
    with pytest.raises(ValueError, match=r".+"):
        http.get(library, "/api/lab/source", {"id": [identity]})
    assert Library(tmp_path / "owned").get(identity).raw == library.get(identity).raw
    assert Library(tmp_path / "owned").export_scope(library.get(identity)) is None
    if rights == "PUBLIC":
        library.authorize_export(identity, "RAW_AND_DERIVED", "RIGHTSHOLDER_PERMISSION", True)
        assert (
            http.get(library, "/api/lab/source", {"id": [identity]})[0] == library.get(identity).raw
        )


@given(st.lists(st.integers(1, 200), min_size=2, max_size=14), st.integers(1, 20))
@settings(max_examples=50, deadline=None)
def test_risk_scale_metamorphism_and_quadratic_oracle(values: list[int], scale: int) -> None:
    from datetime import UTC, datetime, timedelta

    def points(multiplier: int) -> list[list[str]]:
        return [
            [
                (datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i)).isoformat(),
                "1",
                str(v * multiplier),
                "0",
                str(v * multiplier),
            ]
            for i, v in enumerate(values)
        ]

    expected = max(
        Fraction(values[i] - values[j], values[i])
        for i in range(len(values))
        for j in range(i, len(values))
    )
    a, b = episodes(points(1), 86400), episodes(points(scale), 86400)
    assert Fraction(a["max_drawdown_fraction"]) == expected == Fraction(b["max_drawdown_fraction"])
    assert a["drawdowns"] == b["drawdowns"]
    assert [(r["peak_index"], r["trough_index"], r["end_index"]) for r in a["episodes"]] == [
        (r["peak_index"], r["trough_index"], r["end_index"]) for r in b["episodes"]
    ]


@given(
    st.lists(
        st.tuples(st.integers(-20, 20), st.integers(-20, 20), st.integers(0, 100)),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=50, deadline=None)
def test_pareto_orientation_and_permutation(values: list[tuple[int, int, int]]) -> None:
    rows: list[dict[str, Any]] = [
        {
            "account_id": str(i),
            "group_id": "same",
            "metrics": {
                "exact": {
                    "nav_final": str(a),
                    "btc_physical": str(b),
                    "max_drawdown": str(Fraction(c, 100)),
                }
            },
        }
        for i, (a, b, c) in enumerate(values)
    ]
    for objectives in [
        ["nav_final", "max_drawdown"],
        ["nav_final", "btc_physical", "max_drawdown"],
    ]:
        signs = {"nav_final": 1, "btc_physical": 1, "max_drawdown": -1}
        expected = []
        for row in rows:
            a = row["metrics"]["exact"]
            others = [r["metrics"]["exact"] for r in rows if r is not row]
            if not any(
                all(signs[k] * Fraction(b[k]) >= signs[k] * Fraction(a[k]) for k in objectives)
                and any(signs[k] * Fraction(b[k]) > signs[k] * Fraction(a[k]) for k in objectives)
                for b in others
            ):
                expected.append(row["account_id"])
        assert (
            pareto(rows, objectives) == sorted(expected) == pareto(list(reversed(rows)), objectives)
        )


def test_account_order_and_self_comparison_are_not_economic_changes() -> None:
    pack = read_pack(bundled()["favorable"])
    data = deepcopy(pack.results)
    data["accounts"].reverse()
    reordered = read_pack(write_pack(pack.manifest, data))
    a, b = analyze(pack), analyze(reordered)
    for left, right in zip(a["rows"], b["rows"], strict=True):
        assert left["metrics"] == right["metrics"]
    assert a["pareto"] == b["pareto"]
    cash = next(r for r in a["rows"] if r["account_id"] == "CASH")
    assert cash["benchmark_comparison"]["delta_nav"] == "0"
    assert cash["benchmark_comparison"]["delta_btc"] == "0"
