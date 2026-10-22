"""Offline entry point: python -m gridbot.backtest; never changes trading modes."""

from __future__ import annotations

import argparse
import sys
from decimal import DecimalException
from pathlib import Path

from gridbot.backtest.configuration import dataset_spec, read_json, scenario
from gridbot.backtest.data import read_csv
from gridbot.backtest.engine import run_backtest
from gridbot.backtest.export import export_run


def main() -> int:
    parser = argparse.ArgumentParser(description="GridBot deterministic OFFLINE backtest")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    try:
        filename, spec = dataset_spec(read_json(args.dataset))
        path = (args.dataset.parent / filename).resolve()
        dataset = read_csv(path, spec)
        result = run_backtest(
            dataset, scenario(read_json(args.configuration)), code_commit=args.code_commit
        )
        export_run(result, args.output, dataset=dataset)
    except (ValueError, TypeError, OSError, DecimalException) as exc:
        sys.stderr.write(f"BACKTEST_REFUSED: {exc}\n")
        return 2
    sys.stdout.write("OFFLINE_BACKTEST_EXPORTED\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
