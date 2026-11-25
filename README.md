# BookScope AI — Spec-first development workspace (v1.4)

**Status:** Specifications frozen; feature implementation **not started**. This archive is an organized starter workspace, not a functioning application.

## Product

A web PDF/DRM-free EPUB reader that automatically opens a cached, evidence-verified **Book Intelligence Brief**; supports book-only Q&A, passage explanations, chapter summaries and user-requested asynchronous **hierarchical full-book summaries**. Five selective LangGraph roles; deterministic authorization and citation gate. AWS development target **$50/month** (not a guarantee or an approved deployment).

## Start here

1. Read [`docs/START-VSCODE.md`](docs/START-VSCODE.md) for Windows / VS Code setup and safe AI chat workflow.
2. Open **this entire `bookscope-ai` folder** as your VS Code workspace root, *not* `specs` alone.
3. Ask the agent to read [`AGENTS.md`](AGENTS.md) and the v1.4 decision/ticket documents; use the **read-only audit prompt** from [`docs/AGENT-PROMPTS.md`](docs/AGENT-PROMPTS.md).
4. After the agent reports its understanding and any conflicts, authorize **BS-001 only**.
5. Run the frozen contract validator locally. Do not deploy AWS until a dedicated, reviewed ticket authorizes it.

## Folder map

- `specs/`: **all 37 original frozen v1.4 specification files**, API YAML, JSON Schemas, examples and contract tests, copied unchanged.
- `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`: root-level agent discovery/instructions.
- `apps/web/`: React + TypeScript reader (not yet implemented).
- `services/api/`: FastAPI/authentication/response gateway (not yet implemented).
- `services/ingestor/`: PDF/EPUB parser, chapter/section manifest and chunker (not yet implemented).
- `services/agent-runtime/`: local LangGraph, later AgentCore deployment (not yet implemented).
- `packages/contracts/`: generated/shared types and interface utilities (not yet implemented).
- `infra/`: AWS CDK (not yet implemented; paid resources not authorized).
- `tests/{fixtures,unit,integration,security,eval}/`: quality gates, fixtures and recorded evaluations (not yet implemented).
- `docs/architecture/`: editable AWS diagram and preview (target topology, not deployed).
- `docs/BUILD-ORDER.md`: which tickets to implement and what they must prove.

## Verify the supplied specification bundle

On Windows, from the VS Code terminal (PowerShell):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install pyyaml jsonschema
.\.venv\Scripts\python scripts\verify_specs.py
```

On macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pyyaml jsonschema
.venv/bin/python scripts/verify_specs.py
```

The spec validator must print a PASS for checksum verification and the v1.4 schema checks. It does **not** mean the application or any LLM eval passed.

## Contract priority

`specs/15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md` and `specs/14-FULL-BOOK-HIERARCHICAL-SUMMARY.md` supersede contradictory older wording. Stop and request a contract amendment for genuine conflicts. The original files remain unchanged.
