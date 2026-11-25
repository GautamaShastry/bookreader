"""BS-026: full-book summary publication contract on positive/negative examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bookscope_agent_runtime.fake_full_summary import fake_full_summary
from bookscope_contracts import load_example, load_openapi
from bookscope_contracts.full_summary import LedgerChapter, LedgerView, check_full_summary

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "contracts" / "full-summary"
LEDGER = LedgerView.from_json(json.loads((ROOT / "ledger.json").read_text(encoding="utf-8")))
POSITIVE = sorted((ROOT / "positive").glob("*.json"))
NEGATIVE = sorted((ROOT / "negative").glob("*.json"))


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_still_requires_idempotency_and_job_type() -> None:
    api = load_openapi()
    post = api["paths"]["/v1/books/{book_id}/full-summary"]["post"]
    key = next(p for p in post["parameters"] if p["name"] == "Idempotency-Key")
    assert key["required"] is True
    assert (
        "full_book_summary" in api["components"]["schemas"]["Job"]["properties"]["job_type"]["enum"]
    )


def test_spec_example_passes_semantic_publication_checks() -> None:
    assert check_full_summary(load_example("book-full-summary-example"), LEDGER) == []


@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_positive_example_is_publishable(path: Path) -> None:
    violations = check_full_summary(_load(path), LEDGER)
    assert violations == [], [str(v) for v in violations]


def test_example_sets_are_not_trivially_small() -> None:
    assert len(POSITIVE) >= 5
    assert len(NEGATIVE) >= 15


@pytest.mark.parametrize("path", NEGATIVE, ids=lambda p: p.stem)
def test_negative_example_is_blocked_with_expected_codes(path: Path) -> None:
    case = _load(path)
    codes = sorted({v.code for v in check_full_summary(case["response"], LEDGER)})
    assert codes == case["expected_violation_codes"]


def test_ready_requires_complete_coverage_even_if_labels_lie() -> None:
    response = _load(ROOT / "positive" / "ready-spec-example.json")
    response["coverage"]["source_units_accounted"] = 1  # one unit silently skipped
    response["chapter_summaries"][1]["accounted_unit_count"] = 0
    codes = {v.code for v in check_full_summary(response, LEDGER)}
    assert "FALSE_READY" in codes


def test_response_for_another_ledger_is_blocked() -> None:
    other = LedgerView(
        LEDGER.book_id, LEDGER.book_version_id, (LedgerChapter("chapter-1", frozenset({"x"}), 1),)
    )
    codes = {v.code for v in check_full_summary(load_example("book-full-summary-example"), other)}
    assert {"UNKNOWN_SOURCE", "CHAPTER_ORDER", "COVERAGE_MISMATCH"} <= codes


# --- fake executor -------------------------------------------------------------------------------


def test_fake_executor_returns_ordered_ledger_and_publishable_ready() -> None:
    response = fake_full_summary(LEDGER, updated_at="2026-11-25T00:00:00Z")
    assert response["status"] == "ready"
    assert [s["chapter_id"] for s in response["chapter_summaries"]] == ["chapter-1", "chapter-2"]
    assert check_full_summary(response, LEDGER) == []
    assert all(claim["text"].startswith("[fake executor]") for claim in response["overview_claims"])


def test_fake_executor_one_failed_chapter_is_partial_never_ready() -> None:
    response = fake_full_summary(
        LEDGER, updated_at="2026-11-25T00:00:00Z", failed_chapters={"chapter-2"}
    )
    assert response["status"] == "partial"
    assert response["coverage"]["failed_chapter_ids"] == ["chapter-2"]
    assert check_full_summary(response, LEDGER) == []


def test_fake_executor_all_failed_is_failed_without_claims() -> None:
    response = fake_full_summary(
        LEDGER, updated_at="2026-11-25T00:00:00Z", failed_chapters={"chapter-1", "chapter-2"}
    )
    assert response["status"] == "failed"
    assert response["overview_claims"] == []
    assert response["citations"] == []
    assert check_full_summary(response, LEDGER) == []


def test_chapter_without_readable_sources_makes_result_partial() -> None:
    ledger = LedgerView(
        LEDGER.book_id,
        LEDGER.book_version_id,
        (*LEDGER.chapters, LedgerChapter("chapter-3", frozenset(), 1)),
    )
    response = fake_full_summary(ledger, updated_at="2026-11-25T00:00:00Z")
    assert response["status"] == "partial"
    assert response["coverage"]["failed_chapter_ids"] == ["chapter-3"]
    assert check_full_summary(response, ledger) == []
