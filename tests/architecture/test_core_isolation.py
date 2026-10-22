"""Regras de arquitetura (ADR-001, ADR-002, ADR-005) verificadas estaticamente via AST."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "gridbot"

CORE_PACKAGES = ("domain", "strategy", "risk", "execution", "portfolio", "application")
CORE_PREFIXES = tuple(f"gridbot.{pkg}" for pkg in CORE_PACKAGES)
CORE_STDLIB = frozenset(
    {
        "__future__",
        "abc",
        "bisect",
        "collections",
        "contextlib",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "itertools",
        "math",
        "operator",
        "re",
        "typing",
    }
)
NETWORK_LIBS = frozenset(
    {"httpx", "websockets", "requests", "aiohttp", "urllib3", "ccxt", "binance", "fastapi"}
)
WALL_CLOCK_CALLS = frozenset({"now", "utcnow", "today", "time", "monotonic", "perf_counter"})
CLOCK_OWNERS = frozenset({"datetime", "date", "time"})
RANDOMNESS = frozenset({"uuid", "random", "secrets"})


def python_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


CORE_FILES = [p for pkg in CORE_PACKAGES for p in python_files(pkg)]


def test_a16_is_pure_observation_without_sell_effects_or_legacy_snapshot() -> None:
    tree = parse(SRC / "application" / "sell_fills.py")
    modules = imported_modules(tree)
    assert all(m.split(".")[0] in CORE_STDLIB or m.startswith(CORE_PREFIXES) for m in modules)
    names = _identifiers(tree)
    forbidden = {
        "ExchangePort",
        "OrderSnapshot",
        "Balance",
        "Wallet",
        "FeeSchedule",
        "Clock",
        "confirm_sell",
        "settle_sell",
        "FinalizedSell",
        "ObservedSellTerminalReport",
        "profit_harvesting",
        "open",
        "read_text",
        "write_text",
        "sqlite3",
        "send_order",
        "place_order",
        "get_balance",
        "api_key",
        "uuid4",
        "random",
    }
    assert not names & forbidden
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden | WALL_CLOCK_CALLS


def _id(path: Path) -> str:
    return str(path.relative_to(SRC))


@pytest.mark.parametrize("path", CORE_FILES, ids=_id)
def test_core_imports_only_stdlib_subset_and_core(path: Path) -> None:
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        allowed = top in CORE_STDLIB or module.startswith(CORE_PREFIXES)
        assert allowed, f"{_id(path)} importa '{module}', proibido no núcleo"


@pytest.mark.parametrize("path", CORE_FILES, ids=_id)
def test_core_never_reads_wall_clock(path: Path) -> None:
    for node in ast.walk(parse(path)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WALL_CLOCK_CALLS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in CLOCK_OWNERS
        ):
            pytest.fail(f"{_id(path)}:{node.lineno} lê o relógio real; use Clock")


@pytest.mark.parametrize("path", CORE_FILES, ids=_id)
def test_core_has_no_randomness(path: Path) -> None:
    for module in imported_modules(parse(path)):
        assert module.split(".")[0] not in RANDOMNESS, f"{_id(path)} importa '{module}'"


@pytest.mark.parametrize("path", CORE_FILES, ids=_id)
def test_core_has_no_float_literals(path: Path) -> None:
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"{_id(path)}:{node.lineno} contém literal float ({node.value})")


@pytest.mark.parametrize(
    "path",
    [
        SRC / "exchange" / "ports.py",
        SRC / "marketdata" / "ports.py",
        SRC / "marketdata" / "in_memory.py",  # adapter sem I/O: mesma restrição dos ports
    ],
    ids=_id,
)
def test_ports_and_pure_adapters_depend_only_on_domain(path: Path) -> None:
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith("gridbot.domain"), module


def test_no_network_library_anywhere_in_phase_zero() -> None:
    for path in sorted(SRC.rglob("*.py")):
        for module in imported_modules(parse(path)):
            assert module.split(".")[0] not in NETWORK_LIBS, f"{_id(path)} importa '{module}'"


def test_binance_namespace_contains_only_authorized_offline_translation() -> None:
    files = sorted(p.name for p in (SRC / "exchange" / "binance").rglob("*.py"))
    assert files == [
        "__init__.py",
        "offline_evidence.py",
        "offline_replay.py",
        "offline_terminal.py",
    ]
    tree = parse(SRC / "exchange" / "binance" / "__init__.py")
    assert all(isinstance(node, ast.Expr) for node in tree.body)  # apenas docstring


STRATEGY_FILES = python_files("strategy")


@pytest.mark.parametrize("path", STRATEGY_FILES, ids=_id)
def test_strategy_depends_only_on_domain_and_strategy(path: Path) -> None:
    # Mais estrito que o núcleo: a estratégia não conhece execução, portfolio nem risco.
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        allowed = top in CORE_STDLIB or module.startswith(("gridbot.domain", "gridbot.strategy"))
        assert allowed, f"{_id(path)} importa '{module}'"


def test_grid_state_creates_no_orders_and_has_no_quantity() -> None:
    # A4: estado operacional puro; ordens e sizing pertencem à A5 em diante.
    tree = parse(SRC / "strategy" / "grid_state.py")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    forbidden = {"OrderIntent", "Qty", "Fill", "Balance", "Money"}
    forbidden |= {"ClientOrderId", "SequentialIdGenerator", "IdGenerator"}  # A6: sem ids globais
    assert not names & forbidden


def test_grid_sizing_creates_no_orders_reads_no_wallet_and_computes_no_fees() -> None:
    # A5: sizing é plano de compra; ordens, fills, saldos e fees ficam para fases futuras.
    tree = parse(SRC / "strategy" / "grid_sizing.py")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    forbidden = {"OrderIntent", "ClientOrderId", "Fill", "Balance", "FeeSchedule", "LiquidityRole"}
    assert not names & forbidden


def _identifiers(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def test_buy_intents_have_no_exchange_identity_execution_or_fees() -> None:
    # A7: intenção de estratégia, não ordem de exchange; o OrderIntent de execução
    # (client_order_id + timestamp) não é usado.
    names = _identifiers(parse(SRC / "strategy" / "buy_intents.py"))
    forbidden = {
        "OrderIntent",
        "ClientOrderId",
        "client_order_id",
        "exchange_order_id",
        "Fill",
        "Balance",
        "FeeSchedule",
        "LiquidityRole",
    }
    assert not names & forbidden


def test_buy_fill_accounting_depends_only_on_domain_and_strategy() -> None:
    # A8: contabilidade pura; não conhece execução, exchange, storage nem risco.
    path = SRC / "portfolio" / "buy_fills.py"
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        allowed = top in CORE_STDLIB or module.startswith(("gridbot.domain", "gridbot.strategy"))
        assert allowed, f"{_id(path)} importa '{module}'"


def test_buy_fill_accounting_has_no_exchange_identity_wallet_or_state_mutation() -> None:
    # A8: sem Fill/OrderIntent de execução, sem saldo de carteira, sem FeeSchedule
    # substituindo a fee observada e sem mexer no GridState.
    names = _identifiers(parse(SRC / "portfolio" / "buy_fills.py"))
    forbidden = {
        "OrderIntent",
        "Fill",
        "ClientOrderId",
        "client_order_id",
        "exchange_order_id",
        "executed_at",
        "Balance",
        "FeeSchedule",
        "GridState",
        "confirm_buy",
        "confirm_sell",
    }
    assert not names & forbidden


def test_buy_fill_accounting_never_relaxes_financial_precision() -> None:
    # A8.2: erros de precisão viram FINANCIAL_PRECISION_ERROR; o contexto financeiro não
    # pode ser alterado, relaxado nem contornado com arredondamento neste módulo.
    names = _identifiers(parse(SRC / "portfolio" / "buy_fills.py"))
    forbidden = {"getcontext", "setcontext", "localcontext", "quantize", "Context"}
    forbidden |= {n for n in names if n.startswith("ROUND_")}
    assert not names & forbidden


def test_buy_finalization_depends_only_on_domain_strategy_and_portfolio() -> None:
    # A9: finalização pura; sem execução, exchange, storage nem ExchangePort.
    path = SRC / "portfolio" / "buy_finalization.py"
    prefixes = ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio")
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith(prefixes), f"{_id(path)} importa '{module}'"


def test_buy_finalization_never_touches_grid_state_orders_or_precision_context() -> None:
    # A9: produz evidência econômica; não transita GridState, não cria ordens/SELL e não
    # reutiliza o OrderStatus de nomenclatura da exchange.
    names = _identifiers(parse(SRC / "portfolio" / "buy_finalization.py"))
    forbidden = {
        "GridState",
        "confirm_buy",
        "confirm_sell",
        "OrderIntent",
        "OrderStatus",
        "ClientOrderId",
        "client_order_id",
        "exchange_order_id",
        "Fill",
        "Balance",
        "FeeSchedule",
        "ExchangePort",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
    }
    assert not names & forbidden
    assert not {n for n in names if "SellIntent" in n or "retry" in n.lower()}


def test_sell_sizing_depends_only_on_domain_strategy_and_portfolio() -> None:
    # A10: avaliação pura; sem execução, exchange, storage nem ExchangePort.
    path = SRC / "portfolio" / "sell_sizing.py"
    prefixes = ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio")
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith(prefixes), f"{_id(path)} importa '{module}'"


def test_sell_sizing_creates_no_orders_reserves_or_fee_estimates() -> None:
    # A10: SELL_SIZING_ELIGIBLE != SELL_ORDER_AUTHORIZED; nada de ordem, reserva, débito,
    # fee de venda, transição de estado, inventário isolado como entrada ou BTC Core.
    names = _identifiers(parse(SRC / "portfolio" / "sell_sizing.py"))
    forbidden = {
        "OrderIntent",
        "ClientOrderId",
        "client_order_id",
        "GridBuyIntent",
        "FeeSchedule",
        "LiquidityRole",
        "Balance",
        "GridOwnedInventory",
        "confirm_buy",
        "confirm_sell",
        "record",
        "ceil",
        "ceil_to_increment",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
    }
    assert not names & forbidden
    assert not {n for n in names if "SellIntent" in n or "reserve" in n.lower()}


APPLICATION_FILES = python_files("application")


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=_id)
def test_application_depends_only_on_pure_layers(path: Path) -> None:
    # A11: orquestração pura; importa domínio, strategy e portfolio, nunca execução/exchange.
    prefixes = ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio", "gridbot.application")
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith(prefixes), f"{_id(path)} importa '{module}'"


@pytest.mark.parametrize("path", STRATEGY_FILES + python_files("portfolio"), ids=_id)
def test_no_inverse_dependency_on_application(path: Path) -> None:
    for module in imported_modules(parse(path)):
        assert not module.startswith("gridbot.application"), f"{_id(path)} importa '{module}'"


@pytest.mark.parametrize("path", APPLICATION_FILES, ids=_id)
def test_application_sends_no_orders_and_touches_no_balances(path: Path) -> None:
    # A11: book lógico; sem ordem real, client order id, reserva, saldo, fee de venda ou SELL.
    names = _identifiers(parse(path))
    forbidden = {
        "ExchangePort",
        "place_order",
        "OrderIntent",
        "ClientOrderId",
        "client_order_id",
        "Balance",
        "FeeSchedule",
        "confirm_sell",
        "assess_sell_sizing",
        "getcontext",
        "setcontext",
        "localcontext",
    }
    assert not names & forbidden
    # A14 abriu UM módulo para intenções SELL puras (e o facade que o reexporta); os demais
    # módulos de application continuam sem conhecer SELL.
    sell_intents_allowed = path.name in {
        "sell_intents.py",
        "sell_lifecycle.py",
        "operational_grid.py",
        "operational_persistence.py",
        "__init__.py",
    }
    assert not {
        n for n in names if ("SellIntent" in n and not sell_intents_allowed) or "retry" in n.lower()
    }


def test_buy_quote_capital_uses_no_external_balance_fee_estimate_or_capital_flow() -> None:
    # A12: capital fixo e fee hold explícito do chamador; sem saldo externo, wallet, estimativa
    # de fee, depósito/saque, BTC Core ou SELL.
    names = _identifiers(parse(SRC / "application" / "buy_quote_capital.py"))
    forbidden = {"Balance", "FeeSchedule", "LiquidityRole", "ExchangePort", "OrderIntent"}
    forbidden |= {"place_order", "confirm_sell", "assess_sell_sizing", "SellSizingAssessment"}
    assert not names & forbidden
    words = ("wallet", "deposit", "withdraw", "sell", "core", "estimate", "retry")
    assert not {n for n in names if any(w in n.lower() for w in words)}


def test_sell_inventory_depends_only_on_pure_layers() -> None:
    path = SRC / "application" / "sell_inventory.py"
    prefixes = ("gridbot.domain", "gridbot.strategy", "gridbot.portfolio", "gridbot.application")
    for module in imported_modules(parse(path)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith(prefixes), module


def test_sell_inventory_has_no_execution_external_inventory_or_rounding() -> None:
    names = _identifiers(parse(SRC / "application" / "sell_inventory.py"))
    forbidden = {
        "ExchangePort",
        "Balance",
        "GridOwnedInventory",
        "OrderIntent",
        "ClientOrderId",
        "FeeSchedule",
        "LiquidityRole",
        "place_order",
        "confirm_buy",
        "confirm_sell",
        "record",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
        "ceil",
        "ceil_to_increment",
        "floor",
        "floor_to_increment",
        "assess_sell_sizing",
        "open",
        "Path",
        "connect",
        "datetime",
        "uuid",
        "random",
        "asyncio",
    }
    assert not names & forbidden
    words = ("wallet", "harvest", "profit", "pnl", "revenue", "client_order", "retry")
    assert not {n for n in names if any(w in n.lower() for w in words) or "SellIntent" in n}
    assert not {n for n in names if n.startswith("ROUND_")}


def test_sell_inventory_has_no_state_or_inventory_copy_fields() -> None:
    tree = parse(SRC / "application" / "sell_inventory.py")
    fields = {
        node.name: {
            n.target.id
            for n in node.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    assert fields["SellInventoryBook"] == {"funded_buy_book", "reservations"}
    assert fields["SellBaseInventoryReservation"] == {"assessment", "base_fee_hold"}


SELL_INTENTS = SRC / "application" / "sell_intents.py"


def test_only_sell_intents_may_mention_sell_intents_and_nothing_imports_it() -> None:
    # A14: dependência em um sentido só; A11-A13 continuam sem conhecer intenções SELL.
    for path in APPLICATION_FILES:
        if path in {
            SELL_INTENTS,
            SRC / "application" / "__init__.py",
            SRC / "application" / "sell_lifecycle.py",
            SRC / "application" / "operational_grid.py",
            SRC / "application" / "operational_persistence.py",
        }:  # facade reexporta; somente A15 pode depender da A14
            continue
        for module in imported_modules(parse(path)):
            assert module != "gridbot.application.sell_intents", _id(path)
    for path in STRATEGY_FILES + python_files("portfolio") + python_files("domain"):
        assert not any(m.startswith("gridbot.application") for m in imported_modules(parse(path)))


def test_sell_intents_depends_only_on_pure_layers_and_a13() -> None:
    allowed = (
        "gridbot.domain",
        "gridbot.strategy",
        "gridbot.portfolio",
        "gridbot.application.sell_inventory",
    )
    for module in imported_modules(parse(SELL_INTENTS)):
        top = module.split(".")[0]
        assert top in CORE_STDLIB or module.startswith(allowed), module
    forbidden_layers = (
        "gridbot.exchange",
        "gridbot.config",
        "gridbot.infra",
        "gridbot.storage",
        "gridbot.marketdata",
        "gridbot.cli",
        "gridbot.observability",
    )
    assert not any(m.startswith(forbidden_layers) for m in imported_modules(parse(SELL_INTENTS)))


def test_sell_intents_has_no_orders_ids_fills_settlement_io_or_rounding() -> None:
    names = _identifiers(parse(SELL_INTENTS))
    forbidden = {
        "ExchangePort",
        "place_order",
        "OrderIntent",
        "ClientOrderId",
        "client_order_id",
        "Balance",
        "FeeSchedule",
        "LiquidityRole",
        "ObservedBuyFill",
        "BuyFillLedger",
        "GridOwnedInventory",
        "confirm_buy",
        "confirm_sell",
        "disarm_buy",
        "record",
        "assess_sell_sizing",
        "reserve_sell_inventory",
        "settle_inventory_book_buy",
        "settle_funded_buy",
        "prepare_funded_buy",
        "bind_funded_buy_execution",
        "consume_finalized_buy",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
        "floor",
        "ceil",
        "floor_to_increment",
        "ceil_to_increment",
        "open",
        "Path",
        "connect",
        "sqlite3",
        "datetime",
        "time",
        "uuid",
        "random",
        "asyncio",
        "os",
        "subprocess",
    }
    assert not names & forbidden
    words = (
        "wallet",
        "harvest",
        "profit",
        "pnl",
        "revenue",
        "proceeds",
        "client_order",
        "retry",
        "settle",
        "fill",
        "timestamp",
        "binance",
    )
    assert not {n for n in names if any(w in n.lower() for w in words)}
    assert not {n for n in names if n.startswith("ROUND_")}


def test_sell_intents_never_rebuilds_books_or_replaces_reservations() -> None:
    tree = parse(SELL_INTENTS)
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not constructed & {"SellInventoryBook", "FundedBuyBook", "BuyLifecycleBook"}
    keywords = {
        kw.arg for node in ast.walk(tree) if isinstance(node, ast.Call) for kw in node.keywords
    }
    assert not keywords & {"reservations", "funded_buy_book", "grid_state", "lifecycle"}


def test_sell_intents_models_keep_only_their_sources() -> None:
    tree = parse(SELL_INTENTS)
    fields = {
        node.name: {
            n.target.id
            for n in node.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    assert fields["GridSellIntent"] == {"reservation"}
    assert fields["SellIntentPlan"] == {"book", "cycle_refs"}


def test_sell_intents_performs_no_financial_arithmetic() -> None:
    # A14 somente deriva campos da A13; cálculo financeiro pertence ao portfolio/book.
    tree = parse(SELL_INTENTS)
    assert not any(
        isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod))
        for node in ast.walk(tree)
    )


A15_FILES = [SRC / "application" / name for name in ("operational_grid.py", "sell_lifecycle.py")]


@pytest.mark.parametrize("path", A15_FILES, ids=_id)
def test_a15_has_no_economic_sell_effects_or_external_services(path: Path) -> None:
    names = _identifiers(parse(path))
    forbidden = {
        "confirm_sell",
        "confirm_buy",
        "disarm_buy",
        "place_order",
        "ExchangePort",
        "OrderIntent",
        "ClientOrderId",
        "Balance",
        "FeeSchedule",
        "LiquidityRole",
        "open",
        "Path",
        "connect",
        "sqlite3",
        "datetime",
        "time",
        "random",
        "uuid",
        "os",
        "subprocess",
        "getcontext",
        "setcontext",
        "localcontext",
        "quantize",
        "floor",
        "ceil",
        "record",
    }
    assert not names & forbidden
    words = (
        "wallet",
        "binance",
        "http",
        "websocket",
        "secret",
        "api_key",
        "client_order",
        "harvest",
        "profit",
        "pnl",
        "proceeds",
        "release",
        "cancel",
        "timestamp",
    )
    assert not {n for n in names if any(w in n.lower() for w in words) or n.startswith("ROUND_")}


def test_a11_through_a14_do_not_depend_on_a15() -> None:
    for name in (
        "buy_lifecycle.py",
        "buy_quote_capital.py",
        "sell_inventory.py",
        "sell_intents.py",
    ):
        modules = imported_modules(parse(SRC / "application" / name))
        assert not modules & {
            "gridbot.application.operational_grid",
            "gridbot.application.sell_lifecycle",
        }


def test_a15_keeps_only_canonical_sources_as_fields() -> None:
    fields = {
        node.name: {
            n.target.id
            for n in node.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        for path in A15_FILES
        for node in parse(path).body
        if isinstance(node, ast.ClassDef)
    }
    assert fields["GridOperationalBook"] == {
        "inventory_book",
        "sell_attempts",
        "external_sell_bindings",
    }
    assert fields["SellAttempt"] == {"intent", "status", "execution"}
    assert fields["SellExecutionContext"] == {"intent", "execution_ref"}
    assert fields["SellExecutionRef"] == {"value"}


def test_a15_offers_specific_transitions_and_no_public_book_replacement() -> None:
    tree = parse(A15_FILES[0])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            params = {a.arg for a in node.args.args}
            assert not params & {
                "new_funded_buy_book",
                "new_sell_inventory_book",
                "inventory_book",
                "price",
                "qty",
                "wallet",
            }
