> HISTORICAL REVIEW ONLY (v1.2): the open decision to defer full-book summaries has been resolved by ADR-015 in v1.4. The frozen v1.4 contract and spec 14 take precedence over this document.

# BookScope AI — Pre-Coding Readiness Review & Coding-Agent Handoff

**Review version:** 1.2 addendum to BookScope v1.1 specifications  
**Date:** 2026-11-24  
**Status:** Architecture is suitable as a target; authorise only staged implementation until the gates below pass.  
**Source set reviewed:** BookScope v1.1 specification package (22 files), multi-agent workflow, OpenAPI 3.1, JSON Schemas, AGENTS.md, and enterprise AWS architecture guide.

## 1. Executive engineering decision

Do **not** ask a coding agent to build all AWS infrastructure, the frontend, multi-agent orchestration, and retrieval in one task. Start with a small deterministic vertical slice that converts a legal source PDF into canonical passages with verifiable page links. The source-of-truth and security requirements must be demonstrable without an LLM. Expand behind reviewed pull requests and measurable gates.

## 2. What v1.1 already specifies sufficiently

- V1 scope: import text-based PDF and DRM-free EPUB; ask, explain selection, summarize a selected chapter; verified citations or refusal. Scanned PDFs, primary figure reasoning, whole-book summaries and third-party reader interception are out of scope.
- Book isolation: one immutable `book_version_id` per conversation, server-established owner scope and per-query metadata filtering with post-checks.
- Canonical source-map structure, page/EPUB locators, hashes, chunking and refusal constraints.
- Five logical specialist roles (Supervisor, Retrieval, Teaching, Summarization, Verifier), typed handoffs, bounded retries, independent deterministic publisher.
- API and schemas, auth and privacy principles, local-first graph development, AWS production target, evaluation target metrics.

Do not discard these decisions or rewrite them speculatively.

## 3. Open decisions and missing evidence (prioritised)

| ID | Severity | Actual finding / gap | Decision or proof required | Owner |
|---|---|---|---|---|
| R-01 | P0 | The provided evaluation seed file contains **10 unlabeled placeholder cases**, and the multi-agent seeds add 12 scenarios; these are **not** the prescribed 150 labeled, evidence-linked test examples. | Select a legally usable fixture corpus; annotate gold span/chunk IDs, answerability, expected refusal/partial status and chapter coverage. Freeze a book-level holdout. | Product + QA |
| R-02 | P0 | Ingestion path differs between docs: `07-SECURITY-AND-DEPLOYMENT.md` starts with an SQS-triggered Lambda parser and escalates to Step Functions/Fargate if required, while the enterprise diagram uses Step Functions + Fargate from the start. | Freeze one M1 runtime. **Recommendation:** use a local parser first, then a minimal cloud Lambda canary for bounded workloads; adopt Fargate/Step Functions when measured memory/time limits or the portfolio deployment stage justify them. Revise the diagram label to **target**, not implemented. | Architecture |
| R-03 | P0 | Exact AWS Region, model IDs, embedding model, AgentCore IAM invocation and real KB indexing behavior remain untested. | AWS proof-of-compatibility canary: deploy a tiny permitted sample, index, filter by owner/book/version, return exact chunk IDs, resolve the canonical page and delete/revoke. Don't build the full agent until this works. | Cloud |
| R-04 | P0 | Citation source-map logic is specified, but no exercised real PDF/EPUB fixture demonstrates stable clickable page/section navigation. | Test extraction against text-heavy pages, columns, headers/footers, TOC, repeated phrases and EPUB reflow. Distinguish physical PDF page indices from printed labels; EPUB has no invariant physical page number. | Ingestion + Frontend |
| R-05 | P0 | Multi-agent grounding is still a design hypothesis; separate verifier can share the teacher's errors. | Implement independent verdicts, deterministic source ownership/hash/citation checks, negative examples, and a matched-budget single-agent baseline. No unsupported facts released; never claim a guarantee of zero hallucinations. | AI + QA |
| R-06 | P0 | Budget and deployment permissions are unspecified. | Set a hard operating budget, AWS account/Region, allowed model access, max book size, per-user quotas, model output budgets and resource teardown process **before** provisioning AWS. Do not assume a user-approved dollar amount. | Product + Cloud |
| R-07 | P1 | Product says “open any PDF/e-book” while v1 actually **imports** supported text PDFs or DRM-free EPUBs into the app. | Freeze copy and UX: no Chrome/OS reader interception, no DRM bypass, no scanned PDF or figure-based answers in v1; unsupported pages flagged explicitly. | Product |
| R-08 | P1 | Event trigger and duplicate processing need a single authoritative contract. | Choose S3 ObjectCreated -> SQS -> queue consumer, with object key/version + content hash idempotency; ensure no duplicate versions or accidental parallel indexing. `READY` requires verified retrieval canary, not just successful job status. | Backend |
| R-09 | P1 | Deletion involves S3 object versions, KB staging files, vector index, job artifacts and conversation history. | Immediate access revocation; persisted purge job with retries and an auditable completion state; test race with in-flight agent and eventual index removal. | Security |
| R-10 | P1 | Semantic retrieval may miss exact code symbols, API identifiers and chapter headings. | Evaluate `Recall@10` on exact terminology and paraphrases. Add a **book-scoped lexical fallback** only if measurement warrants; S3 Vectors KB integration is semantic-only. | Retrieval |
| R-11 | P1 | Frontend loading/partial/refusal/error behavior is described but not frozen in actual UI contract tests. | Define handling for `uploaded`, `processing`, `ready`, `failed`, `deleting`, `partial`, `insufficient_evidence`, `verification_failed`, `unsupported_content`, `429` and `503`. Never stream unverified draft output. | Frontend |
| R-12 | P1 | P95 latency, cost per answer/summary and ingestion SLA have no achieved baseline. | Instrument first cloud run; freeze explicit release thresholds after measurement; report with test denominators. | QA + Ops |
| R-13 | P0 (product) | Original product idea included summarizing an entire book, but v1.1 explicitly supports **chapter summaries only**; full-book summary is deferred. | Decide whether chapter-level only is acceptable for launch; recommendation: stage full-book, hierarchical summary after chapter coverage and citations are tested. Do not let an agent silently implement or advertise book-wide summary in v1. | Product |

