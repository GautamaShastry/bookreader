# 15 — Frozen Engineering Decisions & Development Contract v1.4

**Date:** 2026-11-24. **Status:** Decision-approved; implementation and AWS deployment not started. **Scope precedence:** this file and `14-FULL-BOOK-HIERARCHICAL-SUMMARY.md` supersede any older v1.0–v1.3 statements excluding full-book summaries or implying empty assistant on open. All other v1.3 rules remain binding.

## Accepted user decisions

| ADR | Decision | Locked requirement | Forbidden deviation |
|---|---|---|---|
| ADR-014 | Web-first | React/TypeScript in-app PDF.js/EPUB.js reader; `BOOK_OPENED` auto-displays assistant/cached verified brief | No Chrome extension, OS-file interception or permission creep in v1 |
| ADR-015 | Full-book hierarchical summaries included in first release | Explicit user-initiated async `SUMMARIZE_BOOK`; canonical every-chapter traversal; grounded citations, coverage ledger | No top-k-only book summary; no on-open full-book generation; no silent omissions |
| ADR-016 | AWS development target $50/month | Region availability check, approved estimate, budgets, alerting, per-job limits, manual teardown | No paid AWS deploy without approval; no claim $50 is a hard cap |

## Inherited immutable policies

- One authorized immutable book version per conversation. `owner_id` always derived server-side; all access mediated with IAM and backend checks.
- Accepted formats: text-selectable PDF ≤25 MiB and ≤600 physical pages; DRM-free EPUB ≤25 MiB compressed; English text V1. No OCR, image/figure claims, DRM bypass, external factual web retrieval, shared libraries, browser interception.
- Five logical selective LangGraph roles in one AgentCore Runtime for cloud deployment; no five independently hosted always-on agents. Deterministic data/authorization gates outside LLM.
- `BOOK_OPENED` triggers zero new LLM calls; cached verified Book Intelligence Brief is produced asynchronously after READY; full-book summary is a separate on-demand product action.
- Stage-specific evals/critical tests accompany every PR; no unsupported fact/citation streaming; output statuses always communicate `partial`, `abstained` or `failed` accurately.
- No unsupported performance claims or resume bullets; outcomes measured from held-out tests and recorded AWS usage only.

## Source-of-truth order (highest first)
1. These locked decisions, `14-FULL-BOOK-HIERARCHICAL-SUMMARY.md`, explicit security requirements.
2. Machine-readable `06-API-OPENAPI.yaml` + JSON Schemas, **when consistent** with normative product requirements (inconsistency blocks coding; do not silently guess).
3. `13-STAGEWISE-EVALUATION-STRATEGY.md`, `08-EVALUATION-AND-TESTING.md` and `16-FIRST-CODING-AGENT-TICKETS.md`.
4. Other v1.3 product, architecture and implementation specs.

If docs contradict each other, submit a proposed change/ADR before implementing. Do not solve contradictions by making up behavior.

## Delivery policy
One ticket per PR; no merged PR without test evidence, schema validation, expected-vs-actual outputs, dataset manifest hash, security impact, estimated/observed AWS cost, and named reviewer approval. Agents may implement pure internal details within ticket scope. They may not create AWS resources, change architecture, model/Region, data formats, budgets, release gates, or user-visible product behavior without review.

**First approved work:** repo and CI, legal evaluation fixtures, PDF extraction/source map, EPUB extraction/source map, canonical chunker/ledger. **Not authorized yet:** paid AWS deployment, AgentCore setup, public demo, or claim of model quality. Those require their own gated tickets and explicit deployment authorization.

## AWS cost controls — obligations, not guarantees
- $50/month account/project target; set AWS Budgets alerts at $25, $40 and $50 with appropriate forecast notifications. AWS Budgets notifications may lag usage; IAM budget actions are optional additional brakes, not instantaneous billing caps. Refer to https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html.
- Hard application controls: per-user quotas, upper-bound model call counts, token ceilings, 2 concurrent book-summary workers max, request-level preflight estimates, local cost ledger and a kill switch denying *new* paid inference when internal ledger reaches $40 unless explicitly approved. Track AWS billed charges separately because they can lag.
- Initial dev full-book summary allowance $2.50 estimated per job; not a claim about actual AWS charges. If estimated cost exceeds allowance, return a clear budget error; never silently truncate the book. Require deliberate approval to change the allowance.
- Keep always-on cost near zero: local-first tests, on-demand serverless cloud, **no default NAT gateway, always-on EC2/RDS, OpenSearch cluster or continuously running Fargate service** under the $50 target. Enterprise architecture diagram is a future target, not a provisioning mandate.
- AWS Region + exact model IDs and pricing remain **deployment prerequisites** verified by a small controlled canary and pricing worksheet; not silently assumed. Work locally until these pass.
- Deploy to a dedicated tagged dev stack, record a teardown command/checklist, enforce lifecycle expiration, mask private uploads in logs and eval artifacts. Require an approved plan before any `cdk deploy` or live inference test.

## Release objective
A user opens a ready book in BookScope, sees cached verified orientation, asks evidence-grounded questions, explains a selected passage, requests chapter and full-book summary, navigates all citations, and receives correct partial/refusal behavior. P0 security/citation gates pass and achieved eval + spend reports are available. This is not proof of impossible zero-hallucination guarantees.

## Change control
All subsequent product/architecture changes require new ADR, updated contracts/evals, and regression impact assessment. Freeze does not mean no bug fixes; it prevents unauthorized expansion or weakening of quality gates.
