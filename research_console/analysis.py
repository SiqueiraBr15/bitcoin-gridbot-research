"""Exact presentation analysis of admitted results; never simulate decisions."""

from __future__ import annotations

import csv
import io
from fractions import Fraction
from typing import Any

from research_console.data import NUMBER, POLICIES, timestamp
from research_console.risk import LIMIT, display, require

SCHEMA = "GRIDBOT_RESEARCH_SELECTION_V3"
UNITS = {
    "nav_usdt": "USDT",
    "return": "ratio",
    "return_pp": "pp",
    "btc_physical": "BTC",
    "btc_equivalent": "BTC",
    "cash_usdt": "USDT",
    "fees_usdt": "USDT",
    "max_drawdown": "ratio",
    "exposure_mean": "ratio",
}


def compare(accounts: list[dict[str, Any]], reference: str) -> dict[str, Any]:
    require(bool(accounts), "Comparação indisponível")
    summaries = [a["summary"] for a in accounts]
    refs = [r for r in summaries if r["policy"] == reference]
    require(len(refs) == 1, "Referência indisponível")
    ref = refs[0]
    require(len({r["policy"] for r in summaries}) == len(summaries), "Política duplicada")
    rows = []
    for row in summaries:
        require(
            all(row[k] == ref[k] for k in ("start", "end", "cost", "months")),
            "Comparação temporal incompatível",
        )
        require(
            all(Fraction(row[k]) == Fraction(ref[k]) for k in ("initial_usdt", "final_mark")),
            "Comparação patrimonial incompatível",
        )
        nav_delta = Fraction(row["nav_usdt"]) - Fraction(ref["nav_usdt"])
        btc_delta = Fraction(row["btc_physical"]) - Fraction(ref["btc_physical"])
        cash_delta = Fraction(row["cash_usdt"]) - Fraction(ref["cash_usdt"])
        mark_component = btc_delta * Fraction(row["final_mark"])
        require(nav_delta == mark_component + cash_delta, "Conservação comparativa divergente")
        dd = Fraction(row["max_drawdown_fraction"])
        rows.append(
            {
                **row,
                "delta_nav_usdt": display(nav_delta),
                "delta_return_pp": display(100 * nav_delta / Fraction(row["initial_usdt"])),
                "delta_btc": display(btc_delta),
                "delta_cash_usdt": display(cash_delta),
                "btc_mark_component_usdt": display(mark_component),
                "more_btc_less_nav": btc_delta > 0 and nav_delta < 0,
                "risk_excess_pp": display(100 * max(dd - LIMIT, Fraction(0))),
            }
        )
    extrema = {}
    for metric in (
        "nav_usdt",
        "return",
        "btc_physical",
        "btc_equivalent",
        "cash_usdt",
        "max_drawdown",
        "fees_usdt",
        "exposure_mean",
    ):
        values = [Fraction(r[metric]) for r in rows]
        extrema[metric] = {
            "minimum": [r["policy"] for r, v in zip(rows, values, strict=True) if v == min(values)],
            "maximum": [r["policy"] for r, v in zip(rows, values, strict=True) if v == max(values)],
        }
    return {"reference": reference, "rows": rows, "extrema": extrema, "units": UNITS}


def frequencies(rows: list[dict[str, Any]], months: int, cost: str) -> list[dict[str, Any]]:
    selected = [r for r in rows if r["months"] == months and r["cost"] == cost]
    result = []
    for policy in sorted({r["policy"] for r in selected}):
        group = [r for r in selected if r["policy"] == policy]
        result.append(
            {
                "policy": policy,
                "observations": len(group),
                "violations": sum(r["violates_20_percent"] for r in group),
            }
        )
    return result


def distributions(rows: list[dict[str, Any]], source_kind: str) -> dict[str, Any]:
    """G2 section 8: new distributions require public admitted or synthetic data."""
    if source_kind != "SYNTHETIC_DEMO":
        return {"status": "UNAVAILABLE", "reason": "PUBLIC_AUDITED_CORPUS_NOT_DISTRIBUTED"}
    result: dict[str, Any] = {"status": "SYNTHETIC_DEMO", "observations": len(rows)}
    for metric in ("return", "max_drawdown"):
        values = [Fraction(r[metric]) for r in rows]
        if not values:
            result[metric] = {"bins": [], "positive": 0, "negative": 0, "zero": 0}
            continue
        low, high = min(values), max(values)
        width = (high - low) / 6 if low < high else Fraction(1, 100)
        bins = [0] * 6
        for value in values:
            bins[min(int((value - low) / width), 5)] += 1
        result[metric] = {
            "bins": [
                {
                    "low": display(low + i * width),
                    "high": display(low + (i + 1) * width),
                    "count": count,
                }
                for i, count in enumerate(bins)
            ],
            "positive": sum(v > 0 for v in values),
            "negative": sum(v < 0 for v in values),
            "zero": sum(v == 0 for v in values),
        }
    return result


