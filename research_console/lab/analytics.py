"""Exact descriptive analysis of validated observations, never a strategy runner."""

from __future__ import annotations

from fractions import Fraction
from itertools import pairwise
from typing import Any

from research_console.data import timestamp
from research_console.lab import ANALYTICS_VERSION
from research_console.lab.packs import Pack, canonical, digest
from research_console.risk import LIMIT, display, require, seconds

OBJECTIVES = {"nav_final": 1, "btc_physical": 1, "max_drawdown": -1, "fees_usdt": -1}


def ratio(numerator: Fraction, denominator: Fraction) -> str | None:
    return display(numerator / denominator) if denominator else None


def episodes(points: list[list[str]], cadence: int) -> dict[str, Any]:
    """Censor at gaps, restart high-water reference; never interpolate missing marks."""
    high = Fraction(points[0][4])
    peak = trough = 0
    first_below: int | None = None
    gaps = []
    result: list[dict[str, Any]] = []
    maximum = Fraction(0)
    drawdowns: list[str | None] = []

    def close(end: int, recovered: bool, reason: str) -> None:
        if first_below is None:
            return
        magnitude = 1 - Fraction(points[trough][4]) / high
        result.append(
            {
                "peak_index": peak,
                "first_below_index": first_below,
                "trough_index": trough,
                "end_index": end,
                "peak_at": points[peak][0],
                "trough_at": points[trough][0],
                "first_below_at": points[first_below][0],
                "recovery_at": points[end][0] if recovered else None,
                "observed_end": points[end][0],
                "censored": not recovered,
                "reason": reason,
                "magnitude": display(magnitude),
                "magnitude_fraction": str(magnitude),
                "exceeds_20_percent": magnitude > LIMIT,
                "observed_seconds": seconds(timestamp(points[peak][0]), timestamp(points[end][0])),
                "peak_nav": points[peak][4],
                "trough_nav": points[trough][4],
            }
        )

    for i, point in enumerate(points):
        value = Fraction(point[4])
        if i and seconds(timestamp(points[i - 1][0]), timestamp(point[0])) != cadence:
            close(i - 1, False, "GAP_CENSORED")
            gaps.append({"before": points[i - 1][0], "after": point[0]})
            high, peak, trough, first_below = value, i, i, None
        if value >= high:
            close(i, True, "RECOVERED_AT_OBSERVED_MARK")
            high, peak, trough, first_below = value, i, i, None
        else:
            if first_below is None:
                first_below, trough = i, i
            if value < Fraction(points[trough][4]):
                trough = i
        dd = 1 - value / high if high else None
        if dd is not None:
            maximum = max(maximum, dd)
        drawdowns.append(display(-dd) if dd is not None else None)
    close(len(points) - 1, False, "END_OF_OBSERVATIONS")
    sufficient = len(points) >= 2 and any(Fraction(p[4]) > 0 for p in points)
    return {
        "status": "OBSERVED_SEGMENTS_ONLY" if sufficient else "INSUFFICIENT_RISK_EVIDENCE",
        "max_drawdown": display(maximum) if sufficient else None,
        "max_drawdown_fraction": str(maximum) if sufficient else None,
        "distance_to_20_pp": display(100 * (LIMIT - maximum)) if sufficient else None,
        "violates_20_percent": maximum > LIMIT if sufficient else None,
        "episodes": result,
        "drawdowns": drawdowns,
        "gaps": gaps,
        "risk_complete": sufficient and not gaps,
        "sampling_seconds": cadence,
        "definition": "G4_SEGMENTED_HIGH_WATER_V1",
    }


def comparable_key(account: dict[str, Any], source: str) -> str:
    return digest(
        canonical(
            {
                "source": source,
                "window": account["window_id"],
                "cost": account["cost_scenario"],
                "initial_nav": str(Fraction(account["initial_nav"])),
                "start": account["start"],
                "end": account["end"],
                "market": [(p[0], str(Fraction(p[1]))) for p in account["points"]],
            }
        )
    )


