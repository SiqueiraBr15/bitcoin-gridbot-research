"""Loopback-only, read-only HTTP UI. No filesystem serving or exchange endpoints."""

from __future__ import annotations

import json
import secrets
import socket
from collections import OrderedDict
from copy import deepcopy
from fractions import Fraction
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from research_console.analysis import UNITS, compare, distributions, export_csv, frequencies
from research_console.data import COSTS, POLICIES, Archive
from research_console.demo import demonstration
from research_console.risk import display

STATIC = Path(__file__).parent / "static"


class Service:
    def __init__(
        self,
        archive: Archive | None = None,
        *,
        archive_error: bool = False,
        archive_reason: str | None = None,
    ) -> None:
        self.archive = archive
        self.archive_error = archive_error
        self.archive_reason = archive_reason
        self.demo: list[dict[str, Any]] | None = None
        self.cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()
        self.cache_hits = 0

    def catalog(self) -> dict[str, Any]:
        if self.archive:
            self.archive.fingerprint("", 0, "")
        return {
            "version": "G2 / 0.1.0.dev0",
            "mode": "PAPER / OFFLINE",
            "archive_status": "ARCHIVED_RESEARCH_RESULT" if self.archive else "UNAVAILABLE",
            "archive_integrity": "MATRICES_VERIFIED_CURVES_ON_SELECTION"
            if self.archive
            else (
                "INVALID_OR_UNRECOGNIZED_SOURCE" if self.archive_error else "SOURCE_NOT_AUTHORIZED"
            ),
            "research_date": "2026-10-22" if self.archive else None,
            "rows": self.archive.summaries if self.archive else [],
            "risk_tolerance": "1/5",
            "sample": "RETROSPECTIVE_OVERLAPPING_WINDOWS",
            "global_coverage": "PENDING",
            "dataset_id": "M1_R_DAILY_MARKS_V1" if self.archive else None,
            "manifest_sha256": self.archive.pin if self.archive else None,
            "archive_marks": self.archive.index.get("marks") if self.archive else None,
            "new_distributions": "UNAVAILABLE_PUBLIC_CORPUS_NOT_DISTRIBUTED",
            "archive_reason": self.archive_reason,
        }

    def selection(self, query: dict[str, list[str]]) -> dict[str, Any]:
        if not self.archive:
            return {"source_kind": "UNAVAILABLE", "accounts": []}
        if (
            not {"start", "months", "cost"} <= set(query)
            or set(query) - {"start", "months", "cost", "reference", "policies"}
            or any(len(v) != 1 for v in query.values())
        ):
            raise ValueError("Seleção inválida")
        start, months, cost = query["start"][0], query["months"][0], query["cost"][0]
        if len(start) != 10 or months not in ("6", "12", "24") or cost not in ("CA", "CX2", "CB"):
            raise ValueError("Seleção inválida")
        if cost not in COSTS:
            raise ValueError("Seleção inválida")
        fingerprint = self.archive.fingerprint(start, int(months), cost)
        key = (str(self.archive.root), "G2_VIEW_V1", start, months, cost, *fingerprint)
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
        else:
            self.cache[key] = self.archive.selection(start, int(months), cost)
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        accounts = deepcopy(self.cache[key])
        reference = query.get(
            "reference", [accounts[0]["summary"]["policy"] if accounts else "B0_BH"]
        )[0]
        wanted = query.get("policies", [",".join(POLICIES)])[0].split(",")
        if (
            reference not in POLICIES
            or not wanted
            or len(wanted) != len(set(wanted))
            or not set(wanted) <= set(POLICIES)
            or reference not in wanted
        ):
            raise ValueError("Seleção inválida")
        accounts = [a for a in accounts if a["summary"]["policy"] in wanted]
        for account in accounts:
            row = account["summary"]
            account["benchmark_gaps"] = {}
            for benchmark in accounts:
                other = benchmark["summary"]
                if any(row[k] != other[k] for k in ("start", "end", "initial_usdt", "final_mark")):
                    raise ValueError("Comparação incompatível")
                delta = Fraction(row["nav_usdt"]) - Fraction(other["nav_usdt"])
                account["benchmark_gaps"][other["policy"]] = {
                    "nav_usdt": display(delta),
                    "return_pp": display(100 * delta / Fraction(row["initial_usdt"])),
                    "btc_physical": display(
                        Fraction(row["btc_physical"]) - Fraction(other["btc_physical"])
                    ),
                    "cash_usdt": display(Fraction(row["cash_usdt"]) - Fraction(other["cash_usdt"])),
                }
        return {
            "source_kind": "ARCHIVED_RESEARCH_RESULT" if accounts else "UNAVAILABLE",
            "accounts": accounts,
            "risk_tolerance": "1/5",
            "schema": "GRIDBOT_RESEARCH_SELECTION_V2",
            "units": UNITS,
            "provenance": {
                "dataset_id": "M1_R_DAILY_MARKS_V1",
                "source": "LOCAL_AUTHORIZED_ARCHIVE",
                "manifest_sha256": self.archive.pin,
                "integrity": "HASH_AND_SELECTED_MARKS_VERIFIED",
                "time_unit": "UTC",
                "sampling": "INITIAL_CAPITAL_AND_OBSERVED_DAILY_CLOSES",
            },
            "comparison": compare(accounts, reference) if accounts else None,
            "frequencies": frequencies(self.archive.summaries, int(months), cost),
            "distributions": distributions([], "LOCAL_AUTHORIZED_ARCHIVE"),
            "reason": None if accounts else "SELECTION_UNAVAILABLE",
        }

    def demonstration(self) -> dict[str, Any]:
        if self.demo is None:
            self.demo = demonstration()
        accounts = deepcopy(self.demo)
        for account in accounts:
            row = account["summary"]
            row.update(return_=account["series"][-1]["return"])
            row["return"] = row.pop("return_")
            row["max_drawdown"] = account["risk"]["max_drawdown_magnitude"]
            row["violates_20_percent"] = account["risk"]["violates_20_percent"]
        return {
            "source_kind": "SYNTHETIC_DEMO",
            "accounts": accounts,
            "units": UNITS,
            "schema": "GRIDBOT_RESEARCH_SELECTION_V2",
            "provenance": {
                "dataset_id": "SYNTHETIC_PUBLIC_DEMO_V1",
                "source": "SYNTHETIC_DEMO",
                "integrity": "FRACTION_CONSERVATION_AND_NATIVE_REPLAY_VERIFIED",
                "time_unit": "UTC",
                "sampling": "OBSERVED_SYNTHETIC_EVENTS",
            },
            "comparison": None,
            "comparison_reason": "DIFFERENT_SYNTHETIC_MARK_PATHS",
            "distributions": distributions([a["summary"] for a in accounts], "SYNTHETIC_DEMO"),
        }


