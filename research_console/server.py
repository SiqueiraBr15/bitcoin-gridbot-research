"""Loopback-only, read-only HTTP UI. No filesystem serving or exchange endpoints."""

from __future__ import annotations

import json
import secrets
import socket
from fractions import Fraction
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from research_console.data import Archive
from research_console.demo import demonstration
from research_console.risk import display

STATIC = Path(__file__).parent / "static"


class Service:
    def __init__(self, archive: Archive | None = None, *, archive_error: bool = False) -> None:
        self.archive = archive
        self.archive_error = archive_error
        self.demo: list[dict[str, Any]] | None = None

    def catalog(self) -> dict[str, Any]:
        return {
            "version": "G1 / 0.1.0.dev0",
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
        }

    def selection(self, query: dict[str, list[str]]) -> dict[str, Any]:
        if not self.archive:
            return {"source_kind": "UNAVAILABLE", "accounts": []}
        if set(query) != {"start", "months", "cost"} or any(len(v) != 1 for v in query.values()):
            raise ValueError("Seleção inválida")
        start, months, cost = query["start"][0], query["months"][0], query["cost"][0]
        if len(start) != 10 or months not in ("6", "12", "24") or cost not in ("CA", "CX2", "CB"):
            raise ValueError("Seleção inválida")
        accounts = self.archive.selection(start, int(months), cost)
        for account in accounts:
            row = account["summary"]
            account["benchmark_gaps"] = {}
            for benchmark in accounts:
                other = benchmark["summary"]
                if other["policy"] not in ("B0_BH", "B1_HALF"):
                    continue
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
        return (
            self.headers.get("Host") == origin.removeprefix("http://")
            and self.headers.get("Origin", origin) == origin
            and self.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin")
        )

    def authenticated(self) -> bool:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        return "console" in cookie and secrets.compare_digest(
            cookie["console"].value, self.server.session
        )

    def respond(
        self,
        code: int,
        body: bytes,
        content_type: str = "application/json",
        *,
        cookie: bool = False,
        export: bool = False,
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
                "Content-Disposition", 'attachment; filename="gridbot-selected-research.json"'
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
            elif url.path in ("/api/selection", "/api/export"):
                result = self.server.service.selection(parse_qs(url.query, max_num_fields=3))
            elif url.path == "/api/demo" and not url.query:
                if self.server.service.demo is None:
                    self.server.service.demo = demonstration()
                result = {"source_kind": "SYNTHETIC_DEMO", "accounts": self.server.service.demo}
            else:
                self.respond(404, b'{"error":"Not found"}')
                return
            body = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
            self.respond(200, body, export=url.path == "/api/export")
        except (ValueError, KeyError, TypeError, OSError, EOFError, OverflowError):
            self.respond(
                422, b'{"source_kind":"UNAVAILABLE","error":"Evidence unavailable or invalid"}'
            )
