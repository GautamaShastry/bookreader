# BookScope AI — Specification Index

**Status:** Frozen BookScope design baseline v1.4 (2026-11-24)  
**Product:** Book-grounded reading and learning assistant  
**Primary outcome:** A user can import a text-based book, ask a question, and receive an answer supported only by the selected book, with working source navigation—or a correct refusal.

## Non-negotiable product contract

> No substantive factual claim may be shown as the book's answer without a verified supporting passage from the active, authorized, immutable book version.

This is an **engineering policy and testable target**, not a claim that language models can be proven to forget all pretrained knowledge. The response gate fails closed when evidence or verification is insufficient.

## Read the specs in this order

| Document | Purpose | Primary implementer |
|---|---|---|
| `AGENTS.md` | Implementation rules for coding agents / IDE sessions | Implementation |
| `01-PRODUCT-REQUIREMENTS.md` | Users, scope, problem, priorities, success measures | Product / all |
| `02-FUNCTIONAL-REQUIREMENTS.md` | User journeys, behaviors, acceptance conditions | Frontend / QA |
| `03-SYSTEM-ARCHITECTURE.md` | Service diagram, trust boundaries, sequence flows, storage | Backend / cloud |
| `04-INGESTION-AND-RETRIEVAL.md` | Parsing, source maps, metadata, retrieval, summarization | RAG / ingestion |
| `05-GROUNDING-AND-AGENT.md` | Selective multi-agent workflows, source-only enforcement, verifier | AI engineering |
| `11-MULTI-AGENT-WORKFLOW.md` | Per-agent context, handoff contracts, bounded retries, failure tests | AI engineering |
| `06-API-OPENAPI.yaml` | HTTP interface contract, models, errors | Backend / frontend |
| `07-SECURITY-AND-DEPLOYMENT.md` | IAM, auth, secrets, deletion, IaC, operations | Cloud / security |
| `08-EVALUATION-AND-TESTING.md` | Gold dataset, metrics, negative tests, exit gates | QA / AI engineering |
| `09-DELIVERY-PLAN.md` | Ordered implementation, dependency graph, definition of done | Implementation |
| `10-DECISION-RECORD.md` | Firm decisions, alternatives, explicitly deferred features | All |
| `schemas/answer.schema.json` | Machine-readable response contract | Backend / tests |
| `schemas/source-chunk.schema.json` | Canonical chunk metadata | Ingestion / tests |
| `schemas/agent-contract.schema.json` | Typed internal agent handoff contracts | AI engineering / tests |
| `examples/agent-evidence-handoff.json` | Synthetic validated handoff reference | AI engineering |
| `examples/multi-agent-evaluation-seeds.jsonl` | Isolation, routing and ablation seeds | Evaluation |
| `examples/evaluation-seeds.jsonl` | Initial evaluation scenarios, NOT scored results | QA |
| `examples/bedrock-chunk.metadata.json` | AWS KB S3 metadata sidecar shape (illustrative IDs) | Ingestion |
| `examples/answer-example.json` | Fictional example of a verified response shape | API / UI |

## V1 scope

- Authenticated single-user-owned uploads; text-based PDF and **DRM-free** EPUB only.
- Book reader with navigation, selection support, and book-scoped chat.
- Ask book, explain selected passage, and summarize **a selected chapter**.
- Citation links to the exact PDF page or resolved EPUB location.
- Grounding validator and abstention for unsupported queries.
- Upload/job status, chat history, book deletion, AWS deployment, logging, tests.

### Intentionally excluded from v1

Scanned/image-only books, charts/figures as primary evidence, external web research, simultaneous multi-book comparisons, Chrome extension, audio/video, autonomous actions, DRM bypass, payment, and collaboration. Later milestones may add these only after evaluation.

## Engineering invariants

1. Caller identity is authenticated. Book ownership is verified *before* accessing an object, retrieving vectors, or invoking a model.
2. `book_version_id` is pinned to every conversation. User cannot change it by editing a prompt.
3. Retrieval has mandatory equality filters for `owner_id`, `book_id`, and `book_version_id`; every retrieved hit is rechecked in application code.
4. Chat history can resolve pronouns but **never** serve as an evidence source.
5. Model outputs are non-authoritative until the citation/claim verifier approves them.
6. All citations resolve to source text plus navigation location in the pinned book version.
7. Deleting a book immediately revokes access; physical removal of raw content, chunks, vectors, derived data, and chat history completes asynchronously and is tracked.
8. A rejection is required when a question is outside the book, retrieval fails, evidence is weak, or verification is inconclusive.
9. The application does not pass book content as trusted system or developer instructions.
10. Uploaded book content and source quotes are private and are not publicly exposed by default.

