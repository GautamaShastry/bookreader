"""EV-009: the full-book summary scorer must catch omissions, missing citations and false ready."""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bookscope_agent_runtime.baseline import SingleAgentBaseline, baseline_system, engine_system
from bookscope_agent_runtime.fake_models import ExtractiveFakeModel, ReducerDropsChapterModel
from bookscope_agent_runtime.summary_engine import EngineConfig, PricingCatalog, SummaryEngine
from bookscope_eval.summary_scorecard import (
    SystemRun,
    build_report,
    fixture_books,
    load_cases,
    score_response,
    to_markdown,
    without_timings,
)

PRICING = PricingCatalog("TEST-ONLY", 0.001, 0.002)
CASES = load_cases()
CASE = next(c for c in CASES if c["case_id"] == "FBS-001")
BOOKS = fixture_books(sorted({c["fixture_id"] for c in CASES}))
BOOK, SCOPE = BOOKS[CASE["fixture_id"]]


def _engine_response(model: ExtractiveFakeModel | None = None) -> dict[str, Any]:
    engine = SummaryEngine(model or ExtractiveFakeModel(), EngineConfig(pricing=PRICING))
    return asyncio.run(engine.run(BOOK, SCOPE)).response


GOOD = _engine_response()


def _score(response: dict[str, Any], judgments: dict[str, bool] | None = None) -> Any:
    return score_response(CASE, "test", SystemRun(response), BOOK, judgments)


def _codes(score: Any) -> set[str]:
    return {c.split(":")[0] for c in score.critical}


# --- positive -------------------------------------------------------------------------------------


def test_good_engine_output_scores_clean() -> None:
    score = _score(GOOD)
    assert score.passed, score.critical
    assert score.topic_recall == 1.0
    assert score.supported_claim_rate == 1.0
    assert score.support_method == "auto_verbatim"
    assert score.topics_missed == []


def test_synthetic_cases_load_and_reference_fixtures() -> None:
    assert len(CASES) >= 4
    assert {c["label_status"] for c in CASES} == {"synthetic"}
    assert any(c["expected_status"] == "partial" for c in CASES)


# --- the three required detections --------------------------------------------------------------


def test_summary_of_only_the_first_chapter_is_caught() -> None:
    only_first = copy.deepcopy(GOOD)
    only_first["chapter_summaries"] = only_first["chapter_summaries"][:1]
    first_sources = {
        s for c in only_first["chapter_summaries"][0]["claims"] for s in c["source_ids"]
    }
    only_first["overview_claims"] = [
        c for c in only_first["overview_claims"] if set(c["source_ids"]) <= first_sources
    ]
    only_first["citations"] = [
        c for c in only_first["citations"] if c["source_id"] in first_sources
    ]
    score = _score(only_first)
    assert not score.passed
    assert {"CHAPTER_ORDER", "FALSE_READY"} <= _codes(score)
    assert score.topic_recall is not None
    assert score.topic_recall < 0.5
    assert score.overview_chapter_coverage is not None
    assert score.overview_chapter_coverage < 0.5


def test_honest_partial_of_first_chapter_still_fails_a_ready_case() -> None:
    model = ExtractiveFakeModel(
        fail_sources={c.chunk_id: 5 for c in BOOK.chunks if c.chapter_id != "ch001"}
    )
    response = _engine_response(model)
    assert response["status"] == "partial"
    score = _score(response)
    assert _codes(score) == {"STATUS_MISMATCH"}
    assert score.topics_missed == ["flags", "winter"]


def test_missing_citations_are_critical() -> None:
    broken = copy.deepcopy(GOOD)
    broken["citations"] = broken["citations"][:1]
    assert "MISSING_CITATION" in _codes(_score(broken))


def test_false_ready_with_skipped_units_is_critical() -> None:
    lying = copy.deepcopy(GOOD)
    lying["chapter_summaries"][2]["accounted_unit_count"] = 0
    lying["coverage"]["source_units_accounted"] -= lying["chapter_summaries"][2][
        "source_unit_count"
    ]
    codes = _codes(_score(lying))
    assert "FALSE_READY" in codes
    assert "FALSE_COMPLETE" in codes


# --- support, omission and label checks ----------------------------------------------------------


