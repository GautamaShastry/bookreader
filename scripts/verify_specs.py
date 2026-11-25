#!/usr/bin/env python3
"""Validate the unchanged frozen specs checksum and available v1.4 contract tests.
This does not validate runtime model accuracy, cloud services or full application code.
"""
from __future__ import annotations
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / 'specs'

def main() -> int:
    manifest = SPECS / 'MANIFEST.sha256'
    issues = []
    checked = 0
    for raw in manifest.read_text(encoding='utf-8').splitlines():
        if not raw.strip():
            continue
        digest, relative = raw.split('  ', 1)
        p = SPECS / relative
        if not p.is_file():
            issues.append('MISSING: ' + relative)
        elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            issues.append('CHANGED: ' + relative)
        checked += 1
    if issues:
        print('FAIL: spec checksum errors:', *issues, sep='\n- ')
        return 1
    print(f'PASS: checksum validation for {checked} frozen spec files')
    try:
        import yaml, jsonschema  # noqa: F401
    except ModuleNotFoundError:
        print('MISSING DEPENDENCIES: install with: python -m pip install pyyaml jsonschema')
        return 2
    run = subprocess.run([sys.executable, str(SPECS / 'tests-contract' / 'validate_v14_contracts.py')], check=False)
    if run.returncode:
        print(f'FAIL: v1.4 contract validator exit code {run.returncode}')
        return run.returncode
    print('PASS: frozen v1.4 contract smoke checks (not product evals)')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
