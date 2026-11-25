"""CLI: ``python -m bookscope_contracts [SCHEMA_DIR ...]``.

Validates every ``*.json`` schema in the given directories (default: ``specs/schemas``) and
the OpenAPI document's local refs. Exits 1 with one diagnostic line per problem.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bookscope_contracts.loader import find_specs_dir, load_openapi
from bookscope_contracts.refs import unresolved_local_refs
from bookscope_contracts.validation import SchemaDiagnostic, check_schema_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bookscope_contracts")
    parser.add_argument("schema_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)

    dirs: list[Path] = args.schema_dirs or [find_specs_dir() / "schemas"]
    files = sorted(p for d in dirs for p in d.glob("*.json"))
    if not files:
        print(f"FAIL: no *.json schemas found in {', '.join(map(str, dirs))}")
        return 1
    diagnostics: list[SchemaDiagnostic] = []
    for path in files:
        diagnostics.extend(check_schema_file(path))
    if not args.schema_dirs:
        openapi_path = find_specs_dir() / "06-API-OPENAPI.yaml"
        diagnostics.extend(
            SchemaDiagnostic(openapi_path, f"unresolved $ref {r.ref!r} at {r.location}")
            for r in unresolved_local_refs(load_openapi())
        )
    for diagnostic in diagnostics:
        print(f"FAIL: {diagnostic}")
    if diagnostics:
        print(f"FAIL: {len(diagnostics)} contract problem(s) in {len(files)} schema file(s)")
        return 1
    print(f"PASS: {len(files)} schema file(s) valid, all local refs resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
