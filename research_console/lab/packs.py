"""Bounded, non-extracting Evidence Pack v1 reader and deterministic writer."""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, cast

from research_console.data import decode, number, timestamp
from research_console.risk import require

MAX_UPLOAD = 2 * 1024 * 1024
MAX_CONTENT = 6 * 1024 * 1024
MAX_ACCOUNTS = 60
MAX_MARKS = 10000
CENTRAL_BYTES = 2 * 46 + len("manifest.json") + len("results.json")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z", re.ASCII)
HASH = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
SOURCES = ("SYNTHETIC_DEMO", "ARCHIVED_RESEARCH_RESULT", "AGGREGATED_RESEARCH_SUMMARY")
RIGHTS = ("PUBLIC", "AGGREGATES_ONLY", "RESTRICTED")
FIELDS = {
    "data_nature",
    "flow_convention",
    "schema_version",
    "pack_id",
    "title",
    "source_kind",
    "created_at",
    "dataset_identity",
    "producer_version",
    "study_identity",
    "start",
    "end",
    "timezone",
    "currency",
    "units",
    "sampling_seconds",
    "license",
    "redistribution",
    "limitations",
    "files",
}
ACCOUNT_FIELDS = {
    "account_id",
    "policy",
    "benchmark",
    "window_id",
    "cost_scenario",
    "start",
    "end",
    "initial_nav",
    "fees_usdt",
    "points",
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def identifier(value: Any) -> str:
    require(isinstance(value, str) and bool(IDENTIFIER.fullmatch(value)), "Identificador inválido")
    return cast(str, value)


def text(value: Any) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 240, "Texto inválido")
    require(
        not any(unicodedata.category(c)[0] == "C" or c in "\u2028\u2029" for c in value),
        "Controle em texto",
    )
    require(not any(c in value for c in ("\\", "/", "<", ">")), "Texto não portátil")
    require(value[0] not in "=+-@", "Texto de fórmula recusado")
    return cast(str, value)


def keys(value: Any, expected: set[str]) -> None:
    require(isinstance(value, dict) and set(value) == expected, "Campos de schema divergentes")


def utc(value: Any) -> str:
    result = timestamp(value)
    require(result.microsecond == 0, "Resolução temporal deve ser segundos UTC")
    return result.isoformat()


@dataclass(frozen=True)
class Pack:
    """Validated private snapshot. Expose copies, never this mutable payload directly."""

    sha256: str
    manifest_sha256: str
    manifest: dict[str, Any]
    results: dict[str, Any]
    raw: bytes


def container_layout(raw: bytes, archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo]) -> None:
    """V1 excludes ZIP comments/extras, descriptors, prefixes and hidden trailing bytes."""
    require(len(raw) >= 22 and not archive.comment, "Metadados ZIP não manifestados")
    end = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
    require(
        end[0] == b"PK\x05\x06" and end[1:5] == (0, 0, 2, 2) and end[7] == 0,
        "Final ZIP não canônico",
    )
    cursor = 0
    central_size = 0
    for entry in sorted(entries, key=lambda e: e.header_offset):
        require(
            entry.filename == entry.orig_filename and not entry.extra and not entry.comment,
            "Nome ou metadados ZIP não manifestados",
        )
        require(
            entry.header_offset == cursor and entry.flag_bits in (0, 0x800),
            "Prefixo ou descritor ZIP não permitido",
        )
        header = struct.unpack_from("<4s5H3I2H", raw, cursor)
        name = entry.filename.encode("ascii")
        require(
            header[0] == b"PK\x03\x04"
            and header[2] == entry.flag_bits
            and header[3] == entry.compress_type
            and header[6] == entry.CRC
            and header[7] == entry.compress_size
            and header[8] == entry.file_size
            and header[9] == len(name)
            and header[10] == 0,
            "Cabeçalho ZIP inconsistente",
        )
        require(raw[cursor + 30 : cursor + 30 + len(name)] == name, "Nome ZIP inconsistente")
        cursor += 30 + len(name) + entry.compress_size
        central_size += 46 + len(name)
    require(
        end[6] == cursor and end[5] == central_size and cursor + central_size == len(raw) - 22,
        "Conteúdo ZIP não manifestado",
    )


