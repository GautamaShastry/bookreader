# 13 — Stage-by-Stage Evaluation, Release Gates, and Production Feedback (v1.3)

**Status:** New release-blocking strategy. This document extends `08-EVALUATION-AND-TESTING.md`; the original 150 labeled-case requirement remains. Proposed scores below are targets, NEVER measured achievements. Evaluation must expose failure provenance by stage, not only final answer pass/fail.

## 1. Architecture of the evaluation system

Three layers run at different cadences:

1. **Deterministic assertions** at every PR/CI run: exact parser spans, source hash, schema, scope, idempotency, citation navigation, state-machine and critical security properties. These are nonnegotiable fail-closed gates.
2. **Versioned offline model evaluations** on developer and book-level frozen holdout datasets: retrieval relevance, agent routing, grounded teaching, refusal behavior, overview/summary coverage and educational usefulness. Run before changes to prompts, retriever, chunker, models or book ingestion rules.
3. **Production quality monitoring** using sampled, privacy-safe traces and aggregate signals. Use AgentCore on-demand/online evaluations where supported; sampling/LLM judge verdicts are alerting/diagnostics rather than authoritative proof. Record costs/latency/refusals, not book plaintext by default.

AWS Bedrock RAG Evaluations supports retrieval and response/citation metrics. Bedrock AgentCore Evaluations supports on-demand and online agent trace quality assessment. Keep custom offline golden assertions for exact book-only rules. See https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-kb.html and https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html.

## 2. Per-stage evaluation matrix

| Stage | Examples / Gold truth | Metrics | Gate |
|---|---|---|---|
| Upload + accepted types | Valid and corrupt PDF/EPUB, zip bombs, oversized files | Accepted/rejected accuracy, ownership, resource limits | 100% critical path, no bypass |
| Parsing/reading order | Labeled pages, code, TOC, columns, EPUB anchors | Text span fidelity, chapter order, missing section disclosure | 100% tested locator integrity; never silently declare complete |
| Normalization/chunking | Canonical passage manifest and reconstruction fixtures | Coverage ratio, duplicate content, source hash match | 100% integrity for fixture set |
| Indexing + KB filter | Authorized version/owner test vectors, delayed index simulation | Index ready-to-query canary, wrong-scope hits | No unauthorized hits admitted; READY requires canary |
| Retrieval | Evidence-linked 60+ answerable cases, terminology/code queries | Recall@10, MRR, evidence coverage | Recall@10 >=90% target; explicit escalation for hard misses |
| Supervisor / routing | Gold intent+mode including ambiguous and unsupported | Intent accuracy, illegal route rate | >=98% accuracy target; 0 forbidden tool routes |
| Specialist contexts | Captured redacted handoff schemas and adversarial injections | Valid handoffs, context leak, token usage | 100% scope and schema validity; bounded context |
| Teaching and explanations | Book quotations and gold support spans | Claim precision, explanation fidelity, invented examples | >=98% supported claim ratio on human-audited set |
| Chapter summary | Full chapter section ledger | Section coverage, omitted key claims, false completeness | >=95% material-section coverage target, omissions disclosed |
| Book Intelligence Brief | Chapter manifest, independent labeled concept map, verified citations | Chapter inventory coverage, supported claims, outline-only correctness, navigation | 100% chapter inventory or explicit omissions; >=98% claim support target |
| Grounding Verifier | Supported, contradicted, unsupported, tricky mixed claims | TPR for unsupported claims, false reject rate, calibration | 0 unsupported escapes in fixed critical regression suite; audit false refusals |
| Deterministic publisher | Forged citation IDs, wrong owner/version, mutated hashes, deletion races | Unauthorized display count, invalid locators published | 0 leaks; 100% integrity on full security suite |
| Open-book UX | Playwright scenarios: first open, repeat, tabs, offline, deletion | Auto-panel activation, zero LLM on reopen, cached brief render, keyboard nav | 100% critical user flow cases |
| Platform operations | SQS duplicates, failed AWS requests, retries, cost caps | job dedupe, DLQ rate, p50/p95, USD/job, fault-recovery rate | No silent corruption; thresholds set from measured baseline |

**Important denominators:** report stage-wise (a) samples attempted, (b) scored, (c) errors, (d) passes and (e) failure severity. Don't hide skipped cases or evaluate only successful runs.

## 3. Curated datasets and independent annotation

- Keep original minimum **150** book-grounded cases from v1.1, with canonical `book_version_id`, gold passage IDs, expected answer/status, rubric and adjudicator notes.
- Add **at least 40 orientation cases** across books of different layouts, with `chapters_expected`, `key_concepts_gold`, `allowed_claims`, `unextractable_sections`, and `expected_status` (`ready|partial|failed`).
- Add **at least 15 UI event scenarios** (`BOOK_OPENED` repeated, switching book, two tabs, unready book, deletion, cache invalidation, retry, keyboard dismissal). These are deterministic UI/E2E cases, not counted as model QA questions.
- Create clear splits: development set (iterative), holdout set frozen at *book* level, adversarial security suite run on every release. A human must verify disputed factual labels with canonical source references.
- Store only openly licensed or authorized corpora; do not publish protected book excerpts in eval reports.
- Record dataset manifest and version hash. Create failure taxonomy: `PARSE_MISSING`, `CHUNK_WRONG`, `INDEX_LAG`, `RETRIEVAL_MISS`, `ROUTE_ERROR`, `UNSUPPORTED_DRAFT`, `VERIFIER_FALSE_PASS`, `VERIFIER_FALSE_REJECT`, `PUBLISH_SCOPE_ERROR`, `UI_TRIGGER_ERROR`, `BRIEF_COVERAGE_GAP`, `UPSTREAM_TIMEOUT`.

