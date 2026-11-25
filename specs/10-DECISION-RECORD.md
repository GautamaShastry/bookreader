# 10 — Architecture Decision Records, Risks and Deferred Questions

## ADR-001 — Build an integrated web reader first

**Decision:** Import PDF/EPUB into BookScope; embed PDF.js and EPUB.js.

**Reason:** We control source identification, selection, citation navigation and content isolation. Arbitrary third-party readers impose browser permissions, extension policies and DRM constraints. **Deferred:** Chrome extension / opening files through OS default app.

## ADR-002 — Book-scoped one-book-per-conversation trust model

**Decision:** Each conversation is pinned to an immutable `book_version_id`. Changing books starts a different conversation.

**Reason:** Simple, testable isolation. Multi-book comparison is a distinct product with its own evidence rules.

## ADR-003 — Canonical extraction and citation map before indexing

**Decision:** App-owned canonical text and locators in S3, versioned and hashed; model/KB are not citation authorities.

**Reason:** Explicit PDF pages and EPUB section/quote resolution, stable cited sources, integrity checking. **Tradeoff:** Additional ingestion engineering vs out-of-box PDF chatbot.

## ADR-004 — Bedrock KB with S3 Vectors baseline

**Decision:** Start with semantic Bedrock KB `Retrieve` and mandatory metadata filters; use pre-chunked `.md` documents with metadata.

**Reason:** AWS-native, managed embeddings/retrieval with low idle infrastructure overhead. **Tradeoff:** No hybrid search at KB+S3 Vectors integration; benchmark keyword-heavy technical questions and consider suitable OpenSearch backend or a scoped lexical retriever when warranted.

## ADR-005 — Bounded specialist multi-agent LangGraph (supersedes v1.0)

**Decision:** One bounded LangGraph consisting of five logical specialist roles: Supervisor, Retrieval, Teaching, Summarization, Grounding Verifier. Invoke only roles required by the request. All external data reads remain deterministic book-scoped tools.

**Reason:** Separate context windows prevent a task-specific model from receiving unrelated full-book or chat material, and allow independent verification. **Tradeoff:** More calls, potential failure propagation, cost and latency. A single-agent baseline remains necessary to establish whether quality actually improves; see `11-MULTI-AGENT-WORKFLOW.md`.

## ADR-006 — AgentCore Runtime for orchestration, Lambda for public API (supersedes v1.0)

**Decision:** Deploy the multi-agent LangGraph inside **one AgentCore Runtime**. Use thin FastAPI Lambda for authenticated public API, quotas and serialization, not for orchestration.

**Reason:** AWS provides purpose-built Runtime hosting for custom LangGraph multi-agent flows; decouples long-running orchestration from API request handling. **Tradeoff:** Additional integration/IAM and invoke cost; one Runtime for all logical roles avoids unnecessary distributed coordination.

## ADR-007 — Do not stream unverified draft answers

**Decision:** Only show content after complete claim verification.

**Reason:** Streaming can leak unsupported facts before verifier rejects them. **Tradeoff:** Higher perceived latency. Show progress indicators instead; later develop a safe sentence-level verified streaming protocol if necessary.

## ADR-008 — No OCR or figure reasoning in v1

**Decision:** Accept only PDFs with extractable text and DRM-free EPUB.

**Reason:** Multimodal correctness is a separate evidence and provenance challenge. Clear unsupported-content responses rather than made-up information about diagrams.

## ADR-009 — Chapter summary uses sequential map-reduce

**Decision:** Load the entire selected chapter in reading order; verify block summaries; reduce with explicit coverage accounting.

**Reason:** RAG top-k is not a completeness algorithm. **Tradeoff:** More tokens/latency and background job state.

## ADR-010 — Refusal on verification uncertainty

**Decision:** Fail closed when citations, source maps or semantic entailment cannot be validated.

**Reason:** Matches product promise. **Risk:** False refusals; evaluate and improve retrieval/sufficiency before loosening the response gate.

