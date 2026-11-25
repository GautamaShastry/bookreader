# Full-book summary evaluation rubric (EV-009)

This rubric defines how people label and score full-book summaries (spec 14 FR-029, spec 13 §3).
The automated scorecard (`python -m bookscope_eval.summary_scorecard`) applies the deterministic
parts; the judgement parts below need human reviewers.

## Status of the gold dataset

| Requirement | Target | Now |
|---|---|---|
| Human-annotated full-book cases | ≥ 20 | **0 — TODO** |
| Distinct legally usable books | ≥ 3 | **0 — TODO** |
| Must include | multi-chapter book, heading-poor PDF, long EPUB, deliberately unreadable segment | synthetic stand-ins only |
| Split | book-level dev / frozen holdout | not created |

`tests/fixtures/summary_cases.jsonl` holds **synthetic** cases (`label_status: synthetic`) that
exercise the scorer. They are not gold and no quality number may be reported from them.

## Labelling a case

For each book version, two reviewers independently record:

1. **Material topics** per chapter: the points a reader must get from that chapter. For each topic
   give `topic_id`, `chapter_ordinal`, an exact `quote` from the canonical text that establishes it,
   and `material: true|false`. Non-material topics (anecdotes, asides) are recorded with
   `material: false` so omissions of them are not penalised.
2. **Expected status**: `ready` only if every chapter has extractable text; `partial` if any chapter
   or section is unreadable (image-only, encrypted region, parse failure); `failed` if nothing
   usable survives.
3. Disagreements go to a third reviewer; record the adjudication in `notes`. Set
   `label_status: human_verified` only after adjudication.

## Scoring a summary

| Dimension | How | Automated? | Gate / target |
|---|---|---|---|
| Publication integrity | BS-026 checks (false ready, missing/foreign citation, wrong chapter, unverified content) | yes | **0 violations (blocking)** |
| Status correctness | observed status equals the labelled status | yes | **blocking** |
| Material-topic coverage | topic covered iff a published claim cites a source containing the topic quote | yes | ≥ 95% target |
| Claim support | each claim: *supported* (entailed by its cited passages), *partially supported*, *unsupported*, *contradicted* | human (auto verbatim check is a smoke signal only) | ≥ 98% supported target |
| Citation navigation | each citation opens the right page/section in the reader | human + E2E (later ticket) | 100% |
| Omissions | material topics not covered and not disclosed as uncovered | human review of `topics_missed` | report every case |
| Faithfulness of ordering | chapter summaries follow the book's order; no cross-chapter conflation | yes (order) + human | — |
| Cost / tokens / latency | from run stats and the reviewed pricing catalog | yes | reported, budget ≤ $2.50/job |

Support labels (human): mark a claim *unsupported* if any part of it is not entailed by the cited
passages, even if it is true elsewhere in the book or in the world. Do not credit general knowledge.

## Reporting

* Always show denominators, failed cases, and the evidence class (`synthetic_workflow_only` or
  `human_labeled`).
* Compare the hierarchical engine with the single-agent baseline at a matched model, token and
  cost budget, by case type; include deltas and failure examples.
* Targets above are targets, not results. A nonzero critical violation blocks release regardless
  of averages. Never present fake-model or synthetic-label runs as product quality.