def validate_manifest(value: Any) -> dict[str, Any]:
    keys(value, FIELDS)
    require(
        type(value["schema_version"]) is int and value["schema_version"] == 1,
        "Versão de pack não suportada",
    )
    for key in ("pack_id", "dataset_identity", "producer_version", "study_identity", "license"):
        identifier(value[key])
    text(value["title"])
    require(value["source_kind"] in SOURCES, "Fonte inválida")
    require(value["data_nature"] in ("SYNTHETIC", "HISTORICAL_DECLARED"), "Natureza inválida")
    require(
        value["source_kind"] != "SYNTHETIC_DEMO" or value["data_nature"] == "SYNTHETIC",
        "Demonstração deve ser sintética",
    )
    require(value["flow_convention"] == "NO_EXTERNAL_FLOWS_DECLARED", "Fluxos não suportados")
    require(value["redistribution"] in RIGHTS, "Permissão de redistribuição inválida")
    for key in ("created_at", "start", "end"):
        require(value[key] == utc(value[key]), "Timestamp deve ser UTC canônico")
    require(timestamp(value["start"]) <= timestamp(value["end"]), "Período invertido")
    require(value["timezone"] == "UTC" and value["currency"] == "USDT", "Unidades incompatíveis")
    require(value["units"] == ["UTC", "USDT_PER_BTC", "USDT", "BTC", "USDT"], "Unidades inválidas")
    require(
        type(value["sampling_seconds"]) is int and 0 < value["sampling_seconds"] <= 2678400,
        "Frequência inválida",
    )
    require(
        isinstance(value["limitations"], list) and 1 <= len(value["limitations"]) <= 12,
        "Limitações obrigatórias",
    )
    for item in value["limitations"]:
        text(item)
    keys(value["files"], {"results.json"})
    record = value["files"]["results.json"]
    keys(record, {"bytes", "sha256"})
    require(type(record["bytes"]) is int and 0 < record["bytes"] <= MAX_CONTENT, "Tamanho inválido")
    require(
        isinstance(record["sha256"], str) and bool(HASH.fullmatch(record["sha256"])),
        "Hash inválido",
    )
    return cast(dict[str, Any], value)


def validate_results(manifest: dict[str, Any], value: Any) -> dict[str, Any]:
    keys(value, {"accounts", "aggregates"})
    accounts, aggregates = value["accounts"], value["aggregates"]
    require(isinstance(accounts, list) and isinstance(aggregates, list), "Resultados inválidos")
    if manifest["source_kind"] == "AGGREGATED_RESEARCH_SUMMARY":
        require(not accounts and 1 <= len(aggregates) <= MAX_ACCOUNTS, "Resumo não é uma série")
        seen = set()
        for row in aggregates:
            keys(row, {"policy", "cost_scenario", "observations", "losses", "violations"})
            identifier(row["policy"])
            identifier(row["cost_scenario"])
            for key in ("observations", "losses", "violations"):
                require(type(row[key]) is int and 0 <= row[key] <= 1000000, "Contagem inválida")
            require(
                row["observations"] > 0
                and max(row["losses"], row["violations"]) <= row["observations"],
                "Contagens inconsistentes",
            )
            identity = (row["policy"], row["cost_scenario"])
            require(identity not in seen, "Resumo duplicado")
            seen.add(identity)
        return cast(dict[str, Any], value)
    require(not aggregates and 1 <= len(accounts) <= MAX_ACCOUNTS, "Contas inválidas")
    ids = set()
    marks = 0
    for account in accounts:
        keys(account, ACCOUNT_FIELDS)
        for key in ("account_id", "policy", "window_id", "cost_scenario"):
            identifier(account[key])
        require(account["account_id"] not in ids, "Conta duplicada")
        ids.add(account["account_id"])
        if account["benchmark"] is not None:
            identifier(account["benchmark"])
        require(
            account["start"] == utc(account["start"]) and account["end"] == utc(account["end"]),
            "Endpoints não canônicos",
        )
        require(
            timestamp(manifest["start"])
            <= timestamp(account["start"])
            <= timestamp(account["end"])
            <= timestamp(manifest["end"]),
            "Janela fora do estudo",
        )
        number(account["initial_nav"])
        number(account["fees_usdt"])
        points = account["points"]
        require(
            isinstance(points, list) and 1 <= len(points) <= MAX_MARKS, "Série vazia ou excessiva"
        )
        marks += len(points)
        require(marks <= MAX_MARKS, "Pack excede limite de marcas")
        previous = None
        exhausted = False
        for point in points:
            require(isinstance(point, list) and len(point) == 5, "Marca inválida")
            require(point[0] == utc(point[0]), "Timestamp não canônico")
            time = timestamp(point[0])
            require(previous is None or previous < time, "Duplicata ou ordem temporal inválida")
            previous = time
            price, cash, btc, nav = (number(v, positive=i == 0) for i, v in enumerate(point[1:]))
            require(
                Fraction(nav) == Fraction(cash) + Fraction(btc) * Fraction(price),
                "NAV não conserva BTC e USDT",
            )
            require(not exhausted or nav == 0, "Capital nulo não pode reaparecer sem fluxo externo")
            exhausted = nav == 0
        require(
            points[0][0] == account["start"] and points[-1][0] == account["end"],
            "Endpoints divergentes",
        )
        require(
            Fraction(points[0][4]) == Fraction(account["initial_nav"]), "Capital inicial divergente"
        )
    for account in accounts:
        require(account["benchmark"] is None or account["benchmark"] in ids, "Benchmark ausente")
        if account["benchmark"] is not None:
            reference = next(a for a in accounts if a["account_id"] == account["benchmark"])
            require(
                all(
                    account[k] == reference[k]
                    for k in ("window_id", "cost_scenario", "start", "end")
                )
                and Fraction(account["initial_nav"]) == Fraction(reference["initial_nav"])
                and [(p[0], Fraction(p[1])) for p in account["points"]]
                == [(p[0], Fraction(p[1])) for p in reference["points"]],
                "Benchmark incompatível",
            )
    return cast(dict[str, Any], value)


