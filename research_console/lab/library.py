"""Explicitly enabled owned storage; no discovery outside the operator's lab."""

from __future__ import annotations

import os
import re
import secrets
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any

from research_console.lab import ANALYTICS_VERSION
from research_console.lab.analytics import analyze
from research_console.lab.fixtures import bundled
from research_console.lab.packs import MAX_UPLOAD, Pack, canonical, digest, read_pack
from research_console.risk import require

MARKER = b"GRIDBOT_OWNED_LAB_V1\n"
MAX_PACKS = 32


def no_links(path: Path) -> None:
    require(
        path.is_absolute() and not str(path).startswith(("\\\\", "//")),
        "Pasta local absoluta exigida",
    )
    require(
        not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)), "Links recusados"
    )


class Library:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.builtin = {digest(raw): raw for raw in bundled().values()}
        self.pending: OrderedDict[str, tuple[float, Pack]] = OrderedDict()
        self.cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.cache_hits = 0
        if root is not None:
            no_links(root)
            if not root.exists():
                root.mkdir(parents=False)
            marker = root / ".gridbot-lab-v1"
            if not marker.exists():
                require(not any(root.iterdir()), "Persistência exige pasta nova ou vazia")
                with marker.open("xb") as stream:
                    stream.write(MARKER)
            self.check_root()

    def check_root(self) -> None:
        if self.root is None:
            raise ValueError("Persistência desativada. Use --lab-dir explicitamente")
        no_links(self.root)
        marker = self.root / ".gridbot-lab-v1"
        no_links(marker)
        with marker.open("rb") as stream:
            require(stream.read(len(MARKER) + 1) == MARKER, "Pasta sem identidade de laboratório")

    def owned_paths(self) -> list[Path]:
        if self.root is None:
            return []
        self.check_root()
        paths = sorted(self.root.glob("*.gbpack"))
        require(len(paths) <= MAX_PACKS, "Biblioteca excede limite")
        for path in paths:
            no_links(path)
            require(bool(re.fullmatch(r"[a-f0-9]{64}\.gbpack", path.name)), "Índice local inválido")
        return paths

    def get(self, identity: str) -> Pack:
        require(bool(re.fullmatch(r"[a-f0-9]{64}", identity)), "Identidade de pack inválida")
        if identity in self.builtin:
            return read_pack(self.builtin[identity])
        self.check_root()
        assert self.root is not None  # noqa: S101 - established by check_root
        path = self.root / (identity + ".gbpack")
        no_links(path)
        with path.open("rb") as stream:
            raw = stream.read(MAX_UPLOAD + 1)
        require(digest(raw) == identity, "Pack local adulterado")
        return read_pack(raw)

    def describe(self, pack: Pack, origin: str) -> dict[str, Any]:
        return {
            "id": pack.sha256,
            **deepcopy(pack.manifest),
            "origin": origin,
            "integrity": "VALIDATED",
            "provenance": "DECLARED_NOT_AUTHENTICATED",
            "manifest_sha256": pack.manifest_sha256,
            "wallets": len(pack.results["accounts"]),
            "marks": sum(len(a["points"]) for a in pack.results["accounts"]),
            "policies": sorted(
                {a["policy"] for a in pack.results["accounts"]}
                | {a["policy"] for a in pack.results["aggregates"]}
            ),
            "benchmarks": sorted(
                {a["benchmark"] for a in pack.results["accounts"] if a["benchmark"]}
            ),
            "costs": sorted(
                {a["cost_scenario"] for a in pack.results["accounts"]}
                | {a["cost_scenario"] for a in pack.results["aggregates"]}
            ),
            "deletable": origin == "LOCAL_CONFIRMED",
        }

    def catalog(self) -> dict[str, Any]:
        rows = [self.describe(self.get(identity), "BUNDLED") for identity in sorted(self.builtin)]
        for path in self.owned_paths():
            identity = path.stem
            if identity in self.builtin:
                continue
            try:
                rows.append(self.describe(self.get(identity), "LOCAL_CONFIRMED"))
            except (ValueError, OSError):
                rows.append(
                    {
                        "id": identity,
                        "source_kind": "DATA_INVALID",
                        "title": "Pack local inválido",
                        "integrity": "INVALID",
                        "provenance": "UNAVAILABLE",
                        "deletable": True,
                    }
                )
        return {
            "studies": rows,
            "persistence_enabled": self.root is not None,
            "historical_source": "DATA_UNAVAILABLE_UNLESS_EXPLICIT_ARCHIVE_ADAPTER",
        }

    def preview(self, raw: bytes) -> dict[str, Any]:
        pack = read_pack(raw)
        now = time.monotonic()
        self.pending = OrderedDict((k, v) for k, v in self.pending.items() if now - v[0] < 300)
        token = secrets.token_hex(32)
        self.pending[token] = (now, pack)
        while len(self.pending) > 2:
            self.pending.popitem(last=False)
        return {
            "preview_token": token,
            "study": self.describe(pack, "PREVIEW_ONLY"),
            "persistence_enabled": self.root is not None,
            "expires_seconds": 300,
        }

    def confirm(self, token: str, confirmed: bool) -> dict[str, Any]:
        self.check_root()
        require(confirmed is True and token in self.pending, "Confirmação explícita exigida")
        created, pack = self.pending[token]
        require(time.monotonic() - created < 300, "Prévia expirada")
        if pack.sha256 in self.builtin:
            del self.pending[token]
            return self.describe(pack, "BUNDLED")
        assert self.root is not None  # noqa: S101 - established by check_root
        path = self.root / (pack.sha256 + ".gbpack")
        no_links(path)
        if path.exists():
            require(self.get(pack.sha256).raw == pack.raw, "Sem sobrescrita silenciosa")
        else:
            require(len(self.owned_paths()) < MAX_PACKS, "Biblioteca cheia")
            temporary = self.root / (".pending-" + secrets.token_hex(16))
            try:
                with temporary.open("xb") as stream:
                    stream.write(pack.raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        del self.pending[token]
        return self.describe(self.get(pack.sha256), "LOCAL_CONFIRMED")

    def remove(self, identity: str, confirmed: bool) -> None:
        self.check_root()
        require(
            confirmed is True
            and identity not in self.builtin
            and bool(re.fullmatch(r"[a-f0-9]{64}", identity)),
            "Remoção não autorizada",
        )
        assert self.root is not None  # noqa: S101 - established by check_root
        path = self.root / (identity + ".gbpack")
        no_links(path)
        path.unlink()
        self.cache = OrderedDict(
            (k, v) for k, v in self.cache.items() if not k.startswith(identity + ":")
        )

    def analysis(
        self, identity: str, selected: list[str] | None = None, objectives: list[str] | None = None
    ) -> dict[str, Any]:
        return self.snapshot(identity, selected, objectives)[1]

    def snapshot(
        self, identity: str, selected: list[str] | None = None, objectives: list[str] | None = None
    ) -> tuple[Pack, dict[str, Any]]:
        pack = self.get(identity)  # revalidate bytes even on hit; never trust stat alone
        key = identity + ":" + digest(canonical([ANALYTICS_VERSION, selected, objectives]))
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
        else:
            self.cache[key] = analyze(pack, selected, objectives)
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        return pack, deepcopy(self.cache[key])
