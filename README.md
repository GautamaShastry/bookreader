# BookScope AI — Spec-first development workspace (v1.4)

**Status:** Specifications frozen. BS-001 (repo skeleton + contract CI) in progress; product features **not started**. This is not a functioning application.

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

## Development setup (BS-001)

Requirements: **Python 3.12**, **Node.js ≥ 22.13** (see `apps/web/.nvmrc`), git. No AWS account or credentials are needed.

Windows (PowerShell, from the repo root):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
cd apps\web; npm ci; npx playwright install chromium; cd ..\..
```

macOS/Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
(cd apps/web && npm ci && npx playwright install chromium)
```

## Run every check (one command)

```bash
.venv/Scripts/python scripts/check.py      # Windows; use .venv/bin/python elsewhere
```

It runs all of these, keeps going after a failure, prints a PASS/FAIL summary naming every failing step, and exits 1 if any failed:

| Step | Command it runs |
|---|---|
| Frozen spec checksums + packaged v1.4 validator | `python scripts/verify_specs.py` |
| Contract validator (all schemas, all OpenAPI local refs) | `python -m bookscope_contracts` |
| Python lint / format | `ruff check .`, `ruff format --check .` |
| Python types | `mypy` (strict, config in `pyproject.toml`) |
| Python tests | `pytest` → `test-results/pytest.xml` |
| Web lint / types | `npm run lint` (ESLint, strict type-checked), `npm run typecheck` |
| Web unit tests | `vitest run` → `test-results/vitest.xml` |
| Web build | `npm run build` |
| Web end-to-end smoke | `npm run e2e` (Playwright, Chromium) → `test-results/playwright.xml` |

Flags: `--skip-e2e`, `--python-only`. CI (`.github/workflows/ci.yml`) runs the same command on Ubuntu with no secrets.

To see the negative contract fixture fail on purpose:
`python -m bookscope_contracts tests/fixtures/contracts/malformed-schemas` (exits 1, one diagnostic per problem).

### Pinned tool versions

Python (exact environment in `requirements-dev.lock`): fastapi 0.165.0, jsonschema 4.26.0, referencing 0.37.0, openapi-spec-validator 0.9.0, PyYAML 6.0.4, ruff 0.17.6, mypy 2.4.1, pytest 9.2.0, httpx 0.28.1.
Web (exact versions in `apps/web/package.json`, locked by `package-lock.json`): react 19.3.1, typescript 6.0.3, vite 8.3.8, vitest 5.1.2, eslint 10.15.0, typescript-eslint 8.74.0, @playwright/test 1.65.1.

### What exists after BS-001 (and what does not)

Skeleton packages only: `bookscope_contracts` (loads/validates the frozen specs in place), `bookscope_api` (FastAPI factory with **no routes**), `bookscope_ingestor` and `bookscope_agent_runtime` (empty). `apps/web` is a placeholder shell. **No parsing, retrieval, agents, model calls, AWS infrastructure or product features are implemented.**

The frozen contract is changed only by approved contract changes, recorded in `docs/contract-changes/`.

## Contract priority

`specs/15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md` and `specs/14-FULL-BOOK-HIERARCHICAL-SUMMARY.md` supersede contradictory older wording. Stop and request a contract amendment for genuine conflicts. The original files remain unchanged.
