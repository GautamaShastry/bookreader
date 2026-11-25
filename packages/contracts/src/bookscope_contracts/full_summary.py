"""Deterministic publication checks for ``FullBookSummaryResponse`` (BS-026, spec 14).

JSON Schema validates shape; this module enforces the semantics the schema cannot express and that
spec 14 makes release-blocking:

* ``ready`` implies complete manifest accounting, zero failed material chapters and
  ``completeness_label == complete``; ``complete`` is never used for any other status;
* ``partial`` names what is missing; ``failed``/``unavailable``/in-progress states publish no claims
  (no unverified content ever reaches the client);
* every claim cites at least one source listed in ``citations``; every citation is a real source of
  this book version's ledger, filed under the chapter that actually contains it; chapter claims cite
  only their own chapter;
* chapter summaries follow the ledger's chapter order exactly, once each;
* coverage counters agree with the chapter summaries and the ledger.

The checker never trusts the response: the ledger (from canonical storage) is the source of truth.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bookscope_contracts.validation import openapi_component_validator, schema_validator

CLAIMLESS_STATUSES = {"queued", "generating", "verifying", "failed", "unavailable"}


@dataclass(frozen=True)
class LedgerChapter:
    chapter_id: str
    source_ids: frozenset[str]
    source_unit_count: int


@dataclass(frozen=True)
class LedgerView:
    """The parts of a canonical ledger the publisher needs (no book text)."""

    book_id: str
    book_version_id: str
    chapters: tuple[LedgerChapter, ...]

    @property
    def source_units(self) -> int:
        return sum(c.source_unit_count for c in self.chapters)

    def chapter_of(self, source_id: str) -> str | None:
        for chapter in self.chapters:
            if source_id in chapter.source_ids:
                return chapter.chapter_id
        return None

    @classmethod
    def from_canonical_ledger(cls, ledger: Mapping[str, Any]) -> LedgerView:
        """Build from a BS-006 ledger: sources are chunk IDs; units counted per section."""
        chapters = []
        for chapter in ledger["chapters"]:
            ids = frozenset(cid for s in chapter["sections"] for cid in s["chunk_ids"])
            chapters.append(LedgerChapter(chapter["chapter_id"], ids, len(chapter["sections"])))
        return cls(ledger["book_id"], ledger["book_version_id"], tuple(chapters))

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LedgerView:
        return cls(
            data["book_id"],
            data["book_version_id"],
            tuple(
                LedgerChapter(c["chapter_id"], frozenset(c["source_ids"]), c["source_unit_count"])
                for c in data["chapters"]
            ),
        )


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def _schema_violations(response: Any) -> list[Violation]:
    out = []
    for name, validator in (
        ("schema", schema_validator("book-full-summary")),
        ("openapi", openapi_component_validator("FullBookSummaryResponse")),
    ):
        for error in validator.iter_errors(response):
            where = "/".join(str(p) for p in error.absolute_path) or "<root>"
            out.append(Violation("SCHEMA_INVALID", f"{name} {where}: {error.message}"))
    return out


def check_full_summary(response: Any, ledger: LedgerView) -> list[Violation]:
    """Return every publication violation; an empty list means the response may be published."""
    violations = _schema_violations(response)
    if violations:
        return violations
    v = violations.append
    status = response["status"]
    coverage = response["coverage"]
    summaries: list[dict[str, Any]] = response["chapter_summaries"]
    overview: list[dict[str, Any]] = response["overview_claims"]
    citations: list[dict[str, Any]] = response["citations"]
    chapter_claims = [c for s in summaries for c in s["claims"]]
    all_claims = overview + chapter_claims

    if (
        response["book_id"] != ledger.book_id
        or response["book_version_id"] != ledger.book_version_id
    ):
        v(Violation("SCOPE_MISMATCH", "response is not bound to the authorized book version"))

    # --- claims only for publishable statuses ------------------------------------------------
    if status in CLAIMLESS_STATUSES and (all_claims or citations):
        v(
            Violation(
                "UNVERIFIED_CONTENT", f"status {status!r} must not publish claims or citations"
            )
        )

    # --- claim / citation integrity --------------------------------------------------------
    for dup in sorted(k for k, n in Counter(c["claim_id"] for c in all_claims).items() if n > 1):
        v(Violation("DUPLICATE_CLAIM_ID", dup))
    cited = {c["source_id"]: c["chapter_id"] for c in citations}
    for dup in sorted(k for k, n in Counter(c["source_id"] for c in citations).items() if n > 1):
        v(Violation("DUPLICATE_CITATION", dup))
    for citation in citations:
        actual = ledger.chapter_of(citation["source_id"])
        if actual is None:
            v(
                Violation(
                    "UNKNOWN_SOURCE", f"citation {citation['source_id']} not in this book version"
                )
            )
        elif actual != citation["chapter_id"]:
            v(Violation("CITATION_CHAPTER_MISMATCH", f"{citation['source_id']} is in {actual}"))
    for claim in all_claims:
        for source_id in claim["source_ids"]:
            if source_id not in cited:
                v(
                    Violation(
                        "MISSING_CITATION", f"claim {claim['claim_id']} cites uncited {source_id}"
                    )
                )
    for summary in summaries:
        for claim in summary["claims"]:
            for source_id in claim["source_ids"]:
                owner = ledger.chapter_of(source_id)
                if owner is not None and owner != summary["chapter_id"]:
                    v(Violation("CROSS_CHAPTER_CLAIM", f"{claim['claim_id']} cites {owner} source"))
    if citations and not all_claims:
        v(Violation("ORPHAN_CITATIONS", "citations without any claim"))
    used = {s for c in all_claims for s in c["source_ids"]}
    for source_id in sorted(set(cited) - used):
        v(Violation("ORPHAN_CITATIONS", f"citation {source_id} supports no claim"))

    # --- chapter inventory and order -----------------------------------------------------------
    expected_order = [c.chapter_id for c in ledger.chapters]
    observed_order = [s["chapter_id"] for s in summaries]
    if (summaries or status in {"ready", "partial"}) and observed_order != expected_order:
        v(Violation("CHAPTER_ORDER", f"expected {expected_order}, got {observed_order}"))
    by_id = {c.chapter_id: c for c in ledger.chapters}
    for summary in summaries:
        chapter = by_id.get(summary["chapter_id"])
        if chapter is None:
            continue
        if summary["source_unit_count"] != chapter.source_unit_count:
            v(Violation("UNIT_COUNT_MISMATCH", f"{summary['chapter_id']} source_unit_count"))
        if summary["accounted_unit_count"] > summary["source_unit_count"]:
            v(
                Violation(
                    "UNIT_COUNT_MISMATCH", f"{summary['chapter_id']} accounts more than exists"
                )
            )
        complete = summary["state"] in {"complete", "excluded_nonmaterial"}
        if complete and summary["accounted_unit_count"] != summary["source_unit_count"]:
            v(Violation("FALSE_COMPLETE", f"{summary['chapter_id']} complete with skipped units"))
        if summary["state"] == "complete" and not summary["claims"]:
            v(Violation("FALSE_COMPLETE", f"{summary['chapter_id']} complete without any claim"))

    # --- coverage counters ---------------------------------------------------------------------
    failed_ids = sorted(s["chapter_id"] for s in summaries if s["state"] == "failed")
    completed = sum(s["state"] in {"complete", "excluded_nonmaterial"} for s in summaries)
    if coverage["chapters_expected"] != len(ledger.chapters):
        v(Violation("COVERAGE_MISMATCH", "chapters_expected differs from the ledger"))
    if coverage["source_units_expected"] != ledger.source_units:
        v(Violation("COVERAGE_MISMATCH", "source_units_expected differs from the ledger"))
    if summaries:
        if coverage["chapters_accounted"] != len(summaries):
            v(Violation("COVERAGE_MISMATCH", "chapters_accounted differs from chapter_summaries"))
        if coverage["chapters_completed"] != completed:
            v(Violation("COVERAGE_MISMATCH", "chapters_completed differs from chapter states"))
        if sorted(coverage["failed_chapter_ids"]) != failed_ids:
            v(Violation("COVERAGE_MISMATCH", "failed_chapter_ids differ from chapter states"))
        accounted = sum(s["accounted_unit_count"] for s in summaries)
        if coverage["source_units_accounted"] != accounted:
            v(Violation("COVERAGE_MISMATCH", "source_units_accounted differs from chapters"))
    for counter in ("chapters_accounted", "chapters_completed"):
        if coverage[counter] > coverage["chapters_expected"]:
            v(Violation("COVERAGE_MISMATCH", f"{counter} exceeds chapters_expected"))
    if coverage["source_units_accounted"] > coverage["source_units_expected"]:
        v(Violation("COVERAGE_MISMATCH", "source_units_accounted exceeds expected"))

    # --- status semantics ----------------------------------------------------------------------
    label = coverage["completeness_label"]
    fully_covered = (
        coverage["chapters_expected"]
        == coverage["chapters_accounted"]
        == coverage["chapters_completed"]
        and not coverage["failed_chapter_ids"]
        and coverage["source_units_accounted"] == coverage["source_units_expected"]
    )
    if status == "ready":
        if label != "complete" or not fully_covered:
            v(Violation("FALSE_READY", "ready requires complete coverage and no failed chapter"))
        elif len(summaries) != len(ledger.chapters) or completed != len(ledger.chapters):
            # counters can lie; the chapter summaries themselves must cover every ledger chapter
            v(Violation("FALSE_READY", "ready requires a completed summary for every chapter"))
        if not overview:
            v(Violation("FALSE_READY", "ready requires overview claims"))
    elif label == "complete":
        v(Violation("FALSE_COMPLETE", f"completeness_label complete with status {status!r}"))
    if status == "partial":
        if label != "partial":
            v(Violation("PARTIAL_MISLABELED", "partial requires completeness_label partial"))
        if fully_covered:
            v(Violation("PARTIAL_MISLABELED", "partial must name missing chapters or units"))
    if status in {"failed", "unavailable"} and label != "unavailable":
        v(Violation("STATUS_LABEL_MISMATCH", f"{status} requires completeness_label unavailable"))
    if status == "failed" and not response.get("error_code"):
        v(Violation("STATUS_LABEL_MISMATCH", "failed requires an error_code"))
    return violations
