"""Source-integrity scorecard (EV-002): parser output vs EV-001 gold labels.

Deterministic and model-free. For every fixture it records which checks passed and, for each
failure, the expected and observed values. Ratios use gold denominators, so an empty or partial
parser output can never score 100%, and a metric with no applicable gold items is reported as
``null`` (not applicable), never as a perfect score.

    python -m bookscope_eval.source_scorecard [--out DIR]

writes ``source-scorecard.json`` and ``.md``; exits 1 on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bookscope_eval.fixtures import FIXTURES_DIR, load_manifest, manifest_sha256
from bookscope_ingestor.errors import IngestError
from bookscope_ingestor.locate import find_quote
from bookscope_ingestor.models import ParsedDocument

Parser = Callable[[bytes], ParsedDocument]
SCORECARD_VERSION = "1.0.0"


@dataclass(frozen=True)
class Failure:
    fixture_id: str
    check: str
    expected: Any
    observed: Any
    category: str  # failure taxonomy (spec 13): PARSE_MISSING, PARSE_ORDER, LOCATOR, HASH, OUTCOME


@dataclass
class FixtureScore:
    fixture_id: str
    format: str
    evaluated: bool
    expected_outcome: str
    observed_outcome: str
    total_source_units: int
    units_parsed: int
    unreadable_units: int
    units_accounted: int
    quotes_total: int
    quotes_valid: int
    hash_valid: bool
    reading_order_issues: int
    extraction_version: str | None
    failures: list[Failure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.evaluated and not self.failures


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _index(source_id: str) -> int:
    return int(source_id.rsplit(":", 1)[1][1:])


def score_fixture(
    fixture: dict[str, Any], parser: Parser | None, fixtures_dir: Path = FIXTURES_DIR
) -> FixtureScore:
    fid = fixture["fixture_id"]
    gold_units: list[dict[str, Any]] = fixture["source_units"]
    expected_outcome = fixture["expected_outcome"]["status"]
    score = FixtureScore(
        fixture_id=fid,
        format=fixture["format"],
        evaluated=parser is not None,
        expected_outcome=expected_outcome,
        observed_outcome="not_evaluated",
        total_source_units=len(gold_units),
        units_parsed=0,
        unreadable_units=0,
        units_accounted=0,
        quotes_total=len(fixture["quotes"]),
        quotes_valid=0,
        hash_valid=False,
        reading_order_issues=0,
        extraction_version=None,
    )
    fail = score.failures.append
    data = (fixtures_dir / fixture["path"]).read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()
    score.hash_valid = file_hash == fixture["sha256"]
    if not score.hash_valid:
        fail(Failure(fid, "file_sha256", fixture["sha256"], file_hash, "HASH"))
    if parser is None:
        return score

    try:
        document = parser(data)
    except IngestError as exc:
        score.observed_outcome = f"rejected:{exc.code}"
        expected = (
            f"rejected:{fixture['expected_outcome']['error_code']}"
            if expected_outcome == "rejected"
            else "accepted"
        )
        if score.observed_outcome != expected:
            fail(Failure(fid, "outcome", expected, score.observed_outcome, "OUTCOME"))
        return score

    score.observed_outcome = "accepted"
    score.extraction_version = document.extraction_version
    if expected_outcome == "rejected":
        expected = f"rejected:{fixture['expected_outcome']['error_code']}"
        fail(Failure(fid, "outcome", expected, "accepted", "OUTCOME"))
        return score
    if document.sha256 != file_hash:
        score.hash_valid = False
        fail(Failure(fid, "document_sha256", file_hash, document.sha256, "HASH"))

    units = {u.unit_index: u for u in document.units}
    score.units_parsed = len(document.units)
    score.unreadable_units = len(document.unreadable_units)
    if [u.unit_index for u in document.units] != list(range(len(document.units))):
        fail(
            Failure(
                fid, "unit_order", "0..n-1", [u.unit_index for u in document.units], "PARSE_ORDER"
            )
        )
    if len(document.units) != len(gold_units):
        fail(Failure(fid, "unit_count", len(gold_units), len(document.units), "PARSE_MISSING"))

    for position, gold in enumerate(gold_units):
        unit = units.get(position)
        sid = gold["source_id"]
        if unit is None:
            fail(Failure(fid, f"unit:{sid}", "present", "missing", "PARSE_MISSING"))
            continue
        observed_status = "readable" if unit.is_readable else "unreadable"
        if observed_status != gold["status"]:
            fail(Failure(fid, f"status:{sid}", gold["status"], observed_status, "PARSE_MISSING"))
            continue
        text = unit.normalized_text
        ok = True
        if "first_line" in gold and not text.startswith(gold["first_line"]):
            fail(Failure(fid, f"first_line:{sid}", gold["first_line"], text[:80], "PARSE_MISSING"))
            ok = False
        if "last_line" in gold and not text.endswith(gold["last_line"]):
            fail(Failure(fid, f"last_line:{sid}", gold["last_line"], text[-80:], "PARSE_MISSING"))
            ok = False
        for excluded in gold.get("excluded_text", []):
            if excluded in text:
                fail(Failure(fid, f"excluded_text:{sid}", "absent", excluded, "PARSE_MISSING"))
                ok = False
        lines = gold.get("reading_order_lines", [])
        positions = [text.find(line) for line in lines]
        if lines and (-1 in positions or positions != sorted(positions)):
            score.reading_order_issues += 1
            fail(Failure(fid, f"reading_order:{sid}", lines, positions, "PARSE_ORDER"))
            ok = False
        if ok:
            score.units_accounted += 1

    for quote in fixture["quotes"]:
        expected_units = tuple(_index(s) for s in quote["expected_source_ids"])
        expected_status = "ambiguous" if quote["ambiguous"] else "unique"
        resolution = find_quote(document, quote["text"])
        if resolution.unit_indexes == expected_units and resolution.status == expected_status:
            score.quotes_valid += 1
        else:
            fail(
                Failure(
                    fid,
                    f"quote:{quote['quote_id']}",
                    {"status": expected_status, "units": list(expected_units)},
                    {"status": resolution.status, "units": list(resolution.unit_indexes)},
                    "LOCATOR",
                )
            )
    return score


def build_scorecard(
    parsers: Mapping[str, Parser], fixtures_dir: Path = FIXTURES_DIR
) -> dict[str, Any]:
    manifest = load_manifest(fixtures_dir)
    scores = [
        score_fixture(f, parsers.get(f["format"]), fixtures_dir) for f in manifest["fixtures"]
    ]
    evaluated = [s for s in scores if s.evaluated]
    accepted = [s for s in evaluated if s.expected_outcome == "accepted"]
    total_units = sum(s.total_source_units for s in accepted)
    quotes = sum(s.quotes_total for s in accepted)
    failures = [asdict(f) for s in scores for f in s.failures]
    summary = {
        "fixtures_total": len(scores),
        "fixtures_evaluated": len(evaluated),
        "fixtures_not_evaluated": sorted(s.fixture_id for s in scores if not s.evaluated),
        "fixtures_passed": sum(s.passed for s in scores),
        "fixtures_failed": sum(1 for s in evaluated if not s.passed),
        "total_source_units": total_units,
        "units_parsed": sum(s.units_parsed for s in accepted),
        "unreadable_units": sum(s.unreadable_units for s in accepted),
        "coverage": _ratio(sum(s.units_accounted for s in accepted), total_units),
        "locator_valid": _ratio(sum(s.quotes_valid for s in accepted), quotes),
        "hash_valid": _ratio(sum(s.hash_valid for s in evaluated), len(evaluated)),
        "outcome_correct": _ratio(
            sum(not any(f.check == "outcome" for f in s.failures) for s in evaluated),
            len(evaluated),
        ),
        "reading_order_issues": sum(s.reading_order_issues for s in accepted),
        "failure_count": len(failures),
        "passed": bool(evaluated) and all(s.passed for s in evaluated),
    }
    return {
        "scorecard": "source-integrity",
        "scorecard_version": SCORECARD_VERSION,
        "dataset_manifest_sha256": manifest_sha256(fixtures_dir),
        "evaluated_formats": sorted(parsers),
        "summary": summary,
        "fixtures": [
            {k: v for k, v in asdict(s).items() if k != "failures"} | {"passed": s.passed}
            for s in scores
        ],
        "failures": failures,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def to_markdown(card: dict[str, Any]) -> str:
    s = card["summary"]
    lines = [
        "# Source-integrity scorecard (EV-002)",
        "",
        f"- Dataset manifest SHA-256: `{card['dataset_manifest_sha256']}`",
        f"- Formats evaluated: {', '.join(card['evaluated_formats']) or 'none'}",
        f"- Result: **{'PASS' if s['passed'] else 'FAIL'}** "
        f"({s['fixtures_passed']}/{s['fixtures_evaluated']} evaluated fixtures passed; "
        f"{len(s['fixtures_not_evaluated'])} not evaluated)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| total_source_units | {s['total_source_units']} |",
        f"| units_parsed | {s['units_parsed']} |",
        f"| unreadable_units | {s['unreadable_units']} |",
        f"| coverage | {_pct(s['coverage'])} |",
        f"| locator_valid | {_pct(s['locator_valid'])} |",
        f"| hash_valid | {_pct(s['hash_valid'])} |",
        f"| outcome_correct | {_pct(s['outcome_correct'])} |",
        f"| reading_order_issues | {s['reading_order_issues']} |",
        "",
        "| Fixture | Format | Expected | Observed | Units (parsed/gold) | Quotes valid | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in card["fixtures"]:
        result = "PASS" if f["passed"] else ("not evaluated" if not f["evaluated"] else "FAIL")
        lines.append(
            f"| {f['fixture_id']} | {f['format']} | {f['expected_outcome']} | "
            f"{f['observed_outcome']} | {f['units_parsed']}/{f['total_source_units']} | "
            f"{f['quotes_valid']}/{f['quotes_total']} | {result} |"
        )
    if card["failures"]:
        lines += [
            "",
            "## Failures",
            "",
            "| Fixture | Check | Category | Expected | Observed |",
            "|---|---|---|---|---|",
        ]
        for f in card["failures"]:
            lines.append(
                f"| {f['fixture_id']} | {f['check']} | {f['category']} | "
                f"`{json.dumps(f['expected'], ensure_ascii=False)[:80]}` | "
                f"`{json.dumps(f['observed'], ensure_ascii=False)[:80]}` |"
            )
    if s["fixtures_not_evaluated"]:
        lines += [
            "",
            f"Not evaluated (no parser for format): {', '.join(s['fixtures_not_evaluated'])}",
        ]
    return "\n".join(lines) + "\n"


def default_parsers() -> dict[str, Parser]:
    from bookscope_ingestor.pdf import parse_pdf

    parsers: dict[str, Parser] = {"pdf": parse_pdf}
    try:  # the EPUB adapter arrives in BS-005; until then EPUB fixtures are "not evaluated"
        epub = importlib.import_module("bookscope_ingestor.epub")
    except ModuleNotFoundError:
        pass
    else:
        parsers["epub"] = epub.parse_epub
    return parsers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("test-results"))
    args = parser.parse_args(argv)
    card = build_scorecard(default_parsers())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source-scorecard.json").write_text(
        json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown = to_markdown(card)
    (args.out / "source-scorecard.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if card["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