## 4. Evaluation execution policy

- On *every commit*: lint/types + schema checks, authz/state-machine tests, parser fixture assertions, fake-agent graph tests, critical citation/security cases, UI event unit tests. No remote model invocation in default CI.
- On *every relevant PR*: run the fixed offline per-stage suite where inputs/model access are available; cache/report exact config, compare to last green baseline, surface regression deltas. Enforce deterministic hard gates; model-quality thresholds are reviewed from the dataset with confidence intervals rather than a single synthetic grader score.
- Before staging promotion: run AWS canary (KB scope roundtrip, AgentCore role invocation, verified brief generation, citation click), frozen holdout and critical adversarial suite; enforce cost-budget approval.
- Before production: review human-audited support samples and known failures, user journey tests, privacy and access revocation; do not release when critical gate fails.
- After release: monitor sampled traces for route correctness, groundedness and unexpected refusals via AgentCore Evaluations where enabled; alert on elevated error and cost; manual review privacy-sanitized incident evidence. Never silently allow LLM judge to override deterministic policy.

## 5. Runtime evaluations and self-checking (not model-generated self-certification)

At request time, enforce schema validity, authorized book/version, passage hash and citation resolution, bounded retrieval retries, semantic support verifier, and final publication gate. Per-request support judgments are runtime safeguards; offline labeled evaluations demonstrate whether they actually work.

On `BOOK_OPENED`: do **not** evaluate/generate using a fresh LLM invocation. Check versioned cached brief `verified_at`, permissions and content hash. If not ready, return stage status and canonical TOC. Asynchronous job handles full generation and verification.

## 6. Success as learning product (measured, not inferred)

Use voluntary usability studies with a book-approved corpus and pre/post questions:
- `time_to_first_verified_insight`: from opening ready book to displaying first verified content the user can navigate to.
- `task_completion_rate`: can a user locate and explain a requested concept with citations?
- `comprehension_delta`: difference in answered questions before and after interacting with the assistant compared to reading-only or standard single-agent baseline, where practical.
- `source_navigation_rate`: user can verify cited passage, not just click a decorative link.
- `false_confidence_report_rate`: how often a user believes an unsupported response was source-verified (target minimize).
- `time_to_task_completion` and satisfaction from a scripted usability study; do not promise that a person need never read the original book.

## 7. Evaluation record format

Save immutable run artifacts with `eval_run_id`, `git_sha`, `dataset_manifest_sha256`, `book_version_id`, `task_type`, `stage`, `model_id`, `embedding_model_id`, `prompt_version`, `retrieval_config`, `agent_graph_version`, `judge_version`, `region`, `input_case_id`, `expected_status`, `observed_status`, `numeric_metrics`, `critical_violation`, `token_counts`, `estimated_cost_usd`, `latency_ms`, `trace_id`, `error_category`. Private text is excluded from public reports.

Report stage scorecards and aggregate results by type; show a meaningful failure sample and comparison against matched-budget single-agent baseline. A nonzero critical integrity/security failure always blocks release, regardless of high average quality scores.

## 8. Implementation work packages

- **EV-001** Dataset and legal book fixture manifest; gold source IDs and human adjudication.
- **EV-002** Parser/normalization/citation integrity metrics and unit test suite.
- **EV-003** Knowledge Base retrieval evaluation harness + hard scope test.
- **EV-004** Typed specialist context, routing and verifier negative suite.
- **EV-005** Book Intelligence Brief full-inventory coverage and factual support evals.
- **EV-006** React Playwright event/cached-open/keyboard and book-switch tests.
- **EV-007** CI release gate and regression report pipeline.
- **EV-008** AWS staging AgentCore Evaluations integration, privacy-safe observability and cost scorecards.

Each feature PR must include traceable requirement IDs, unit tests, integration tests and its intended metric. No shipping based exclusively on an LLM evaluator claiming success.


## v1.4 evaluation extension: whole-book summaries

New stage `FULL_BOOK_SUMMARY`: fixed canonical source inventory, chapter completeness, material-topic coverage, semantic faithfulness, claim-level citation verification, cost/preflight handling. Hard gates: 100% inventory accounted and zero false `ready` on missing material, 100% displayed citations in authorized active version, 0 budget-denied jobs invoking model. Human targets: ≥95% material-topic coverage and ≥98% supported claims, as scored with denominators and frozen book-level holdout. Target dataset addition: ≥20 annotated full-book cases across ≥3 books. Full-book job retries, cancellation on deletion, cached GET without LLM, and low-cost/disabled AWS paths are also tested. New failure codes: `BOOK_LEDGER_GAP`, `FULL_SUMMARY_FALSE_COMPLETE`, `BUDGET_PREFLIGHT_DENIED`, `BOOK_SUMMARY_UNSUPPORTED_CLAIM`.
