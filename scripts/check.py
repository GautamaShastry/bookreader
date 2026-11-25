#!/usr/bin/env python3
"""Run every BookScope local/CI check: ``python scripts/check.py``.

Runs all steps even after a failure so every failing step is reported, then prints a summary and
exits 1 if anything failed. Needs no AWS credentials and makes no network calls except what the
installed tools already do. Machine-readable results are written to ``test-results/``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# realpath normalises Windows drive-letter case (c:\ vs C:\), which otherwise makes Vitest load
# two copies of itself and fail with "failed to find the current suite".
ROOT = Path(os.path.realpath(Path(__file__).resolve().parents[1]))
WEB = ROOT / "apps" / "web"
RESULTS = ROOT / "test-results"


@dataclass(frozen=True)
class Step:
    name: str
    cmd: list[str]
    cwd: Path = ROOT


def _npm() -> str:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("FAIL: npm not found on PATH (Node.js >= 22.13 required)")
    return npm


def build_steps(*, include_web: bool, include_e2e: bool) -> list[Step]:
    py = sys.executable
    steps = [
        Step("spec checksums + frozen v1.4 validator", [py, "scripts/verify_specs.py"]),
        Step("contract validator (schemas + OpenAPI refs)", [py, "-m", "bookscope_contracts"]),
        Step("fixture manifest + eval cases (EV-001)", [py, "-m", "bookscope_eval"]),
        Step(
            "source-integrity scorecard (EV-002)",
            [py, "-m", "bookscope_eval.source_scorecard", "--out", str(RESULTS)],
        ),
        Step("ruff lint", [py, "-m", "ruff", "check", "."]),
        Step("ruff format --check", [py, "-m", "ruff", "format", "--check", "."]),
        Step("mypy --strict", [py, "-m", "mypy"]),
        Step("pytest", [py, "-m", "pytest", f"--junitxml={RESULTS / 'pytest.xml'}"]),
    ]
    if include_web:
        npm = _npm()
        steps += [
            Step("web: eslint", [npm, "run", "lint"], WEB),
            Step("web: tsc --noEmit", [npm, "run", "typecheck"], WEB),
            Step(
                "web: vitest",
                [
                    npm,
                    "test",
                    "--",
                    "--reporter=default",
                    "--reporter=junit",
                    f"--outputFile.junit={RESULTS / 'vitest.xml'}",
                ],
                WEB,
            ),
            Step("web: vite build", [npm, "run", "build"], WEB),
        ]
        if include_e2e:
            steps.append(Step("web: playwright e2e", [npm, "run", "e2e"], WEB))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-only", action="store_true", help="skip all web steps")
    parser.add_argument("--skip-e2e", action="store_true", help="skip Playwright")
    args = parser.parse_args(argv)

    RESULTS.mkdir(exist_ok=True)
    steps = build_steps(include_web=not args.python_only, include_e2e=not args.skip_e2e)
    results: list[tuple[Step, int, float]] = []
    for index, step in enumerate(steps, start=1):
        print(f"\n=== [{index}/{len(steps)}] {step.name} ===", flush=True)
        started = time.monotonic()
        code = subprocess.run(step.cmd, cwd=step.cwd, check=False).returncode
        results.append((step, code, time.monotonic() - started))

    print("\n=== Summary ===")
    for step, code, seconds in results:
        status = "PASS" if code == 0 else f"FAIL (exit {code})"
        print(f"{status:<14} {seconds:6.1f}s  {step.name}")
    failed = [step.name for step, code, _ in results if code != 0]
    skipped = []
    if args.python_only:
        skipped.append("web")
    elif args.skip_e2e:
        skipped.append("playwright e2e")
    if skipped:
        print(f"SKIPPED: {', '.join(skipped)}")
    if failed:
        print(f"\nFAIL: {len(failed)} of {len(results)} step(s) failed: {', '.join(failed)}")
        return 1
    print(f"\nPASS: all {len(results)} step(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
