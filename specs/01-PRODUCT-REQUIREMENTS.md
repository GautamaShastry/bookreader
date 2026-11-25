# 01 — Product Requirements Document (PRD)

**Product name:** BookScope AI (working name)  
**Version:** v1.1  
**Owner:** Project team  
**Status:** Approved baseline for engineering; replace assumptions with measured results.

## 1. The problem

A reader studying a technical book must repeatedly switch between the reader and an LLM, copy passages, and check whether the explanation is grounded in the source. General-purpose assistants may introduce outside knowledge and invented citations. Readers need an assistant that operates inside the reading experience and has an enforceable **selected-book-only evidence boundary**.

## 2. Target users and jobs to be done

**Primary:** Student or self-directed technical learner reading a textbook/manual (100–600 pages).

- When I read a difficult passage, explain it in simpler terms without introducing facts not in the book.
- When I ask about a topic, find where the author discusses it, give a coherent answer, and link back to the text.
- When I finish a chapter, summarize the chapter's key points without skipping most of the chapter.
- When the book does not cover a topic, say so explicitly rather than hallucinating.

**Secondary (later):** Corporate training, internal learning documents, and shared reading workspaces. Do not build enterprise roles or teams in v1.

## 3. Product principles

1. **Grounding > fluency.** A cautious refusal is better than a confident unsupported answer.
2. **Explain, don't replace reading.** References should bring the user back to the book.
3. **A book is the authority, not the LLM.** The model may paraphrase but may not import external facts.
4. **A reader can audit answers.** Each claim has a supporting citation and navigable source.
5. **Privacy by default.** Books are not public, shareable, or indexed outside the owner's authorized environment.
6. **Specialist contexts, one trust boundary.** Use a selectively invoked five-role multi-agent workflow; one book/version per conversation and one final deterministic publish gate. Do not run all agents for every user request.

## 4. V1 in scope

| ID | Priority | Requirement | Why |
|---|---|---|---|
| P-01 | P0 | Cognito sign-in and book library | Isolation and access control |
| P-02 | P0 | Import text PDFs / DRM-free EPUB up to 25 MB and 600 pages | Core content sources; bounded initial load |
| P-03 | P0 | Processing status and ingestion errors | User must know when document is ready |
| P-04 | P0 | PDF/EPUB viewer with table of contents | Integrated reading experience |
| P-05 | P0 | Ask with cited, book-scoped answer | Core value proposition |
| P-06 | P0 | Explain selected passage | Low-friction learning |
| P-07 | P0 | Correct refusal for out-of-book requests | Differentiator |
| P-08 | P0 | Click citation and jump to source | Auditability |
| P-09 | P0 | Chapter summary (coverage-aware) | Reduce study time safely |
| P-10 | P0 | Delete book, history and index data | Privacy/security requirement |
| P-11 | P0 | Grounding, retrieval, cross-tenant and cross-agent handoff evaluation | Prove reliability |
| P-15 | P0 | Route to focused specialist subgraphs with typed evidence handoffs | Reduce context noise without weakening evidence checks |
| P-12 | P1 | Persist per-book conversation history | Follow-up convenience |
| P-13 | P1 | Keyboard accessibility + responsive desktop-first layout | Usability |
| P-14 | P1 | Cost/error monitoring and rate limits | Sustainable cloud operation |

## 5. Out of scope for v1

- Importing an ebook automatically from any third-party commercial reading app; first release imports into BookScope.
- OCR of image-only scans, handwritten notes, image-heavy diagrams and table reasoning.
- EPUB with DRM and DRM removal.
- Cross-book synthesis (requires separately verified pipeline).
- Browser extension, flashcards, quizzes, personalized learning recommendations.
- Web search, external code execution, user document editing, agents taking actions.
- Billing, multi-tenant organization workspaces, public sharing.

## 6. High-priority user stories and acceptance

**US-01 — Import:** As an authenticated reader I upload a supported book, see indexing progress, and can open it when ready. On invalid/corrupt/DRM-protected files I see a clear actionable error.

**US-02 — Ask:** Given a ready book, when I ask a factually supported question, the assistant returns a book-only answer with valid source citations. A click navigates to the source.

**US-03 — Refuse:** When I ask an out-of-scope question, I receive `insufficient_evidence` with a direct explanation. No material answer to the external question is provided.

**US-04 — Selection:** When I highlight a passage and select Explain, the answer prioritizes the selected passage and local context. No invented technical examples.