def read_pack(raw: bytes) -> Pack:
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_UPLOAD, "Pack excede limite de upload")
    try:
        require(len(raw) >= 22 and raw[:4] == b"PK\x03\x04", "Prefixo ZIP não permitido")
        footer = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
        require(
            footer[0] == b"PK\x05\x06" and footer[1:5] == (0, 0, 2, 2),
            "Pack deve conter somente manifesto e resultados sem duplicatas",
        )
        require(
            footer[5] == CENTRAL_BYTES
            and footer[7] == 0
            and footer[6] + CENTRAL_BYTES == len(raw) - 22,
            "Conteúdo ZIP não manifestado",
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(
                len(entries) == 2
                and {e.filename for e in entries} == {"manifest.json", "results.json"},
                "Pack deve conter somente manifesto e resultados sem duplicatas",
            )
            container_layout(raw, archive, entries)
            total = 0
            contents = {}
            for entry in entries:
                require(
                    entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and not entry.flag_bits & 1,
                    "Compressão ou criptografia recusada",
                )
                require(
                    stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG),
                    "Links e tipos especiais recusados",
                )
                total += entry.file_size
                require(
                    0 < entry.file_size <= MAX_CONTENT and total <= MAX_CONTENT,
                    "Descompressão excessiva",
                )
                require(
                    entry.file_size <= 100 * max(1, entry.compress_size),
                    "Razão de compressão excessiva",
                )
                with archive.open(entry) as stream:
                    content = stream.read(min(MAX_CONTENT, entry.file_size) + 1)
                require(len(content) == entry.file_size, "Entrada incompleta")
                contents[entry.filename] = content
    except (
        struct.error,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        OSError,
        EOFError,
        zlib.error,
    ) as exc:
        raise ValueError("Contêiner de evidência inválido") from exc
    require(len(contents["manifest.json"]) <= 16384, "Manifesto excessivo")
    manifest = validate_manifest(decode(contents["manifest.json"]))
    expected = manifest["files"]["results.json"]
    require(
        len(contents["results.json"]) == expected["bytes"]
        and digest(contents["results.json"]) == expected["sha256"],
        "Integridade SHA-256 divergente",
    )
    results = validate_results(manifest, decode(contents["results.json"]))
    return Pack(digest(raw), digest(contents["manifest.json"]), manifest, results, raw)


def write_pack(metadata: dict[str, Any], results: dict[str, Any]) -> bytes:
    data = canonical(results)
    manifest = {**metadata, "files": {"results.json": {"bytes": len(data), "sha256": digest(data)}}}
    validate_manifest(manifest)
    validate_results(manifest, results)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, content in (("manifest.json", canonical(manifest)), ("results.json", data)):
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(entry, content, compresslevel=6)
    raw = output.getvalue()
    read_pack(raw)
    return raw
