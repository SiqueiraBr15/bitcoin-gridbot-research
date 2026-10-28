"""Small route adapter; receives bytes and opaque identities, never local paths."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from research_console.data import decode
from research_console.lab.exports import export_analysis, manifest_for_result, replay
from research_console.lab.library import Library
from research_console.lab.numeric import MAX_ANALYSIS_BYTES, AnalysisError
from research_console.lab.packs import canonical, keys
from research_console.risk import display, require


def error_code(error: BaseException) -> str:
    """Fixed diagnostics; exception values and operator paths never enter HTTP."""
    if isinstance(error, OSError):
        return "DATA_UNAVAILABLE"
    message = str(error)
    for fragments, code in [
        (("Biblioteca ocupada",), "LIBRARY_BUSY"),
        (("SHA-256", "adulterado"), "INTEGRITY_MISMATCH"),
        (("excede", "excessiv"), "SIZE_LIMIT"),
        (("Versão",), "UNSUPPORTED_VERSION"),
        (("Benchmark incompatível",), "INCOMPATIBLE_BENCHMARK"),
        (("NAV não conserva",), "NAV_CONSERVATION_FAILED"),
        (("ordem temporal", "Endpoints"), "INVALID_TIMESTAMPS"),
        (("desativada",), "PERSISTENCE_DISABLED"),
        (("expirada",), "PREVIEW_EXPIRED"),
        (("Confirmação",), "CONFIRMATION_REQUIRED"),
        (("bloqueado", "Redistribuição", "Revisão explícita", "autoriza"), "EXPORT_RESTRICTED"),
    ]:
        if any(fragment in message for fragment in fragments):
            return code
    return "INVALID_SCHEMA_OR_DATA"


def selection(query: dict[str, list[str]]) -> tuple[str, list[str] | None, list[str] | None]:
    require(
        set(query) <= {"id", "accounts", "objectives", "reviewed"}
        and "id" in query
        and all(len(v) == 1 and bool(v[0]) for v in query.values()),
        "Seleção inválida",
    )
    return (
        query["id"][0],
        query["accounts"][0].split(",") if "accounts" in query else None,
        query["objectives"][0].split(",") if "objectives" in query else None,
    )


def get(library: Library, route: str, query: dict[str, list[str]]) -> tuple[bytes, str, str | None]:
    if route == "/api/lab/library":
        require(not query, "Seleção inválida")
        return canonical(library.catalog()), "application/json", None
    identity, accounts, objectives = selection(query)
    if route == "/api/lab/analysis":
        require("reviewed" not in query, "Seleção inválida")
        pack, result = library.snapshot(identity, accounts, objectives)
        result["analysis_manifest"] = manifest_for_result(pack, result)
        result["export_scope"] = library.export_scope(pack)
        # Only the selected source's validated observations; none are synthesized.
        result["accounts"] = [
            a for a in pack.results["accounts"] if accounts is None or a["account_id"] in accounts
        ]
        try:
            raw = canonical(result)
        except (ValueError, TypeError, OverflowError) as error:
            raise AnalysisError("Internal analytical serialization failed") from error
        if len(raw) > MAX_ANALYSIS_BYTES:
            raise AnalysisError("Analysis response exceeds the transport budget")
        return raw, "application/json", None
    pack = library.get(identity)
    if route == "/api/lab/source":
        require(
            set(query) == {"id"} and library.export_scope(pack) == "RAW_AND_DERIVED",
            "Redistribuição bruta não autorizada",
        )
        return pack.raw, "application/zip", "gridbot-evidence.gbpack"
    if route == "/api/lab/export":
        require(query.get("reviewed", ["0"])[0] in ("0", "1"), "Revisão inválida")
        raw = export_analysis(
            pack,
            accounts,
            objectives,
            reviewed=query.get("reviewed") == ["1"],
            permission=library.export_scope(pack),
        )
        return raw, "application/zip", "gridbot-analysis.zip"
    raise ValueError("Rota inválida")


def post(library: Library, route: str, raw: bytes) -> dict[str, Any]:
    if route == "/api/lab/preview":
        return library.preview(raw)
    data = decode(raw)
    if route == "/api/lab/authorize-export":
        keys(data, {"id", "scope", "basis", "confirmed"})
        return library.authorize_export(data["id"], data["scope"], data["basis"], data["confirmed"])
    if route == "/api/lab/confirm":
        keys(data, {"preview_token", "confirmed"})
        return library.confirm(data["preview_token"], data["confirmed"])
    if route == "/api/lab/remove":
        keys(data, {"id", "confirmed"})
        library.remove(data["id"], data["confirmed"])
        return {"status": "REMOVED_OWNED_COPY_ONLY"}
    if route == "/api/lab/replay":
        keys(data, {"id", "manifest"})
        return replay(library.get(data["id"]), data["manifest"])
    raise ValueError("Rota inválida")


def paper_trace(account: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconcile existing simulated fills; no order or strategy is executed here."""
    first = account["series"][0]
    cash, btc = Fraction(first["cash"]), Fraction(first["btc"])
    events = []
    for index, fill in enumerate(account["fills"]):
        qty, price, fee = (Fraction(fill[k]) for k in ("btc", "price", "fee_usdt"))
        before_cash, before_btc = cash, btc
        buy = fill["side"] == "BUY"
        cash += -qty * price - fee if buy else qty * price - fee
        btc += qty if buy else -qty
        require(min(cash, btc) >= 0, "Conservação de fills inválida")
        events.append(
            {
                "fill_index": index,
                **fill,
                "before_cash": display(before_cash),
                "after_cash": display(cash),
                "before_btc": display(before_btc),
                "after_btc": display(btc),
                "delta_cash": display(cash - before_cash),
                "delta_btc": display(btc - before_btc),
                "reconciliation": "FRACTION_EXACT",
            }
        )
    require(
        cash == Fraction(account["series"][-1]["cash"])
        and btc == Fraction(account["series"][-1]["btc"]),
        "Saldo de fills divergente",
    )
    return events
