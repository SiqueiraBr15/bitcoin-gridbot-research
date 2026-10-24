"""Deterministic analysis manifests, replay and explicit rights-aware downloads."""

from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from research_console.lab import ANALYTICS_VERSION
from research_console.lab.analytics import analyze
from research_console.lab.packs import Pack, canonical, digest, keys
from research_console.lab.permissions import export_scope
from research_console.risk import require


def _loaded_source_hash() -> str:
    root = Path(__file__).parent
    sources = {
        name: digest((root / name).read_bytes().replace(b"\r\n", b"\n"))
        for name in ("__init__.py", "analytics.py", "packs.py", "exports.py")
    }
    sources.update(
        {
            name: digest((root.parent / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("data.py", "risk.py")
        }
    )
    return digest(canonical(sources))


_IMPLEMENTATION_SHA256 = _loaded_source_hash()


def implementation_hash() -> str:
    """Identity of code loaded at startup, never relabel old execution after file edits."""
    return _IMPLEMENTATION_SHA256


def analysis_manifest(
    pack: Pack, selected: list[str] | None = None, objectives: list[str] | None = None
) -> dict[str, Any]:
    result = analyze(pack, selected, objectives)
    return manifest_for_result(pack, result)


def manifest_for_result(pack: Pack, result: dict[str, Any]) -> dict[str, Any]:
    """Project an internally derived result; HTTP never accepts caller-supplied metrics."""
    require(
        result["pack_sha256"] == pack.sha256 and result["manifest_sha256"] == pack.manifest_sha256,
        "Identidade de análise divergente",
    )
    return {
        "schema": "GRIDBOT_ANALYSIS_V1",
        "analytics_version": ANALYTICS_VERSION,
        "implementation_sha256": implementation_hash(),
        "pack_sha256": pack.sha256,
        "manifest_sha256": pack.manifest_sha256,
        "accounts": [r["account_id"] for r in result["rows"]],
        "objectives": result["pareto"]["objectives"],
        "expected_result_sha256": digest(canonical(result)),
        "provenance": "DECLARED_NOT_AUTHENTICATED",
        "redistribution": pack.manifest["redistribution"],
    }


def replay(pack: Pack, manifest: Any) -> dict[str, Any]:
    keys(
        manifest,
        {
            "schema",
            "analytics_version",
            "implementation_sha256",
            "pack_sha256",
            "manifest_sha256",
            "accounts",
            "objectives",
            "expected_result_sha256",
            "provenance",
            "redistribution",
        },
    )
    require(
        manifest["schema"] == "GRIDBOT_ANALYSIS_V1"
        and manifest["analytics_version"] == ANALYTICS_VERSION
        and manifest["implementation_sha256"] == implementation_hash(),
        "Código analítico incompatível",
    )
    require(
        manifest["pack_sha256"] == pack.sha256
        and manifest["manifest_sha256"] == pack.manifest_sha256,
        "Dados incompatíveis",
    )
    require(
        isinstance(manifest["accounts"], list) and isinstance(manifest["objectives"], list),
        "Seleção de replay inválida",
    )
    selected = manifest["accounts"] if pack.results["accounts"] else None
    expected = analysis_manifest(pack, selected, manifest["objectives"])
    require(expected == manifest, "Replay não equivalente")
    return {
        "status": "EQUIVALENT",
        "result_sha256": expected["expected_result_sha256"],
        "strategies_executed": False,
    }


def safe_cell(value: Any) -> str:
    cell = str(value) if value is not None else "UNAVAILABLE"
    return "'" + cell if cell.lstrip().startswith(("=", "+", "-", "@")) else cell


def export_analysis(
    pack: Pack,
    selected: list[str] | None = None,
    objectives: list[str] | None = None,
    *,
    reviewed: bool = False,
    permission: str | None = None,
) -> bytes:
    rights = pack.manifest["redistribution"]
    require(rights != "RESTRICTED", "Export bloqueado pela restrição declarada")
    require(
        rights != "AGGREGATES_ONLY" or reviewed is True, "Revisão explícita de agregados exigida"
    )
    scope = export_scope(pack, permission)
    require(scope is not None, "Export sem autorização independente do operador")
    result = analyze(pack, selected, objectives)
    manifest = manifest_for_result(pack, result)
    # Selection manifest contains identities, never origin paths or source data.
    table = io.StringIO(newline="")
    writer = csv.writer(table)
    writer.writerow(
        ["account", "policy", "window", "cost", "NAV_USDT", "BTC", "DD_ratio", "fees_USDT"]
    )
    for row in result["rows"]:
        m = row["metrics"]
        writer.writerow(
            [
                safe_cell(v)
                for v in [
                    row["account_id"],
                    row["policy"],
                    row["window_id"],
                    row["cost_scenario"],
                    m["nav_final"],
                    m["btc_physical"],
                    m["max_drawdown"],
                    m["fees_usdt"],
                ]
            ]
        )
    projected = (
        result
        if scope == "RAW_AND_DERIVED"
        else {
            **{
                k: result[k]
                for k in (
                    "analytics_version",
                    "pack_sha256",
                    "source_kind",
                    "data_nature",
                    "provenance",
                    "redistribution",
                    "limitations",
                    "descriptive",
                    "aggregates",
                )
            },
            "rows": [
                {
                    "account_id": r["account_id"],
                    "policy": r["policy"],
                    "window_id": r["window_id"],
                    "cost_scenario": r["cost_scenario"],
                    "metrics": {
                        k: v for k, v in r["metrics"].items() if k not in ("risk", "exact")
                    },
                }
                for r in result["rows"]
            ],
        }
    )
    content: dict[str, bytes] = {
        "analysis-manifest.json": canonical(manifest),
        "metrics.json": canonical(projected),
        "metrics.csv": table.getvalue().encode("utf-8-sig"),
    }
    title = html.escape(pack.manifest["title"])
    content["report.html"] = (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;">'
        f"<title>GridBot análise</title><h1>{title}</h1>"
        "<p>Proveniência declarada, sem autenticação criptográfica. Sem previsão ou trading.</p>"
        "<p>Janelas dependentes: análise descritiva. Referência 20% não garante proteção.</p>"
        "<pre>" + html.escape(json.dumps(projected, ensure_ascii=False, indent=2)) + "</pre></html>"
    ).encode()
    # Never include raw source bytes when redistributing only aggregates.
    if scope == "RAW_AND_DERIVED":
        content["source.gbpack"] = pack.raw
    content["checksums.json"] = canonical(
        {
            name: {"sha256": digest(data), "bytes": len(data)}
            for name, data in sorted(content.items())
        }
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(content.items()):
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
    return stream.getvalue()