**US-05 — Summarize:** When I request a chapter summary, the system processes the chapter in sequential blocks and cites all material sections, or explicitly reports an incomplete/failed summary.

**US-06 — Private:** I cannot retrieve another user's book by guessing IDs, using stale citations, or manipulating prompts. Deleting a book prevents subsequent access immediately.

## 7. Product success metrics (evaluation targets, not actual achievements)

- **Unsupported-answer leakage:** zero in release-blocking adversarial suite; track escaped errors in a growing holdout suite.
- **Claim support rate:** >= 98% supported factual claims on manually adjudicated answer samples.
- **Out-of-book refusal recall:** >= 95%; also track false refusals, target <= 10% on known answerable questions.
- **Citation navigation validity:** 100% of shown citations resolve to the same book/version and a navigable source.
- **Retrieval Recall@10:** >= 90% for answerable questions with gold supporting passages.
- **Chapter-summary coverage:** >= 95% of annotated material sections represented or explicitly marked missing.
- **Operational:** upload and answer error rate dashboards; performance targets to be established after baseline load tests rather than fabricated.

These are targets. A serious portfolio project should publish the dataset, test method, achieved numbers and failure examples.

## 8. UX requirements

Desktop-first two-panel reader: book on left, assistant on right; user can collapse assistant. Always display active book name and indexing status. Citation chips show chapter and source location; clicking jumps/highlights. Responses distinguish `ANSWERED`, `NOT FOUND IN THIS BOOK`, `PROCESSING`, `ERROR`. Avoid pretending unsupported answers were verified. A book upload success is not reported until parsing/index readiness is confirmed.

## 9. Operational constraints and assumptions

- Initial single-Region deployment; choose a Region after confirming Bedrock model, embeddings, KB/S3 Vectors and AgentCore (if used) availability.
- Use an explicit cloud spending budget and alert before deployment. Do not represent pricing as fixed.
- Content in uploaded books is untrusted. Copyright remains with the user/rightsholder.
- For PDF, cite the physical PDF page (1-based in UI). Printed page labels may differ.
- V1 handles English text; multilingual materials are later scope pending testing.

## 10. Definition of product release

Release v1 only when **all P0 requirements** have passing end-to-end acceptance tests, security isolation tests, citation integrity tests and documented evaluation scores. See `08-EVALUATION-AND-TESTING.md`.

## 11. Multi-agent product acceptance (v1.1 amendment)

- The supervisor routes `ASK`, `EXPLAIN_SELECTION` and `SUMMARIZE_CHAPTER` to distinct bounded paths, and never substitutes an outside search source.
- The retrieval specialist may decompose a question into at most three book-local subqueries; each candidate is backend-authorized and canonicalized before teaching.
- The teaching specialist receives only the question, short resolved referents, validated evidence, and rendering style. It cannot request other books or search the web.
- The summarization specialist traverses **every** chapter block, reducing verified local summaries with a section coverage ledger. Its context is intentionally limited per block.
- The grounding verifier independently evaluates each final factual claim against canonical sources and applies a fail-closed verdict; source IDs and ownership are deterministically checked by code.
- Multi-agent improvements are **hypotheses** until evaluated against a single-agent baseline on the same documents, questions, model budget, and metrics. Report accuracy, false refusals, p95 latency, tokens and cost, not just successes.

## v1.3 product requirement: first-meaningful-insight experience

P-12 (P0): Opening an eligible book inside BookScope auto-opens a dismissible assistant panel and shows a previously verified, source-linked **Book Intelligence Brief**, or an explicit preparing/partial state with canonical TOC. P-13 (P0): Evaluate each system stage independently with CI and staging gates, including book-open UX and orientation coverage; see `12-AGENT-FIRST-BOOK-OPEN.md` and `13-STAGEWISE-EVALUATION-STRATEGY.md`. Do not claim arbitrary third-party PDF interception, full-book exhaustive summarization, or guaranteed model correctness.


## v1.4 product amendment — P-16 (P0)

**Full-book hierarchical summary is included in initial release.** User requests summary explicitly. System enumerates all canonical chapters, synthesizes section->chapter->book with verified source citations and coverage ledger. Incomplete chapters/failed extraction must produce `partial`/`failed`, never a misleading complete result. V1 still does NOT provide cross-book synthesis. P-17 (P0): AWS $50/month development target with dev budget actions/limits and no paid deployment without approval. P-18 (P0): required full-book evaluation and negative test suite. See specs 14–16.
