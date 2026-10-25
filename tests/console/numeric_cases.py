"""Literal synthetic observations and independent decimal-chunk test oracle."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from functools import lru_cache
from math import isqrt
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


def rational(text: str) -> Fraction:
    """Avoid the same CPython decimal-string limit in the independent test reader."""

    def integer(value: str) -> int:
        negative = value.startswith("-")
        value = value.removeprefix("-")
        result = 0
        for i in range(0, len(value), 9):
            chunk = value[i : i + 9]
            result = result * 10 ** len(chunk) + int(chunk)
        return -result if negative else result

    parts = text.split("/")
    return Fraction(integer(parts[0]), integer(parts[1]) if len(parts) == 2 else 1)


@lru_cache(maxsize=8)
def primes(count: int) -> tuple[int, ...]:
    values: list[int] = []
    candidate = 1009
    while len(values) < count:
        if all(candidate % divisor for divisor in range(2, isqrt(candidate) + 1)):
            values.append(candidate)
        candidate += 1
    return tuple(values)


def archive(manifest: dict[str, Any], results: dict[str, Any]) -> bytes:
    data = json.dumps(results, sort_keys=True, separators=(",", ":")).encode()
    manifest = {
        **manifest,
        "files": {"results.json": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}},
    }
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as zipped:
        zipped.writestr("manifest.json", json.dumps(manifest).encode())
        zipped.writestr("results.json", data)
    return stream.getvalue()


def coprime_pack(count: int, scale: int = 0) -> tuple[bytes, Fraction]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    points = [
        [
            (start + timedelta(days=i)).isoformat(),
            f"{p - 1}e{scale}",
            f"1e{scale}",
            "1",
            f"{p}e{scale}",
        ]
        for i, p in enumerate(primes(count))
    ]
    manifest = {
        "schema_version": 1,
        "pack_id": "NUMERIC_REGRESSION",
        "title": "SYNTHETIC exact numeric regression",
        "source_kind": "SYNTHETIC_DEMO",
        "data_nature": "SYNTHETIC",
        "flow_convention": "NO_EXTERNAL_FLOWS_DECLARED",
        "created_at": start.isoformat(),
        "dataset_identity": "FICTIONAL_COPRIME",
        "producer_version": "TEST_V1",
        "study_identity": "NUMERIC_REGRESSION",
        "start": points[0][0],
        "end": points[-1][0],
        "timezone": "UTC",
        "currency": "USDT",
        "units": ["UTC", "USDT_PER_BTC", "USDT", "BTC", "USDT"],
        "sampling_seconds": 86400,
        "license": "OWN_FICTIONAL_TEST",
        "redistribution": "PUBLIC",
        "limitations": ["Fictional observations only", "No investment or market research"],
    }
    account = {
        "account_id": "HOLD",
        "policy": "HOLD",
        "benchmark": None,
        "window_id": "WINDOW",
        "cost_scenario": "ZERO",
        "start": points[0][0],
        "end": points[-1][0],
        "initial_nav": points[0][4],
        "fees_usdt": "0",
        "points": points,
    }
    expected = 1 - sum((Fraction(1, p) for p in reversed(primes(count)[:-1])), Fraction()) / (
        count - 1
    )
    return archive(manifest, {"accounts": [account], "aggregates": []}), expected
