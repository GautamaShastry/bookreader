# 09 — Implementation Plan and Work Breakdown

**Implementation approach:** Vertical slices; build something testable at every milestone. This is an ordered plan, **not a promise of elapsed time**.

## Milestone M0 — Environment and fixtures

**Deliverables:** Monorepo, Python backend project, React frontend, CDK, CI (lint/typecheck/tests), sample permitted PDF and EPUB, baseline AWS budget alerts and local secrets strategy.

**Tasks:**
- Decide one AWS Region after verifying Bedrock model, embedding model, KB+S3 Vectors availability.
- Bootstrap `/apps/web`, `/services/api`, `/services/ingestor`, `/infra`, `/packages/contracts`, `/tests/eval`.
- Add `ruff`, `pytest`, `mypy` or pyright for backend, TypeScript strict, eslint, and YAML/OpenAPI/schema validation in CI.
- Acquire 3–5 legally reproducible documents of varied structure; create fixture manifest.

**Exit:** Clean local build and CI; budget alarm created before paid experiments.

## Milestone M1 — Reader and ingestion vertical slice

**Deliverables:** Sign-in, library/upload UI, private S3 upload, ingestion worker, PDF and EPUB readers, TOC and page/section locators, chunk index and source map.

**Tasks:**
1. Build Cognito JWT and backend ownership middleware.
2. Upload reservation + signed POST + completion endpoint.
3. Implement PDF extraction (physical pages and text spans) and EPUB extraction (safe ZIP, spine, XHTML).
4. Persist normalized source maps and stable chunks.
5. Provision Bedrock KB with S3 Vectors; ingest chunks with metadata.
6. Show status progress; harden retry/idempotency and failure UI.

**Exit:** One PDF and one EPUB load into reader; click a test source-map citation and navigate to correct location. Metadata round-trip checks pass.

## Milestone M2 — Verified ask-the-book

**Deliverables:** Chat conversation, scoped LangGraph multi-agent subgraphs (Supervisor, Retrieval, Teaching, Grounding Verifier), AgentCore Runtime adapter, Retrieve adapter, source sufficiency gate, typed handoffs, verification gate, citation-aware response.

**Tasks:**
1. Implement conversations pinned to immutable book version.
2. Implement book-scoped retrieval filters + post-filter scope checks and validated `EvidenceBundle` contract.
2a. Build bounded Supervisor routing, Retrieval specialist, and Teaching specialist with minimal private context; wire one AgentCore Runtime behind the authorized API.
3. Implement canonical chunk loader; never cite KB text without map resolution.
4. Implement evidence sufficiency and generated structured claims.
5. Implement independent Grounding Verifier subgraph, schema validation, citation integrity and semantic support checks, plus deterministic publish gate.
6. Implement no-draft streaming policy and correct abstention UX.
7. Add adversarial cross-tenant/out-of-book integration tests.

**Exit:** P0 answerable and out-of-scope cases pass core eval suite; source navigation works; unsafe results never display.

## Milestone M3 — Contextual explanation and chapter summary

**Deliverables:** Explain selection route, complete chapter traversal + bounded parallel Summarization Agent map/reduce, coverage verifier, summary job state, per-book conversation list.

**Tasks:**
1. Validate selection against canonical text, not only client payload.
2. Expand within book section as needed; generate verified explanation.
3. Build chapter text traversal; map and reduce with section coverage tracking.
4. Implement API job status for summaries; cache by version and spec version.
5. Add summary and explanation evaluation cases.

**Exit:** One long chapter is fully traversed and summarization is demonstrably complete or clearly marked partial; selection cannot inject outside text.

## Milestone M4 — Cloud production quality and portfolio evidence

**Deliverables:** Deployed dev/prod environments, private content and IAM tests, observability, deletion, cost/perf report, demo on openly licensed book, README with architecture and failure cases.

**Tasks:**
1. Deploy CDK, HTTPS/CloudFront, Cognito, API, workers, DynamoDB, KB and alerts.
2. Add deletion and verified index purge, secret handling, rate limiting and audit trails.
3. Run frozen holdout eval and record achieved metrics with source links.
4. Load-test representative books and capture stage-wise latency/cost.
5. Publish architecture, test design and a guarded demo; do not publish copyrighted private books.
6. Compare multi-agent to a frozen single-agent baseline; evaluate whether book-scoped lexical retrieval improves measured misses; OCR remains deferred.

**Exit:** Reproducible AWS deployment, passing security tests, documented measured results, user-demo journey complete.

## Work packages / sample implementation tickets

