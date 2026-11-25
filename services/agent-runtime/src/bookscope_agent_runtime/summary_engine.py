"""Hierarchical full-book summary engine (BS-027, spec 14). Runs only with injected models.

Pipeline: verified canonical ledger -> bounded blocks per chapter (reading order) -> cost preflight
-> map each block (<= 2 concurrent, 1 retry) -> deterministic verification -> chapter reduction over
verified block claims -> book reduction over verified chapter claims -> BS-026 publication gate.

Guarantees, all enforced by trusted code rather than by a model:

* traversal is the ledger, never retrieval top-k; every section is accounted or reported missing;
* a claim survives only if every cited source is allowed at that step (its block / chapter / book
  verified set) and each of its evidence quotes occurs verbatim in a cited source's canonical text;
  book text is data, so injected instructions cannot widen scope;
* ``ready`` only when every section is covered by verified blocks and every chapter reduced;
* preflight refuses over-allowance jobs before any model call; cancellation (book deletion) is
  checked before every call and nothing is cached or published after it;
* verified blocks are checkpointed, so an interrupted job resumes without redoing them;
* results are cached by owner/version/spec/model/prompt/manifest; duplicate concurrent runs
  share one computation.

Model quality is NOT measured here: tests use fake models (see EV-009 for scoring).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Protocol

from bookscope_contracts.full_summary import LedgerView, check_full_summary
from bookscope_ingestor.chunking import BookScope, Chunk, approx_tokens
from bookscope_ingestor.ledger import CanonicalBook, LedgerError, verify_canonical_book

SUMMARY_SPEC_VERSION = "1.4.0"
ENGINE_VERSION = "summary-engine/1"


# --- model interface ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    text: str
    source_ids: tuple[str, ...]
    evidence: tuple[str, ...]  # exact quotes from the cited sources' canonical text


@dataclass(frozen=True)
class SourceText:
    source_id: str
    text: str  # untrusted book content; never instructions


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelOutput:
    claims: tuple[Claim, ...]
    usage: Usage


class SummaryModel(Protocol):
    model_id: str
    prompt_hash: str

    async def map_block(self, chapter_title: str, sources: Sequence[SourceText]) -> ModelOutput: ...

    async def reduce_chapter(self, chapter_title: str, claims: Sequence[Claim]) -> ModelOutput: ...

    async def reduce_book(self, chapter_claims: Sequence[Sequence[Claim]]) -> ModelOutput: ...


# --- configuration, pricing and results ----------------------------------------------------------


@dataclass(frozen=True)
class PricingCatalog:
    """Per-1k-token prices; real values need a reviewed per-Region catalog (spec 14 §3)."""

    name: str
    input_usd_per_1k: float
    output_usd_per_1k: float


@dataclass(frozen=True)
class EngineConfig:
    pricing: PricingCatalog
    allowance_usd: float = 2.50
    max_concurrency: int = 2
    block_tokens: int = 2_000
    max_output_tokens: int = 400
    block_retries: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_concurrency <= 2:
            raise ValueError("full-book jobs allow at most 2 concurrent model workers")
        if self.block_retries not in (0, 1):
            raise ValueError("at most one retry per block")


@dataclass(frozen=True)
class Preflight:
    blocks: int
    model_calls_upper_bound: int
    input_tokens_upper_bound: int
    output_tokens_upper_bound: int
    estimated_usd: float
    allowance_usd: float

    @property
    def allowed(self) -> bool:
        return self.estimated_usd <= self.allowance_usd


@dataclass
class RunStats:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    provider_errors: int = 0
    rejected_claims: int = 0
    max_concurrent: int = 0
    checkpoint_hits: int = 0


@dataclass(frozen=True)
class SummaryResult:
    response: dict[str, Any]
    preflight: Preflight | None
    stats: RunStats
    cached: bool = False

    @property
    def status(self) -> str:
        return str(self.response["status"])


class Cancelled(Exception):  # noqa: N818 - control-flow signal, not an error condition
    pass


@dataclass(frozen=True)
class _Block:
    block_id: str
    chapter_id: str
    chunks: tuple[Chunk, ...]
    section_ids: frozenset[str]

    @property
    def source_ids(self) -> frozenset[str]:
        return frozenset(c.chunk_id for c in self.chunks)


# --- deterministic verifier ----------------------------------------------------------------------


def verify_claims(
    claims: Sequence[Claim], allowed_sources: frozenset[str], texts: dict[str, str]
) -> tuple[list[Claim], int]:
    """Keep claims whose sources are all allowed and whose every evidence quote is verbatim in one
    of the claim's cited sources. Returns (kept, rejected_count)."""
    kept: list[Claim] = []
    rejected = 0
    for claim in claims:
        sources_ok = bool(claim.source_ids) and set(claim.source_ids) <= allowed_sources
        quotes_ok = bool(claim.evidence) and all(
            quote.strip() and any(quote in texts.get(s, "") for s in claim.source_ids)
            for quote in claim.evidence
        )
        if sources_ok and quotes_ok and claim.text.strip():
            kept.append(claim)
        else:
            rejected += 1
    return kept, rejected


