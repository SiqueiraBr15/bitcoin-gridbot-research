from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.marketdata import public_archives as acquisition
from gridbot.marketdata.archive_contract import (
    ALLOWED_URLS,
    MAX_CHECKSUM_BYTES,
    MAX_CSV_BYTES,
    MAX_ZIP_BYTES,
    MONTHS,
    ArchiveError,
    Month,
    checksum,
    unpack,
)

M = Month(2024, 12)


def zipped(payload: bytes = b"1,2,3\n", name: str | None = None) -> tuple[bytes, bytes]:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(M.stem + ".csv" if name is None else name, payload)
    raw = target.getvalue()
    return raw, digest(raw)


def digest(raw: bytes, month: Month = M) -> bytes:
    return f"{hashlib.sha256(raw).hexdigest()}  {month.stem}.zip\n".encode()


def test_finite_contract_and_payload() -> None:
    assert len(MONTHS) == 48
    assert len(ALLOWED_URLS) == 96
    assert MONTHS[0] == Month(2022, 1)
    assert MONTHS[-1] == Month(2025, 12)
    assert M.unit == "ms"
    assert Month(2025, 1).unit == "us"
    assert M.end == Month(2025, 1).start
    raw, official = zipped()
    assert unpack(raw, official, M) == b"1,2,3\n"
    assert checksum(official, M) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    ("year", "month"), [(2021, 1), (2026, 1), (2022, 0), (2022, 13), (True, 1)]
)
def test_outside_finite_month_contract(year: int, month: int) -> None:
    with pytest.raises(ArchiveError):
        Month(year, month)


@pytest.mark.parametrize(
    "name", ["../outside.csv", "/absolute.csv", "C:/absolute.csv", "x\\file.csv", "other.csv", "x/"]
)
def test_no_extraction_or_unexpected_member(name: str, tmp_path: Path) -> None:
    before = list(tmp_path.iterdir())
    raw, official = zipped(name=name)
    with pytest.raises(ArchiveError, match="member"):
        unpack(raw, official, M)
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    "payload",
    [b"", b"truncated", b"0" * (MAX_CSV_BYTES + 1) + b"\n"],
    ids=["empty", "missing_newline", "oversized"],
)
def test_incomplete_or_oversized_payload(payload: bytes) -> None:
    raw, official = zipped(payload)
    with pytest.raises(ArchiveError):
        unpack(raw, official, M)


def test_checksum_truncated_zip_bomb_duplicate_symlink_and_crc() -> None:
    raw, official = zipped()
    for bad in [b"", b"f" * (MAX_ZIP_BYTES + 1), raw[:-8]]:
        with pytest.raises(ArchiveError):
            unpack(bad, digest(bad), M)
    with pytest.raises(ArchiveError, match="checksum"):
        unpack(raw + b"x", official, M)
    bomb, check = zipped(b"a" * 100_000 + b"\n")
    with pytest.raises(ArchiveError, match="ratio"):
        unpack(bomb, check, M)
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(M.stem + ".csv", b"x\n")
        archive.writestr("extra.csv", b"x\n")
    with pytest.raises(ArchiveError, match="exactly one"):
        unpack(target.getvalue(), digest(target.getvalue()), M)
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        entry = zipfile.ZipInfo(M.stem + ".csv")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, b"outside\n")
    with pytest.raises(ArchiveError, match="nonregular"):
        unpack(target.getvalue(), digest(target.getvalue()), M)
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(M.stem + ".csv", b"UNIQUE_BYTES\n")
    corrupt = target.getvalue().replace(b"UNIQUE_BYTES", b"BROKEN_BYTES")
    with pytest.raises(ArchiveError, match="corrupt"):
        unpack(corrupt, digest(corrupt), M)


@pytest.mark.parametrize(
    "value",
    [b"", b"x" * (MAX_CHECKSUM_BYTES + 1), b"f" * 64, b"f" * 64 + b"  other.zip\n"],
)
def test_checksum_closed_schema(value: bytes) -> None:
    with pytest.raises(ArchiveError):
        checksum(value, M)


