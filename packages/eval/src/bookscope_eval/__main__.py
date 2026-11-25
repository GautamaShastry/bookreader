"""``python -m bookscope_eval`` — validate the fixture manifest and eval cases (EV-001)."""

from __future__ import annotations

import sys

from bookscope_eval.fixtures import (
    FIXTURES_DIR,
    load_cases,
    load_manifest,
    manifest_sha256,
    validate_cases,
    validate_manifest,
)


def main() -> int:
    manifest = load_manifest()
    problems = validate_manifest(manifest)
    rows = load_cases(FIXTURES_DIR / "eval_cases.jsonl")
    if not problems:
        problems += validate_cases(rows, manifest)
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        print(f"FAIL: {len(problems)} fixture/eval-case problem(s)")
        return 1
    fixtures = manifest["fixtures"]
    pending = sum(f["reviewer_status"] != "verified" for f in fixtures)
    print(
        f"PASS: {len(fixtures)} fixtures, {len(rows)} eval cases valid; "
        f"manifest sha256 {manifest_sha256()}"
    )
    print(f"NOTE: {pending}/{len(fixtures)} fixtures await human label review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
