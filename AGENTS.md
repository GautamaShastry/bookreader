# BookScope AI — Repository instructions for coding agents

> Read before modifying this repository. Frozen spec version **v1.4 (2026-11-24)**.

## Read order and precedence

1. `specs/15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md` — highest-priority accepted decisions.
2. `specs/14-FULL-BOOK-HIERARCHICAL-SUMMARY.md` — full-book summary normative behavior.
3. `specs/AGENTS.md` — security, workflow, tests and restrictions.
4. `specs/00-START-HERE.md` — map to other specifications.
5. `specs/16-FIRST-CODING-AGENT-TICKETS.md` and `specs/17-FIRST-AGENT-ASSIGNMENT.md` — current authorized work.
6. `specs/06-API-OPENAPI.yaml` and `specs/schemas/*.json` — interface contracts.
7. `specs/13-STAGEWISE-EVALUATION-STRATEGY.md` / `specs/08-EVALUATION-AND-TESTING.md` — per-stage gates.

Older statements excluding full-book summaries are superseded by the v1.4 decisions. If a normative document and schema disagree, STOP and describe the conflict; don't silently improvise.

## Scope of work

**Current authorized ticket: BS-001 only.** Repository tooling, skeleton and deterministic contract CI. No ingestion/AI feature implementation in this ticket. Start with read-only spec review and a plan, then request permission before edits.

- No paid AWS deployment, cloud resource creation, API key use, or model inference without a separate approved ticket.
- No new requirements, services, agents, frameworks or changes to accepted ADRs without authorization.
- Don't touch `specs/` except an explicitly approved contract change. Existing `specs/MANIFEST.sha256` is the frozen checksum baseline.
- The first release is web-reader-first; cached verified Book Intelligence Brief opens beside the book. Full-book hierarchical summary is a **separate user-triggered async action**.
- Five *logical* selectively run LangGraph roles in one planned AgentCore Runtime; book/version authorization and deterministic publication gates sit outside agents.
- No external fact retrieval to augment a book, no unverified factual answer streaming, no citation invented by a model.
- AWS development target $50/month, *not a hard cap*; no paid deployment without human approval.
- One ticket per branch/PR, per-stage positive and adversarial evaluations, exact command outputs and test counts required.

## Per-ticket completion report

Ticket; files changed; constraints checked; test commands with passed/failed counts; negative tests; fixture manifest/checksum; security/privacy impact; observed AWS usage ($0 for purely local work); deviations; follow-on work.

## Helpful local check

`python scripts/verify_specs.py` checks the frozen checksum manifest and runs the packaged schema/OpenAPI validator if `PyYAML` and `jsonschema` are installed. This is only a **spec contract check**, not application/evaluation evidence.
