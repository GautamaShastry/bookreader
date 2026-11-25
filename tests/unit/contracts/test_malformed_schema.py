"""The contract validator must fail loudly on deliberately malformed schemas (BS-001)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bookscope_contracts import check_schema_file

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "contracts" / "malformed-schemas"


def test_invalid_keyword_values_are_reported_with_location() -> None:
    diagnostics = check_schema_file(FIXTURES / "invalid-keyword-values.schema.json")
    assert len(diagnostics) == 1
    message = str(diagnostics[0])
    assert "invalid-keyword-values.schema.json" in message
    assert "invalid JSON Schema at properties/" in message


def test_dangling_ref_is_reported_with_location() -> None:
    diagnostics = check_schema_file(FIXTURES / "dangling-ref.schema.json")
    assert [d.message for d in diagnostics] == [
        "unresolved $ref '#/$defs/Claim' at /properties/claims/items"
    ]


def test_unparseable_json_is_reported() -> None:
    diagnostics = check_schema_file(FIXTURES / "not-json.schema.json")
    assert len(diagnostics) == 1
    assert diagnostics[0].message.startswith("cannot load JSON:")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bookscope_contracts", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_fails_on_malformed_fixture_directory_with_clear_diagnostics() -> None:
    result = _run_cli(str(FIXTURES))
    assert result.returncode == 1, result.stdout + result.stderr
    out = result.stdout
    for name in (
        "dangling-ref.schema.json",
        "invalid-keyword-values.schema.json",
        "not-json.schema.json",
    ):
        assert name in out, out
    assert "FAIL: 3 contract problem(s) in 3 schema file(s)" in out


def test_cli_fails_on_empty_directory(tmp_path: Path) -> None:
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "no *.json schemas found" in result.stdout


def test_cli_passes_on_frozen_specs() -> None:
    result = _run_cli()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("PASS: 5 schema file(s) valid")
