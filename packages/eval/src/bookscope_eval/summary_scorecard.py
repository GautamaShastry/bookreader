"""Full-book summary scorecard and baseline comparison (EV-009, spec 13/14).

Scores ``FullBookSummaryResponse`` outputs against case labels, deterministically:

* **critical** (release-blocking): any BS-026 publication violation (false ``ready``, missing or
  foreign citations, skipped units marked complete, ...) and a status different from the label;
* **topic_recall**: gold material topics covered / material topics. A topic is covered only when a
  published claim cites a source whose canonical text contains the topic's gold quote;
* **claim_precision**: claims that cite at least one gold-topic source / all claims;
* **supported_claim_rate**: human support judgments when provided, otherwise a deterministic
  verbatim check (claim text found in its cited sources), reported with its method;
* **overview_chapter_coverage**: chapters represented in overview claims / chapters;
* counters: model calls, tokens, estimated USD, latency.

Results from fake models or synthetic labels are workflow evidence only and are labelled so; they
must never be reported as product quality. Human-annotated gold cases (>= 20 across >= 3 books,
spec 14 FR-029) are tracked as TODO until they exist.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from bookscope_contracts.full_summary import LedgerView, check_full_summary
from bookscope_eval.fixtures import FIXTURES_DIR
from bookscope_ingestor.chunking import BookScope
from bookscope_ingestor.ledger import CanonicalBook
from bookscope_ingestor.normalize import normalize_text

SCORECARD_VERSION = "1.0.0"
REQUIRED_HUMAN_CASES = 20
REQUIRED_BOOKS = 3


@dataclass(frozen=True)
class SystemRun:
    """What a system under test returns for one book."""

    response: dict[str, Any]
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0


System = Callable[[CanonicalBook, BookScope], Coroutine[Any, Any, SystemRun]]


@dataclass
class CaseScore:
    case_id: str
    system: str
    expected_status: str
    observed_status: str
    label_status: str
    critical: list[str]
    material_topics: int
    topics_covered: list[str]
    topics_missed: list[str]
    topic_recall: float | None
    claims: int
    claim_precision: float | None
    supported_claim_rate: float | None
    support_method: str
    overview_chapter_coverage: float | None
    model_calls: int
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    latency_ms: float = field(default=0.0)

    @property
    def passed(self) -> bool:
        return not self.critical


def load_cases(path: Path = FIXTURES_DIR / "summary_cases.jsonl") -> list[dict[str, Any]]:
    schema = json.loads(
        (FIXTURES_DIR / "schemas" / "summary-case.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        errors = [e.message for e in validator.iter_errors(case)]
        if errors:
            raise ValueError(f"{path.name}:{number}: {errors[0]}")
        cases.append(case)
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in summary cases")
    return cases


def _claims(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(response["overview_claims"]) + [
        c for s in response["chapter_summaries"] for c in s["claims"]
    ]


def score_response(
    case: Mapping[str, Any],
    system: str,
    run: SystemRun,
    book: CanonicalBook,
    judgments: Mapping[str, bool] | None = None,
    latency_ms: float = 0.0,
) -> CaseScore:
    response = run.response
    view = LedgerView.from_canonical_ledger(book.ledger)
    critical = [f"{v.code}: {v.detail}" for v in check_full_summary(response, view)]
    if response.get("status") != case["expected_status"]:
        critical.append(
            f"STATUS_MISMATCH: expected {case['expected_status']}, got {response.get('status')}"
        )

    texts = {c.chunk_id: c.text for c in book.chunks}
    chapter_of = {c.chunk_id: c.chapter_id for c in book.chunks}
    ordinal = {c["chapter_id"]: c["ordinal"] for c in book.ledger["chapters"]}
    claims = _claims(response) if "overview_claims" in response else []
    material = [t for t in case["topics"] if t["material"]]

    def sources_with(quote: str) -> set[str]:
        needle = normalize_text(quote)
        return {sid for sid, text in texts.items() if needle in text}

    topic_sources = {t["topic_id"]: sources_with(t["quote"]) for t in case["topics"]}
    for topic in case["topics"]:
        located = {ordinal[chapter_of[s]] for s in topic_sources[topic["topic_id"]]}
        if topic["chapter_ordinal"] not in located:
            critical.append(
                f"LABEL_INVALID: topic {topic['topic_id']} quote not in chapter "
                f"{topic['chapter_ordinal']}"
            )
    cited = {sid for claim in claims for sid in claim["source_ids"]}
    covered = sorted(t["topic_id"] for t in material if topic_sources[t["topic_id"]] & cited)
    missed = sorted(t["topic_id"] for t in material if t["topic_id"] not in covered)
    gold_sources = set().union(*topic_sources.values()) if topic_sources else set()
    relevant = sum(1 for claim in claims if set(claim["source_ids"]) & gold_sources)

    if judgments is not None:
        method = "human"
        judged = [judgments[c["claim_id"]] for c in claims if c["claim_id"] in judgments]
        supported = sum(judged)
        denominator = len(judged)
    else:
        method = "auto_verbatim"
        supported = sum(
            1
            for c in claims
            if any(normalize_text(c["text"]) in texts.get(s, "") for s in c["source_ids"])
        )
        denominator = len(claims)

    chapters = len(book.ledger["chapters"])
    overview_chapters = {
        chapter_of[s]
        for c in response.get("overview_claims", [])
        for s in c["source_ids"]
        if s in chapter_of
    }

    def ratio(a: int, b: int) -> float | None:
        return None if b == 0 else round(a / b, 6)

    return CaseScore(
        case_id=case["case_id"],
        system=system,
        expected_status=case["expected_status"],
        observed_status=str(response.get("status")),
        label_status=case["label_status"],
        critical=critical,
        material_topics=len(material),
        topics_covered=covered,
        topics_missed=missed,
        topic_recall=ratio(len(covered), len(material)),
        claims=len(claims),
        claim_precision=ratio(relevant, len(claims)),
        supported_claim_rate=ratio(supported, denominator),
        support_method=method,
        overview_chapter_coverage=ratio(len(overview_chapters), chapters),
        model_calls=run.model_calls,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        estimated_usd=round(run.estimated_usd, 6),
        latency_ms=round(latency_ms, 3),
    )


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return None if not present else round(sum(present) / len(present), 6)


def summarize(scores: Sequence[CaseScore]) -> dict[str, Any]:
    return {
        "cases": len(scores),
        "cases_passed": sum(s.passed for s in scores),
        "critical_violations": sum(len(s.critical) for s in scores),
        "false_ready": sum(any(c.startswith("FALSE_READY") for c in s.critical) for s in scores),
        "mean_topic_recall": _mean([s.topic_recall for s in scores]),
        "mean_claim_precision": _mean([s.claim_precision for s in scores]),
        "mean_supported_claim_rate": _mean([s.supported_claim_rate for s in scores]),
        "model_calls": sum(s.model_calls for s in scores),
        "input_tokens": sum(s.input_tokens for s in scores),
        "output_tokens": sum(s.output_tokens for s in scores),
        "estimated_usd": round(sum(s.estimated_usd for s in scores), 6),
    }


def build_report(
    cases: Sequence[Mapping[str, Any]],
    books: Mapping[str, tuple[CanonicalBook, BookScope]],
    systems: Mapping[str, System],
    *,
    synthetic_systems: bool,
    judgments: Mapping[str, Mapping[str, bool]] | None = None,
) -> dict[str, Any]:
    import asyncio

    per_system: dict[str, list[CaseScore]] = {}
    for name, system in systems.items():
        scores = []
        for case in cases:
            book, scope = books[case["fixture_id"]]
            started = time.perf_counter()
            run = asyncio.run(system(book, scope))
            elapsed = (time.perf_counter() - started) * 1000
            scores.append(
                score_response(
                    case,
                    name,
                    run,
                    book,
                    (judgments or {}).get(f"{name}:{case['case_id']}"),
                    elapsed,
                )
            )
        per_system[name] = scores
    human = [c for c in cases if c["label_status"] == "human_verified"]
    human_books = {c["fixture_id"] for c in human}
    summaries = {name: summarize(scores) for name, scores in per_system.items()}
    names = list(systems)
    comparison = None
    if len(names) == 2:
        a, b = (summaries[n] for n in names)
        comparison = {
            "systems": names,
            "delta_mean_topic_recall": _delta(a["mean_topic_recall"], b["mean_topic_recall"]),
            "delta_model_calls": a["model_calls"] - b["model_calls"],
            "delta_estimated_usd": round(a["estimated_usd"] - b["estimated_usd"], 6),
            "delta_critical_violations": a["critical_violations"] - b["critical_violations"],
        }
    return {
        "scorecard": "full-book-summary",
        "scorecard_version": SCORECARD_VERSION,
        "evidence_class": "synthetic_workflow_only"
        if synthetic_systems or len(human) < len(cases)
        else "human_labeled",
        "notice": (
            "Fake models and/or synthetic labels: workflow evidence only, NOT product quality."
            if synthetic_systems or len(human) < len(cases)
            else "Human-labeled cases."
        ),
        "gold_status": {
            "human_verified_cases": len(human),
            "human_verified_books": len(human_books),
            "required_cases": REQUIRED_HUMAN_CASES,
            "required_books": REQUIRED_BOOKS,
            "status": "TODO"
            if len(human) < REQUIRED_HUMAN_CASES or len(human_books) < REQUIRED_BOOKS
            else "met",
        },
        "summary": summaries,
        "comparison": comparison,
        "cases": {
            name: [asdict(s) | {"passed": s.passed} for s in scores]
            for name, scores in per_system.items()
        },
        "passed": all(s.passed for scores in per_system.values() for s in scores),
    }


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 6)


def without_timings(report: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = json.loads(json.dumps(report))
    for scores in clean["cases"].values():
        for score in scores:
            score.pop("latency_ms", None)
    return clean


def to_markdown(report: Mapping[str, Any]) -> str:
    gold = report["gold_status"]
    lines = [
        "# Full-book summary scorecard (EV-009)",
        "",
        f"> **{report['notice']}**",
        "",
        f"- Evidence class: `{report['evidence_class']}`",
        f"- Human-annotated gold: {gold['human_verified_cases']}/{gold['required_cases']} cases, "
        f"{gold['human_verified_books']}/{gold['required_books']} books -> **{gold['status']}**",
        f"- Result: **{'PASS' if report['passed'] else 'FAIL'}** (critical violations block)",
        "",
        "| System | Cases passed | Critical | False ready | Topic recall | Claim precision "
        "| Supported | Calls | USD (est.) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in report["summary"].items():
        lines.append(
            f"| {name} | {s['cases_passed']}/{s['cases']} | {s['critical_violations']} "
            f"| {s['false_ready']} | {s['mean_topic_recall']} | {s['mean_claim_precision']} "
            f"| {s['mean_supported_claim_rate']} | "
            f"{s['model_calls']} | {s['estimated_usd']} |"
        )
    for name, scores in report["cases"].items():
        failing = [s for s in scores if not s["passed"]]
        if failing:
            lines += ["", f"## {name}: failing cases", ""]
            for s in failing:
                lines.append(f"- `{s['case_id']}`: " + "; ".join(s["critical"][:3]))
    return "\n".join(lines) + "\n"


def fixture_books(
    fixture_ids: Sequence[str], owner_id: str = "eval-owner"
) -> dict[str, tuple[CanonicalBook, BookScope]]:
    """Canonical books for EV-001 fixtures (parsed + chunked locally; no network)."""
    from bookscope_eval.fixtures import load_manifest
    from bookscope_ingestor.epub import parse_epub
    from bookscope_ingestor.ledger import build_canonical_book
    from bookscope_ingestor.pdf import parse_pdf

    manifest = {f["fixture_id"]: f for f in load_manifest()["fixtures"]}
    books = {}
    for fixture_id in fixture_ids:
        fixture = manifest[fixture_id]
        data = (FIXTURES_DIR / fixture["path"]).read_bytes()
        document = parse_pdf(data) if fixture["format"] == "pdf" else parse_epub(data)
        scope = BookScope(owner_id, fixture["book_id"], fixture["book_version_id"])
        books[fixture_id] = (build_canonical_book(document, scope), scope)
    return books


def main(argv: list[str] | None = None) -> int:
    """Run the synthetic scorecard: hierarchical engine vs single-agent baseline, fake models."""
    import argparse

    from bookscope_agent_runtime.baseline import SingleAgentBaseline, baseline_system, engine_system
    from bookscope_agent_runtime.fake_models import ExtractiveFakeModel
    from bookscope_agent_runtime.summary_engine import EngineConfig, PricingCatalog, SummaryEngine

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--out", type=Path, default=Path("test-results"))
    args = parser.parse_args(argv)
    cases = load_cases()
    books = fixture_books(sorted({c["fixture_id"] for c in cases}))
    pricing = PricingCatalog("TEST-ONLY synthetic prices, not AWS", 0.001, 0.002)
    systems: dict[str, System] = {
        "hierarchical-engine": engine_system(
            SummaryEngine(ExtractiveFakeModel(), EngineConfig(pricing=pricing))
        ),
        "single-agent-baseline": baseline_system(
            SingleAgentBaseline(ExtractiveFakeModel(), 2_000), pricing
        ),
    }
    report = build_report(cases, books, systems, synthetic_systems=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary-scorecard.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown = to_markdown(report)
    (args.out / "summary-scorecard.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
