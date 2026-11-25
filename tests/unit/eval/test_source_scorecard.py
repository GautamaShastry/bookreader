"""EV-002: the source-integrity scorecard must catch every class of parser/source failure."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bookscope_eval.fixtures import FIXTURES_DIR
from bookscope_eval.source_scorecard import Parser, build_scorecard, to_markdown
from bookscope_ingestor.errors import ErrorCode, IngestError
from bookscope_ingestor.models import ParsedDocument, SourceUnit
from bookscope_ingestor.pdf import parse_pdf

Transform = Callable[[ParsedDocument], ParsedDocument]


def _wrapped(transform: Transform) -> Parser:
    def parser(data: bytes) -> ParsedDocument:
        return transform(parse_pdf(data))

    return parser


def _card(parser: Parser, fixtures_dir: Path = FIXTURES_DIR) -> dict[str, Any]:
    return build_scorecard({"pdf": parser}, fixtures_dir)


def _checks(card: dict[str, Any]) -> set[str]:
    return {f["check"].split(":")[0] for f in card["failures"]}


def _units(doc: ParsedDocument, units: list[SourceUnit]) -> ParsedDocument:
    return dataclasses.replace(doc, units=tuple(units))


# --- positive ------------------------------------------------------------------------------------


def test_real_pdf_parser_scores_100_percent() -> None:
    card = _card(parse_pdf)
    summary = card["summary"]
    assert summary["passed"] is True
    assert summary["failure_count"] == 0
    assert summary["coverage"] == 1.0
    assert summary["locator_valid"] == 1.0
    assert summary["hash_valid"] == 1.0
    assert summary["reading_order_issues"] == 0
    assert summary["total_source_units"] == summary["units_parsed"] == 14


def test_scorecard_is_deterministic() -> None:
    assert json.dumps(_card(parse_pdf), sort_keys=True) == json.dumps(
        _card(parse_pdf), sort_keys=True
    )


def test_unevaluated_formats_are_listed_not_scored() -> None:
    card = _card(parse_pdf)
    assert card["evaluated_formats"] == ["pdf"]
    assert "epub3-orchard" in card["summary"]["fixtures_not_evaluated"]
    epub = next(f for f in card["fixtures"] if f["fixture_id"] == "epub3-orchard")
    assert epub["evaluated"] is False
    assert epub["passed"] is False


# --- negative: empty / missing output ------------------------------------------------------------


def test_empty_parser_output_cannot_score_100_percent() -> None:
    card = _card(_wrapped(lambda d: _units(d, [])))
    summary = card["summary"]
    assert summary["passed"] is False
    assert summary["coverage"] == 0.0
    assert summary["locator_valid"] == 0.0
    assert {"unit_count", "unit"} <= _checks(card)


def test_no_parsers_at_all_is_not_a_pass() -> None:
    card = build_scorecard({})
    assert card["summary"]["passed"] is False
    assert card["summary"]["fixtures_evaluated"] == 0
    assert card["summary"]["coverage"] is None  # not applicable, never "100%"


def test_silently_dropped_unreadable_page_fails() -> None:
    def drop_unreadable(doc: ParsedDocument) -> ParsedDocument:
        kept = [u for u in doc.units if u.is_readable]
        return _units(doc, [dataclasses.replace(u, unit_index=i) for i, u in enumerate(kept)])

    card = _card(_wrapped(drop_unreadable))
    failing = {f["fixture_id"] for f in card["failures"]}
    assert failing == {"pdf-image-only-page"}
    assert card["summary"]["coverage"] < 1.0


def test_unreadable_page_reported_readable_fails() -> None:
    def fake_text(doc: ParsedDocument) -> ParsedDocument:
        return _units(
            doc,
            [
                u
                if u.is_readable
                else dataclasses.replace(u, status="readable", normalized_text="x")
                for u in doc.units
            ],
        )

    card = _card(_wrapped(fake_text))
    assert "status" in _checks(card)


# --- negative: locators / text / order -----------------------------------------------------------


def test_text_shifted_to_wrong_page_fails_locator_check() -> None:
    def shift(doc: ParsedDocument) -> ParsedDocument:
        texts = [u.normalized_text for u in doc.units]
        rotated = texts[1:] + texts[:1]
        return _units(
            doc,
            [
                dataclasses.replace(u, normalized_text=t)
                for u, t in zip(doc.units, rotated, strict=True)
            ],
        )

    card = _card(_wrapped(shift))
    assert card["summary"]["locator_valid"] < 1.0
    assert {"quote", "first_line"} <= _checks(card)
    assert {f["category"] for f in card["failures"]} >= {"LOCATOR", "PARSE_MISSING"}


def test_out_of_order_lines_are_counted() -> None:
    def reverse_words(doc: ParsedDocument) -> ParsedDocument:
        def flip(u: SourceUnit) -> SourceUnit:
            parts = u.normalized_text.split(". ")
            return dataclasses.replace(u, normalized_text=". ".join(reversed(parts)))

        return _units(doc, [flip(u) for u in doc.units])

    card = _card(_wrapped(reverse_words))
    assert card["summary"]["reading_order_issues"] >= 1
    assert "reading_order" in _checks(card)


def test_unit_index_gap_fails() -> None:
    def gap(doc: ParsedDocument) -> ParsedDocument:
        return _units(doc, [dataclasses.replace(u, unit_index=u.unit_index * 2) for u in doc.units])

    assert "unit_order" in _checks(_card(_wrapped(gap)))


def test_false_unique_location_for_repeated_text_fails() -> None:
    def dedupe(doc: ParsedDocument) -> ParsedDocument:
        repeated = "The lantern keeper counts every ship that passes the breakwater."
        units = []
        for u in doc.units:
            text = u.normalized_text
            if u.unit_index > 1:
                text = text.replace(repeated, "")
            units.append(dataclasses.replace(u, normalized_text=text))
        return _units(doc, units)

    card = _card(_wrapped(dedupe))
    quote_failures = [f for f in card["failures"] if f["check"].endswith("q-repeated")]
    assert quote_failures
    assert quote_failures[0]["observed"]["status"] == "unique"


# --- negative: outcomes and hashes ---------------------------------------------------------------


def test_accepting_a_corrupt_fixture_fails() -> None:
    def accept_everything(data: bytes) -> ParsedDocument:
        try:
            return parse_pdf(data)
        except IngestError:
            return parse_pdf((FIXTURES_DIR / "books" / "pdf-three-chapters.pdf").read_bytes())

    card = _card(accept_everything)
    outcome_failures = {f["fixture_id"] for f in card["failures"] if f["check"] == "outcome"}
    assert outcome_failures == {
        "pdf-all-images",
        "pdf-encrypted",
        "pdf-corrupt",
        "pdf-bad-signature",
    }


def test_wrong_error_code_fails() -> None:
    def wrong_code(data: bytes) -> ParsedDocument:
        try:
            return parse_pdf(data)
        except IngestError as exc:
            raise IngestError(ErrorCode.PDF_CORRUPT, "everything is corrupt") from exc

    card = _card(wrong_code)
    failing = {f["fixture_id"] for f in card["failures"]}
    assert failing == {"pdf-all-images", "pdf-encrypted", "pdf-bad-signature"}


def test_rejecting_a_valid_fixture_fails() -> None:
    def reject_all(data: bytes) -> ParsedDocument:
        raise IngestError(ErrorCode.PDF_CORRUPT, "no")

    card = _card(reject_all)
    assert card["summary"]["coverage"] == 0.0
    assert any(
        f["fixture_id"] == "pdf-three-chapters" and f["check"] == "outcome"
        for f in card["failures"]
    )


def test_wrong_document_hash_fails() -> None:
    card = _card(_wrapped(lambda d: dataclasses.replace(d, sha256="0" * 64)))
    assert "document_sha256" in _checks(card)
    assert card["summary"]["hash_valid"] < 1.0


def test_intentionally_corrupted_fixture_file_fails(tmp_path: Path) -> None:
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, copy)
    target = copy / "books" / "pdf-three-chapters.pdf"
    target.write_bytes(target.read_bytes()[:-200] + b"\x00" * 200)
    card = _card(parse_pdf, copy)
    failures = [f for f in card["failures"] if f["fixture_id"] == "pdf-three-chapters"]
    assert any(f["check"] == "file_sha256" for f in failures)
    assert card["summary"]["passed"] is False


# --- reports -------------------------------------------------------------------------------------


def test_markdown_lists_failures_with_expected_and_observed() -> None:
    markdown = to_markdown(_card(_wrapped(lambda d: _units(d, []))))
    assert "**FAIL**" in markdown
    assert "## Failures" in markdown
    assert "| pdf-three-chapters | unit_count | PARSE_MISSING | `6` | `0` |" in markdown


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bookscope_eval.source_scorecard", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    card = json.loads((tmp_path / "source-scorecard.json").read_text(encoding="utf-8"))
    assert card["summary"]["passed"] is True
    assert (
        (tmp_path / "source-scorecard.md")
        .read_text(encoding="utf-8")
        .startswith("# Source-integrity")
    )


@pytest.mark.parametrize("key", ["coverage", "locator_valid", "hash_valid", "outcome_correct"])
def test_summary_ratios_are_bounded(key: str) -> None:
    value = _card(parse_pdf)["summary"][key]
    assert value is None or 0.0 <= value <= 1.0
