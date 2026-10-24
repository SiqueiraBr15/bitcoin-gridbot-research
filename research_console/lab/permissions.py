"""Export consent is operator state, never an assertion trusted from imported data."""

from __future__ import annotations

from types import MappingProxyType

from research_console.lab.fixtures import bundled
from research_console.lab.packs import Pack, digest

SCOPES = ("DERIVED_ONLY", "RAW_AND_DERIVED")
BASES = ("OWN_DATA", "VERIFIED_PUBLIC_LICENSE", "RIGHTSHOLDER_PERMISSION")
PROJECT_PACKS = MappingProxyType({digest(raw): raw for raw in bundled().values()})


def export_scope(pack: Pack, operator_scope: str | None = None) -> str | None:
    if pack.manifest["redistribution"] == "RESTRICTED":
        return None
    if PROJECT_PACKS.get(pack.sha256) == pack.raw:
        return "RAW_AND_DERIVED"
    if operator_scope not in SCOPES:
        return None
    if pack.manifest["redistribution"] == "AGGREGATES_ONLY":
        return "DERIVED_ONLY"
    return operator_scope