def export_csv(payload: dict[str, Any]) -> bytes:
    """Only projected scalar fields; metadata travels with every CSV row."""
    fields = [
        "schema",
        "schema_version",
        "dataset_id",
        "focused_policy",
        "source_kind",
        "manifest_sha256",
        "start_utc",
        "end_utc",
        "cost",
        "months",
        "policy",
        "initial_usdt",
        "final_mark",
        "marks_sha256",
        "nav_usdt",
        "return_ratio",
        "btc_physical",
        "btc_equivalent",
        "cash_usdt",
        "max_drawdown_ratio",
        "fees_usdt",
        "exposure_mean_ratio",
        "reference",
        "delta_nav_usdt",
        "delta_return_pp",
        "delta_btc",
        "units",
    ]
    require(
        payload.get("source_kind") in ("ARCHIVED_RESEARCH_RESULT", "SYNTHETIC_DEMO"),
        "Export indisponível",
    )
    require(bool(payload.get("accounts")), "Export indisponível")
    require(payload.get("schema") == SCHEMA, "Export schema inválido")
    require(
        payload["provenance"]["dataset_id"] in ("M1_R_DAILY_MARKS_V1", "SYNTHETIC_PUBLIC_DEMO_V1"),
        "Export dataset inválido",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    comparison = payload.get("comparison") or {}
    require(comparison.get("reference") in (*POLICIES, None), "Export referência inválida")
    differences = {r["policy"]: r for r in comparison.get("rows", [])}
    for account in payload["accounts"]:
        row = account["summary"]
        require(row["policy"] in (*POLICIES, "round_trip", "falling_mark"), "Export inválido")
        require(row["cost"] in ("CA", "CB", "CX2", "FICTIONAL"), "Export inválido")
        require(
            type(row["months"]) is int and row["months"] in (0, 6, 12, 24),
            "Export horizonte inválido",
        )
        marks_hash = row.get("marks_sha256")
        require(
            marks_hash is None
            or (
                isinstance(marks_hash, str)
                and len(marks_hash) == 64
                and all(c in "0123456789abcdef" for c in marks_hash)
            ),
            "Export hash inválido",
        )
        timestamp(row["start"])
        timestamp(row["end"])
        for field in (
            "initial_usdt",
            "final_mark",
            "nav_usdt",
            "return",
            "btc_physical",
            "btc_equivalent",
            "cash_usdt",
            "max_drawdown",
            "fees_usdt",
            "exposure_mean",
        ):
            require(
                isinstance(row[field], str) and bool(NUMBER.fullmatch(row[field])),
                "Export numérico inválido",
            )
        delta = differences.get(row["policy"], {})
        for field in ("delta_nav_usdt", "delta_return_pp", "delta_btc"):
            require(
                field not in delta
                or (isinstance(delta[field], str) and bool(NUMBER.fullmatch(delta[field]))),
                "Export inválido",
            )
        identity = payload.get("selection", {})
        require(
            identity.get("focused_policy", row["policy"])
            in (*POLICIES, "round_trip", "falling_mark"),
            "Export foco inválido",
        )
        manifest = payload["provenance"].get("manifest_sha256")
        require(
            manifest is None
            or (
                isinstance(manifest, str)
                and len(manifest) == 64
                and all(c in "0123456789abcdef" for c in manifest)
            ),
            "Export hash inválido",
        )
        writer.writerow(
            {
                "schema": payload["schema"],
                "schema_version": 3,
                "dataset_id": payload["provenance"]["dataset_id"],
                "focused_policy": identity.get("focused_policy", row["policy"]),
                "source_kind": payload["source_kind"],
                "manifest_sha256": payload["provenance"].get("manifest_sha256", ""),
                "start_utc": row["start"],
                "end_utc": row["end"],
                "cost": row["cost"],
                "months": row["months"],
                "policy": row["policy"],
                "initial_usdt": row["initial_usdt"],
                "final_mark": row["final_mark"],
                "marks_sha256": row.get("marks_sha256", ""),
                "nav_usdt": row["nav_usdt"],
                "return_ratio": row["return"],
                "btc_physical": row["btc_physical"],
                "btc_equivalent": row["btc_equivalent"],
                "cash_usdt": row["cash_usdt"],
                "max_drawdown_ratio": row["max_drawdown"],
                "fees_usdt": row["fees_usdt"],
                "exposure_mean_ratio": row["exposure_mean"],
                "reference": comparison.get("reference", ""),
                "delta_nav_usdt": delta.get("delta_nav_usdt", ""),
                "delta_return_pp": delta.get("delta_return_pp", ""),
                "delta_btc": delta.get("delta_btc", ""),
                "units": "USDT; BTC; dimensionless ratios; pp; UTC",
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def selection_identity(
    accounts: list[dict[str, Any]],
    *,
    source: str,
    dataset: str,
    reference: str | None,
    focus: str,
    manifest: str | None = None,
) -> dict[str, Any]:
    """Portable identity shared by API and exports; no operator filesystem paths."""
    first = accounts[0]["summary"]
    require(focus in {a["summary"]["policy"] for a in accounts}, "Seleção inválida")
    return {
        "schema": SCHEMA,
        "schema_version": 3,
        "source_kind": source,
        "dataset_id": dataset,
        "manifest_sha256": manifest,
        "focused_policy": focus,
        "reference": reference,
        "policies": [a["summary"]["policy"] for a in accounts],
        "start": first["start"],
        "end": first["end"],
        "months": first["months"],
        "cost": first["cost"],
        "units": UNITS,
    }
