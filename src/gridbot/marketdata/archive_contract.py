"""Finite public Spot archive contract; no network and no filesystem extraction."""

from __future__ import annotations

import hashlib
import io
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_CSV_BYTES = 4 * 1024 * 1024
MAX_CHECKSUM_BYTES = 512
MAX_RATIO = 100
BASE = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/"


class ArchiveError(ValueError):
    """Rejected archive is never admitted as a usable dataset."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ArchiveError(message)


@dataclass(frozen=True, slots=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        require(type(self.year) is int and 2022 <= self.year <= 2025, "2022-2025 only")
        require(type(self.month) is int and 1 <= self.month <= 12, "invalid month")

    @property
    def stem(self) -> str:
        return f"BTCUSDT-1h-{self.year:04}-{self.month:02}"

    @property
    def url(self) -> str:
        return BASE + self.stem + ".zip"

    @property
    def start(self) -> datetime:
        return datetime(self.year, self.month, 1, tzinfo=UTC)

    @property
    def end(self) -> datetime:
        return datetime(self.year + (self.month == 12), self.month % 12 + 1, 1, tzinfo=UTC)

    @property
    def unit(self) -> str:
        return "us" if self.year >= 2025 else "ms"


MONTHS = tuple(Month(year, month) for year in range(2022, 2026) for month in range(1, 13))
ALLOWED_URLS = frozenset(url for m in MONTHS for url in (m.url, m.url + ".CHECKSUM"))


def checksum(raw: bytes, month: Month) -> str:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_CHECKSUM_BYTES, "checksum size")
    try:
        match = re.fullmatch(
            rb"([0-9a-f]{64})[ \t]+\*?" + re.escape((month.stem + ".zip").encode()) + rb"\r?\n?",
            raw,
        )
        require(match is not None, "checksum digest/filename/schema mismatch")
        if match is None:
            raise ArchiveError("checksum absent")
        return match[1].decode("ascii")
    except UnicodeError as exc:
        raise ArchiveError("invalid checksum encoding") from exc


def unpack(raw: bytes, official: bytes, month: Month) -> bytes:
    """Authenticate bytes against the supplied official digest, then inspect one CSV.

    HTTPS/source provenance remains a separate acquisition concern. A checksum
    alone does not prove the external authenticity of manually supplied bytes.
    """
    require(type(month) is Month, "native month required")
    Month(month.year, month.month)
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ZIP_BYTES, "ZIP byte quota")
    require(hashlib.sha256(raw).hexdigest() == checksum(official, month), "ZIP checksum mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1, "exactly one CSV required; duplicate/extra member")
            entry = entries[0]
            require(entry.filename == month.stem + ".csv", "unexpected or unsafe ZIP member")
            require(not entry.is_dir() and not entry.flag_bits & 1, "directory/encrypted ZIP")
            mode = entry.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "nonregular ZIP member")
            require(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "ZIP codec")
            require(0 < entry.file_size <= MAX_CSV_BYTES, "CSV byte quota")
            require(
                entry.compress_size > 0 and entry.file_size <= MAX_RATIO * entry.compress_size,
                "ZIP compression ratio quota",
            )
            with archive.open(entry) as source:
                payload = source.read(MAX_CSV_BYTES + 1)
            require(len(payload) == entry.file_size, "truncated/oversized CSV")
            require(payload.endswith(b"\n"), "CSV must end with a complete line")
            return payload
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, EOFError, zlib.error) as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError("invalid, truncated or corrupt ZIP") from exc