def metrics(account: dict[str, Any], cadence: int) -> dict[str, Any]:
    points = account["points"]
    first, last = points[0], points[-1]
    initial, final, price, cash, btc = (
        Fraction(v) for v in (first[4], last[4], last[1], last[2], last[3])
    )
    risk = episodes(points, cadence)
    elapsed = seconds(timestamp(first[0]), timestamp(last[0]))
    exposure_time, observed_time, underwater = Fraction(0), 0, 0
    exposure_known = True
    returns = []
    for i, (left, right) in enumerate(pairwise(points)):
        dt = seconds(timestamp(left[0]), timestamp(right[0]))
        if dt != cadence:
            continue
        observed_time += dt
        nav = Fraction(left[4])
        if nav:
            exposure_time += Fraction(left[3]) * Fraction(left[1]) / nav * dt
            returns.append(Fraction(right[4]) / nav - 1)
        else:
            exposure_known = False
        if risk["drawdowns"][i] is not None and Fraction(risk["drawdowns"][i]) < 0:
            underwater += dt
    return {
        "exact": {
            "nav_initial": str(initial),
            "nav_final": str(final),
            "btc_physical": str(btc),
            "btc_equivalent": str(final / price),
            "fees_usdt": str(Fraction(account["fees_usdt"])),
            "return_ratio": str((final - initial) / initial) if initial else None,
            "max_drawdown": risk["max_drawdown_fraction"] if risk["risk_complete"] else None,
        },
        "nav_initial": display(initial),
        "nav_final": display(final),
        "return_usdt": display(final - initial),
        "return_ratio": ratio(final - initial, initial),
        "btc_physical": display(btc),
        "btc_equivalent": display(final / price),
        "cash_usdt": display(cash),
        "fees_usdt": account["fees_usdt"],
        "btc_change": display(btc - Fraction(first[3])),
        "exposure_mean_left": ratio(exposure_time, Fraction(observed_time))
        if exposure_known
        else None,
        "exposure_final": ratio(btc * price, final),
        "annualized_return": None,
        "annualized_reason": "NO_COMPOUNDING_OR_EXTERNAL_FLOW_CONVENTION_IN_V1",
        "observed_seconds": elapsed,
        "sampled_seconds": observed_time,
        "underwater_seconds_left": underwater,
        "valid_sample_returns": len(returns),
        "sample_loss_count": sum(r < 0 for r in returns),
        "risk": risk,
    }


def pareto(rows: list[dict[str, Any]], objectives: list[str]) -> list[str]:
    require(
        1 <= len(objectives) <= len(OBJECTIVES)
        and len(set(objectives)) == len(objectives)
        and set(objectives) <= set(OBJECTIVES),
        "Objetivos inválidos",
    )
    eligible = [
        r for r in rows if all(r["metrics"]["exact"].get(k) is not None for k in objectives)
    ]
    result = []
    for row in eligible:
        dominated = False
        for other in eligible:
            if other["group_id"] != row["group_id"] or other is row:
                continue
            differences = [
                OBJECTIVES[k]
                * (Fraction(other["metrics"]["exact"][k]) - Fraction(row["metrics"]["exact"][k]))
                for k in objectives
            ]
            if all(d >= 0 for d in differences) and any(d > 0 for d in differences):
                dominated = True
                break
        if not dominated:
            result.append(row["account_id"])
    return sorted(result)


