"""Ponto de entrada ``gridbot``.

Códigos de saída do ``doctor``: 0 = READY, 1 = WARNING, 2 = BLOCKED.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from gridbot import __version__
from gridbot.cli.doctor import DoctorContext, overall, render_report, run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gridbot",
        description="GridBot Spot BTC/USDT -- Fase 0 (fundação). Não envia ordens reais.",
    )
    parser.add_argument("--version", action="version", version=f"gridbot {__version__}")
    sub = parser.add_subparsers(dest="command")
    doctor = sub.add_parser("doctor", help="diagnostica o ambiente local (READY/WARNING/BLOCKED)")
    doctor.add_argument(
        "--create-dirs",
        action="store_true",
        help="cria os diretórios de dados/logs configurados, se ausentes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        checks = run_doctor(DoctorContext.from_runtime(create_dirs=args.create_dirs))
        print(render_report(checks))
        return overall(checks).exit_code
    parser.print_help()
    return 0