# --- engine --------------------------------------------------------------------------------------


@dataclass
class SummaryEngine:
    model: SummaryModel
    config: EngineConfig
    is_cancelled: Callable[[], bool] = lambda: False
    cache: dict[tuple[str, ...], dict[str, Any]] = field(default_factory=dict)
    checkpoints: dict[tuple[str, ...], tuple[Claim, ...]] = field(default_factory=dict)
    clock: Callable[[], str] = lambda: "1970-01-01T00:00:00Z"
    _locks: dict[tuple[str, ...], asyncio.Lock] = field(default_factory=dict)

    def cache_key(self, book: CanonicalBook) -> tuple[str, ...]:
        ledger = book.ledger
        return (
            ledger["owner_id"],
            ledger["book_version_id"],
            SUMMARY_SPEC_VERSION,
            self.model.model_id,
            self.model.prompt_hash,
            ledger["manifest_sha256"],
        )

    # -- planning ---------------------------------------------------------------------------

    def plan_blocks(self, book: CanonicalBook) -> list[_Block]:
        by_id = {c.chunk_id: c for c in book.chunks}
        blocks: list[_Block] = []
        for chapter in book.ledger["chapters"]:
            current: list[Chunk] = []
            tokens = 0

            def flush(chapter_id: str = chapter["chapter_id"]) -> None:
                nonlocal current, tokens
                if current:
                    ordinal = sum(b.chapter_id == chapter_id for b in blocks) + 1
                    blocks.append(
                        _Block(
                            f"{chapter_id}.b{ordinal:03d}",
                            chapter_id,
                            tuple(current),
                            frozenset(c.section_id for c in current),
                        )
                    )
                current, tokens = [], 0

            for section in chapter["sections"]:
                for chunk_id in section["chunk_ids"]:
                    chunk = by_id[chunk_id]
                    size = approx_tokens(chunk.text)
                    if current and tokens + size > self.config.block_tokens:
                        flush()
                    current.append(chunk)
                    tokens += size
            flush()
        return blocks

    def preflight(self, book: CanonicalBook, blocks: Sequence[_Block]) -> Preflight:
        cfg = self.config
        chapters = len(book.ledger["chapters"])
        calls_once = len(blocks) + chapters + 1
        calls = len(blocks) * (1 + cfg.block_retries) + chapters + 1
        source_tokens = sum(approx_tokens(c.text) for b in blocks for c in b.chunks)
        output_tokens = calls * cfg.max_output_tokens
        # map inputs (with retries) + every reduction reads at most all prior outputs
        input_tokens = source_tokens * (1 + cfg.block_retries) + calls_once * cfg.max_output_tokens
        usd = (
            input_tokens / 1000 * cfg.pricing.input_usd_per_1k
            + output_tokens / 1000 * cfg.pricing.output_usd_per_1k
        )
        return Preflight(
            len(blocks), calls, input_tokens, output_tokens, round(usd, 6), cfg.allowance_usd
        )

    # -- running ------------------------------------------------------------------------------

    async def run(self, book: CanonicalBook, scope: BookScope) -> SummaryResult:
        key = self.cache_key(book)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:  # duplicate concurrent jobs share one computation
            if key in self.cache and key[0] == scope.owner_id:
                return SummaryResult(self.cache[key], None, RunStats(), cached=True)
            return await self._run(book, scope, key)

    async def _run(
        self, book: CanonicalBook, scope: BookScope, key: tuple[str, ...]
    ) -> SummaryResult:
        stats = RunStats()
        try:
            verify_canonical_book(book, scope)
        except LedgerError as exc:
            return SummaryResult(self._failed(book, exc.code), None, stats)
        view = LedgerView.from_canonical_ledger(book.ledger)
        if not book.ledger["structure"]["reliable"]:
            return SummaryResult(self._failed(book, "INVALID_SOURCE_INVENTORY", view), None, stats)
        blocks = self.plan_blocks(book)
        plan = self.preflight(book, blocks)
        if not plan.allowed:
            return SummaryResult(self._failed(book, "COST_BUDGET_EXCEEDED", view), plan, stats)

        texts = {c.chunk_id: c.text for c in book.chunks}
        semaphore = asyncio.Semaphore(self.config.max_concurrency)
        active = 0

        async def call(make: Callable[[], Any]) -> ModelOutput:
            nonlocal active
            async with semaphore:
                if self.is_cancelled():
                    raise Cancelled
                active += 1
                stats.max_concurrent = max(stats.max_concurrent, active)
                stats.model_calls += 1
                try:
                    output: ModelOutput = await make()
                finally:
                    active -= 1
                stats.input_tokens += output.usage.input_tokens
                stats.output_tokens += output.usage.output_tokens
                return output

        chapter_titles = {c["chapter_id"]: c["title"] for c in book.ledger["chapters"]}

        async def map_block(block: _Block) -> tuple[Claim, ...] | None:
            checkpoint = (key[1], block.chapter_id, block.block_id, key[3], key[4], key[5])
            if checkpoint in self.checkpoints:
                stats.checkpoint_hits += 1
                return self.checkpoints[checkpoint]
            sources = [SourceText(c.chunk_id, c.text) for c in block.chunks]
            for attempt in range(1 + self.config.block_retries):
                if attempt:
                    stats.retries += 1
                try:
                    output = await call(
                        partial(self.model.map_block, chapter_titles[block.chapter_id], sources)
                    )
                except Cancelled:
                    raise
                except Exception:
                    stats.provider_errors += 1  # recorded; retried once, then the block fails
                    continue
                kept, rejected = verify_claims(output.claims, block.source_ids, texts)
                stats.rejected_claims += rejected
                if kept and not rejected:
                    self.checkpoints[checkpoint] = tuple(kept)
                    return tuple(kept)
            return None

        try:
            block_results = await asyncio.gather(*(map_block(b) for b in blocks))
            response = await self._reduce(book, view, blocks, block_results, texts, call, stats)
        except Cancelled:
            return SummaryResult(self._failed(book, "CANCELLED", view), plan, stats)

        if check_full_summary(response, view):
            return SummaryResult(self._failed(book, "PUBLICATION_REJECTED", view), plan, stats)
        if response["status"] in {"ready", "partial"} and not self.is_cancelled():
            self.cache[key] = response
        return SummaryResult(response, plan, stats)

    async def _reduce(
        self,
        book: CanonicalBook,
        view: LedgerView,
        blocks: Sequence[_Block],
        block_results: Sequence[tuple[Claim, ...] | None],
        texts: dict[str, str],
        call: Callable[[Callable[[], Any]], Any],
        stats: RunStats,
    ) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        chapter_claims: list[list[Claim]] = []
        verified_sections: set[str] = set()
        for block, result in zip(blocks, block_results, strict=True):
            if result is not None:
                verified_sections |= block.section_ids
        for chapter in book.ledger["chapters"]:
            cid = chapter["chapter_id"]
            sections = [s["section_id"] for s in chapter["sections"]]
            # a section with no chunks (unreadable) can never be verified
            covered = [s for s in sections if s in verified_sections]
            verified = [
                claim
                for block, result in zip(blocks, block_results, strict=True)
                if block.chapter_id == cid and result is not None
                for claim in result
            ]
            claims: list[Claim] = []
            if verified:
                allowed = frozenset(s for claim in verified for s in claim.source_ids)
                output = await call(partial(self.model.reduce_chapter, chapter["title"], verified))
                claims, rejected = verify_claims(output.claims, allowed, texts)
                stats.rejected_claims += rejected
            if claims and len(covered) == len(sections):
                state = "complete"
            elif claims:
                state = "partial"
            else:
                state, covered = "failed", []
            chapter_claims.append(claims)
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
                    "accounted_unit_count": len(covered) if state != "failed" else 0,
                }
            )

        overview: list[Claim] = []
        usable = [claims for claims in chapter_claims if claims]
        if usable:
            allowed = frozenset(s for claims in usable for c in claims for s in c.source_ids)
            output = await call(partial(self.model.reduce_book, usable))
            overview, rejected = verify_claims(output.claims, allowed, texts)
            stats.rejected_claims += rejected

        failed_ids = [s["chapter_id"] for s in summaries if s["state"] == "failed"]
        completed = sum(s["state"] == "complete" for s in summaries)
        everything = completed == len(summaries) and bool(overview)
        if not overview:
            status, label = "failed", "unavailable"
        elif everything:
            status, label = "ready", "complete"
        else:
            status, label = "partial", "partial"
        if status == "failed":
            return self._failed(book, "NO_VERIFIED_CONTENT", view)

        chunk_chapter = {c.chunk_id: c.chapter_id for c in book.chunks}
        cited: dict[str, str] = {}
        for claim in [*overview, *(c for claims in chapter_claims for c in claims)]:
            for source_id in claim.source_ids:
                cited[source_id] = chunk_chapter[source_id]
        return {
            "book_id": view.book_id,
            "book_version_id": view.book_version_id,
            "summary_spec_version": SUMMARY_SPEC_VERSION,
            "status": status,
            "overview_claims": [
                {
                    "claim_id": f"overview-c{i}",
                    "text": c.text,
                    "source_ids": list(dict.fromkeys(c.source_ids)),
                }
                for i, c in enumerate(overview, start=1)
            ],
            "chapter_summaries": summaries,
            "coverage": {
                "chapters_expected": len(summaries),
                "chapters_accounted": len(summaries),
                "chapters_completed": completed,
                "failed_chapter_ids": failed_ids,
                "source_units_expected": view.source_units,
                "source_units_accounted": sum(s["accounted_unit_count"] for s in summaries),
                "completeness_label": label,
            },
            "citations": [{"source_id": s, "chapter_id": c} for s, c in cited.items()],
            "updated_at": self.clock(),
            "job_id": None,
            "error_code": None if status == "ready" else "INCOMPLETE_COVERAGE",
        }

    def _failed(
        self, book: CanonicalBook, code: str, view: LedgerView | None = None
    ) -> dict[str, Any]:
        ledger = book.ledger
        chapters = len(view.chapters) if view else len(ledger.get("chapters", []))
        units = view.source_units if view else 0
        return {
            "book_id": ledger.get("book_id"),
            "book_version_id": ledger.get("book_version_id"),
            "summary_spec_version": SUMMARY_SPEC_VERSION,
            "status": "failed",
            "overview_claims": [],
            "chapter_summaries": [],
            "coverage": {
                "chapters_expected": chapters,
                "chapters_accounted": 0,
                "chapters_completed": 0,
                "failed_chapter_ids": [],
                "source_units_expected": units,
                "source_units_accounted": 0,
                "completeness_label": "unavailable",
            },
            "citations": [],
            "updated_at": self.clock(),
            "job_id": None,
            "error_code": code,
        }


def prompt_hash(*prompts: str) -> str:
    return hashlib.sha256("\x1e".join(prompts).encode("utf-8")).hexdigest()[:16]