class LocalServer(HTTPServer):
    def __init__(self, service: Service, port: int = 8765) -> None:
        self.service = service
        self.session = secrets.token_hex(32)
        super().__init__(("127.0.0.1", port), Handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Do not expose source paths, requests, traceback or data in logs.
        pass


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "GridBotLocal"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def allowed(self) -> bool:
        origin = f"http://127.0.0.1:{self.server.server_port}"
        # Top-level entry may originate at another site. Only the public shell is
        # allowed there; cross-site API requests and frames remain forbidden.
        shell_navigation = (
            self.path == "/"
            and self.headers.get("Sec-Fetch-Mode") == "navigate"
            and self.headers.get("Sec-Fetch-Dest") == "document"
        )
        return (
            self.headers.get("Host") == origin.removeprefix("http://")
            and self.headers.get("Origin", origin) == origin
            and (
                self.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin")
                or shell_navigation
            )
        )

    def authenticated(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        token = cookie["console"].value if "console" in cookie else ""
        return (
            len(token) == 64
            and token.isascii()
            and secrets.compare_digest(token, self.server.session)
        )

    def respond(
        self,
        code: int,
        body: bytes,
        content_type: str = "application/json",
        *,
        cookie: bool = False,
        export: bool = False,
        csv_export: bool = False,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie", f"console={self.server.session}; HttpOnly; SameSite=Strict; Path=/"
            )
        if export:
            self.send_header(
                "Content-Disposition",
                'attachment; filename="gridbot-selected-research.'
                + ('csv"' if csv_export else 'json"'),
            )
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.respond(405, b'{"error":"Read only"}')

    def do_GET(self) -> None:
        if not self.allowed() or len(self.path) > 2048:
            self.respond(403, b'{"error":"Local origin required"}')
            return
        url = urlsplit(self.path)
        assets = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
            "/charts.js": ("charts.js", "text/javascript"),
            "/state.js": ("state.js", "text/javascript"),
        }
        if url.path in assets and not url.query:
            name, mime = assets[url.path]
            self.respond(200, (STATIC / name).read_bytes(), mime, cookie=url.path == "/")
            return
        if not self.authenticated():
            self.respond(403, b'{"error":"Session required"}')
            return
        try:
            if url.path == "/api/catalog" and not url.query:
                result = self.server.service.catalog()
            elif url.path in ("/api/selection", "/api/export", "/api/export.csv"):
                result = self.server.service.selection(parse_qs(url.query, max_num_fields=5))
            elif url.path in ("/api/demo", "/api/demo.csv") and not url.query:
                result = self.server.service.demonstration()
            else:
                self.respond(404, b'{"error":"Not found"}')
                return
            is_csv = url.path.endswith(".csv")
            body = (
                export_csv(result)
                if is_csv
                else json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
            )
            self.respond(
                200,
                body,
                "text/csv" if is_csv else "application/json",
                export=url.path.startswith("/api/export") or is_csv,
                csv_export=is_csv,
            )
        except (ValueError, KeyError, TypeError, OSError, EOFError, OverflowError) as exc:
            message = str(exc)
            reason = (
                "MISSING_SOURCE"
                if isinstance(exc, FileNotFoundError)
                else "INTEGRITY_MISMATCH"
                if any(v in message for v in ("Integridade", "Manifesto", "adulterada"))
                else "INVALID_SELECTION"
                if message == "Seleção inválida"
                else "INVALID_SCHEMA_OR_SERIES"
            )
            self.respond(
                422,
                json.dumps(
                    {
                        "source_kind": "UNAVAILABLE",
                        "reason": reason,
                        "error": "Evidence unavailable or invalid",
                    }
                ).encode(),
            )
