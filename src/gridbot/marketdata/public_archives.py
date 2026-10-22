"""Opt-in HTTPS GET acquisition of exactly 48 predetermined public Spot archives.

No credentials, proxy discovery, redirects, private endpoints or arbitrary URLs.
Run: python -m gridbot.marketdata.public_archives NEW_DIRECTORY
The directory must not exist. Only a final acquisition.json denotes completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from gridbot.marketdata.archive_contract import (
    ALLOWED_URLS,
    MAX_CHECKSUM_BYTES,
    MAX_ZIP_BYTES,
    MONTHS,
    ArchiveError,
    checksum,
    require,
    unpack,
)

ACQUISITION_SECONDS = 1200


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise ArchiveError("public download redirect refused")


def get(url: str, limit: int) -> bytes:
    require(url in ALLOWED_URLS, "URL outside predefined public archive allowlist")
    require(type(limit) is int and 0 < limit <= MAX_ZIP_BYTES, "download byte quota")
    require(not url.endswith(".CHECKSUM") or limit <= MAX_CHECKSUM_BYTES, "checksum download quota")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    # S310: exact immutable HTTPS allowlist above; no user supplied URL reaches urllib.
    request = urllib.request.Request(  # noqa: S310
        url, method="GET", headers={"Accept-Encoding": "identity"}
    )
    with opener.open(request, timeout=20) as response:
        require(response.status == 200 and response.geturl() == url, "unexpected HTTP response")
        length = response.headers.get("Content-Length")
        require(length is not None and length.isascii() and length.isdecimal(), "HTTP length")
        require(0 < int(length) <= limit, "HTTP payload quota")
        require(response.headers.get("Content-Encoding") in (None, "identity"), "HTTP encoding")
        start = time.monotonic()
        pieces = []
        total = 0
        while True:
            require(time.monotonic() - start <= 30, "download deadline")
            piece = response.read(min(65536, limit + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
            require(total <= limit, "download exceeded byte quota")
        require(total == int(length), "partial download")
        return b"".join(pieces)


def acquire(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    entries = []
    for month in MONTHS:
        require(time.monotonic() - started < ACQUISITION_SECONDS, "acquisition deadline")
        official = get(month.url + ".CHECKSUM", MAX_CHECKSUM_BYTES)
        raw = get(month.url, MAX_ZIP_BYTES)
        csv = unpack(raw, official, month)
        filename = month.stem + ".zip"
        # Exclusive creation: a previous dataset version is never overwritten.
        for name, content in ((filename, raw), (filename + ".CHECKSUM", official)):
            with (output / name).open("xb") as target:
                target.write(content)
        entries.append(
            dict(
                url=month.url,
                checksum_url=month.url + ".CHECKSUM",
                acquired_at=datetime.now(UTC).isoformat(),
                filename=filename,
                start=month.start.isoformat(),
                end=month.end.isoformat(),
                bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                official_sha256=checksum(official, month),
                checksum_match=True,
                csv_bytes=len(csv),
                csv_sha256=hashlib.sha256(csv).hexdigest(),
                epoch_unit=month.unit,
            )
        )
    manifest: dict[str, object] = dict(
        version=1, status="ACQUIRED_CHECKSUM_VERIFIED_NOT_YET_CANDLE_VALIDATED", files=entries
    )
    with (output / "acquisition.json").open("x", encoding="utf8") as target:
        json.dump(manifest, target, ensure_ascii=True, indent=2)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    acquire(args.output)


if __name__ == "__main__":
    main()
