"""BS-005: safe EPUB parsing and locators, asserted against EV-001 gold labels."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

from bookscope_eval.fixtures import FIXTURES_DIR, load_manifest
from bookscope_eval.source_scorecard import build_scorecard
from bookscope_ingestor.epub import EpubLimits, parse_epub, verified_locator
from bookscope_ingestor.errors import ErrorCode, IngestError
from bookscope_ingestor.locate import find_quote
from bookscope_ingestor.models import ParsedDocument
from bookscope_ingestor.pdf import parse_pdf

MANIFEST = load_manifest()
EPUB_FIXTURES = [f for f in MANIFEST["fixtures"] if f["format"] == "epub"]
ACCEPTED = [f for f in EPUB_FIXTURES if f["expected_outcome"]["status"] == "accepted"]
REJECTED = [f for f in EPUB_FIXTURES if f["expected_outcome"]["status"] == "rejected"]


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["fixture_id"] for i in items]


def _parsed(fixture: dict[str, Any]) -> ParsedDocument:
    return parse_epub((FIXTURES_DIR / fixture["path"]).read_bytes())


def _index(source_id: str) -> int:
    return int(source_id.rsplit(":s", 1)[1])


# --- accepted fixtures ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_spine_documents_are_ordered_units(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    assert [u.href for u in document.units] == [u["spine_href"] for u in fixture["source_units"]]
    assert [u.unit_index for u in document.units] == list(range(len(fixture["source_units"])))
    assert all(u.status == "readable" for u in document.units)


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_unit_text_and_anchors_match_gold(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    for gold in fixture["source_units"]:
        unit = document.unit(_index(gold["source_id"]))
        assert unit.normalized_text.startswith(gold["first_line"])
        assert unit.normalized_text.endswith(gold["last_line"])
        assert [a for a, _ in unit.anchors] == gold["anchors"]
        for excluded in gold.get("excluded_text", []):
            assert excluded not in unit.normalized_text


def test_script_and_style_are_never_extracted() -> None:
    document = _parsed(next(f for f in ACCEPTED if f["fixture_id"] == "epub3-orchard"))
    text = " ".join(u.normalized_text for u in document.units)
    assert "SCRIPT TEXT" not in text
    assert "color: red" not in text


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_toc_entries_resolve_to_gold_spine_and_anchor(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    assert document.toc_origin == fixture["chapters"][0]["toc_origin"]
    observed = [
        (t.title, t.unit_index, t.anchor_id if t.anchor_resolved else None) for t in document.toc
    ]
    expected = [
        (c["title"], _index(c["source_ids"][0]), c["anchor_id"]) for c in fixture["chapters"]
    ]
    assert observed == expected


def test_missing_toc_anchor_is_flagged_not_guessed() -> None:
    fixture = next(f for f in ACCEPTED if f["fixture_id"] == "epub-missing-anchor")
    document = _parsed(fixture)
    entry = document.toc[1]
    assert entry.anchor_id == "no-such-anchor"
    assert entry.anchor_resolved is False
    assert document.diagnostics == ("unresolved_toc_anchor:1:no-such-anchor",)


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_quotes_resolve_to_spine_and_anchor(fixture: dict[str, Any]) -> None:
    document = _parsed(fixture)
    for quote in fixture["quotes"]:
        resolution = find_quote(document, quote["text"])
        expected = tuple(_index(s) for s in quote["expected_source_ids"])
        assert resolution.unit_indexes == expected, quote["quote_id"]
        locator = verified_locator(document, quote["text"])
        if quote["ambiguous"]:
            assert resolution.status == "ambiguous"
            assert locator is None  # ambiguous sources are never shown as verified
        else:
            assert locator is not None
            assert locator.anchor_id == quote["anchor_id"], quote["quote_id"]
            assert locator.spine_href == document.unit(expected[0]).href
            assert locator.text_quote == quote["text"]


def test_epub_locator_matches_source_chunk_schema_shape() -> None:
    document = _parsed(ACCEPTED[0])
    locator = verified_locator(document, "A curved saw removes branches thicker than a thumb.")
    assert locator is not None
    assert locator.as_json() == {
        "kind": "epub",
        "spine_href": "OEBPS/ch2.xhtml",
        "anchor_id": "ch2-tools",
        "normalized_offset": locator.normalized_offset,
        "text_quote": "A curved saw removes branches thicker than a thumb.",
    }


@pytest.mark.parametrize("fixture", ACCEPTED, ids=_ids(ACCEPTED))
def test_epub_parsing_is_deterministic(fixture: dict[str, Any]) -> None:
    assert _parsed(fixture) == _parsed(fixture)


def test_headings_are_marked_on_spans() -> None:
    unit = _parsed(ACCEPTED[0]).unit(0)
    levels = [s.heading_level for s in unit.spans]
    assert levels[0] == 1
    assert 2 in levels


# --- rejections ----------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", REJECTED, ids=_ids(REJECTED))
def test_rejected_fixture_fails_with_gold_code(fixture: dict[str, Any]) -> None:
    with pytest.raises(IngestError) as caught:
        _parsed(fixture)
    assert caught.value.code == fixture["expected_outcome"]["error_code"]


CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    '<rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def _opf(spine: str = '<itemref idref="c1"/>', extra_items: str = "") -> str:
    return (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title></metadata>'
        '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        f"{extra_items}</manifest><spine>{spine}</spine></package>"
    )


def _xhtml(body: str) -> str:
    return f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'


def _epub(
    *,
    files: dict[str, bytes | str] | None = None,
    mimetype: bytes = b"application/epub+zip",
    mimetype_first: bool = True,
    compress: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    content: dict[str, bytes | str] = {
        "META-INF/container.xml": CONTAINER,
        "OPS/book.opf": _opf(),
        "OPS/c1.xhtml": _xhtml("<h1 id='a'>One</h1><p>Plain readable text.</p>"),
    }
    content.update(files or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if mimetype_first:
            zf.writestr(zipfile.ZipInfo("mimetype"), mimetype)
        for name, data in content.items():
            zf.writestr(name, data, compress_type=compress)
        if not mimetype_first:
            zf.writestr("mimetype", mimetype)
    return buffer.getvalue()


def test_minimal_generated_epub_parses() -> None:
    document = parse_epub(_epub())
    assert document.units[0].normalized_text == "One Plain readable text."
    assert document.toc_origin == "none"
    assert document.title == "T"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"files": {"/abs/evil.xhtml": "x"}}, ErrorCode.EPUB_UNSAFE_PATH),
        ({"files": {"OPS\\..\\evil.xhtml": "x"}}, ErrorCode.EPUB_UNSAFE_PATH),
        ({"files": {"C:/evil.xhtml": "x"}}, ErrorCode.EPUB_UNSAFE_PATH),
        ({"files": {"OPS/a/../../../evil": "x"}}, ErrorCode.EPUB_UNSAFE_PATH),
        ({"mimetype_first": False}, ErrorCode.EPUB_BAD_CONTAINER),
        ({"mimetype": b"text/plain"}, ErrorCode.EPUB_BAD_CONTAINER),
        ({"files": {"META-INF/container.xml": "<container/>"}}, ErrorCode.EPUB_MALFORMED_PACKAGE),
        (
            {"files": {"OPS/book.opf": _opf(spine='<itemref idref="nope"/>')}},
            ErrorCode.EPUB_MALFORMED_PACKAGE,
        ),
        ({"files": {"OPS/book.opf": _opf(spine="")}}, ErrorCode.EPUB_MISSING_SPINE),
        ({"files": {"META-INF/rights.xml": "<rights/>"}}, ErrorCode.EPUB_ENCRYPTED),
        (
            {"files": {"OPS/c1.xhtml": _xhtml("<p>  </p><script>x()</script>")}},
            ErrorCode.EPUB_NO_TEXT,
        ),
        (
            {
                "files": {
                    "OPS/c1.xhtml": (
                        '<!DOCTYPE html [<!ENTITY a "aaaa">]><html><body>&a;</body></html>'
                    )
                }
            },
            ErrorCode.EPUB_FORBIDDEN_XML,
        ),
        (
            {
                "files": {
                    "OPS/c1.xhtml": '<!DOCTYPE x [<!ENTITY e SYSTEM "http://example.invalid/x">]><x>&e;</x>'
                }
            },
            ErrorCode.EPUB_FORBIDDEN_XML,
        ),
    ],
)
def test_generated_hostile_or_broken_package_is_rejected(
    kwargs: dict[str, Any], code: ErrorCode
) -> None:
    with pytest.raises(IngestError) as caught:
        parse_epub(_epub(**kwargs))
    assert caught.value.code is code


def test_not_a_zip_is_bad_container() -> None:
    with pytest.raises(IngestError) as caught:
        parse_epub(b"%PDF-1.7 definitely not a zip")
    assert caught.value.code is ErrorCode.EPUB_BAD_CONTAINER


def test_billion_laughs_is_rejected() -> None:
    laughs = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><lolz>&lol2;</lolz>'
    )
    with pytest.raises(IngestError) as caught:
        parse_epub(_epub(files={"OPS/book.opf": laughs}))
    assert caught.value.code is ErrorCode.EPUB_FORBIDDEN_XML


def test_font_obfuscation_is_allowed_but_content_encryption_is_drm() -> None:
    def encryption(algorithm: str, uri: str) -> str:
        return (
            '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
            f'<enc:EncryptionMethod Algorithm="{algorithm}"/>'
            f'<enc:CipherData><enc:CipherReference URI="{uri}"/></enc:CipherData>'
            "</enc:EncryptedData></encryption>"
        )

    fonts = encryption("http://www.idpf.org/2008/embedding", "OPS/font.otf")
    assert parse_epub(_epub(files={"META-INF/encryption.xml": fonts})).units
    drm = encryption("http://www.w3.org/2001/04/xmlenc#aes256-cbc", "OPS/c1.xhtml")
    with pytest.raises(IngestError) as caught:
        parse_epub(_epub(files={"META-INF/encryption.xml": drm}))
    assert caught.value.code is ErrorCode.EPUB_ENCRYPTED


@pytest.mark.parametrize(
    ("limits", "files"),
    [
        (EpubLimits(max_entries=3), None),
        (EpubLimits(max_entry_bytes=1000), {"OPS/big.bin": b"a" * 5000}),
        (
            EpubLimits(max_total_bytes=2000),
            {"OPS/a.bin": b"a" * 900, "OPS/b.bin": b"b" * 900, "OPS/c.bin": b"c" * 900},
        ),
        (EpubLimits(ratio_floor_bytes=1000, max_ratio=10), {"OPS/zeros.bin": b"\x00" * 50_000}),
    ],
)
def test_expansion_limits_are_enforced(
    limits: EpubLimits, files: dict[str, bytes | str] | None
) -> None:
    with pytest.raises(IngestError) as caught:
        parse_epub(_epub(files=files), limits)
    assert caught.value.code is ErrorCode.EPUB_EXPANSION_LIMIT


def test_file_over_25_mib_is_rejected_before_unzipping() -> None:
    with pytest.raises(IngestError) as caught:
        parse_epub(b"PK" + b"\x00" * (25 * 1024 * 1024))
    assert caught.value.code is ErrorCode.EPUB_TOO_LARGE


def test_malformed_chapter_is_unreadable_unit_not_dropped() -> None:
    opf = _opf(
        spine='<itemref idref="c1"/><itemref idref="c2"/>',
        extra_items='<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>',
    )
    document = parse_epub(_epub(files={"OPS/book.opf": opf, "OPS/c2.xhtml": "<html><body><p>oops"}))
    assert [u.status for u in document.units] == ["readable", "unreadable"]
    assert document.units[1].diagnostics == ("malformed_xhtml",)


def test_non_text_spine_item_is_unreadable_unit() -> None:
    opf = _opf(
        spine='<itemref idref="c1"/><itemref idref="img"/>',
        extra_items='<item id="img" href="p.png" media-type="image/png"/>',
    )
    document = parse_epub(_epub(files={"OPS/book.opf": opf, "OPS/p.png": b"\x89PNG"}))
    assert document.units[1].status == "unreadable"
    assert document.units[1].diagnostics == ("non_text_spine_item:image/png",)


def test_external_toc_links_are_ignored_not_fetched() -> None:
    nav = _xhtml(
        '<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc"><ol>'
        '<li><a href="https://example.invalid/steal">Remote</a></li>'
        '<li><a href="c1.xhtml#a">One</a></li></ol></nav>'
    )
    opf = _opf(
        extra_items=(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    )
    document = parse_epub(_epub(files={"OPS/book.opf": opf, "OPS/nav.xhtml": nav}))
    assert [(t.title, t.unit_index, t.anchor_id) for t in document.toc] == [("One", 0, "a")]


def test_missing_manifest_file_is_malformed() -> None:
    opf = _opf(
        spine='<itemref idref="c1"/><itemref idref="c2"/>',
        extra_items='<item id="c2" href="missing.xhtml" media-type="application/xhtml+xml"/>',
    )
    with pytest.raises(IngestError) as caught:
        parse_epub(_epub(files={"OPS/book.opf": opf}))
    assert caught.value.code is ErrorCode.EPUB_MALFORMED_PACKAGE


def test_scorecard_now_evaluates_every_fixture() -> None:
    card = build_scorecard({"pdf": parse_pdf, "epub": parse_epub})
    summary = card["summary"]
    assert summary["fixtures_not_evaluated"] == []
    assert summary["passed"] is True, card["failures"]
    assert summary["coverage"] == 1.0
    assert summary["locator_valid"] == 1.0


def test_nested_nav_entries_keep_their_level() -> None:
    nav = _xhtml(
        '<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc"><ol>'
        '<li><a href="c1.xhtml#a">One</a><ol><li><a href="c1.xhtml#a">One A</a></li></ol></li>'
        "</ol></nav>"
    )
    opf = _opf(
        extra_items=(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    )
    document = parse_epub(_epub(files={"OPS/book.opf": opf, "OPS/nav.xhtml": nav}))
    assert [(t.title, t.level) for t in document.toc] == [("One", 1), ("One A", 2)]
