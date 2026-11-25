"""Fake full-book summary executor for contract/workflow tests (BS-026). Calls no model.

It walks the ledger in chapter order and emits a placeholder, ledger-derived summary whose claims
cite real source IDs, so API, job and publisher plumbing can be exercised end to end. Its text
states facts about the *ledger* ("N canonical source units"), never about book content. It is
NOT a summarizer and must never be presented as one; BS-027 adds the hierarchical engine.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from bookscope_contracts.full_summary import LedgerView

SUMMARY_SPEC_VERSION = "1.4.0"


def fake_full_summary(
    ledger: LedgerView,
    *,
    updated_at: str,
    job_id: str | None = None,
    failed_chapters: Collection[str] = (),
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    citations: dict[str, str] = {}
    overview_sources: list[str] = []
    failed_ids: list[str] = []
    for chapter in ledger.chapters:
        sources = sorted(chapter.source_ids)
        if chapter.chapter_id in failed_chapters or not sources:
            failed_ids.append(chapter.chapter_id)
            summaries.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "state": "failed",
                    "claims": [],
                    "source_unit_count": chapter.source_unit_count,
                    "accounted_unit_count": 0,
                }
            )
            continue
        cited = sources[:3]
        for source_id in cited:
            citations[source_id] = chapter.chapter_id
        overview_sources.append(cited[0])
        summaries.append(
            {
                "chapter_id": chapter.chapter_id,
                "state": "complete",
                "claims": [
                    {
                        "claim_id": f"{chapter.chapter_id}-c1",
                        "text": f"[fake executor] {chapter.chapter_id} has "
                        f"{chapter.source_unit_count} canonical source unit(s).",
                        "source_ids": cited,
                    }
                ],
                "source_unit_count": chapter.source_unit_count,
                "accounted_unit_count": chapter.source_unit_count,
            }
        )
    completed = len(summaries) - len(failed_ids)
    accounted = sum(s["accounted_unit_count"] for s in summaries)
    if completed == 0:
        status, label = "failed", "unavailable"
    elif failed_ids:
        status, label = "partial", "partial"
    else:
        status, label = "ready", "complete"
    if status == "failed":
        summaries, citations, overview_sources = [], {}, []
    overview = (
        [
            {
                "claim_id": "overview-c1",
                "text": f"[fake executor] The ledger lists {len(ledger.chapters)} chapter(s); "
                f"{completed} were processed.",
                "source_ids": overview_sources,
            }
        ]
        if overview_sources
        else []
    )
    return {
        "book_id": ledger.book_id,
        "book_version_id": ledger.book_version_id,
        "summary_spec_version": SUMMARY_SPEC_VERSION,
        "status": status,
        "overview_claims": overview,
        "chapter_summaries": summaries,
        "coverage": {
            "chapters_expected": len(ledger.chapters),
            "chapters_accounted": len(summaries),
            "chapters_completed": completed if status != "failed" else 0,
            "failed_chapter_ids": failed_ids if status != "failed" else [],
            "source_units_expected": ledger.source_units,
            "source_units_accounted": accounted if status != "failed" else 0,
            "completeness_label": label,
        },
        "citations": [{"source_id": s, "chapter_id": c} for s, c in citations.items()],
        "updated_at": updated_at,
        "job_id": job_id,
        "error_code": None if status == "ready" else ("CHAPTERS_FAILED" if failed_ids else None),
    }
