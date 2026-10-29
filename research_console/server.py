"""Loopback research UI; only explicitly confirmed owned imports can write data."""

from __future__ import annotations

import json
import re
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

from gridbot import __version__
from research_console.analysis import (
    SCHEMA,
    UNITS,
    compare,
    distributions,
    export_csv,
    frequencies,
    selection_identity,
)
from research_console.data import COSTS, POLICIES, Archive
from research_console.demo import demonstration
from research_console.lab import http as lab_http
from research_console.lab.library import Library
from research_console.lab.numeric import AnalysisError
from research_console.lab.packs import MAX_UPLOAD
from research_console.risk import display

STATIC = Path(__file__).parent / "static"


class Service:
    def __init__(
        self,
        archive: Archive | None = None,
        *,
        archive_error: bool = False,
        archive_reason: str | None = None,
        lab_root: Path | None = None,
    ) -> None:
        self.archive = archive
        self.archive_error = archive_error
        self.archive_reason = archive_reason
        self.demo: list[dict[str, Any]] | None = None
        self.cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()
        self.cache_hits = 0
        self._lab: Library | None = None
        self.lab_root = lab_root

    @property
    def lab(self) -> Library:
        if self._lab is None:
            self._lab = Library(self.lab_root)
        return self._lab

    def catalog(self) -> dict[str, Any]:
        if self.archive:
            self.archive.fingerprint("", 0, "")
        return {
            "version": f"G4 / {__version__}",
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
            "global_coverage": "LOCAL_G3_1_PASS",
            "local_validation": {
                "phase": "G3.1",
                "native_coverage_percent": "96.52624362001981",
                "source": "gridbot",
                "branches": True,
                "threshold_percent": "85",
                "environment": "Windows / Python 3.13.16",
                "remote_ci": "NOT_EXECUTED",
                "measured_baseline": "d2cdf2f",
            },
            "dataset_id": "M1_R_DAILY_MARKS_V1" if self.archive else None,
            "manifest_sha256": self.archive.pin if self.archive else None,
            "archive_marks": self.archive.index.get("marks") if self.archive else None,
            "new_distributions": "UNAVAILABLE_PUBLIC_CORPUS_NOT_DISTRIBUTED",
            "archive_reason": self.archive_reason,
        }

    def lab_catalog(self) -> dict[str, Any]:
        result = self.lab.catalog()
        if self.archive is not None:
            self.archive.fingerprint("", 0, "")
        result["archive_adapter"] = {
            "source_kind": "ARCHIVED_RESEARCH_RESULT"
            if self.archive
            else (
                "DATA_INVALID"
                if self.archive_error and self.archive_reason != "MISSING_SOURCE"
                else "DATA_UNAVAILABLE"
            ),
            "wallets": len(self.archive.summaries) if self.archive else 0,
            "marks": self.archive.index.get("marks") if self.archive else 0,
            "manifest_sha256": self.archive.pin if self.archive else None,
            "integrity": "MATRICES_VERIFIED_CURVES_ON_SELECTION" if self.archive else "UNAVAILABLE",
            "redistribution": "RESTRICTED_RAW_REVIEWED_SUMMARY_CSV_ONLY",
            "read_only": True,
        }
        return result

    def selection(self, query: dict[str, list[str]]) -> dict[str, Any]:
        if not self.archive:
            return {"source_kind": "UNAVAILABLE", "accounts": []}
        if (
            not {"start", "months", "cost"} <= set(query)
            or set(query) - {"start", "months", "cost", "reference", "policies", "focus"}
            or any(len(v) != 1 or not v[0] for v in query.values())
        ):
            raise ValueError("Seleção inválida")
        start, months, cost = query["start"][0], query["months"][0], query["cost"][0]
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start) or months not in (
            "6",
            "12",
            "24",
        ):
            raise ValueError("Seleção inválida")
        if cost not in COSTS:
            raise ValueError("Seleção inválida")
        reference = query.get("reference", ["B0_BH"])[0]
        wanted = query.get("policies", [",".join(POLICIES)])[0].split(",")
        focus = query.get("focus", [reference])[0]
        if (
            reference not in POLICIES
            or not wanted
            or len(wanted) != len(set(wanted))
            or not set(wanted) <= set(POLICIES)
            or reference not in wanted
            or focus not in wanted
        ):
            raise ValueError("Seleção inválida")
        fingerprint = self.archive.fingerprint(start, int(months), cost)
        key = (str(self.archive.root), "G3_VIEW_V1", start, months, cost, *fingerprint)
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
        else:
            self.cache[key] = self.archive.selection(start, int(months), cost)
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        # Profiled G2 copied all six trajectories even for a one-policy view.
        # Project first, but deep-copy every selected nested value before exposure.
        accounts = deepcopy([a for a in self.cache[key] if a["summary"]["policy"] in wanted])
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
            "schema": SCHEMA,
            "selection": selection_identity(
                accounts,
                source="ARCHIVED_RESEARCH_RESULT",
                dataset="M1_R_DAILY_MARKS_V1",
                reference=reference,
                focus=focus,
                manifest=self.archive.pin,
            )
            if accounts
            else None,
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

    def demonstration(self, focus: str = "round_trip", *, rerun: bool = False) -> dict[str, Any]:
        if focus not in ("round_trip", "falling_mark"):
            raise ValueError("Seleção inválida")
        if self.demo is None or rerun:
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
            "schema": SCHEMA,
            "selection": selection_identity(
                accounts,
                source="SYNTHETIC_DEMO",
                dataset="SYNTHETIC_PUBLIC_DEMO_V1",
                reference=None,
                focus=focus,
            ),
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
    allow_reuse_address = False

    def __init__(self, service: Service, port: int = 8765) -> None:
        self.service = service
        self.session = secrets.token_hex(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.cookie_name = f"gridbot_console_{self.server_port}"

    def server_bind(self) -> None:
        # Windows SO_REUSEADDR can allow a second listener on the same address.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

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
            len(self.headers.get_all("Host", [])) == 1
            and len(self.headers.get_all("Origin", [])) <= 1
            and self.headers.get("Host") == origin.removeprefix("http://")
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
        name = self.server.cookie_name
        token = cookie[name].value if name in cookie else ""
        return (
            len(self.headers.get_all("Cookie", [])) == 1
            and len(token) == 64
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
        attachment_name: str | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header(
            "Content-Type",
            content_type + ("; charset=utf-8" if content_type != "application/zip" else ""),
        )
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
                "Set-Cookie",
                f"{self.server.cookie_name}={self.server.session}; "
                "HttpOnly; SameSite=Strict; Path=/",
            )
        if attachment_name:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        elif export:
            self.send_header(
                "Content-Disposition",
                'attachment; filename="gridbot-selected-research.'
                + ('csv"' if csv_export else 'json"'),
            )
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        routes = {
            "/api/lab/preview",
            "/api/lab/confirm",
            "/api/lab/remove",
            "/api/lab/replay",
            "/api/lab/authorize-export",
        }
        if self.path not in routes:
            self.respond(405, b'{"error":"Read only"}')
            return
        if (
            not self.allowed()
            or not self.authenticated()
            or len(self.headers.get_all("X-GridBot-Lab", [])) != 1
            or self.headers.get("X-GridBot-Lab") != "1"
        ):
            self.respond(403, b'{"error":"Local session required"}')
            return
        try:
            lengths = self.headers.get_all("Content-Length", [])
            expected_type = (
                "application/zip" if self.path.endswith("preview") else "application/json"
            )
            limit = MAX_UPLOAD if self.path.endswith("preview") else 16384
            if (
                len(lengths) != 1
                or not lengths[0].isascii()
                or not lengths[0].isdigit()
                or not 0 < int(lengths[0]) <= limit
                or self.headers.get("Transfer-Encoding")
                or len(self.headers.get_all("Content-Type", [])) != 1
                or self.headers.get("Content-Type") != expected_type
            ):
                raise ValueError("Corpo não permitido")
            size = int(lengths[0])
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Corpo incompleto")
            result = lab_http.post(self.server.service.lab, self.path, raw)
            self.respond(200, json.dumps(result, ensure_ascii=False, sort_keys=True).encode())
        except AnalysisError:
            self.respond(500, b'{"reason":"ANALYSIS_FAILED","error":"Internal analytical failure"}')
        except (ValueError, KeyError, TypeError, OSError, EOFError, OverflowError) as exc:
            self.close_connection = True
            self.respond(
                422,
                json.dumps(
                    {
                        "source_kind": "DATA_INVALID",
                        "reason": lab_http.error_code(exc),
                        "error": "Invalid or restricted evidence",
                    }
                ).encode(),
            )
        return

    def do_GET(self) -> None:
        path_limit = 8192 if self.path.startswith("/api/lab/") else 2048
        if not self.allowed() or len(self.path) > path_limit:
            self.respond(403, b'{"error":"Local origin required"}')
            return
        try:
            url = urlsplit(self.path)
        except ValueError:
            self.respond(400, b'{"error":"Invalid request target"}')
            return
        if url.scheme or url.netloc:
            self.respond(400, b'{"error":"Local path required"}')
            return
        assets = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
            "/charts.js": ("charts.js", "text/javascript"),
            "/numbers.js": ("numbers.js", "text/javascript"),
            "/state.js": ("state.js", "text/javascript"),
            "/lab.js": ("lab.js", "text/javascript"),
            "/review_model.js": ("review_model.js", "text/javascript"),
            "/review_view.js": ("review_view.js", "text/javascript"),
        }
        if url.path in assets and not url.query:
            name, mime = assets[url.path]
            try:
                body = (STATIC / name).read_bytes()
            except OSError:
                self.respond(503, b'{"error":"Local asset unavailable"}')
                return
            self.respond(200, body, mime, cookie=url.path == "/")
            return
        if not self.authenticated():
            self.respond(403, b'{"error":"Session required"}')
            return
        try:
            if url.path in {
                "/api/lab/library",
                "/api/lab/analysis",
                "/api/lab/source",
                "/api/lab/export",
            }:
                query = parse_qs(
                    url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4
                )
                if url.path == "/api/lab/library" and not query:
                    self.respond(
                        200, json.dumps(self.server.service.lab_catalog(), sort_keys=True).encode()
                    )
                    return
                body, mime, attachment = lab_http.get(self.server.service.lab, url.path, query)
                self.respond(200, body, mime, attachment_name=attachment)
                return
            if url.path == "/api/lab/paper" and not url.query:
                result = {
                    "source_kind": "SYNTHETIC_DEMO",
                    "accounts": [
                        {"policy": a["summary"]["policy"], "fills": lab_http.paper_trace(a)}
                        for a in self.server.service.demonstration()["accounts"]
                    ],
                }
                self.respond(200, json.dumps(result, sort_keys=True).encode())
                return
            if url.path == "/api/catalog" and not url.query:
                result = self.server.service.catalog()
            elif url.path in ("/api/selection", "/api/export", "/api/export.csv"):
                if (
                    url.path.startswith("/api/export")
                    and self.server.service.archive is not None
                    and (
                        url.path != "/api/export.csv"
                        or self.headers.get("X-GridBot-Reviewed") != "1"
                    )
                ):
                    self.respond(
                        403,
                        b'{"reason":"EXPORT_RESTRICTED",'
                        b'"error":"Only explicitly reviewed summary CSV is permitted"}',
                    )
                    return
                result = self.server.service.selection(
                    parse_qs(
                        url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=6
                    )
                )
            elif url.path in ("/api/demo", "/api/demo.csv"):
                query = parse_qs(
                    url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2
                )
                if (
                    set(query) - {"focus", "rerun"}
                    or any(len(v) != 1 for v in query.values())
                    or ("rerun" in query and query["rerun"] != ["1"])
                ):
                    raise ValueError("Seleção inválida")
                result = self.server.service.demonstration(
                    query.get("focus", ["round_trip"])[0], rerun=query.get("rerun") == ["1"]
                )
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
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return  # A disconnected reader does not change state or trigger another response.
        except AnalysisError:
            self.respond(500, b'{"reason":"ANALYSIS_FAILED","error":"Internal analytical failure"}')
        except (ValueError, KeyError, TypeError, OSError, EOFError, OverflowError) as exc:
            if url.path.startswith("/api/lab/"):
                self.respond(
                    422,
                    json.dumps(
                        {
                            "source_kind": "DATA_INVALID",
                            "reason": lab_http.error_code(exc),
                            "error": "Invalid or restricted evidence",
                        }
                    ).encode(),
                )
                return
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
