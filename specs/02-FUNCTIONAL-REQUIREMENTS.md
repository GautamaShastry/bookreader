# 02 — Functional Specification and User Journeys

## 1. Primary screens

1. **Sign in** — Cognito-backed user authentication; error and recovery UI.
2. **Library** — private list of book title, file type, size, indexing state, imported date; upload and delete.
3. **Reader** — PDF.js or EPUB.js in left pane; chapter TOC, search within page/section, selection action; assistant in right pane.
4. **Assistant panel** — book title/version, conversation thread, `Ask`, `Explain Selection`, `Summarize Chapter`, citation links and explicit refusal states.
5. **Processing/error** — progress stage (`pending_upload`, `uploaded`, `parsing`, `indexing`, `ready`, `failed`, `deleting`), retry when safe.

## 2. User journey UJ-01: import a book

**Preconditions:** signed in; upload quota not exceeded.

1. Select a PDF/EPUB <= 25 MB. UI checks extension, MIME and byte size for early feedback.
2. Request a presigned S3 POST with fixed ownership and bounded content length.
3. Upload to private quarantine/raw bucket prefix. Client calls `complete-upload`.
4. Server checks S3 object size/checksum, file signature and quotas; transitions to `parsing` via queued event.
5. Worker extracts text, structure and exact source locators. Reject DRM, broken EPUB zip, suspicious decompression ratios, image-only PDF, empty/unreadable content or >600 pages.
6. Worker writes normalized source JSON and source-map artifacts to private S3, and one pre-split indexing document per chunk with metadata.
7. Bedrock KB ingestion sync/ingest starts. Worker polls state asynchronously. Document becomes `ready` only when indexing succeeded and canary retrieval returns expected chunk under the correct metadata filters.
8. The user may open the original book in the reader once accepted; AI actions remain disabled until `ready`.

**Failure:** show code and human-readable stage; do not expose raw parser stack trace. Retry must be idempotent for the same book version.

## 3. UJ-02: ask book question

1. User opens a `ready` book and asks a question <= 2,000 characters.
2. API verifies JWT + book ownership + `book_version_id` on conversation, and enforces per-user rate limit.
3. Supervisor returns a schema-validated `ASK` decision with bounded subqueries/section hints (not arbitrary tool choices). The backend locks authorized book scope before invoking specialists.
4. Retrieval uses `owner_id AND book_id AND book_version_id` metadata filters; rechecks every returned item. If retrieval or access control fails, **do not** generate answer.
5. Evidence sufficiency evaluator determines whether relevant passages support answering.
6. If enough evidence: model produces structured factual claims tied to chunk IDs; verifier re-reads canonical text, verifies citation metadata and evaluates semantic support.
7. If all substantive claims supported: deliver answer with source links and save to thread; otherwise retry once with only validated evidence, then refuse.

**UI:** citations can be clicked; refuse with precise language, e.g. “I couldn't find enough support for that in this book.” The UI must not display draft tokens that have not passed verification.

## 4. UJ-03: explain selection

1. User highlights text in the viewer. Frontend sends selected text and source locator.
2. Backend resolves selection against canonical normalized content (do not trust client-provided selection alone); rejects if mismatch/outside chosen book.
3. Retrieve adjacent paragraphs and relevant same-book context, capped by token budget.
4. Explain with plain language faithful to the selected text; do not add examples, formulas or claims absent from supplied passages.
5. Cite primary passage and context if used. If selection is image-only/unreadable, return a clear unsupported-content message.

## 5. UJ-04: summarize chapter

1. User selects `Summarize current chapter`; backend identifies canonical `chapter_id` from TOC.
2. Enqueue a chapter-summary job, avoiding expensive synchronous requests.
3. Load **all** normalized text spans assigned to chapter in reading order; break into bounded blocks.
4. For each block, generate an extractive/faithful summary with source span identifiers. Verify each map summary.
5. Reduce verified block summaries into a concise chapter overview. Track sections covered; include citation groups.
6. Run a final support and coverage check. If any material block failed, do not mark a complete summary; return `partial` with explicitly identified uncovered sections, or `failed`.

**Deliberately not:** use a single top-k vector search to summarize an entire chapter.

## 6. UJ-05: follow-up question

Chat history is used to recover referents (“What does that mean?”), but **never** as source evidence. Rewritten stand-alone query goes through normal book-only retrieval and verification. If referent is ambiguous, ask user to specify the passage/chapter.

## 7. UJ-06: book deletion

1. Owner selects Delete and confirms.
2. Backend immediately marks book and versions `deleting`, prevents new presigned URLs and rejects query/read operations.
3. Asynchronous purge deletes ingestion documents, index data, normalized pages, raw object and derived summaries; then conversations and messages. Track purge status and failures.
4. Mark `deleted` only after required storage removals are confirmed. Logs redact book text; backups obey documented retention policy.

