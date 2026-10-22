"""Collect every public test and classify scope without executing its body."""

from __future__ import annotations

import contextlib
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class Catalog:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        smoke_modules = set((ROOT / "ci/fast-suite.txt").read_text().splitlines())
        measured = json.loads((ROOT / "ci/observed-test-costs.json").read_text())
        timings = measured["calls_seconds"]
        for item in session.items:
            path = item.path.relative_to(ROOT).as_posix()
            labels = ["expanded_regression"]
            if path in smoke_modules:
                labels.append("smoke")
            if path.startswith(("tests/domain/", "tests/strategy/", "tests/portfolio/")):
                labels.append("fast_unit")
            if path.startswith(("tests/storage/", "tests/paper/", "tests/backtest/")):
                labels.append("integration")
            if path.startswith(
                (
                    "tests/domain/",
                    "tests/strategy/",
                    "tests/portfolio/",
                    "tests/application/",
                    "tests/paper/",
                    "tests/backtest/",
                )
            ):
                labels.append("financial")
            obj = getattr(item, "obj", None)
            if hasattr(obj, "hypothesis") or any(
                word in path for word in ("properties", "stateful")
            ):
                labels.append("properties")
            if item.nodeid in timings and Decimal(timings[item.nodeid]) >= 1:
                labels.append("long_running")
            self.items.append({"nodeid": item.nodeid, "path": path, "categories": labels})


def main() -> int:
    catalog = Catalog()
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = pytest.main(["--collect-only", "-q", str(ROOT / "tests")], plugins=[catalog])
    if code != 0:
        print(captured.getvalue())  # noqa: T201
        return int(code)
    print(  # noqa: T201
        json.dumps(
            {
                "collection_only": True,
                "total": len(catalog.items),
                "note": "Categories overlap. Long-running is measured, not inferred from names.",
                "items": catalog.items,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
