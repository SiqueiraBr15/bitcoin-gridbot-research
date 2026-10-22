"""Run documented test groups with a finite timeout for each explicit target.

Never treats timeout as success. Every existing test remains available in "all".
No coverage options or Hypothesis settings are rewritten by this runner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "smoke": "ci/fast-suite.txt",
    "unit": "ci/unit-suite.txt",
    "integration": "ci/integration-suite.txt",
    "extended": "ci/smoke-suite.txt",  # Historical 930-case list; preserved verbatim.
}


def targets(profile: str) -> list[str]:
    if profile == "all":
        return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py"))
    paths = (ROOT / PROFILES[profile]).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in paths if line.strip()]


def run(profile: str, timeout: int) -> tuple[int, dict[str, object]]:
    env = os.environ.copy()
    env.setdefault("HYPOTHESIS_PROFILE", "ci")
    outcomes = []
    for target in targets(profile):
        command = [sys.executable, "-m", "pytest", "-q", target, "--durations=5"]
        started = perf_counter_ns()
        try:
            result = subprocess.run(  # noqa: S603
                command, cwd=ROOT, env=env, timeout=timeout, check=False
            )
            status = "PASS" if result.returncode == 0 else "FAIL"
            code: int | None = result.returncode
        except subprocess.TimeoutExpired:
            status, code = "TIMEOUT", None
        outcomes.append(
            {
                "target": target,
                "status": status,
                "exit_code": code,
                "elapsed_ns": perf_counter_ns() - started,
            }
        )
        if status != "PASS":
            return 1, {"profile": profile, "status": "INCOMPLETE", "outcomes": outcomes}
    return 0, {"profile": profile, "status": "PASS", "outcomes": outcomes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=(*PROFILES, "all"), default="smoke")
    parser.add_argument("--timeout", type=int, default=90, help="seconds per module/group target")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1800:
        parser.error("timeout must be between 1 and 1800 seconds")
    code, report = run(args.profile, args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201
    return code


if __name__ == "__main__":
    raise SystemExit(main())