def analyze(
    pack: Pack, selected: list[str] | None = None, objectives: list[str] | None = None
) -> dict[str, Any]:
    manifest = pack.manifest
    objectives = (
        objectives if objectives is not None else ["nav_final", "btc_physical", "max_drawdown"]
    )
    require(
        1 <= len(objectives) <= 4
        and len(set(objectives)) == len(objectives)
        and set(objectives) <= set(OBJECTIVES),
        "Objetivos inválidos",
    )
    accounts = pack.results["accounts"]
    available = {a["account_id"] for a in accounts}
    require(
        selected is None
        or (bool(selected) and len(set(selected)) == len(selected) and set(selected) <= available),
        "Seleção inválida",
    )
    chosen = sorted(available if selected is None else selected)
    rows = []
    for account in sorted(accounts, key=lambda a: a["account_id"]):
        if account["account_id"] not in chosen:
            continue
        result = metrics(account, manifest["sampling_seconds"])
        result["max_drawdown"] = (
            result["risk"]["max_drawdown"] if result["risk"]["risk_complete"] else None
        )
        rows.append(
            {
                "account_id": account["account_id"],
                "policy": account["policy"],
                "window_id": account["window_id"],
                "cost_scenario": account["cost_scenario"],
                "start": account["start"],
                "end": account["end"],
                "benchmark": account["benchmark"],
                "group_id": comparable_key(account, manifest["source_kind"]),
                "metrics": result,
                "evidence": {
                    "file": "results.json",
                    "sha256": manifest["files"]["results.json"]["sha256"],
                    "account_id": account["account_id"],
                    "final_point_index": len(account["points"]) - 1,
                    "timestamp": account["points"][-1][0],
                    "units": manifest["units"],
                },
            }
        )
    by_id = {r["account_id"]: r for r in rows}
    for row in rows:
        reference = by_id.get(row["benchmark"])
        row["benchmark_comparison"] = {"status": "NOT_SELECTED_OR_UNDECLARED"}
        if reference:
            require(row["group_id"] == reference["group_id"], "Benchmark incompatível")
            a, b = row["metrics"]["exact"], reference["metrics"]["exact"]
            row["benchmark_comparison"] = {
                "status": "COMPARABLE",
                "reference": reference["account_id"],
                "delta_nav": display(Fraction(a["nav_final"]) - Fraction(b["nav_final"])),
                "delta_btc": display(Fraction(a["btc_physical"]) - Fraction(b["btc_physical"])),
                "relative_nav": ratio(
                    Fraction(a["nav_final"]) - Fraction(b["nav_final"]), Fraction(b["nav_final"])
                ),
                "relative_btc": ratio(
                    Fraction(a["btc_physical"]) - Fraction(b["btc_physical"]),
                    Fraction(b["btc_physical"]),
                ),
            }
    descriptive = []
    for policy, cost, duration, initial in sorted(
        {
            (
                r["policy"],
                r["cost_scenario"],
                r["metrics"]["observed_seconds"],
                r["metrics"]["exact"]["nav_initial"],
            )
            for r in rows
        }
    ):
        group = [
            r
            for r in rows
            if (
                r["policy"],
                r["cost_scenario"],
                r["metrics"]["observed_seconds"],
                r["metrics"]["exact"]["nav_initial"],
            )
            == (policy, cost, duration, initial)
        ]
        values = [
            Fraction(r["metrics"]["exact"]["return_ratio"])
            for r in group
            if r["metrics"]["exact"]["return_ratio"] is not None
        ]
        valid_risk = [r for r in group if r["metrics"]["risk"]["risk_complete"]]
        overlap = any(
            timestamp(a["start"]) < timestamp(b["end"])
            and timestamp(b["start"]) < timestamp(a["end"])
            for i, a in enumerate(group)
            for b in group[i + 1 :]
        )
        descriptive.append(
            {
                "policy": policy,
                "cost_scenario": cost,
                "duration_seconds": duration,
                "initial_nav": initial,
                "windows": len(group),
                "defined_returns": len(values),
                "losses": sum(v < 0 for v in values),
                "return_min": display(min(values)) if values else None,
                "return_max": display(max(values)) if values else None,
                "complete_risk_windows": len(valid_risk),
                "violations": sum(r["metrics"]["risk"]["violates_20_percent"] for r in valid_risk),
                "overlapping": overlap,
                "inference": "DESCRIPTIVE_DEPENDENT_WINDOWS_NO_CONFIDENCE_INTERVAL",
            }
        )
    return {
        "analytics_version": ANALYTICS_VERSION,
        "pack_sha256": pack.sha256,
        "manifest_sha256": pack.manifest_sha256,
        "source_kind": manifest["source_kind"],
        "data_nature": manifest["data_nature"],
        "integrity": "SHA256_AND_CONSERVATION_VALIDATED",
        "provenance": "DECLARED_NOT_AUTHENTICATED",
        "status": "AGGREGATE_ONLY_NO_CURVES" if not accounts else "VALIDATED_OBSERVATIONS",
        "rows": rows,
        "pareto": {
            "objectives": objectives,
            "non_dominated": pareto(rows, objectives),
            "meaning": "WITHIN_COMPARABLE_GROUPS_NOT_GLOBAL_WINNER",
        },
        "descriptive": descriptive,
        "aggregates": pack.results["aggregates"],
        "limitations": manifest["limitations"],
        "redistribution": manifest["redistribution"],
    }
