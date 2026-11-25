# 04 — Document Ingestion, Source Mapping and Retrieval Specification

## 1. Accepted inputs and explicit constraints

- **PDF:** Text-selectable, unencrypted PDFs; max 25 MiB and 600 physical pages in v1. Parse with PyMuPDF. Preserve 1-based physical page number and extraction diagnostics. Printed page numbers are not authoritative.
- **EPUB:** DRM-free EPUB 2/3, max 25 MiB compressed. Parse ZIP safely, OPF manifest/spine/TOC, and XHTML with defused, bounded XML/HTML parsing; preserve `spine_href`, `anchor_id` where present, a normalized text quote, and a deterministic text offset. Ignore scripts and active content.
- Reject corrupted/encrypted/improper file signatures, decompression bombs, excessive expansion, zero meaningful text, unreadable image-only PDFs. No DRM circumvention. Give clear error codes, not fabricated summaries.
- Other ebooks (`mobi`, `azw`, `kfx`) are not supported in v1. The app **imports** files into BookScope; it does not automatically intercept third-party reading apps.

## 2. Extraction output contract

For each page (PDF) or spine document/section (EPUB):

```
book_id, book_version_id, owner_id
chapter_id, chapter_title, section_id, heading_path
reading_order, normalized_text, text_start_offset, text_end_offset
locator: { kind: 'pdf', page_index: 0, page_label: '1' }
      | { kind: 'epub', spine_href: '...', anchor_id: '...',
          text_quote: '...', normalized_offset: 117 }
```

- Normalize whitespace/Unicode for retrieval but keep a canonical map to original quote offsets for navigation.
- Extract table of contents from PDF bookmarks or EPUB navigation. If unavailable in a PDF, derive a conservative fallback from headings, with an `inferred=true` flag; do not pretend inferred structure came from the author.
- Record pages with poor extraction as **unsupported spans**; queries whose answer depends on these pages must abstain.
- For EPUB location, use `spine_href + anchor_id` when stable; otherwise resolve using a bounded exact text quote inside the rendered spine document. If ambiguous/unresolvable, citation cannot be displayed as verified.

## 3. Chunking policy

- Goal: 250–600 model-token chunks with paragraph-first boundaries, ~50 token same-source overlap when helpful, subject to index limits. Benchmark on actual source material; values are defaults, not universal optimum.
- **Never cross a physical PDF page** for an indexed chunk in v1. This ensures a citation to a physical page is accurate.
- **Never cross an EPUB spine document or logical section**. Chunks have stable deterministic `chunk_id = SHA256(book_version_id | section_id | normalized_span_start | normalized_span_end | content_hash)[:32]`.
- Preserve heading path as prefix in the retrievable text, but treat injected headings as metadata rather than author text.
- For long pages, multiple ordered chunks. For short pages, index the page as one chunk rather than merging across pages.
- Canonical chunk JSON includes `span_text`, source locator and hash, source content offsets, chapter, section and reading order (see `schemas/source-chunk.schema.json`).

## 4. Knowledge Base staging strategy

1. Write each canonical chunk to immutable private S3 as `<chunk_id>.md` with the relevant passage and heading context.
2. Write `<chunk_id>.md.metadata.json` with metadata attributes: `owner_id`, `book_id`, `book_version_id`, `chunk_id`, `chapter_id`, `source_kind`, `page_index` (when applicable). Keep it under S3 Vectors Knowledge Base metadata limits (1 KiB custom metadata and <=35 keys/vector).
3. Example KB staging sidecar for one chunk (`chunk.md.metadata.json`; full example in `examples/bedrock-chunk.metadata.json`):

```json
{
  "metadataAttributes": {
    "owner_id": {"value": {"type": "STRING", "stringValue": "cognito-user-sub"}},
    "book_id": {"value": {"type": "STRING", "stringValue": "c4bfc070-559c-4257-bff7-cae729d0266d"}},
    "book_version_id": {"value": {"type": "STRING", "stringValue": "638b2d68-6975-4e1b-ab3d-2ce5e1f2ba90"}},
    "chunk_id": {"value": {"type": "STRING", "stringValue": "examplechunk01"}},
    "chapter_id": {"value": {"type": "STRING", "stringValue": "chapter-04"}}
  }
}
```

The exact sidecar schema and per-vector metadata limits must be enforced in integration tests. See [AWS S3 source metadata documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html).

4. Configure Bedrock Knowledge Base using S3 data source and S3 Vectors vector store. Set **no additional chunking** because BookScope already split the material into canonical citation units. Validate indexing behavior on a real sample before relying on the mapping.
5. Trigger ingestion and poll until synchronized; use returned retrieval `chunk_id` metadata to validate canary results against stored canonical content.
6. If a chunk's metadata cannot be round-tripped exactly, mark ingestion failed rather than serving unverifiable citations.

**Important:** Bedrock Knowledge Base with S3 Vectors is **semantic-only**. The underlying S3 Vectors product's evolving search capabilities should not be mistaken for features supported by the Bedrock KB integration. Optional keyword/hybrid retrieval is a separate measured upgrade, e.g. switching to a suitable OpenSearch-backed KB or adding a simple book-scoped lexical retriever.

## 5. Ask retrieval contract

Input: `authenticated_owner_id`, `conversation.book_id`, `conversation.book_version_id`, `question`, optional validated selection/selected chapter.

Algorithm:

1. Resolve pronouns using recent conversation history (history is context **not evidence**).
2. Classify intent with strict supported modes: `ask`, `explain_selection`, `summarize_chapter`; unknown intent is treated as `ask` or prompts for clarification.
3. Use Bedrock KB `Retrieve` **with explicit equality filters** for owner + book + version, starting `top_k = 10`, and optional chapter filter where appropriate.
4. `Retrieve` filter configuration must be equivalent to:

```python
retrievalConfiguration = {
  "vectorSearchConfiguration": {
    "numberOfResults": 10,
    "filter": {"andAll": [
      {"equals": {"key": "owner_id", "value": authenticated_owner_id}},
      {"equals": {"key": "book_id", "value": active_book_id}},
      {"equals": {"key": "book_version_id", "value": active_book_version_id}}
    ]}
  }
}
```

5. Reject response if any returned hit has missing/mismatched metadata, invalid chunk ID, or unreadable canonical source text.
6. Fetch canonical passage by `chunk_id` from the private source map, not from model-supplied quotes.
7. Score sufficiency with task-specific criteria (key entities, coverage of necessary facts, explicit vs inferred support, missing context). Retrieval scores alone do not establish sufficiency.
8. Optionally expand to adjacent chunks / `top_k=20` **only within the same book/version** if the evidence is likely incomplete. Bounded two-pass retrieval; no endless agent loops.
9. Pass canonical evidence excerpts (not the user's entire uploaded book) into answer-generation and verifier.

## 6. Selection explanation

The client sends a locator and short selection (<= 3,000 characters); backend verifies that the selected text is present at the supplied canonical source location. Retrieve same-section adjacent content and, if necessary, other same-book references. A forged selection must not become evidence. Do not add a code example that the source did not support.

## 7. Chapter summarization (not vector top-k)

- Read the complete chapter from normalized content in reading order.
- Group into bounded sequential blocks; each maps to a canonical list of source IDs.
- Summarize and verify each block with grounded source IDs.
- Reduce verified block summaries, preserving concept ordering and primary caveats.
- Check that material chapter sections are represented, and citations correctly resolve. If missing material, mark partial/failed rather than claiming a complete summary.
- Cache by `book_version_id + chapter_id + summary_spec_version`; invalidate on new book version or summarizer version.

## 8. Citation semantics and navigation

Each citation is a server-assigned ID bound to `book_id`, `book_version_id`, `chunk_id`, an optional exact text quote, chapter/section and a validated locator.

- PDF: navigate to `page_index` zero-based in PDF.js, display `page_index + 1` as PDF page; highlight matching quote when possible.
- EPUB: navigate to canonical spine+anchor, or exact quote in that spine document; if quote ambiguous, show section location with a warning **and do not claim exact highlight**. V1 citation must resolve to at least the correct section or the answer is withheld.
- Always re-authorize on citation source lookup (e.g., `GET /books/{id}/sources/{chunk_id}`); client cannot get arbitrary S3 keys.

## 9. Ingestion quality gates

- `ING-01`: Every indexed chunk round-trips `book_id`, `book_version_id`, `owner_id`, `chunk_id` and source locator without alteration.
- `ING-02`: Corrupt, encrypted, DRM EPUB, image-only PDFs, decompression bombs safely fail; no partial ready state.
- `ING-03`: PDF source chunks retain exact physical pages; no cross-page indexes.
- `ING-04`: EPUB TOC and source links resolve in viewer on fixture book.
- `ING-05`: Source text hash survives normalization/indexing where required.
- `ING-06`: SQS retries produce no duplicate logical versions/chunks; failed jobs can be safely retried.

## 10. AWS reference links

- Supported KB source formats: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-ds.html
- KB + S3 Vectors limitations: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html
- Retrieve with metadata filters: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html
- KB chunking strategies: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking-parsing.html

## 10. v1.1 retrieval-specialist boundary

The retrieval specialist may generate at most three scoped subqueries and select chapter hints. It **cannot** modify the authorized book identity or authoritatively decide which sources are safe. Retrieval tools enforce metadata equality filters, then rehydrate and hash-check passages from canonical source maps. A deterministic sufficiency gate decides whether an EvidenceBundle may reach the Teaching Agent. Each handoff contains IDs/locators/hashes, not copies of the entire conversation or indexed corpus. The Teaching Agent receives the validated text only through an authorized resolver. For chapter summaries, do **not** call nearest-neighbor top-k; enumerate every canonical chapter block in order.

S3 Vectors with Bedrock Knowledge Bases is semantic-only at the KB integration layer (not hybrid). Evaluate an additional book-scoped keyword retriever only as a separately measured option.

## v1.3 orientation indexing requirement

Every chapter must have canonical section IDs and locators before an overview can claim book-level scope. Generate the book brief only after `READY` with a verified chapter inventory. Reopening the book never initiates a redundant generation call. Treat the TOC as an outline, not evidence of chapter content; source-backed chapter concept claims require canonical passages. Track unreadable sections and `partial` explicitly.


## v1.4 full-book use of canonical manifest

The parser/chunker MUST produce an auditable entire-book ordered chapter/section inventory suitable for deterministic traversal. This ledger is authoritative for full-book summaries. `SUMMARIZE_BOOK` uses all canonical blocks rather than top-k; no silent skips. See `14-FULL-BOOK-HIERARCHICAL-SUMMARY.md`. Summary cache invalidated by immutable book version, manifest hash, summary implementation/config version.