### AWS compatibility hazards to test, not assume

1. Bedrock Knowledge Bases with S3 Vectors supports semantic retrieval, not hybrid; custom per-vector metadata is constrained (currently 1 KiB and 35 keys). Keep large source maps in private canonical S3, not vector metadata. Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html
2. Automatic PDF page-number metadata is not a substitute for an app-owned source map; AWS documentation describes specific page metadata behavior for other vector stores. Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-test-config.html
3. KB ingestion sync is incremental and retrieved vectors may lag behind completed synchronization. Require a real retrieval canary before marking a book `READY`. Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html
4. AgentCore Runtime hosts **our** LangGraph logic; it does not supply our orchestration policy. The Runtime packaging and invocation contract needs a dedicated smoke test. Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-vs-runtime.html

## 4. Product contract to freeze (v1)

- One authenticated owner, one selected immutable book version, one conversation. Every model-visible passage must come from that authorized version.
- Core modes: `ASK`, `EXPLAIN_SELECTION`, `SUMMARIZE_CHAPTER`.
- Questions requiring book-absent facts must yield refusal; mixed questions may return explicitly marked supported-only `partial` output; no silent outside examples or fresh external data.
- A chapter summary must enumerate every supported section in order, use coverage ledger, and disclose missing/unextractable sections. Top-k RAG is not an acceptable chapter summarization strategy.
- Verified answers include claim-level canonical chunk IDs that point to a valid PDF page index or EPUB spine/anchor/quote in the reader; UI opens the exact valid location.
- Hostile book instructions are never interpreted as control instructions. User text and model outputs cannot supply authoritative IDs/identity.
- No raw draft token streaming before independent verification and deterministic publication policy.
- Unsupported inputs fail safely. No DRM circumvention, no unauthorised sample book distribution.

## 5. Mandatory component contracts

### Canonical passage
`owner_id`, `book_id`, `book_version_id`, `chunk_id`, `content_hash`, `chapter_id`, `section_id`, `reading_order`, `canonical_text`, `locator`, `coverage_quality`.

PDF locator: `page_index` (zero-based, immutable physical position), optional page label and offsets. EPUB locator: spine href, section/anchor, normalized quote and offset; never invent a physical EPUB page.

### Retrieval and evidence
- Input scope is created by trusted backend auth. The model cannot mutate it.
- `EvidenceBundle` includes list of `chunk_id`s, canonical hashes, sufficiency-by-subquestion and missing-evidence reasons.
- Separate adapter validates every returned result's owner/book/version metadata and rehydrates canonical source text, never trusts generated citations.
- Strict two-pass retrieval cap, exact failure codes, no outside search.

### Multi-agent contracts
- Supervisor: intent + routing only; no evidence or answer.
- Retrieval: bounded scoped subqueries and passage references; no answer.
- Teaching: user question + validated evidence, typed claims linked to chunk IDs; no tool invocation.
- Summarization: complete chapter ledger -> bounded block summaries -> ordered reducer; explicit omissions.
- Verifier: canonical evidence + output claims, three-way supported/contradicted/uncertain verdict; no access to teaching's untrusted rationale.
- Final deterministic publisher: confirms auth/version, source hash, citation integrity, schema validity and all mandatory verdicts; failure = no factual draft released.

