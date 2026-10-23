"""Pinned archived evidence, bounded reads and a common validated view model."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from research_console.risk import Mark, display, profile, require

ARCHIVE_PIN = "405755ffd2c3de0abeab4751e59f428e0dd5c8f933c329d097842585df58b68d"
POLICIES = ("B0_BH", "B1_HALF", "B2_DCA", "B3_CASH", "P_BANDS", "P_MONTHLY")
COSTS = ("CA", "CX2", "CB")
MAX_RAW = 512 * 1024
MAX_JSON = 8 * 1024 * 1024
NUMBER = re.compile(r"-?\d{1,20}(?:\.\d{1,60})?(?:[eE][+-]?\d{1,3})?\Z", re.ASCII)


def number(value: Any, *, positive: bool = False) -> Decimal:
    require(isinstance(value, str) and bool(NUMBER.fullmatch(value)), "Número inválido")
    result = Decimal(value)
    require(result.is_finite() and result >= 0 and (not positive or result > 0), "Saldo inválido")
    require(result == 0 or -100 <= result.adjusted() <= 20, "Magnitude inválida")
    return result


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and len(value) <= 32, "Data inválida")
    result = datetime.fromisoformat(value)
    require(result.utcoffset() == timedelta(0), "Data deve ser UTC")
    return result


def safe_read(root: Path, relative: str) -> bytes:
    """No user paths in HTTP; operator root plus fixed, validated basenames only."""
    require(bool(re.fullmatch(r"[A-Za-z0-9_]+(?:\.json|\.json\.gz)", relative)), "Origem inválida")
    path = root / relative
    require(
        not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)),
        "Links de origem recusados",
    )
    require(path.resolve().parent == root.resolve(), "Origem fora do limite")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RAW + 1)
    require(len(raw) <= MAX_RAW, "Arquivo excede limite")
    return raw


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, "Campo JSON duplicado")
        result[key] = value
    return result


def decode(raw: bytes, compressed: bool = False) -> Any:
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(MAX_JSON + 1)
    require(len(raw) <= MAX_JSON, "JSON excede limite")
    return json.loads(raw, object_pairs_hook=_unique_pairs)


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Explicit projection, never echo unexpected strings, paths or private fields."""
    require(row.get("policy") in POLICIES and row.get("cost") in COSTS, "Política/custo inválido")
    require(row.get("months") in (6, 12, 24) and row.get("status") == "VALID", "Janela inválida")
    require(timestamp(row["start"]) < timestamp(row["end"]), "Período inválido")
    fields = (
        "initial_usdt",
        "nav_usdt",
        "btc_physical",
        "btc_equivalent",
        "cash_usdt",
        "final_mark",
        "fees_usdt",
        "exposure_mean",
        "exposure_max",
    )
    for field in fields:
        number(row[field], positive=field in ("initial_usdt", "nav_usdt", "final_mark"))
    nav, btc, cash, price = (
        Fraction(row[k]) for k in ("nav_usdt", "btc_physical", "cash_usdt", "final_mark")
    )
    require(nav == cash + btc * price, "Identidade patrimonial divergente")
    require(
        abs(Fraction(row["btc_equivalent"]) - nav / price) < Fraction(1, 10**45),
        "BTC equivalente divergente",
    )
    dd = Fraction(row["max_drawdown_fraction"])
    require(0 <= dd < 1 and type(row["violates_20_percent"]) is bool, "Risco inválido")
    require(row["violates_20_percent"] == (dd > Fraction(1, 5)), "Classificação divergente")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", row["marks_sha256"])), "Hash inválido")
    return {
        **{k: row[k] for k in ("policy", "cost", "months", "start", "end", *fields)},
        "max_drawdown_fraction": str(dd),
        "max_drawdown": display(dd),
        "violates_20_percent": dd > Fraction(1, 5),
        "return": display(nav / Fraction(row["initial_usdt"]) - 1),
        "classification": "EXPLORATORY_ALREADY_EXAMINED_FIXED_RULE_WALK_FORWARD",
    }


def view(row: dict[str, Any], marks: list[list[str]]) -> dict[str, Any]:
    require(2 <= len(marks) <= 1000, "Série insuficiente ou excessiva")
    points = []
    for mark in marks:
        require(isinstance(mark, list) and len(mark) == 5, "Marca inválida")
        time = timestamp(mark[0])
        price, cash, btc, nav = (number(x, positive=i in (0, 3)) for i, x in enumerate(mark[1:]))
        require(
            Fraction(nav) == Fraction(cash) + Fraction(btc) * Fraction(price),
            "Conservação divergente",
        )
        points.append(Mark(time, price, cash, btc, nav))
    risk = profile(points)
    require(
        points[0].time == timestamp(row["start"]) and points[-1].time == timestamp(row["end"]),
        "Endpoint divergente",
    )
    require(Fraction(points[0].nav) == Fraction(row["initial_usdt"]), "Capital divergente")
    require(
        all(
            Fraction(getattr(points[-1], attr)) == Fraction(row[field])
            for attr, field in (
                ("nav", "nav_usdt"),
                ("btc", "btc_physical"),
                ("cash", "cash_usdt"),
                ("price", "final_mark"),
            )
        ),
        "Saldo final divergente",
    )
    require(
        Fraction(risk["max_drawdown_fraction"]) == Fraction(row["max_drawdown_fraction"]),
        "Drawdown divergente",
    )
    peak = Fraction(points[0].nav)
    series = []
    for p in points:
        peak = max(peak, Fraction(p.nav))
        series.append(
            {
                "time": p.time.isoformat(),
                "price": str(p.price),
                "nav": str(p.nav),
                "cash": str(p.cash),
                "btc": str(p.btc),
                "btc_equivalent": display(Fraction(p.nav) / Fraction(p.price)),
                "drawdown": display(Fraction(p.nav) / peak - 1),
                "return": display(Fraction(p.nav) / Fraction(points[0].nav) - 1),
                "exposure": display(Fraction(p.btc) * Fraction(p.price) / Fraction(p.nav)),
            }
        )
    return {"summary": row, "risk": risk, "series": series}


