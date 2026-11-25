"""EV-001: fixture manifest, licensing, hashes and eval-case integrity."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bookscope_eval.fixtures import (
    FIXTURES_DIR,
    Problem,
    load_cases,
    load_manifest,
    validate_cases,
    validate_manifest,
)

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def manifest() -> dict[str, Any]:
    return load_manifest()


@pytest.fixture
def fixtures_copy(tmp_path: Path) -> Path:
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, target)
    return target


def _messages(problems: list[Problem]) -> str:
    return "\n".join(map(str, problems))


# --- positive ---------------------------------------------------------------------------------


def test_committed_manifest_is_valid(manifest: dict[str, Any]) -> None:
    problems = validate_manifest(manifest)
    assert problems == [], _messages(problems)


def test_committed_eval_cases_are_valid(manifest: dict[str, Any]) -> None:
    rows = load_cases(FIXTURES_DIR / "eval_cases.jsonl")
    assert len(rows) >= 10
    problems = validate_cases(rows, manifest)
    assert problems == [], _messages(problems)


def test_corpus_meets_ev001_minimums(manifest: dict[str, Any]) -> None:
    accepted = [f for f in manifest["fixtures"] if f["expected_outcome"]["status"] == "accepted"]
    assert len(manifest["fixtures"]) >= 3
    assert {f["format"] for f in accepted} == {"pdf", "epub"}
    assert all(f["license"]["verified"] for f in manifest["fixtures"])
    assert all(f["license"]["origin"] == "synthetic" for f in manifest["fixtures"])


def test_labels_are_not_claimed_human_verified(manifest: dict[str, Any]) -> None:
    # Generator-derived labels must stay pending until a person reviews them.
    for fixture in manifest["fixtures"]:
        if fixture["label_source"] == "generator":
            assert fixture["reviewer_status"] == "pending_human_review", fixture["fixture_id"]
    rows = load_cases(FIXTURES_DIR / "eval_cases.jsonl")
    assert {row["reviewer_status"] for _, row in rows} == {"pending_human_review"}


def test_committed_fixtures_match_fresh_generation() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_fixtures.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_passes_and_reports_manifest_hash() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bookscope_eval"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout
    assert "manifest sha256" in result.stdout
    assert "await human label review" in result.stdout


# --- negative: manifest -----------------------------------------------------------------------

Mutation = Callable[[dict[str, Any]], None]


def _first(manifest: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    return next(f for f in manifest["fixtures"] if f["fixture_id"] == fixture_id)


def _dup_fixture(m: dict[str, Any]) -> None:
    m["fixtures"].append(copy.deepcopy(m["fixtures"][0]))


def _dup_version(m: dict[str, Any]) -> None:
    m["fixtures"][1]["book_version_id"] = m["fixtures"][0]["book_version_id"]


def _bad_hash(m: dict[str, Any]) -> None:
    m["fixtures"][0]["sha256"] = "0" * 64


def _bad_size(m: dict[str, Any]) -> None:
    m["fixtures"][0]["size_bytes"] += 1


def _unverified_license(m: dict[str, Any]) -> None:
    m["fixtures"][0]["license"]["verified"] = False


def _unknown_license(m: dict[str, Any]) -> None:
    m["fixtures"][0]["license"]["spdx"] = "All-Rights-Reserved"


def _missing_license(m: dict[str, Any]) -> None:
    del m["fixtures"][0]["license"]


def _path_traversal(m: dict[str, Any]) -> None:
    m["fixtures"][0]["path"] = "books/../../secret.pdf"


def _missing_file(m: dict[str, Any]) -> None:
    m["fixtures"][0]["path"] = "books/does-not-exist.pdf"


def _quote_unknown_source(m: dict[str, Any]) -> None:
    _first(m, "pdf-three-chapters")["quotes"][0]["expected_source_ids"] = [
        "pdf-three-chapters:p0099"
    ]


def _quote_foreign_source(m: dict[str, Any]) -> None:
    _first(m, "pdf-three-chapters")["quotes"][0]["expected_source_ids"] = ["epub3-orchard:s0000"]


def _chapter_unknown_source(m: dict[str, Any]) -> None:
    _first(m, "epub3-orchard")["chapters"][0]["source_ids"] = ["epub3-orchard:s0042"]


def _chapter_drops_unit(m: dict[str, Any]) -> None:
    _first(m, "pdf-three-chapters")["chapters"][2]["source_ids"].pop()


def _wrong_ambiguity(m: dict[str, Any]) -> None:
    _first(m, "pdf-three-chapters")["quotes"][-1]["ambiguous"] = False


def _rejected_with_units(m: dict[str, Any]) -> None:
    _first(m, "pdf-corrupt")["source_units"] = [
        {"source_id": "pdf-corrupt:p0000", "status": "readable"}
    ]


def _unknown_error_code(m: dict[str, Any]) -> None:
    _first(m, "pdf-corrupt")["expected_outcome"]["error_code"] = "PDF_SOMETHING"


def _page_gap(m: dict[str, Any]) -> None:
    _first(m, "pdf-three-chapters")["source_units"][3]["page_index"] = 9


def _dup_source(m: dict[str, Any]) -> None:
    units = _first(m, "pdf-three-chapters")["source_units"]
    units[1]["source_id"] = units[0]["source_id"]


MANIFEST_MUTATIONS: dict[str, tuple[Mutation, str]] = {
    "duplicate_fixture_id": (_dup_fixture, "duplicate fixture_id"),
    "duplicate_book_version_id": (_dup_version, "duplicate book_version_id"),
    "sha256_mismatch": (_bad_hash, "sha256 mismatch"),
    "size_mismatch": (_bad_size, "size mismatch"),
    "unverified_license": (_unverified_license, "verified"),
    "unknown_license": (_unknown_license, "All-Rights-Reserved"),
    "missing_license": (_missing_license, "'license' is a required property"),
    "path_traversal": (_path_traversal, "does not match"),
    "missing_file": (_missing_file, "file missing"),
    "quote_unknown_source": (_quote_unknown_source, "cites unknown"),
    "quote_foreign_source": (_quote_foreign_source, "cites unknown"),
    "chapter_unknown_source": (_chapter_unknown_source, "cites unknown"),
    "chapter_drops_unit": (_chapter_drops_unit, "account for every source unit"),
    "wrong_ambiguity_flag": (_wrong_ambiguity, "ambiguity flag wrong"),
    "rejected_fixture_with_units": (_rejected_with_units, "must not declare"),
    "unknown_error_code": (_unknown_error_code, "PDF_SOMETHING"),
    "page_index_gap": (_page_gap, "page_index"),
    "duplicate_source_id": (_dup_source, "duplicate source_id"),
}


@pytest.mark.parametrize("case", sorted(MANIFEST_MUTATIONS))
def test_manifest_negative_case_is_rejected(case: str, manifest: dict[str, Any]) -> None:
    mutate, expected = MANIFEST_MUTATIONS[case]
    mutate(manifest)
    problems = validate_manifest(manifest)
    assert problems, f"{case} unexpectedly passed"
    assert expected in _messages(problems)


def test_tampered_fixture_file_is_detected(fixtures_copy: Path) -> None:
    target = fixtures_copy / "books" / "epub3-orchard.epub"
    target.write_bytes(target.read_bytes() + b"tamper")
    problems = validate_manifest(load_manifest(fixtures_copy), fixtures_copy)
    assert "sha256 mismatch for books/epub3-orchard.epub" in _messages(problems)


# --- negative: eval cases ---------------------------------------------------------------------


def _case(manifest: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base = {
        "case_id": "QA-900",
        "book_version_id": _first(manifest, "pdf-three-chapters")["book_version_id"],
        "question": "What lifts the moored boats?",
        "gold_source_ids": ["pdf-three-chapters:p0000"],
        "expected_status": "answered",
        "reviewer_status": "pending_human_review",
    }
    return {**base, **overrides}


def test_valid_synthetic_case_passes(manifest: dict[str, Any]) -> None:
    assert validate_cases([(1, _case(manifest))], manifest) == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"gold_source_ids": ["pdf-three-chapters:p0042"]}, "not in pdf-three-chapters"),
        ({"gold_source_ids": ["epub3-orchard:s0000"]}, "not in pdf-three-chapters"),
        ({"gold_source_ids": ["not-a-source-id"]}, "does not match"),
        ({"book_version_id": "00000000-0000-4000-8000-000000000000"}, "unknown book_version_id"),
        ({"book_version_id": "not-a-uuid"}, "is not a 'uuid'"),
        ({"gold_source_ids": []}, "should be non-empty"),
        ({"expected_status": "insufficient_evidence"}, "is expected to be empty"),
        ({"expected_status": "maybe"}, "is not one of"),
        ({"reviewer_status": "approved_by_model"}, "is not one of"),
        ({"case_id": "qa-1"}, "does not match"),
        ({"question": ""}, "should be non-empty"),
        ({"answer": "fabricated gold answer"}, "Additional properties"),
    ],
)
def test_invalid_eval_case_is_rejected(
    manifest: dict[str, Any], overrides: dict[str, Any], expected: str
) -> None:
    problems = validate_cases([(1, _case(manifest, **overrides))], manifest)
    assert problems
    assert expected in _messages(problems)


def test_gold_source_on_unreadable_page_is_rejected(manifest: dict[str, Any]) -> None:
    case = _case(
        manifest,
        book_version_id=_first(manifest, "pdf-image-only-page")["book_version_id"],
        gold_source_ids=["pdf-image-only-page:p0001"],
    )
    assert "is unreadable" in _messages(validate_cases([(1, case)], manifest))


def test_case_on_rejected_fixture_is_rejected(manifest: dict[str, Any]) -> None:
    case = _case(
        manifest,
        book_version_id=_first(manifest, "pdf-corrupt")["book_version_id"],
        gold_source_ids=[],
        expected_status="insufficient_evidence",
    )
    assert "expected to be rejected" in _messages(validate_cases([(1, case)], manifest))


def test_duplicate_case_id_is_rejected(manifest: dict[str, Any]) -> None:
    problems = validate_cases([(1, _case(manifest)), (2, _case(manifest))], manifest)
    assert "duplicate case_id 'QA-900'" in _messages(problems)


def test_malformed_jsonl_line_is_rejected(tmp_path: Path, manifest: dict[str, Any]) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(_case(manifest)) + "\n{not json\n", encoding="utf-8")
    problems = validate_cases(load_cases(path), manifest)
    assert [p.where for p in problems] == ["eval_cases.jsonl:2"]
    assert "invalid JSON" in problems[0].message
