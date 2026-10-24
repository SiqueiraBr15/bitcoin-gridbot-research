"""Read-only Fraction oracle against an explicitly authorized, pinned M1.R archive.

No historical runner, orders, candles, credentials or private package imports.
Print a bounded summary; never redistribute trajectories or write to the source.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import io
import json
import threading
from collections import Counter
from contextlib import closing
from datetime import datetime
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from research_console.data import COSTS, Archive
from research_console.server import LocalServer, Service

DATES = ("2020-01-02", "2021-12-02", "2022-12-02")
TOLERANCE = Fraction(1, 10**44)


def audit(root: Path) -> dict[str, Any]:
    archive = Archive(root)
    # Independent JSON/gzip parser and rational formulas; production projection
    # is only the subject under test, not the source of the expected metrics.
    matrices = [
        row
        for months in (6, 12, 24)
        for cost in COSTS
        for row in json.loads(
            gzip.decompress(archive.checked_raw(f"M1_RISK_MATRIX_{months}_{cost}.json.gz"))
        )["rows"]
    ]
    source = {(r["start"][:10], r["months"], r["cost"], r["policy"]): r for r in matrices}
    counts: Counter[str] = Counter()
    ui_cases = []
    chunks: dict[str, Any] = {}
    server = LocalServer(Service(archive), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path: str, cookie: str = "") -> tuple[bytes, dict[str, str]]:
        with closing(
            http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
        ) as connection:
            connection.request("GET", path, headers={"Cookie": cookie})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Oracle API request refused")
            return response.read(), dict(response.getheaders())

    def equal(actual: str, expected: Fraction) -> None:
        if abs(Fraction(actual) - expected) >= TOLERANCE:
            raise ValueError("Oracle metric mismatch")

    try:
        cookie = request("/")[1]["Set-Cookie"].split(";")[0]
        for start in DATES:
            for months in (6, 12, 24):
                for cost in COSTS:
                    reference = "B0_BH" if months == 6 else "B1_HALF"
                    query = urlencode(
                        {
                            "start": start,
                            "months": months,
                            "cost": cost,
                            "reference": reference,
                            "focus": "P_BANDS",
                        }
                    )
                    raw = request("/api/selection?" + query, cookie)[0]
                    value = json.loads(raw)
                    exported = json.loads(request("/api/export?" + query, cookie)[0])
                    if value != exported:
                        raise ValueError("JSON round trip mismatch")
                    csv_rows = list(
                        csv.DictReader(
                            io.StringIO(
                                request("/api/export.csv?" + query, cookie)[0].decode("utf-8-sig")
                            )
                        )
                    )
                    csv_by_policy = {r["policy"]: r for r in csv_rows}
                    deltas = {r["policy"]: r for r in value["comparison"]["rows"]}
                    baseline = source[(start, months, cost, reference)]
                    for account in value["accounts"]:
                        row = account["summary"]
                        original = source[(start, months, cost, row["policy"])]
                        index = next(i for i, r in enumerate(archive.rows) if r == original)
                        filename = archive.locations[index]
                        if filename not in chunks:
                            chunks[filename] = json.loads(
                                gzip.decompress(archive.checked_raw(filename))
                            )["wallets"]
                        wallet = next(
                            w
                            for w in chunks[filename]
                            if all(
                                w[k] == original[k]
                                for k in ("start", "end", "months", "cost", "policy")
                            )
                        )
                        marks = wallet["marks"]
                        digest = hashlib.sha256(
                            json.dumps(marks, separators=(",", ":")).encode()
                        ).hexdigest()
                        if digest != original["marks_sha256"] or digest != row["marks_sha256"]:
                            raise ValueError("Oracle source hash mismatch")
                        peak = Fraction(original["initial_usdt"])
                        maximum_dd = Fraction(0)
                        for mark, point in zip(marks, account["series"], strict=True):
                            stamp, price, cash, btc, nav = mark
                            p, c, b, n = map(Fraction, (price, cash, btc, nav))
                            if n != c + b * p or point["time"] != stamp:
                                raise ValueError("Oracle asset/time mismatch")
                            for key, expected in (
                                ("price", p),
                                ("cash", c),
                                ("btc", b),
                                ("nav", n),
                            ):
                                equal(point[key], expected)
                            peak = max(peak, n)
                            maximum_dd = max(maximum_dd, 1 - n / peak)
                            equal(point["drawdown"], n / peak - 1)
                            equal(point["btc_equivalent"], n / p)
                            equal(point["return"], n / Fraction(original["initial_usdt"]) - 1)
                            equal(point["exposure"], b * p / n)
                            counts["marks"] += 1
                        numerator = denominator = Fraction(0)
                        for left, right in pairwise(marks):
                            seconds = int(
                                (
                                    datetime.fromisoformat(right[0])
                                    - datetime.fromisoformat(left[0])
                                ).total_seconds()
                            )
                            numerator += Fraction(left[1]) * Fraction(left[3]) * seconds
                            denominator += Fraction(left[4]) * seconds
                        equal(row["exposure_mean"], numerator / denominator)
                        equal(account["risk"]["max_drawdown_fraction"], maximum_dd)
                        if account["risk"]["violates_20_percent"] != (maximum_dd > Fraction(1, 5)):
                            raise ValueError("Oracle risk classification mismatch")
                        csv_row = csv_by_policy[row["policy"]]
                        for key, expected_identity in (
                            ("start_utc", original["start"]),
                            ("end_utc", original["end"]),
                            ("cost", cost),
                            ("months", str(months)),
                            ("focused_policy", "P_BANDS"),
                            ("dataset_id", "M1_R_DAILY_MARKS_V1"),
                            ("manifest_sha256", archive.pin),
                            ("marks_sha256", digest),
                        ):
                            if csv_row[key] != expected_identity:
                                raise ValueError("Oracle CSV provenance mismatch")
                        equal(csv_row["initial_usdt"], Fraction(original["initial_usdt"]))
                        equal(csv_row["final_mark"], Fraction(original["final_mark"]))
                        for key in (
                            "nav_usdt",
                            "btc_physical",
                            "btc_equivalent",
                            "cash_usdt",
                            "fees_usdt",
                            "exposure_mean",
                        ):
                            equal(row[key], Fraction(original[key]))
                            equal(
                                csv_row[key if key != "exposure_mean" else "exposure_mean_ratio"],
                                Fraction(original[key]),
                            )
                        for key in ("start", "end", "cost", "months", "policy"):
                            if row[key] != original[key]:
                                raise ValueError("Oracle identity mismatch")
                        for key, source_key in (
                            ("delta_nav_usdt", "nav_usdt"),
                            ("delta_btc", "btc_physical"),
                        ):
                            expected = Fraction(original[source_key]) - Fraction(
                                baseline[source_key]
                            )
                            equal(deltas[row["policy"]][key], expected)
                            equal(csv_row[key], expected)
                        equal(
                            csv_row["delta_return_pp"],
                            100
                            * (Fraction(original["nav_usdt"]) - Fraction(baseline["nav_usdt"]))
                            / Fraction(original["initial_usdt"]),
                        )
                        equal(csv_row["return_ratio"], Fraction(original["return"]))
                        equal(csv_row["max_drawdown_ratio"], maximum_dd)
                        if (
                            csv_row["schema"] != value["schema"]
                            or csv_row["reference"] != reference
                        ):
                            raise ValueError("Oracle export identity mismatch")
                        change = Fraction(original["nav_usdt"]) - Fraction(original["initial_usdt"])
                        counts["gains" if change > 0 else "losses" if change < 0 else "ties"] += 1
                        counts["btc_increasing"] += any(
                            Fraction(b[3]) > Fraction(a[3]) for a, b in pairwise(marks)
                        )
                        counts["btc_decreasing"] += any(
                            Fraction(b[3]) < Fraction(a[3]) for a, b in pairwise(marks)
                        )
                        counts["wallets"] += 1
                    counts["selections"] += 1
                    if (
                        cost == "CA"
                        and months == {"2020-01-02": 6, "2021-12-02": 12, "2022-12-02": 24}[start]
                    ):
                        ui_cases.append(
                            {
                                "query": query,
                                "focus": "P_BANDS",
                                "reference": reference,
                                "summary": next(
                                    a["summary"]
                                    for a in value["accounts"]
                                    if a["summary"]["policy"] == "P_BANDS"
                                ),
                            }
                        )
        if any(
            counts[k] == 0 for k in ("gains", "losses", "ties", "btc_increasing", "btc_decreasing")
        ):
            raise ValueError("Oracle sample lacks required coverage")
        return {
            "status": "PASS",
            "counts": dict(counts),
            "manifest_sha256": archive.pin,
            "method": (
                "independent gzip/JSON and Fraction formulas; live HTTP and CSV/JSON round trips"
            ),
            "fees_limit": (
                "fees compared with archived summary; synthetic fills verified separately"
            ),
            "ui_cases": ui_cases,
            "new_backtests": 0,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Oracle server did not stop")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.archive_root), indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
