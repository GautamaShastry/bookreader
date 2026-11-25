# 16 — First Coding-Agent Tickets with Evaluation Gates (v1.4)

All tickets below are **approved for local implementation only**, subject to review. Complete one PR per ticket. No paid AWS deployment or LLM API calls in the default CI. The agent must read `AGENTS.md`, `15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md`, this ticket file, the relevant normative spec and JSON Schemas.

## Ordered dependency plan

| Order | Ticket | Depends on | Scope | Merge gate |
|---|---|---|---|---|
| 1 | BS-001 | none | Monorepo and CI contract validators | green deterministic CI |
| 2 | EV-001 | BS-001 | Licensed fixture corpus and gold eval manifest | provenance and label integrity |
| 3 | BS-004 | BS-001, EV-001 | Text PDF parsing and source mapping | page/quote integrity on gold fixtures |
| 4 | EV-002 | BS-004 | Parser/chunker scorecard tooling | machine-readable failing-case report |
| 5 | BS-005 | BS-001, EV-001 | Safe EPUB parsing and source mapping | EPUB spine/anchor navigation and safety |
| 6 | BS-006 | BS-004, BS-005, EV-002 | Canonical chapters, deterministic chunks and ledgers | all source units accounted for |
| 7 | BS-026 | BS-001 | Full-book API/schema contracts and fake workflow harness | schema and negative-contract CI |
| 8 | BS-027 | BS-006, BS-026 | Hierarchical book-summary engine with mocked LLM | full-manifest traversal, fail-closed and cost tests |
| 9 | EV-009 | BS-027, EV-001 | Book-summary scorecard and comparative baseline harness | no false-complete; saved run manifests |

### BS-001 — Repository bootstrap and contract CI
**Goal:** Establish a reproducible workspace, without touching AWS. **Scope:** `/apps/web`, `/services/api`, `/services/ingestor`, `/services/agent-runtime`, `/packages/contracts`, `/tests`, `/infra`, `/specs` (scaffolding only). Add Python project tooling, React+TypeScript strict, ruff, pytest, mypy/pyright, ESLint, Playwright setup, JSON Schema/YAML parsing and CI.

**Evals:** a schema smoke test validating all JSON schemas and OpenAPI references, a malformed schema fixture that must fail CI, lint/typecheck/unit smoke, no AWS credentials required. **Merge:** fresh clone + one command reports green; error output retains failing test name. **Forbidden:** models, vector DB, cloud deploy, UI animations, external content.

### EV-001 — Legal corpus and gold labels
**Goal:** Make eval truth independent from models. **Scope:** create `/tests/fixtures/manifest.json` with ≥3 permitted small documents or synthetic fixtures (at least one PDF and one EPUB), license/provenance, SHA-256, known ordered pages/chapters/sections, canonical quotes and expected locators. Create `eval_cases.jsonl` template with `case_id`, `book_version_id`, `question`, `gold_source_ids`, `expected_status`, `reviewer_status`.

**Evals:** fixture hash validation, duplicate ID rejection, invalid gold source ID rejection, verified license metadata, JSONL/schema validation. **Merge:** all references resolve; manual verified initial gold excerpt labels. **Forbidden:** proprietary books committed as fixtures or fabricated gold answers. The eventual 150 QA, 40 brief, 20 full-book, 15 UX targets are future datasets—not declared complete by this ticket.

### BS-004 — PDF parser and canonical page locator
**Goal:** From an authorized sample PDF, extract every text-bearing physical page and source spans. **Scope:** PyMuPDF adapter, page-inventory diagnostics, normalized text offsets, page-boundary-safe locators, error classifications; no embeddings. **Evals:** multi-page, repeated phrase, Unicode, missing bookmarks, out-of-order blocks, empty/image-only, corrupted and encrypted fixtures. Assert that each emitted span's canonical quote resolves to the correct physical page. **Merge:** 100% exact fixture locator assertions; unreadable material is explicitly marked, not silently dropped. **Forbidden:** OCR, LLM summaries, AWS service calls.

