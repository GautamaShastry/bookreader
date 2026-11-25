# Claude Code repository guide

Read `AGENTS.md` first. All frozen source documents are in `specs/`; the authoritative decisions are `specs/15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md`. Read `specs/17-FIRST-AGENT-ASSIGNMENT.md` before doing BS-001. This is a spec-first project, not permission to build every feature. First respond with a read-only understanding and scoped plan; only modify files when the user explicitly instructs you to execute BS-001.

Keep code changes within one ticket. Don't create AWS resources or call models. Require reproducible tests, failure output, and a precise report. If specs are inconsistent, identify the mismatch and stop.
