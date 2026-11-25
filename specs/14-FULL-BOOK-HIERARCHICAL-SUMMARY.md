# 14 — Full-Book Hierarchical Summary (v1.4, normative)

## Product requirement FR-028 / P-16 — First release
Authenticated users can request an evidence-grounded overview of the entire **selected immutable book version**. The workflow uses a complete canonical chapter inventory rather than `Retrieve(top_k)`. It supports English text-based PDF/DRM-free EPUB within existing ingestion limits. It does **not** promise a line-by-line paraphrase or the complete retention of every fact.

**Distinct from Book Intelligence Brief:** The brief is generated once after ingestion and is automatically *read* from cache on `BOOK_OPENED`. The full-book summary is requested deliberately using a button and queued asynchronously. Book open NEVER triggers full-book inference. The full summary has its own spec/version, status, citations, coverage ledger, cost limits and cache.

## Workflow and boundaries

1. API authenticates the user, checks ownership and immutable `book_version_id`, READY status, and per-account quotas. A distinct idempotency key collapses duplicate submissions. No user-supplied `owner_id` or arbitrary source keys are accepted.
2. Read **authoritative chapter inventory** from canonical manifest in S3. The inventory covers every chapter or inferred section. Mark unreadable sections explicitly. Assign stable ordered units/section IDs. Reject books with no reliable chapter inventory until structure is repaired.
3. Preflight the work *before* a paid model call: count source tokens, derive upper-bound map/reduce calls and input/output tokens, estimate using a reviewed per-Region pricing catalog and apply a configurable maximum job allowance (initial dev allowance $2.50); if over allowance, refuse/require approved reconfiguration—never silently skip chapters. This is a control, not a guarantee against delayed billing or model-level cost overruns.
4. For each chapter, traverse **all source blocks in reading order**, ensuring the `source_id`, hash and book scope resolve. Map blocks into bounded evidence-linked partial summaries. Use no web search. Bounded parallelism: default max 2 concurrent model workers for full-book jobs; retry one failed block once, only if estimated remaining budget allows.
5. Verify every block summary against its canonical passages. Invalid blocks are retried or marked failed; never silently promoted. Aggregate verified blocks into a chapter summary, using bounded reduction levels with an explicit section coverage ledger.
6. Verify each chapter summary against the chapter's canonical material (source IDs, claims and annotated coverage). Aggregate ordered chapter summaries into a book-level synthesis and structured chapter map. The final synthesis has citations to real source IDs, not citations to intermediate model text.
7. Validate *every* final material claim against canonical authorized passages (model verifier + deterministic citation authorization, hash, locator and coverage gate). The final result returns `ready` only if the whole chapter inventory is accounted for, no material unit failed or was silently skipped, and all published claims have valid supported citations. Otherwise return `partial` with named uncovered chapters/sections, or `failed` with no misleading complete summary.
8. Publish an immutable artifact keyed by `owner_id|book_version_id|summary_spec_version|model_id|prompt_hash|source_manifest_sha`. Expose a cached GET and verified citation navigation; subsequent GETs and repeated book openings do not invoke the LLM. Expiration/version changes invalidate cached result. Deletion revokes access immediately and purges derived summaries asynchronously.

## Five logical roles, selective execution
- **Supervisor:** selects `SUMMARIZE_BOOK`, validates job prerequisites and invokes summarization path, never reads full book.
- **Retrieval:** not part of full-book completeness traversal. Canonical manifest reader (deterministic tool) enumerates content; optional book-scoped retrieval is allowed only to check individual evidence gaps, never to decide which chapters to cover.
- **Summarization Agent:** section-level map, chapter reduction, final book synthesis; each invocation gets a bounded, purpose-specific context and validated source IDs.
- **Teaching Agent:** not used automatically for full-book summary; only for separate user questions and explanations.
- **Grounding Verifier:** independently validates block, chapter and book-level claims; deterministic publication gate remains final authority for source ID, ownership, version, locator and coverage.

## Output contract
Public response `FullBookSummaryResponse`: `book_id`, `book_version_id`, `summary_spec_version`, `status` (`queued|generating|verifying|ready|partial|failed|unavailable`), `overview_claims[]`, `chapter_summaries[]`, `coverage`, `citations[]`, `updated_at`, optional `job_id`/`error_code`. Each verified claim has `claim_id`, `text`, and at least one canonical `source_id`. `coverage` contains total chapters, accounted chapters, completed chapters, failed chapters and an explicit `complete|partial|unavailable` label. `ready` implies complete manifest accounting and zero failed material units; `partial` never implies comprehensive coverage.

## API contract
- `POST /v1/books/{book_id}/full-summary` requires authorized book and `Idempotency-Key`. Queues background work; returns existing cached or in-flight job if identical. Never triggers a synchronous full-book model call. Returns `202 Job` or a structured cost/limit error before model inference.
- `GET /v1/books/{book_id}/full-summary` returns cached/result state **without new LLM calls**. Results must be bound to the authenticated owner's active immutable version and valid manifest hash.
- `GET /v1/jobs/{job_id}` retains common job polling; `job_type=full_book_summary`.
- Explicit cancel operation is a later API addition; initial dev worker uses cooperative internal cancellation on deletion/budget-stop flags. No uncontrolled auto-retries.
- Schemas: `schemas/book-full-summary.schema.json`, plus `components.schemas.FullBookSummaryResponse` in OpenAPI. Both must pass contract tests on positive/negative examples.

## Failure semantics
| Condition | Behavior |
|---|---|
| Chapter unavailable/image-only segment | `partial` + identified chapter/section, or `failed` if nothing useful survives |
| Worker/model failure | bounded retry; never mark `ready` if material parts are missing |
| Invalid or wrong-owner citation | fail closed; no unsupported text shown |
| Budget preflight insufficient | reject/queue nothing, return `COST_BUDGET_EXCEEDED` or approved lower-scope alternative; do not change full-book definition |
| Duplicate POST | idempotently reuse same in-flight/completed job and result |
| Book deletion during processing | cancel/revoke; purge summary and intermediate artifacts; `404/409` for further reads |
| KB retrieval misses material | does not affect manifest traversal; retrieval is not the summary enumerator |

## Evaluation FR-029 (release blocking)
- Construct ≥20 **human-annotated full-book summary cases across ≥3 legally usable books**, including a multi-chapter book, heading-poor PDF, long EPUB, and deliberately unreadable segment. Keep long synthetic fixtures for stress testing. These 20 are additional to existing QA, brief and UI counts; count case/fixture separately.
- Unit/integration: 100% chapter + source-unit manifest accounting for labeled fixtures, in-order reduction, dedupe, no chunk ID mutations, no cross-book reads, verified cache/migration/deletion behavior; 0 critical gate escapes.
- Model eval targets (not achieved): ≥95% coverage of **human-annotated material topics**, ≥98% supported claims, 100% valid displayed citations, zero false `ready` on partial fixtures. Show raw denominators and failed cases, and separately record summarization cost, latency, token use and false omissions.
- Benchmark against the single-agent baseline at matched book/model/budget; include differences in quality, latency and cost. Use the frozen book-level holdout only for final evaluation.

## Cost safety
The $50/month AWS amount is a **target**, not a billing stop. No unapproved paid infrastructure. Summaries are on-demand, capped by a configurable per-job preflight allowance (default $2.50 for dev), and cached by immutable source/config version. Concurrency 2; new paid jobs denied when a local spending ledger reaches a conservative stop threshold. Keep AWS Budgets alerts plus manual spend review. A 600-page book may exceed the allowance; the application must clearly refuse and permit a later approved budget/config change, not pretend it analyzed the whole book.