class Archive:
    """Only matrices and selected curve chunks; no candles, ledgers or simulators."""

    def __init__(self, root: Path, *, pin: str = ARCHIVE_PIN) -> None:
        require(not any("bimstruct" in p.lower() for p in root.parts), "Origem recusada")
        require(
            root.is_absolute() and not str(root).startswith(("\\\\", "//")), "Origem local exigida"
        )
        require(
            not any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)),
            "Links de origem recusados",
        )
        self.root = root / "m1_risk"
        raw = safe_read(self.root, "M1_RISK_ARTIFACT_MANIFEST.json")
        require(hashlib.sha256(raw).hexdigest() == pin, "Manifesto não reconhecido")
        self.pin = pin
        self.metadata_files: list[str] = []
        self.files = decode(raw)["files"]
        rows = []
        for months in (6, 12, 24):
            for cost in COSTS:
                name = f"M1_RISK_MATRIX_{months}_{cost}.json.gz"
                partition = self.load(name)["rows"]
                require(len(partition) <= 600, "Matriz excessiva")
                require(
                    all(r["months"] == months and r["cost"] == cost for r in partition),
                    "Partição divergente",
                )
                rows.extend(partition)
                self.metadata_files.append(name)
        require(0 < len(rows) <= 4266, "Catálogo excessivo ou vazio")
        self.rows = sorted(rows, key=lambda r: (r["months"], r["cost"], r["start"], r["policy"]))
        self.summaries = [public_row(r) for r in self.rows]
        keys = {(r["start"], r["months"], r["cost"], r["policy"]) for r in self.rows}
        require(len(keys) == len(rows), "Duplicata na matriz")
        self.index = self.load("M1_RISK_CURVE_INDEX.json")
        self.metadata_files.append("M1_RISK_CURVE_INDEX.json")
        require(
            self.index["wallets"] == len(rows) and len(self.index["parts"]) <= 200,
            "Índice divergente",
        )
        self.locations: list[str] = []
        for part in self.index["parts"]:
            require(type(part["wallets"]) is int and 0 < part["wallets"] <= 30, "Chunk inválido")
            self.locations.extend([part["file"]] * part["wallets"])
        require(len(self.locations) == len(rows), "Índice incompleto")
        if pin == ARCHIVE_PIN:
            require(
                len(rows) == 4266 and self.index["marks"] == 1730196,
                "Contagem do contrato divergente",
            )
            require(
                self.index["columns"] == ["time_utc", "price", "cash_usdt", "btc", "nav_usdt"],
                "Schema de unidades divergente",
            )

    def checked_raw(self, name: str) -> bytes:
        raw = safe_read(self.root, name)
        expected = self.files["docs/reviews/m1_risk/" + name]
        require(
            len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"],
            "Integridade da origem divergente",
        )
        return raw

    def fingerprint(self, start: str, months: int, cost: str) -> tuple[str, ...]:
        """Rehash inputs even on cache hit; modification never returns stale values."""
        require(
            hashlib.sha256(safe_read(self.root, "M1_RISK_ARTIFACT_MANIFEST.json")).hexdigest()
            == self.pin,
            "Manifesto não reconhecido",
        )
        names = set(self.metadata_files)
        names.update(
            self.locations[i]
            for i, r in enumerate(self.rows)
            if (r["start"][:10], r["months"], r["cost"]) == (start, months, cost)
        )
        return (
            self.pin,
            *(hashlib.sha256(self.checked_raw(name)).hexdigest() for name in sorted(names)),
        )

    def load(self, name: str) -> Any:
        raw = self.checked_raw(name)
        return decode(raw, name.endswith(".gz"))

    def selection(self, start: str, months: int, cost: str) -> list[dict[str, Any]]:
        selected = []
        chunks: dict[str, Any] = {}
        for index, row in enumerate(self.rows):
            if (row["start"][:10], row["months"], row["cost"]) != (start, months, cost):
                continue
            name = self.locations[index]
            if name not in chunks:
                chunks[name] = self.load(name)["wallets"]
            matches = [
                w
                for w in chunks[name]
                if all(w[k] == row[k] for k in ("start", "end", "months", "cost", "policy"))
            ]
            require(len(matches) == 1, "Courbe indisponível")
            marks = matches[0]["marks"]
            require(len(marks) == row["marks"], "Contagem de marcas divergente")
            actual = hashlib.sha256(json.dumps(marks, separators=(",", ":")).encode()).hexdigest()
            require(actual == row["marks_sha256"] == matches[0]["marks_sha256"], "Série adulterada")
            selected.append(view(self.summaries[index], marks))
        return selected