### EV-002 — Source-integrity evaluation harness
**Goal:** Make parser and source-map accuracy measurable. **Scope:** deterministic `pytest`/CLI producing JSON and Markdown summary for `total_source_units`, `units_parsed`, `unreadable_units`, `coverage`, `locator_valid`, `hash_valid`, `reading_order_issues` and case-level failures. **Evals:** intentionally corrupt fixture must fail; an empty output cannot score 100%. **Merge:** deterministic results from fixed fixtures, report saved in CI artifact. **Forbidden:** fabricated metrics or treating model judge verdict as deterministic truth.

### BS-005 — Safe EPUB parser and locators
**Goal:** Extract ordered spine/XHTML and TOC with stable anchors. **Scope:** safe ZIP expansion limits, XML/HTML sanitization, exact section anchors and quote fallback; no DRM bypass. **Evals:** valid EPUB 2/3 samples, missing anchor, ambiguous quote, ZIP slip, expansion bomb, malformed OPF, missing spine, encrypted/DRM EPUB. **Merge:** every displayed fixture citation resolves to the correct section; ambiguous sources explicitly marked unverified; malicious packages rejected. **Forbidden:** DRM stripping or arbitrary external fetches.

### BS-006 — Canonical chunker, chapter ledger and identity
**Goal:** Build authoritative passage/section/chapter manifests for RAG and full-book summaries. **Scope:** paragraph-aware chunker, stable hashes/IDs, physical-page and EPUB spine limits, ordered chapter+section ledger, SHA-256 cache identity, storage adapter with mock S3 interface. **Evals:** 100% input-unit accounting, no cross-page/spine chunks, deterministic reconstruction, duplicate processing idempotent, corrupted hash and foreign book/version rejection. **Merge:** fixtures round-trip by source ID and locator and produce an auditable full-book manifest. **Forbidden:** vector similarity as source-of-truth and untracked omission.

### BS-026 — Full-book contract and fake-workflow tests
**Goal:** Make the v1.4 scope machine-readable without real inference. **Scope:** API POST/GET and job schemas in `06-API-OPENAPI.yaml`, `schemas/book-full-summary.schema.json`, synthetic positive/negative examples, and fake executor returning an ordered ledger. **Evals:** OpenAPI/schema parse, required `Idempotency-Key`, `job_type=full_book_summary`, `ready` requires complete coverage; missing-source and false-ready examples fail validation/publisher checks. **Merge:** API+example contract tests green. **Forbidden:** silently sharing the orientation-brief cache as a comprehensive summary.

### BS-027 — Hierarchical full-book engine (offline fake model)
**Goal:** Prove orchestration from canonical manifest to verified answer without paying for inference. **Scope:** bounded section map, per-chapter reduce, final book reduce, typed evidence handoffs, source-grounded verifier stub and deterministic publication gate, caching and quota preflight. **Evals:** 3+ chapters, synthetic 600-page fixture, repeated text, one chapter fails, wrong-owner source ID, prompt injection in book text, job duplicated, deletion mid-flight, budget estimate over $2.50, interrupted worker. **Merge:** zero false `ready` on incomplete fixtures, exact ledger accounting, no unsupported citation published, bounded concurrency/retries and preserved chapter order. **Forbidden:** claiming real quality metrics from fake models.

### EV-009 — Full-book evaluation harness and baseline
**Goal:** Define final gold quality measurement separately from deterministic workflow tests. **Scope:** human rubric, case metadata, coverage precision/recall, support judgments, cost/token/latency counters, single-agent baseline adapter; later populate ≥20 annotated full-book cases from ≥3 books. **Evals:** scoring catches a summary containing only the first chapter, missing citations, and a false `ready` with skipped units. **Merge:** scorer deterministic against synthetic expected labels; incomplete real gold coverage labeled TODO rather than completed. **Forbidden:** reporting fake/synthetic results as production quality.

## Required PR report template

```
Ticket: BS-___
Specs/ADR references:
Source commit / changes:
Files changed:
New tests / changed tests:
Fixture manifest SHA-256:
Tests executed + counts + failures:
Expected vs observed outputs:
Security / privacy impact:
Estimated AWS cost $ (default local = $0); observed AWS spend $ if any:
Known limitations / deferred functionality:
Deployment changes: NONE unless specifically approved
Reviewer approval:
```

**Stop policy:** A failure of source mapping, access scope, chapter ledger accounting, or citation integrity blocks dependent tickets. Any inconsistent document/schema blocks implementation until the contract is reconciled.
