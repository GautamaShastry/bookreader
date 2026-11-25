"""BS-004: PDF parsing and page locators, asserted against EV-001 gold labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from bookscope_eval.fixtures import FIXTURES_DIR, load_manifest
from bookscope_ingestor.errors import ErrorCode, IngestError
from bookscope_ingestor.locate import find_quote
from bookscope_ingestor.models import ParsedDocument
from bookscope_ingestor.pdf import PdfLimits, parse_pdf

MANIFEST = load_manifest()
PDF_FIXTURES = [f for f in MANIFEST["fixtures"] if f["format"] == "pdf"]
ACCEPTED = [f for f in PDF_FIXTURES if f["expected_outcome"]["status"] == "accepted"]
REJECTED = [f for f in PDF_FIXTURES if f["expected_outcome"]["status"] == "rejected"]


def _data(fixture: dict[str, Any]) -> bytes:
    path: Path = FIXTURES_DIR / fixture["path"]
    return path.read_bytes()


def _parsed(fixture: dict[str, Any]) -> ParsedDocument:
    return parse_pdf(_data(fixture))


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["fixture_id"] for i in items]


def _index(source_id: str) -> int:
    return int(source_id.rsplit(":p", 1)[1])


# --- accepted fixtures: exact locator assertions -----------------------------------------------


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_every_physical_page_is_one_unit_with_gold_status(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    assert [u.unit_index for u in document.units] == [
        u["page_index"] for u in fixture["source_units"]
    ]
    observed = ["unreadable" if u.status == "unreadable" else "readable" for u in document.units]
    assert observed == [u["status"] for u in fixture["source_units"]]


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_page_text_starts_and_ends_with_gold_lines(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    for gold in fixture["source_units"]:
        unit = document.unit(gold["page_index"])
        if gold["status"] == "unreadable":
            assert unit.normalized_text == ""
            assert unit.diagnostics == ("no_extractable_text:graphics_only",)
            continue
        assert unit.normalized_text.startswith(gold["first_line"]), gold["source_id"]
        assert unit.normalized_text.endswith(gold["last_line"]), gold["source_id"]


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_every_gold_quote_resolves_to_its_physical_pages(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    for quote in fixture["quotes"]:
        resolution = find_quote(document, quote["text"])
        expected = tuple(_index(s) for s in quote["expected_source_ids"])
        assert resolution.unit_indexes == expected, quote["quote_id"]
        assert resolution.status == ("ambiguous" if quote["ambiguous"] else "unique")


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_toc_matches_gold_chapters_and_origin(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    level_one = [(t.title, t.unit_index, t.origin) for t in document.toc if t.level == 1]
    expected = [
        (c["title"], _index(c["source_ids"][0]), c["toc_origin"]) for c in fixture["chapters"]
    ]
    assert level_one == expected
    assert document.toc_origin == fixture["chapters"][0]["toc_origin"]


def test_inferred_toc_is_flagged_inferred() -> None:
    document = _parsed(next(f for f in ACCEPTED if f["fixture_id"] == "pdf-no-bookmarks"))
    assert document.toc
    assert all(entry.inferred for entry in document.toc)


def test_page_labels_are_recorded_but_indexes_are_physical() -> None:
    fixture = next(f for f in ACCEPTED if f["fixture_id"] == "pdf-three-chapters")
    document = _parsed(fixture)
    assert [u.page_label for u in document.units] == [
        u["page_label"] for u in fixture["source_units"]
    ]
    assert [u.unit_index for u in document.units] == list(range(6))


def test_reading_order_follows_visual_layout_not_content_stream() -> None:
    fixture = next(f for f in ACCEPTED if f["fixture_id"] == "pdf-out-of-order")
    document = _parsed(fixture)
    for gold in fixture["source_units"]:
        text = document.unit(gold["page_index"]).normalized_text
        positions = [text.index(line) for line in gold["reading_order_lines"]]
        assert positions == sorted(positions), gold["source_id"]


def test_unicode_is_nfkc_normalised() -> None:
    document = _parsed(next(f for f in ACCEPTED if f["fixture_id"] == "pdf-three-chapters"))
    page = document.unit(1).normalized_text
    assert "fishing" in page
    assert "ﬁ" not in page
    assert "Café" in page
    assert "Naïve" in page
    assert "“evening flag”" in page
    assert "—" in page


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_spans_are_ordered_in_bounds_and_cover_text(fixture: dict[str, Any]) -> None:
    for unit in _parsed(fixture).units:
        previous_end = -1
        for span in unit.spans:
            assert previous_end < span.start < span.end <= len(unit.normalized_text)
            previous_end = span.end
        assert (
            " ".join(unit.normalized_text[s.start : s.end] for s in unit.spans)
            == unit.normalized_text
        )


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_parsing_is_deterministic(fixture: dict[str, Any]) -> None:
    assert _parsed(fixture) == _parsed(fixture)


def test_document_identity_is_sha256_of_input() -> None:
    fixture = ACCEPTED[0]
    assert _parsed(fixture).sha256 == fixture["sha256"]


# --- quote resolution never invents a location --------------------------------------------------


def test_quote_spanning_a_page_boundary_is_not_found() -> None:
    document = _parsed(next(f for f in ACCEPTED if f["fixture_id"] == "pdf-three-chapters"))
    end_of_page_0 = document.unit(0).normalized_text[-30:]
    start_of_page_1 = document.unit(1).normalized_text[:30]
    assert find_quote(document, f"{end_of_page_0} {start_of_page_1}").status == "not_found"


def test_absent_quote_is_not_found_and_empty_quote_is_an_error() -> None:
    document = _parsed(ACCEPTED[0])
    assert find_quote(document, "submarines patrol the harbor").status == "not_found"
    with pytest.raises(ValueError, match="empty"):
        find_quote(document, " \n\t ")


def test_quote_is_matched_after_normalisation() -> None:
    document = _parsed(next(f for f in ACCEPTED if f["fixture_id"] == "pdf-three-chapters"))
    resolution = find_quote(document, "The  ﬁshing   fleet returns")
    assert resolution.status == "unique"
    assert resolution.unit_indexes == (1,)


# --- rejections ---------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", REJECTED, ids=_ids(REJECTED))
def test_rejected_fixture_fails_with_gold_error_code(fixture: dict[str, Any]) -> None:
    with pytest.raises(IngestError) as caught:
        _parsed(fixture)
    assert caught.value.code == fixture["expected_outcome"]["error_code"]


def _blank_pdf(pages: int, text: str | None = "x") -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    return bytes(doc.tobytes())


def test_more_than_600_pages_is_rejected() -> None:
    with pytest.raises(IngestError) as caught:
        parse_pdf(_blank_pdf(601))
    assert caught.value.code is ErrorCode.PDF_TOO_MANY_PAGES


def test_exactly_600_pages_is_accepted() -> None:
    assert len(parse_pdf(_blank_pdf(600)).units) == 600


def test_file_over_25_mib_is_rejected_before_parsing() -> None:
    data = b"%PDF-1.7\n" + b"0" * (25 * 1024 * 1024)
    with pytest.raises(IngestError) as caught:
        parse_pdf(data)
    assert caught.value.code is ErrorCode.PDF_TOO_LARGE


def test_limits_are_configurable() -> None:
    with pytest.raises(IngestError) as caught:
        parse_pdf(_blank_pdf(3), PdfLimits(max_pages=2))
    assert caught.value.code is ErrorCode.PDF_TOO_MANY_PAGES


def test_owner_password_only_encryption_is_rejected() -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "restricted")
    aes = pymupdf.PDF_ENCRYPT_AES_256  # type: ignore[attr-defined]  # runtime constant
    data = doc.tobytes(encryption=aes, owner_pw="owner", user_pw="")
    with pytest.raises(IngestError) as caught:
        parse_pdf(bytes(data))
    assert caught.value.code is ErrorCode.PDF_ENCRYPTED


def test_blank_pages_only_is_no_text() -> None:
    with pytest.raises(IngestError) as caught:
        parse_pdf(_blank_pdf(2, text=None))
    assert caught.value.code is ErrorCode.PDF_NO_TEXT


def test_blank_page_in_readable_pdf_is_unreadable_not_dropped() -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "first")
    doc.new_page()
    doc.new_page().insert_text((72, 72), "third")
    document = parse_pdf(bytes(doc.tobytes()))
    assert [u.status for u in document.units] == ["readable", "unreadable", "readable"]
    assert document.unit(1).diagnostics == ("no_extractable_text:blank",)
    assert document.unreadable_units == (1,)


def test_empty_bytes_and_truncated_header_are_rejected() -> None:
    for data in (b"", b"%PD", b"\x89PNG\r\n\x1a\n"):
        with pytest.raises(IngestError) as caught:
            parse_pdf(data)
        assert caught.value.code is ErrorCode.PDF_BAD_SIGNATURE


def test_error_detail_never_contains_book_text() -> None:
    fixture = next(f for f in REJECTED if f["fixture_id"] == "pdf-corrupt")
    with pytest.raises(IngestError) as caught:
        _parsed(fixture)
    assert "harbor" not in str(caught.value).lower()


def test_error_codes_match_ev001_vocabulary() -> None:
    schema_path = Path(FIXTURES_DIR) / "schemas" / "fixture-manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert set(schema["$defs"]["ErrorCode"]["enum"]) == {c.value for c in ErrorCode}