| ID | Ticket | Blocked by | Done when |
|---|---|---|---|
| BS-001 | Repo bootstrap and CI | none | clean test and lint pipeline |
| BS-002 | Cognito auth + ownership middleware | 001 | cross-owner 404 tests pass |
| BS-003 | Signed S3 upload contract | 002 | file size/type enforced server-side |
| BS-004 | PDF parser + source map | 001 | accurate physical page citation |
| BS-005 | Safe EPUB parser + source map | 001 | source anchor resolution works |
| BS-006 | Canonical chunker + manifests | 004,005 | deterministic IDs, no boundary crossing |
| BS-007 | KB/S3 Vectors index + metadata filters | 006 | read-back and canary retrieval pass |
| BS-008 | PDF/EPUB reader and TOC | 003 | user can read and navigate |
| BS-009 | Conversations and ask API | 002,007 | pinned conversation and valid errors |
| BS-010 | LangGraph Supervisor + Retrieval subgraphs and evidence gate | 009 | passes source scope tests, bounded handoffs |
| BS-011 | Teaching + independent Grounding Verifier; safe response adapter | 010 | unsupported claims withheld |
| BS-012 | Citation navigator | 008,011 | PDF/EPUB links navigate correctly |
| BS-013 | Explain highlighted text | 011,012 | selected span verified |
| BS-014 | Summarization subgraph + bounded parallel chapter jobs | 006,011 | full coverage traversal verified |
| BS-015 | Deletion, quotas and operations | 003,007,009 | revoke and purge tests pass |
| BS-016 | Eval benchmark + multi-agent ablation + demo report | 011,014,015 | claims backed by real measurements |
| BS-017 | AgentCore Runtime adapter and IAM-bound invocation | 010 | deployed graph inaccessible without authorized backend |
| BS-018 | Typed handoff and context-leakage contract tests | 010,011 | every agent context and schema validated |
| BS-019 | Per-role cost/latency tracing and circuit budgets | 017,018 | bounded retries and spending measurable |

## Reusable engineering decisions

- No feature proceeds without an acceptance test and traceability ID.
- For each milestone, explicitly label what is **implemented**, **deployed**, and **measured**.
- Never insert fabricated resume metrics. After M4, calculate results from saved evaluation and tracing artifacts.
- The first coding session should implement **BS-001 + BS-004** with unit tests, not begin with an agent framework or UI animation.

## v1.1 critical path

**Phase 1: source truth first.** Repo/CI -> PDF/EPUB parser -> canonical source map -> scoped index. Local deterministic tests must pass before model calls are enabled.

**Phase 2: multi-agent local graph.** Typed `SupervisorDecision` -> scoped `EvidenceBundle` -> TeachingDraft -> independent VerificationVerdict -> deterministic final publisher. Run full graph locally with fake KB and model adapters first.

**Phase 3: hosting.** Deploy the graph as **one** AgentCore Runtime, invoked from the thin Lambda API with server-authenticated scope; use smoke tests and cost alarms. Do not deploy five agent services.

**Phase 4: chapter workflow.** Concurrent per-section summary workers, ordered reduction, coverage ledger, verifier, asynchronous job state; add mixed-size chapters.

**Phase 5: comparison.** Freeze a book-level holdout and benchmark v1.0 bounded single-agent baseline versus v1.1 multi-agent under matched budgets. Keep all achieved results and failures as explicit artifacts.

## v1.3 delivery addendum

M0: implement evaluation harness, legally usable fixture manifest, and book-open UI event tests. M1: auto-open assistant panel; safe TOC/loading states; immutable book/version scope. M2: start `BRIEF_REQUESTED` after verified indexing, implement source-ledger brief generation, verifier and cached GET endpoint; do not wait for user to ask first question. M3: production-grade orientation navigation and chapter-summary connection. M4: expand labeled orientation data, freeze book-level holdout, compare single/multi-agent under matched budgets, evaluate learner comprehension and cost. New tickets BS-020 (book-open UI), BS-021 (brief background job), BS-022 (brief API+cache), BS-023 (per-stage evaluation CI), BS-024 (learning usability eval).

BS-025 (P1): Guided teaching session with citation-backed micro-lessons, comprehension checks, and a scored evaluation on an authorized corpus; starts after verified book brief and source navigation gates pass.


## v1.4 mandatory delivery extension

Full-book hierarchical summaries are now P0, NOT post-launch. After BS-006 canonical manifest and BS-026 API schema work, implement BS-027 fake-model hierarchical orchestration and EV-009 evaluation tooling; then replace model adapter with budget-controlled Bedrock execution only after staged approval and metadata compatibility check. Validate full book traversal, citations, partial state, cache and cost. **First PRs, with complete eval gates, are defined in `16-FIRST-CODING-AGENT-TICKETS.md` and supersede older generic ticket descriptions.** v1.3 exclusion of full-book summary is superseded by ADR-015.