def test_unsupported_claim_lowers_auto_support_rate() -> None:
    edited = copy.deepcopy(GOOD)
    edited["chapter_summaries"][0]["claims"][0]["text"] = "The harbor was built by aliens."
    score = _score(edited)
    assert score.supported_claim_rate is not None
    assert score.supported_claim_rate < 1.0


def test_human_judgments_override_auto_support() -> None:
    judgments = {c["claim_id"]: False for c in GOOD["overview_claims"]}
    score = _score(GOOD, judgments)
    assert score.support_method == "human"
    assert score.supported_claim_rate == 0.0


def test_reducer_omitting_chapters_from_overview_is_visible() -> None:
    score = _score(_engine_response(ReducerDropsChapterModel()))
    assert score.overview_chapter_coverage is not None
    assert score.overview_chapter_coverage < 0.5


def test_label_whose_quote_is_not_in_the_named_chapter_is_flagged() -> None:
    bad_case = copy.deepcopy(CASE)
    bad_case["topics"][0]["chapter_ordinal"] = 3
    score = score_response(bad_case, "test", SystemRun(GOOD), BOOK)
    assert "LABEL_INVALID" in _codes(score)


def test_case_loader_rejects_invalid_and_duplicate_cases(tmp_path: Path) -> None:
    line = json.dumps(CASE)
    duplicate = tmp_path / "dup.jsonl"
    duplicate.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(duplicate)
    invalid = tmp_path / "bad.jsonl"
    invalid.write_text(json.dumps({**CASE, "expected_status": "complete"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        load_cases(invalid)


# --- report, baseline comparison and honesty labels ---------------------------------------------


def _systems(baseline_budget: int = 2_000) -> dict[str, Any]:
    return {
        "engine": engine_system(
            SummaryEngine(ExtractiveFakeModel(), EngineConfig(pricing=PRICING))
        ),
        "baseline": baseline_system(
            SingleAgentBaseline(ExtractiveFakeModel(), baseline_budget), PRICING
        ),
    }


def test_report_is_labelled_synthetic_with_gold_todo() -> None:
    report = build_report(CASES, BOOKS, _systems(), synthetic_systems=True)
    assert report["passed"] is True
    assert report["evidence_class"] == "synthetic_workflow_only"
    assert "NOT product quality" in report["notice"]
    assert report["gold_status"] == {
        "human_verified_cases": 0,
        "human_verified_books": 0,
        "required_cases": 20,
        "required_books": 3,
        "status": "TODO",
    }
    assert "**TODO**" in to_markdown(report)


def test_report_is_deterministic_apart_from_timings() -> None:
    first = build_report(CASES, BOOKS, _systems(), synthetic_systems=True)
    second = build_report(CASES, BOOKS, _systems(), synthetic_systems=True)
    assert without_timings(first) == without_timings(second)


def test_budget_starved_baseline_is_partial_not_false_ready() -> None:
    report = build_report([CASE], BOOKS, _systems(baseline_budget=60), synthetic_systems=True)
    baseline = report["cases"]["baseline"][0]
    assert baseline["observed_status"] == "partial"
    assert [c.split(":")[0] for c in baseline["critical"]] == ["STATUS_MISMATCH"]
    assert report["summary"]["baseline"]["false_ready"] == 0
    comparison = report["comparison"]
    assert comparison["systems"] == ["engine", "baseline"]
    assert comparison["delta_mean_topic_recall"] > 0
    assert report["passed"] is False


def test_gold_status_requires_20_human_cases_over_3_books() -> None:
    human = []
    fixtures = ["pdf-three-chapters", "epub3-orchard", "epub2-ncx"]
    for i in range(20):
        base = next(c for c in CASES if c["fixture_id"] == fixtures[i % 3])
        human.append({**base, "case_id": f"FBS-{100 + i}", "label_status": "human_verified"})
    report = build_report(human, BOOKS, {"engine": _systems()["engine"]}, synthetic_systems=True)
    assert report["gold_status"]["status"] == "met"
    assert report["evidence_class"] == "synthetic_workflow_only"  # fake model is still fake


def test_cli_writes_reports(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bookscope_eval.summary_scorecard", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "summary-scorecard.json").read_text(encoding="utf-8"))
    assert report["evidence_class"] == "synthetic_workflow_only"
    assert (tmp_path / "summary-scorecard.md").exists()
