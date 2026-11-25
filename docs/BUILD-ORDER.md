# BookScope delivery order and evaluation gates

The frozen full detail is `specs/16-FIRST-CODING-AGENT-TICKETS.md`. The table below is an executable checklist, not a claim of completion.

| State | Ticket | Deliverable | Evidence required to advance |
|---|---|---|---|
| ☐ | **BS-001** | Monorepo, CI, contracts tooling | Passing fresh install, schema/OpenAPI positive & negative checks, lint/type/unit smoke |
| ☐ | **EV-001** | Permitted fixture documents and independently verified gold labels | Document/license manifest, hash checks, no dangling source IDs |
| ☐ | **BS-004** | PDF parser and page locators | 100% correct locators on labeled fixture pages; explicit unreadable handling |
| ☐ | **EV-002** | Source-map eval reporter | Corrupt source detected; no empty-output perfect scores |
| ☐ | **BS-005** | EPUB parser and anchors | Spine/anchor correctness and ZIP/DRM safety cases |
| ☐ | **BS-006** | Chunker + immutable chapter/section ledger | Full source accounting, stable hashes, integrity / cross-scope rejection |
| ☐ | **BS-026** | Full-book API & contracts with fake executor | Idempotency / invalid status / unsupported citations blocked |
| ☐ | **BS-027** | Hierarchical summary orchestration using fake models | Every chapter visited, no false `ready`, budget and cancellation checks |
| ☐ | **EV-009** | Summary eval harness + baseline | Detects omissions, unsupported claims; scored data not fabricated |

Later work: authenticated reader and auto-open/cached Brief, retrieval canary, local multi-agent graph, real model evaluation, AgentCore/AWS deployment, release benchmark. The early tickets above do **not** by themselves complete the product.

## What counts as done

Each ticket: test fixtures, adversarial case, machine-readable test output, clear failed cases, code review, no unauthorized architecture change, observed cloud usage, and exact revision/commit. If a gate fails, fix it before the next dependent ticket. A model/judge verdict must never override a deterministic authorization, ownership, locator, hash or coverage failure.