@settings(max_examples=20, deadline=None)
@given(st.binary(min_size=1, max_size=128))
def test_tampering_is_rejected(changes: bytes) -> None:
    raw, official = zipped()
    with pytest.raises(ArchiveError, match="checksum"):
        unpack(raw + changes, official, M)


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw: bytes, length: str | None, url: str = M.url) -> None:
        super().__init__(raw)
        self.headers = {} if length is None else {"Content-Length": length}
        self.url = url

    def geturl(self) -> str:
        return self.url


class Opener:
    def __init__(self, response: Response) -> None:
        self.response = response

    @contextmanager
    def open(self, request: Any, timeout: int) -> Iterator[Response]:
        assert request.get_method() == "GET"
        assert timeout == 20
        assert not any("auth" in key.lower() for key in request.headers)
        yield self.response


@pytest.mark.parametrize("length", [None, "-1", "99999999999", "5", "0", "\uff11\uff12"])
def test_partial_or_unbounded_download(length: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *args: Opener(Response(b"abc", length))
    )
    with pytest.raises(ArchiveError):
        acquisition.get(M.url, 100)


def test_public_get_redirect_and_url_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener(Response(b"abc", "3")))
    assert acquisition.get(M.url, 100) == b"abc"
    for url in [
        "file:///x",
        "http://data.binance.vision/",
        "https://api.binance.com/api/v3/account",
    ]:
        with pytest.raises(ArchiveError, match="allowlist"):
            acquisition.get(url, 100)
    with pytest.raises(ArchiveError, match="redirect"):
        acquisition.NoRedirect().redirect_request(
            object.__new__(urllib.request.Request), None, 302, "", None, "https://example.com"
        )


def test_acquisition_failure_has_no_completion_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "new"

    def fail(url: str, limit: int) -> bytes:
        raise ArchiveError("network unavailable")

    monkeypatch.setattr(acquisition, "get", fail)
    with pytest.raises(ArchiveError):
        acquisition.acquire(target)
    assert not (target / "acquisition.json").exists()
    with pytest.raises(FileExistsError):
        acquisition.acquire(target)


def test_successful_acquisition_is_finite_get_only_and_versioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def fake_get(url: str, limit: int) -> bytes:
        calls.append(url)
        month = next(m for m in MONTHS if url in (m.url, m.url + ".CHECKSUM"))
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(month.stem + ".csv", b"fixture not candle validated\n")
        raw = content.getvalue()
        return digest(raw, month) if url.endswith(".CHECKSUM") else raw

    monkeypatch.setattr(acquisition, "get", fake_get)
    result = acquisition.acquire(tmp_path / "version_one")
    assert len(calls) == 96
    assert set(calls) == ALLOWED_URLS
    assert result["status"] == "ACQUIRED_CHECKSUM_VERIFIED_NOT_YET_CANDLE_VALIDATED"
    assert (tmp_path / "version_one/acquisition.json").exists()
    before = (tmp_path / "version_one/acquisition.json").read_bytes()
    with pytest.raises(FileExistsError):
        acquisition.acquire(tmp_path / "version_one")
    assert (tmp_path / "version_one/acquisition.json").read_bytes() == before


def test_wrong_http_response_encoding_size_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in ["status", "url", "encoding", "overflow"]:
        response = Response(b"abcd", "3")
        if kind == "status":
            response.status = 206
        elif kind == "url":
            response.url = "https://example.com"
        elif kind == "encoding":
            response.headers["Content-Encoding"] = "gzip"
        monkeypatch.setattr(
            urllib.request, "build_opener", lambda *args, value=response: Opener(value)
        )
        with pytest.raises(ArchiveError):
            acquisition.get(M.url, 3)


def test_zip_duplicate_encryption_and_unsupported_codec() -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(M.stem + ".csv", b"x\n")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(M.stem + ".csv", b"x\n")
    with pytest.raises(ArchiveError, match="exactly one"):
        unpack(content.getvalue(), digest(content.getvalue()), M)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr(M.stem + ".csv", b"x\n")
    with pytest.raises(ArchiveError, match="codec"):
        unpack(content.getvalue(), digest(content.getvalue()), M)
    raw, _ = zipped()
    flags = bytearray(raw)
    central = raw.index(b"PK\x01\x02")
    flags[central + 8] |= 1
    flags[6] |= 1
    encrypted = bytes(flags)
    with pytest.raises(ArchiveError, match="encrypted"):
        unpack(encrypted, digest(encrypted), M)