## 6. Build order: only hand the next gate to a coding agent

| Gate | Work permitted | Exit test | AWS allowed? |
|---|---|---|---|
| G0 — Repo/contracts | CI, locked dependencies, schema validators, realistic book fixtures, threat and evaluation harness | OpenAPI + Pydantic/TS generated contract CI passes; legal sample corpus selected | No |
| G1 — Source truth | PDF parser, canonical passages, locator resolver, EPUB parser, deterministic chunk IDs | On sample book every chunk opens correct page/section; negative parser tests pass | No |
| G2 — Scoping/index canary | Local scoped retriever; tiny Bedrock KB + S3 Vectors spike with real metadata round trip | Owner/book/version filter, wrong-owner rejection, eventual indexing readiness, exact citation resolution | Small approved staging only |
| G3 — Multi-agent graph locally | Typed five-role selective LangGraph, simulated KB/model, bounded retries, verifier and publish gate | Negative security/grounding and citation tests green; no unverified streams | Optional model test budget |
| G4 — Cloud integration | Cognito, API Gateway, thin Lambda, AgentCore Runtime, private S3, DynamoDB, queued ingestion | Full one-book E2E works with auth, deletion, throttling and trace IDs | Approved IaC deployment |
| G5 — Evaluation & release | 150+ labeled cases, single vs multi agent A/B, telemetry/cost, reader UX polish | Meets release thresholds; benchmark report states failures and achieved costs, not estimates | Controlled staging/prod |

**Stop rule:** If G1 source mapping fails, do not proceed to G2/G3. If G2 metadata isolation fails, do not proceed to live generative answers. If G3 verification fails, do not ship a user-facing answer endpoint.

## 7. Human-versus-coding-agent decision boundary

**Human / engineering lead must decide:** product scope, whether outside-book analogies are allowed (recommend no for v1), legal demo corpus, budget cap, architectural stack changes, public deployment, security exception approvals, model choice after benchmarking, benchmark publication and resume claims.

**Coding agents may decide within their assigned task:** function/module names, private implementation details, test organization, pure refactoring, formatting and CI improvements, as long as behavior and interfaces are unchanged.

**Coding agents must not silently decide:** add web search; weaken refusal; bypass owner/version filtering; disable verification; add a model or AWS service without approval; switch vector backends; change file-size/security limits; make books public; remove tests to make CI pass; invent performance metrics.

## 8. Ready-to-paste assignment for the first coding agent

> Implement **BookScope G0 + G1/PDF only** from the attached BookScope v1.1 specs and this handoff. Read `AGENTS.md`, `04-INGESTION-AND-RETRIEVAL.md`, `schemas/source-chunk.schema.json`, and `08-EVALUATION-AND-TESTING.md` before editing. Create the monorepo minimal Python packages, lint/type/test CI, a safe text-PDF parser, canonical chunk IDs, source hashes and zero-based PDF locators. Add parser tests for multi-page content, Unicode normalization, repeated text, missing TOC, page boundaries, an image-only PDF and a corrupt/encrypted PDF. Use a permitted, checked-in tiny fixture or synthetic generated PDFs with known page references; do not commit third-party proprietary book data. No LLM, Bedrock, KB, AgentCore or new AWS resources in this PR. Run tests and produce an evidence report showing test counts, example parsed JSON, confirmed page navigation and remaining limitations. Open a PR limited to G0+G1/PDF and do not claim other milestones are complete.

### Required pull-request evidence template

```
Ticket: BS-001 / BS-004
Scope: <what changed; explicitly what did not>
Contracts touched: <paths; backward-compatibility>
Tests run: <commands + passing/failed counts>
Security tests: <which cross-owner/input tests, if applicable>
Example fixture: <license, source hash, expected page index>
Observed outputs: <sample canonical chunk and resolved locator>
Cost impact: <none, or actual measured usage>
Known gaps / blockers: <concrete list>
Next unlocked ticket: <one ticket ID>
```

## 9. Release evidence that matters for the resume

Keep actual before/after datasets: retrieval recall@10, supported-claim rate with human audit, false-refusal rate, citation/navigation integrity, chapter-section coverage, p50/p95 response latency, tokens and cost per successful query. Compare to single-agent RAG under a matched budget. Cite date, model IDs, region, corpus version, sample size and failed cases. No success metrics or AWS deployment claims until verified.
