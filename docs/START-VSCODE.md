# Start BookScope in VS Code (Windows-first)

## Step 1 — Put the project on your computer

1. Download `BookScope_VSCode_Starter_v1.4.zip` from the ChatGPT response.
2. Right-click the ZIP, **Extract All**. You should get a folder named `bookscope-ai`.
3. Move `bookscope-ai` to a normal development location (for example `C:\dev\bookscope-ai`). Don't leave it in a temporary ZIP preview.
4. Open VS Code → **File → Open Folder** → select **bookscope-ai** (the root containing `README.md`, `AGENTS.md`, and `specs/`). Trust the workspace only if you trust the files.
5. Verify that Explorer shows `specs/`, `apps/`, `services/`, `tests/`, `infra/` and `AGENTS.md`.

## Step 2 — Set up local tooling

Install Python 3.11+ and Node.js LTS if not already available, plus Git. Python and Node versions should be pinned by the first coding ticket, not guessed by the chat agent. Use the VS Code integrated Terminal (Ctrl+`). Run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install pyyaml jsonschema
.\.venv\Scripts\python scripts\verify_specs.py
```

The validator operates on frozen specs only; it should not require AWS credentials. Don't install large AI libraries or provision cloud resources at this stage.

Optional: `git init`, `git add .`, `git commit -m "chore: import frozen BookScope specs v1.4"` once you've verified the files. Keep the repository private if you later add user books; private uploads, keys and `.env` files must never be committed.

## Step 3 — Ask the agent to understand the spec BEFORE coding

Open your preferred coding agent in VS Code:

- **GitHub Copilot Chat**: use the **Plan/Ask** role for read-only analysis, then switch to **Agent** when you authorize BS-001. Explicitly attach/refer to relevant files; not all files are automatically sent to the model.
- **Claude Code extension**: it uses `CLAUDE.md` project guidance; `CLAUDE.md` points to `AGENTS.md` and frozen specs. In its chat, paste the same audit prompt. Its file reading and approval behavior depend on the harness/permissions; verify which files it actually read.

Use the **Prompt A (read only)** in `docs/AGENT-PROMPTS.md`. Demand a list of documents read, a contract map, inconsistencies and the BS-001 scoped plan, with NO file changes.

## Step 4 — Authorize exactly one ticket

After you review its findings, use **Prompt B (implement BS-001 only)**. In an editing-capable agent mode with manual approvals, review the proposed commands and diffs. Decline commands that invoke AWS, add credentials, download arbitrary executable scripts or introduce unrelated features.

## Step 5 — Enforce the eval gate

Do not accept BS-001 until a fresh-install validation, schema/OpenAPI positive & negative checks, lint/type/unit smoke checks and CI config pass. Ask for actual commands, stdout or test report, number of passed/failed cases, and list of untouched/unfinished milestones. Commit/PR only after reviewing the diff.

## What to do after BS-001

Next ticket is **EV-001**: legally usable fixture corpus and human-verified gold labels. Only then proceed with **BS-004** PDF parser/source mapping. Follow `docs/BUILD-ORDER.md` and `specs/16-FIRST-CODING-AGENT-TICKETS.md`.

## Common mistakes

- Do not paste the whole 37-file spec into the chat; let the agent read relevant files from the workspace, using explicit file references.
- Do not let the agent rewrite requirements while implementing them.
- Do not run five AWS agents or a vector database before the source locator tests pass.
- Do not assume passing JSON Schemas proves the model's grounding accuracy.
- Do not turn on aggressive auto-approve or unattended infrastructure commands.
- Do not treat an AWS Budget alert as an enforceable $50 billing cap.