## 8. Functional requirements, traceability and edge cases

| ID | Behavior | Acceptance reference |
|---|---|---|
| FR-001 | Authenticated users see only their books | SEC-01, E2E-01 |
| FR-002 | Upload validated supported formats | ING-01, E2E-02 |
| FR-003 | Asynchronous processing with visible states | E2E-03 |
| FR-004 | PDF navigation is based on actual PDF page index | CIT-01 |
| FR-005 | EPUB navigation uses spine/anchor/quote fallback | CIT-02 |
| FR-006 | Question answering includes validated citations | GND-01 |
| FR-007 | Unsupported requests have no substantive answer | GND-02 |
| FR-008 | Selected-text explanation validates source selection | GND-03 |
| FR-009 | Chapter summary traverses whole chapter | SUM-01 |
| FR-010 | Conversations cannot switch book/version | SEC-02 |
| FR-011 | Deletion revokes access synchronously | SEC-03 |
| FR-012 | Client never receives unverified draft text | GND-04 |
| FR-013 | External facts/tools never enter response workflow | GND-05 |
| FR-014 | Corrupt, encrypted, image-only books fail cleanly | ING-02 |
| FR-015 | API rate and upload quotas enforced | OPS-01 |

## 9. Not-found and error UX copy

- Unsupported question: “I couldn't find enough information to answer that using this book alone.”
- Book not ready: “This book is still being prepared. Questions will be available when indexing finishes.”
- Citation resolution failed: “Source location is temporarily unavailable. This answer has been withheld.”
- Unsupported EPUB/DRM: “This ebook cannot be imported. BookScope supports DRM-free EPUB files.”
- Image-only PDF: “This PDF appears to be scanned. Text OCR is not supported in this version.”

## 10. Accessibility

Keyboard navigation for TOC, chat and citations; visible focus states; accessible status/live regions; selectable text, sufficient contrast, and no color-only meaning. Do not require pointer-only highlight to use `Ask`.

## 10. v1.1 agent workflow acceptance

| ID | Workflow | Acceptance |
|---|---|---|
| FR-015 | Supervisor routing | `ASK`, `EXPLAIN_SELECTION`, `SUMMARIZE_CHAPTER` route only to approved subgraphs; invalid intents refuse safely |
| FR-016 | Retrieval context isolation | Retriever sees only bounded task, TOC hints and same-book retrieval results; no unrelated thread or cross-book data |
| FR-017 | Teaching context isolation | Teaching agent accepts only validated `EvidenceBundle` references and scoped canonical text; fake sources are rejected |
| FR-018 | Summary parallelism | Per-section mapping is bounded (default 3 concurrent tasks), preserves reading order in reduction and proves coverage |
| FR-019 | Independent verification | Verifier consumes final claims and canonical passages, not generator reasoning; any unsupported displayed claim fails |
| FR-020 | Failure handling | One targeted retrieve retry and one draft-repair maximum; no infinite recursion or unverified streaming |
| FR-021 | Telemetry | Trace route, agent step durations, tokens, refusals and verification verdicts without logging book text |

**UI behavior:** Show simple stage labels (`Finding passages`, `Explaining`, `Checking references`, `Summarizing sections`) driven by backend state—not raw agent thoughts. Only deliver final verified content; summary jobs may report progress independently of final content.

## v1.3 requirement IDs

FR-022 auto-open assistant when BookScope reader emits `BOOK_OPENED` (not a fresh LLM invocation); FR-023 cached, source-verified Book Intelligence Brief; FR-024 processing/partial/failure state; FR-025 per-stage evaluation counters and regression gates; FR-026 navigation and book-context reset on book switch. See detailed contracts in `12-AGENT-FIRST-BOOK-OPEN.md` and `13-STAGEWISE-EVALUATION-STRATEGY.md`.

FR-027 (P1): Guided book understanding follows user selection from the brief, with book-only lessons and evaluated comprehension checks; it is not an unsolicited on-open model run.


## v1.4 functional requirements

FR-028 — User-initiated `SUMMARIZE_BOOK` async job; POST `/v1/books/{book_id}/full-summary`, cached GET; never auto-run on `BOOK_OPENED`. FR-029 — Enumerate all immutable book chapters and sections in order; section->chapter->book hierarchical summarization with canonical source IDs and verified coverage; `ready` only when complete. FR-030 — Cost preflight, bounded concurrency (default 2), idempotent requests and safe partial/failed statuses. FR-031 — Stage-specific evaluations and source navigation for book-level claims. FR-032 — `$50/month` target enforced via app-level usage limits, alerts and explicit paid deployment approval. See `14`, `15`, `16`.
