"""Single-agent full-book baseline (EV-009 comparison arm) and eval adapters.

The baseline reads canonical chunks in reading order until its input-token budget is spent, makes
one map call over everything it read and one book-level reduction, then applies the same
deterministic verifier and publication gate as the hierarchical engine. Chapters it could not read
within budget are reported failed, so it can be ``partial`` but never falsely ``ready``.
Use it at a matched model/token/cost budget (spec 08 §10, spec 14 FR-029); results from fake
models are workflow evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bookscope_agent_runtime.summary_engine import (
    SUMMARY_SPEC_VERSION,
    Claim,
    PricingCatalog,
    SourceText,
    SummaryEngine,
    SummaryModel,
    verify_claims,
)
from bookscope_contracts.full_summary import LedgerView, check_full_summary
from bookscope_eval.summary_scorecard import System, SystemRun
from bookscope_ingestor.chunking import BookScope, approx_tokens
from bookscope_ingestor.ledger import CanonicalBook, LedgerError, verify_canonical_book


def _usd(pricing: PricingCatalog, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1000 * pricing.input_usd_per_1k
        + output_tokens / 1000 * pricing.output_usd_per_1k
    )


@dataclass
class SingleAgentBaseline:
    model: SummaryModel
    input_token_budget: int
    updated_at: str = "1970-01-01T00:00:00Z"

    async def run(
        self, book: CanonicalBook, scope: BookScope
    ) -> tuple[dict[str, Any], int, int, int]:
        """Return (response, model_calls, input_tokens, output_tokens)."""
        verify_canonical_book(book, scope)
        view = LedgerView.from_canonical_ledger(book.ledger)
        read, spent = [], 0
        for chunk in book.chunks:
            size = approx_tokens(chunk.text)
            if spent + size > self.input_token_budget:
                break
            read.append(chunk)
            spent += size
        texts = {c.chunk_id: c.text for c in book.chunks}
        calls = in_tok = out_tok = 0
        kept: list[Claim] = []
        if read:
            output = await self.model.map_block(
                "whole book", [SourceText(c.chunk_id, c.text) for c in read]
            )
            calls, in_tok, out_tok = 1, output.usage.input_tokens, output.usage.output_tokens
            kept, _ = verify_claims(output.claims, frozenset(c.chunk_id for c in read), texts)
        read_ids = {c.chunk_id for c in read}
        chapter_of = {c.chunk_id: c.chapter_id for c in book.chunks}
        summaries = []
        per_chapter = []
        for chapter in book.ledger["chapters"]:
            cid = chapter["chapter_id"]
            sections = chapter["sections"]
            complete_sections = [
                s for s in sections if s["chunk_ids"] and set(s["chunk_ids"]) <= read_ids
            ]
            claims = [c for c in kept if all(chapter_of[s] == cid for s in c.source_ids)][:2]
            per_chapter.append(claims)
            if claims and len(complete_sections) == len(sections):
                state, accounted = "complete", len(sections)
            elif claims:
                state, accounted = "partial", len(complete_sections)
            else:
                state, accounted = "failed", 0
            summaries.append(
                {
                    "chapter_id": cid,
                    "state": state,
                    "claims": [
                        {
                            "claim_id": f"{cid}-c{i}",
                            "text": c.text,
                            "source_ids": list(dict.fromkeys(c.source_ids)),
                        }
                        for i, c in enumerate(claims, start=1)
                    ],
                    "source_unit_count": len(sections),
                    "accounted_unit_count": accounted,
                }
            )
        overview: list[Claim] = []
        usable = [c for c in per_chapter if c]
        if usable:
            output = await self.model.reduce_book(usable)
            calls += 1
            in_tok += output.usage.input_tokens
            out_tok += output.usage.output_tokens
            allowed = frozenset(s for claims in usable for c in claims for s in c.source_ids)
            overview, _ = verify_claims(output.claims, allowed, texts)
        failed = [s["chapter_id"] for s in summaries if s["state"] == "failed"]
        completed = sum(s["state"] == "complete" for s in summaries)
        if not overview:
            status, label, summaries_out = "failed", "unavailable", []
        elif completed == len(summaries):
            status, label, summaries_out = "ready", "complete", summaries
        else:
            status, label, summaries_out = "partial", "partial", summaries
        cited: dict[str, str] = {}
        if status != "failed":
            for claim in [*overview, *(c for claims in per_chapter for c in claims)]:
                for sid in claim.source_ids:
                    cited[sid] = chapter_of[sid]
        response = {
            "book_id": view.book_id,
            "book_version_id": view.book_version_id,
            "summary_spec_version": SUMMARY_SPEC_VERSION,
            "status": status,
            "overview_claims": []
            if status == "failed"
            else [
                {
                    "claim_id": f"overview-c{i}",
                    "text": c.text,
                    "source_ids": list(dict.fromkeys(c.source_ids)),
                }
                for i, c in enumerate(overview, start=1)
            ],
            "chapter_summaries": summaries_out,
            "coverage": {
                "chapters_expected": len(summaries),
                "chapters_accounted": len(summaries_out),
                "chapters_completed": completed if summaries_out else 0,
                "failed_chapter_ids": failed if summaries_out else [],
                "source_units_expected": view.source_units,
                "source_units_accounted": sum(s["accounted_unit_count"] for s in summaries_out),
                "completeness_label": label,
            },
            "citations": [{"source_id": s, "chapter_id": c} for s, c in cited.items()],
            "updated_at": self.updated_at,
            "job_id": None,
            "error_code": None if status == "ready" else "BASELINE_INCOMPLETE",
        }
        if check_full_summary(response, view):
            raise LedgerError("LEDGER_INVALID", "baseline produced an unpublishable response")
        return response, calls, in_tok, out_tok


def engine_system(engine: SummaryEngine) -> System:
    async def run(book: CanonicalBook, scope: BookScope) -> SystemRun:
        result = await engine.run(book, scope)
        stats = result.stats
        return SystemRun(
            result.response,
            stats.model_calls,
            stats.input_tokens,
            stats.output_tokens,
            _usd(engine.config.pricing, stats.input_tokens, stats.output_tokens),
        )

    return run


def baseline_system(baseline: SingleAgentBaseline, pricing: PricingCatalog) -> System:
    async def run(book: CanonicalBook, scope: BookScope) -> SystemRun:
        response, calls, in_tok, out_tok = await baseline.run(book, scope)
        return SystemRun(response, calls, in_tok, out_tok, _usd(pricing, in_tok, out_tok))

    return run
