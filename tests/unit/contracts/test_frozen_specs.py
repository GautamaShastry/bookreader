"""Frozen spec baseline: checksum manifest and the packaged v1.4 validator (BS-001)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from bookscope_contracts import find_specs_dir

REPO_ROOT = Path(__file__).resolve().parents[3]


def manifest_problems(specs: Path) -> tuple[int, list[str]]:
    problems: list[str] = []
    checked = 0
    for line in (specs / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        path = specs / relative
        checked += 1
        if not path.is_file():
            problems.append(f"MISSING: {relative}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"CHANGED: {relative}")
    return checked, problems


def test_frozen_spec_checksums_match_manifest() -> None:
    checked, problems = manifest_problems(find_specs_dir())
    assert checked == 36
    assert problems == []


def test_checksum_check_detects_tampering_and_deletion(tmp_path: Path) -> None:
    copy = tmp_path / "specs"
    shutil.copytree(find_specs_dir(), copy)
    (copy / "06-API-OPENAPI.yaml").write_bytes(
        (copy / "06-API-OPENAPI.yaml").read_bytes() + b"\n# tampered\n"
    )
    (copy / "schemas" / "answer.schema.json").unlink()
    _, problems = manifest_problems(copy)
    assert sorted(problems) == [
        "CHANGED: 06-API-OPENAPI.yaml",
        "MISSING: schemas/answer.schema.json",
    ]


def test_checksum_check_detects_crlf_conversion(tmp_path: Path) -> None:
    # Guards the .gitattributes eol=lf rule: a CRLF checkout must not silently pass.
    copy = tmp_path / "specs"
    shutil.copytree(find_specs_dir(), copy)
    target = copy / "15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    _, problems = manifest_problems(copy)
    assert problems == ["CHANGED: 15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md"]


def test_packaged_v14_contract_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(find_specs_dir() / "tests-contract" / "validate_v14_contracts.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "v1.4 contract checks PASS" in result.stdout


def test_verify_specs_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_specs.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: checksum validation for 36 frozen spec files" in result.stdout
