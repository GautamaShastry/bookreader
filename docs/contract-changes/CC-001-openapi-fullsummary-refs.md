# CC-001 — Fix unresolvable `$ref`s in `FullBookSummaryResponse` (OpenAPI)

- **Date:** 2026-11-25
- **Status:** Approved by project owner (2026-11-25) before BS-001 implementation.
- **Files:** `specs/06-API-OPENAPI.yaml`, `specs/MANIFEST.sha256`
- **Behavior change:** none. Schema shape, fields, enums and requirements are unchanged.

## Problem

`components/schemas/FullBookSummaryResponse` in `specs/06-API-OPENAPI.yaml` contained five references of the form
`$ref: '#/$defs/<Name>'`. The schema declares no `$id`, so under OpenAPI 3.1 / JSON Schema 2020-12 these resolve
against the OpenAPI document root, which has no `$defs`. They were unresolvable:

| Location | Old ref |
|---|---|
| `properties/overview_claims/items` | `#/$defs/Claim` |
| `properties/chapter_summaries/items` | `#/$defs/ChapterSummary` |
| `properties/coverage` | `#/$defs/Coverage` |
| `properties/citations/items` | `#/$defs/Citation` |
| `$defs/ChapterSummary/properties/claims/items` | `#/$defs/Claim` |

The refs were correct in the standalone `specs/schemas/book-full-summary.schema.json`; they were not rewritten when the
schema was embedded in OpenAPI. The sibling `BookBriefResponse` already uses the correct form
(`#/components/schemas/BookBriefResponse/$defs/...`). The packaged `validate_v14_contracts.py` only checked refs
under `paths`, so it did not detect this. BS-001's gate "all local refs resolve" requires the fix.

## Change

Each ref above rewritten to `#/components/schemas/FullBookSummaryResponse/$defs/<Name>`.

`MANIFEST.sha256` entry for `06-API-OPENAPI.yaml`:

- old: `434132f9d7f51e7888a99e20b097eaf078e581c44f11a150160307af2b868e8c`
- new: `b957fdf8c6825a01b8291f9256f8ef45dd227fb0d03b07d8c8f622d50bd192dd`

## Verification

`python scripts/verify_specs.py` → PASS (36 frozen files, v1.4 contract smoke checks). BS-001 adds a whole-document
ref-resolution test that would have caught the original defect.
