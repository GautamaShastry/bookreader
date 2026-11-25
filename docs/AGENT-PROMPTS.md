# Copy/paste prompts for VS Code coding agents

## Prompt A — Read-only spec audit (FIRST MESSAGE)

> We are implementing BookScope AI, frozen engineering specification v1.4. **Do not write, create, delete or edit files yet. Do not execute cloud commands.**
>
> First read these workspace files, in this order:
> `AGENTS.md`, `CLAUDE.md` (if your harness uses it), `specs/15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md`, `specs/14-FULL-BOOK-HIERARCHICAL-SUMMARY.md`, `specs/AGENTS.md`, `specs/00-START-HERE.md`, `specs/16-FIRST-CODING-AGENT-TICKETS.md`, `specs/17-FIRST-AGENT-ASSIGNMENT.md`, `specs/06-API-OPENAPI.yaml`, `specs/schemas/*.json`, and `specs/13-STAGEWISE-EVALUATION-STRATEGY.md`.
>
> Follow links into the product/architecture/ingestion/agent/security specs as needed. List the exact filenames actually inspected; do not claim to have read files you did not open.
>
> Report: (1) the product's primary user journey; (2) the five logical agent roles and tool boundaries; (3) the source-of-truth/book-version/citation rules; (4) the separate first-open brief and user-triggered full-book summary workflows; (5) $50 development budget and forbidden cloud actions; (6) ambiguous/conflicting requirements, with filenames/sections; (7) the minimal BS-001 directory/tooling plan; (8) its exact evaluation gates and commands. **STOP after the plan and wait for my authorization to implement BS-001.**

## Prompt B — Implement BS-001 only (SECOND MESSAGE)

> I approve implementation of **BS-001 only**, as described in `specs/17-FIRST-AGENT-ASSIGNMENT.md` and `specs/16-FIRST-CODING-AGENT-TICKETS.md`. Do not implement EV-001, parsing, RAG, agent inference, a vector database or cloud deployment. Preserve `specs/` byte-for-byte, including the SHA-256 manifest.
>
> Set up the smallest reproducible Python/FastAPI and React/TypeScript monorepo skeleton, formatting/type/unit-test tooling, packaged schema/OpenAPI validation, a negative malformed-schema test, and GitHub Actions CI. Ensure the repository installs and checks cleanly from a fresh clone, with documented local commands and pinned dependencies. Make one cohesive set of changes; write tests before claiming success.
>
> Run each relevant check and give me its exact result: commands, pass/fail counts, failures, and anything not run. Demonstrate the negative schema fixture fails when intentionally invalid. Report files changed, security/privacy impact, expected vs actual, and observed AWS cost ($0 for this strictly local ticket). No AWS calls, credentials, model API calls, new AWS infrastructure, or fabricated benchmarks. Stop after BS-001 and recommend EV-001 as the next ticket.

## Prompt C — Review after BS-001 before merge

> Act as a skeptical senior engineer reviewing only BS-001. Compare the actual diff and test outputs against `specs/17-FIRST-AGENT-ASSIGNMENT.md`. Search for out-of-scope changes, unpinned dependencies, missing negative tests, accidental secrets or paid cloud integrations, and broken OpenAPI/schema contracts. List blocking issues first; if none, present the evidence for each acceptance condition and a clean handoff to EV-001. Do not make changes without asking.