## AWS compatibility notes (verified 2026-11-23)

- Bedrock Knowledge Bases S3 data source supports PDF/Markdown/TXT/HTML but **not EPUB** as a native listed type: normalize EPUB first.
- Bedrock Knowledge Bases + S3 Vectors is supported and **semantic-only at the Knowledge Base integration layer**. Do not configure `HYBRID` against that pairing.
- `Retrieve` supports metadata filtering. BookScope creates metadata for each indexed source chunk, and filters on each retrieval.
- AgentCore Runtime is the **chosen multi-agent orchestration host** for v1.1; a thin FastAPI-on-Lambda gateway remains responsible for public APIs and authorization. Runtime hosts one bounded LangGraph with specialist subgraphs, not five independent deployments.

AWS references:
- https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-ds.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-vs-runtime.html

## Multi-agent execution policy

- Supervisor, Retrieval, Teaching, Summarization, and Grounding Verifier are **five logical roles**, not five always-active agents.
- QA: Supervisor -> Retrieval -> Teaching -> Grounding Verifier. Selection explanation: Supervisor -> canonical selection resolver -> Teaching -> Grounding Verifier. Chapter summary: Supervisor -> complete chapter traversal -> Summarization workers/reducer -> Grounding Verifier.
- Every specialist receives a minimal typed task. Full conversation histories and speculative agent reasoning are **not** handoff data.
- Scope checks, source integrity and final publish gate are deterministic backend controls outside the agents; model-based verification is an additional defense.

## Working agreements

- Scope changes require updates to PRD, applicable acceptance tests, and decision record.
- No resume performance metrics are claimed until a recorded test run establishes them.
- Initial sample books must be public-domain, openly licensed, or explicitly authorized for testing; do not redistribute third-party copyrighted books or bypass DRM.

## Version 1.1 change summary

Supersedes v1.0 ADR-005 and ADR-006: BookScope uses selective specialist subgraphs in **one** LangGraph graph on AgentCore Runtime, with typed minimal-context handoffs and a separate deterministic publish gate. The public API preserves existing routes and request shapes; it adds `partial` to the answer-status enum to explicitly flag supported-but-incomplete mixed responses (clients must render this state). New specs: `11-MULTI-AGENT-WORKFLOW.md`, `schemas/agent-contract.schema.json`, and multi-agent test examples. Implementation/deployment and performance improvement remain **unverified**.

## v1.3 authoritative change (2026-11-24)

This release adds `12-AGENT-FIRST-BOOK-OPEN.md` and `13-STAGEWISE-EVALUATION-STRATEGY.md` as normative specifications. The previous v1.1 text describing an empty chat pane or purely user-initiated summaries is superseded by FR-022 through FR-024. Book opening inside BookScope **auto-opens the assistant and retrieves a cached verified Book Intelligence Brief**, never a fresh unverified model answer. v1.3 retains v1.1's source-only constraints, scoped 5-role selective LangGraph, immutable citations and no unverified drafts. The brief is a **verified orientation, not a complete full-book summary**.

`06-API-OPENAPI.yaml` now includes the private GET `/v1/books/{book_id}/brief`. `schemas/book-brief.schema.json` is the equivalent contract for offline validation. `examples/book-brief-example.json` is synthetic and NOT a real book; orientation/evaluation seeds are illustrative, not scored evidence. `PRE-CODING-GATE-v1.2.md` is retained to document unresolved real-world testing.


## Version 1.4 approved scope freeze (2026-11-24)

ADR-014 web reader first, ADR-015 **hierarchical full-book summaries included in initial release**, ADR-016 **$50/month AWS development target**. Read `15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md` (normative), `14-FULL-BOOK-HIERARCHICAL-SUMMARY.md`, and `16-FIRST-CODING-AGENT-TICKETS.md`. The v1.3 "brief is not full-book summary" distinction still holds; the *separate* full-book summary workflow is triggered by the user, not by `BOOK_OPENED`. New API POST/GET `/v1/books/{book_id}/full-summary`, full-summary JSON Schema and stage-specific evaluations are included. Prior exclusions are superseded.
