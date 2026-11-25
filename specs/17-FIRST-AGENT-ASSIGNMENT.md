# 17 — Paste into the first coding agent (BS-001 only)

You are implementing **BookScope AI v1.4**. Scope is **BS-001 only** (monorepo scaffold, local CI, contract validation). You must read in this order:

1. `15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md`
2. `16-FIRST-CODING-AGENT-TICKETS.md` (BS-001)
3. `AGENTS.md`
4. `00-START-HERE.md`
5. `06-API-OPENAPI.yaml` and `schemas/*.json`
6. `13-STAGEWISE-EVALUATION-STRATEGY.md`

## Task

Create the minimal working monorepo structure: `/apps/web`, `/services/api`, `/services/ingestor`, `/services/agent-runtime`, `/packages/contracts`, `/tests`, `/infra`, `/specs`. Initialize Python dependency tooling, strict TypeScript, React and a minimal testable web app, backend skeleton, Ruff, Pytest, MyPy/Pyright, ESLint, Playwright test harness, schema/OpenAPI validation, and GitHub Actions CI. Ensure the project can be installed and tested from a fresh clone using documented commands. The existing `tests-contract/validate_v14_contracts.py` is a spec-only sanity check; integrate and expand it in the new repo.

## Acceptance/evaluation gates

- Valid OpenAPI and JSON schemas load; all local refs resolve, full-book `POST/GET` and `Idempotency-Key` are preserved; `job_type=full_book_summary` exists.
- `schemas/book-full-summary.schema.json` validates the provided positive example and rejects malformed statuses, missing citations/source IDs, and invalid book UUIDs.
- All core source/package imports and blank app/backend smoke tests run.
- Lint, type checks and tests run in CI without any AWS credentials. A deliberately invalid JSON Schema test fixture fails with a clear diagnostic.
- All test commands and dependency versions are captured in a README. The PR report includes actual passed/failed test counts and remaining gaps. Do not claim source parsing or AWS features are implemented.

## Prohibited in this PR

Do not deploy AWS, invoke models, implement full-book summarization, invent evaluation scores, create a vector database, build a complex UI, change the frozen ADRs, change request schemas without review, or delete failed tests.

## Required final response from coding agent

Summarize files changed; exact commands run and test counts; schema validation results; expected vs actual; estimated and observed AWS cost (`$0` for local-only work); known limitations; and handoff to **EV-001** next. If any prerequisite is missing, report a blocker explicitly rather than faking completion.