## Key risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Source map/page mismatch | False citations | pre-chunk page boundaries, source-hash validation, reader E2E |
| Book text prompt injection | External or fabricated claims | bounded tools, untrusted context, final verifier |
| Semantic retrieval misses exact terms | False refusal | benchmark, bounded expansion, evaluate lexical fallback |
| Large ingestion exceeds Lambda time | Failed imports | explicit size/page cap; move worker to Fargate if observed |
| EPUB location cannot highlight precisely | Weak citation UX | spine/anchor/quote fallback, refuse claims of exact match |
| KB ingestion sync eventually consistent | Premature ready status | canary retrieval and async state machine |
| Excessive AWS model costs | Unaffordable demo | quotas, budget alerts, measured tokens, caching |
| Uploaded copyrighted content | Distribution/legal risk | private uploads; open content for demo; no DRM bypass |
| LLM verifier itself mistaken | Unsupported answer escapes | adversarial testing, human audit, claim-level fail closed |

## Open decisions requiring evidence, not guesses

1. **Cloud Region/model IDs:** choose after checking same-Region availability for Bedrock KB, embeddings, generation and S3 Vectors.
2. **Exact chunk sizes/overlap:** set defaults 250–600 tokens and ~50 overlap, then tune on frozen retrieval dataset.
3. **Parser/EPUB citation fidelity:** test a mixed-layout book; where anchors cannot resolve, improve before release.
4. **Cloud cost budget:** set user's real monthly spending cap and per-day traffic allowance at deploy time.
5. **Production latency objective:** establish baseline on actual AWS deployment, then agree a meaningful target.
6. **Legal demo corpus:** select open or public-domain books with redistribution rights before public portfolio.

These do not block initial coding; the spec provides working defaults and measurable gates.

## ADR-011 — Typed minimal handoffs, not shared chat history

**Decision:** Each role gets its own narrowly shaped context. Pass IDs, hashed canonical source locators, task parameters and structured verdicts; do not forward entire prompt histories, speculative rationales or unverified intermediate drafts between specialists.

**Reason:** Directly addresses context noise. **Tradeoff:** More engineering work to validate schemas and load canonical texts under authorization. Deterministic source adapters are authoritative for identity, source integrity and publication.

## ADR-012 — AgentCore is hosting, LangGraph is orchestration

**Decision:** Run one custom LangGraph multi-agent application on AgentCore Runtime, not Bedrock Agents Classic or five managed independent agents. Evaluate deploying separate runtimes only after real scaling/latency evidence.

**Reason:** Keeps workflow debuggable and testable locally, while retaining AWS deployment value and avoiding needless agent-to-agent network hops.

## ADR-013 — Multi-agent quality must be established empirically

**Decision:** Preserve the v1.0 single-agent graph as a benchmark baseline. Do not claim better fidelity because there are more agents. Compare quality, safety, latency and cost on frozen gold queries with calibrated human adjudication.

**Reason:** Multi-agent creates new failure modes (handoff truncation, agent disagreement, correlated LLM errors); specialization is a design hypothesis until tested.

## ADR-007 (v1.3): agent-first book entry, not on-open inference

**Accepted design:** Opening a ready book inside BookScope auto-displays the assistant panel and already-verified, source-linked orientation brief; generation is an idempotent asynchronous effect of reaching `READY`, not a per-open model call. `partial` and `outline_only` states are explicit. As of v1.4, full-book hierarchical summaries are first-release scope, but are generated only on an explicit user request; the cached brief remains a separate orientation.

## ADR-008 (v1.3): evaluation is a release contract

**Accepted design:** deterministic hard gates at every build, human-audited gold sets and book-level holdouts for model evaluations, stage-specific AWS staging canaries, and sampled privacy-safe production quality monitoring. No LLM-as-judge can override ownership, hash or citation fail-closed policy.


## Accepted v1.4 ADRs (2026-11-24)

**ADR-014:** Web reader first. Opening a book inside BookScope auto-opens assistant and cached verified brief; no external browser extension in v1.

**ADR-015:** **Full-book hierarchical summaries included in first release**, as a separate *user-triggered asynchronous* chapter-inventory traversal and staged grounding pipeline. Not the brief-on-open; not top-k retrieval.

**ADR-016:** **AWS development budget target $50/month**. Cost estimate, notifications, manual approval and application-level admission controls; a budget notification is not a billing cap. Local-first development, avoid always-on expensive components by default.

Frozen implementation contract: `15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md`. Full-book details `14-FULL-BOOK-HIERARCHICAL-SUMMARY.md`. First tickets `16-FIRST-CODING-AGENT-TICKETS.md`.
