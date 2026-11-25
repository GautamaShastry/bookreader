"""Text-PDF adapter (BS-004): every physical page becomes exactly one ordered source unit.

Rules (spec 04 §1-2, spec 15):

* accept only text-selectable, unencrypted PDFs, <= 25 MiB and <= 600 physical pages;
* reject bad signatures, repaired/corrupt files, encryption, and PDFs with no extractable text;
* never OCR; a page without extractable text is kept as an ``unreadable`` unit, not dropped;
* page locators are 0-based physical indexes; printed labels are informational only;
* TOC comes from PDF bookmarks; without bookmarks it is inferred from large-font headings and
  flagged ``inferred`` (never presented as author structure).
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass
from typing import Any

import pymupdf

from bookscope_ingestor.errors import ErrorCode, IngestError
from bookscope_ingestor.models import ParsedDocument, SourceUnit, TextSpan, TocEntry, UnitStatus
from bookscope_ingestor.normalize import normalize_text

MiB = 1024 * 1024
EXTRACTION_VERSION = f"pdf-pymupdf-{pymupdf.VersionBind}/1"
_TEXT_BLOCK = 0
_REPLACEMENT = "�"


@dataclass(frozen=True)
class PdfLimits:
    max_bytes: int = 25 * MiB
    max_pages: int = 600
    header_window: int = 1024  # PDF spec allows the %PDF- header within the first 1 KiB
    low_confidence_replacement_ratio: float = 0.05
    heading_size_ratio: float = 1.4


def parse_pdf(data: bytes, limits: PdfLimits = PdfLimits()) -> ParsedDocument:
    if len(data) > limits.max_bytes:
        raise IngestError(ErrorCode.PDF_TOO_LARGE, f"{len(data)} bytes > {limits.max_bytes}")
    if b"%PDF-" not in data[: limits.header_window]:
        raise IngestError(ErrorCode.PDF_BAD_SIGNATURE, "missing %PDF- header")
    document = _open(data)
    try:
        return _parse_open(document, data, limits)
    finally:
        document.close()


def _open(data: bytes) -> Any:
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several unrelated exception types
        raise IngestError(ErrorCode.PDF_CORRUPT, f"cannot open: {type(exc).__name__}") from exc
    finally:
        pymupdf.TOOLS.mupdf_display_errors(True)
    # Owner-password-only PDFs open without a password and report is_encrypted=False after
    # authentication, so also check the trailer's encryption dictionary.
    if document.needs_pass or document.is_encrypted or (document.metadata or {}).get("encryption"):
        document.close()
        raise IngestError(ErrorCode.PDF_ENCRYPTED, "PDF is encrypted")
    if document.is_repaired:
        document.close()
        raise IngestError(ErrorCode.PDF_CORRUPT, "cross-reference table is damaged")
    return document


def _parse_open(document: Any, data: bytes, limits: PdfLimits) -> ParsedDocument:
    if document.page_count > limits.max_pages:
        raise IngestError(
            ErrorCode.PDF_TOO_MANY_PAGES, f"{document.page_count} pages > {limits.max_pages}"
        )
    if document.page_count == 0:
        raise IngestError(ErrorCode.PDF_NO_TEXT, "PDF has no pages")

    units = tuple(_page_unit(document[i], i, limits) for i in range(document.page_count))
    if not any(u.is_readable for u in units):
        raise IngestError(ErrorCode.PDF_NO_TEXT, "no page has extractable text (OCR unsupported)")

    toc, origin, diagnostics = _bookmarks(document)
    if not toc:
        toc = _inferred_toc(document, units, limits)
        origin = "inferred" if toc else "none"
    title = (document.metadata or {}).get("title") or None
    return ParsedDocument(
        format="pdf",
        sha256=hashlib.sha256(data).hexdigest(),
        extraction_version=EXTRACTION_VERSION,
        units=units,
        toc=tuple(toc),
        toc_origin=origin,
        title=title,
        diagnostics=tuple(diagnostics),
    )


def _page_unit(page: Any, index: int, limits: PdfLimits) -> SourceUnit:
    blocks = [
        b[4]
        for b in page.get_text("blocks", sort=True)
        if b[6] == _TEXT_BLOCK and normalize_text(b[4])
    ]
    parts: list[str] = []
    spans: list[TextSpan] = []
    cursor = 0
    for raw in blocks:
        text = normalize_text(raw)
        if parts:
            cursor += 1  # joining space
        spans.append(TextSpan(cursor, cursor + len(text)))
        parts.append(text)
        cursor += len(text)
    normalized = " ".join(parts)
    diagnostics: list[str] = []
    status: UnitStatus
    if not normalized:
        status = "unreadable"
        if page.get_images() or page.get_drawings():
            diagnostics.append("no_extractable_text:graphics_only")
        else:
            diagnostics.append("no_extractable_text:blank")
    elif normalized.count(_REPLACEMENT) / len(normalized) > limits.low_confidence_replacement_ratio:
        status = "low_confidence"
        diagnostics.append("replacement_characters")
    else:
        status = "readable"
    label = page.get_label() or None
    return SourceUnit(
        unit_index=index,
        status=status,
        normalized_text=normalized,
        spans=tuple(spans),
        page_label=label,
        diagnostics=tuple(diagnostics),
    )


def _bookmarks(document: Any) -> tuple[list[TocEntry], Any, list[str]]:
    entries: list[TocEntry] = []
    diagnostics: list[str] = []
    for level, title, page_number, *_ in document.get_toc(simple=True):
        clean = normalize_text(title)
        if not 1 <= page_number <= document.page_count:
            diagnostics.append(f"bookmark_without_valid_page:level{level}")
            continue
        if clean:
            entries.append(TocEntry(level, clean, page_number - 1, "bookmark"))
    return entries, ("bookmark" if entries else "none"), diagnostics


def _inferred_toc(
    document: Any, units: tuple[SourceUnit, ...], limits: PdfLimits
) -> list[TocEntry]:
    """Treat the first line of a page as a heading if its font is clearly larger than body text."""
    sizes: list[float] = []
    first_lines: dict[int, tuple[float, str]] = {}
    for unit in units:
        if not unit.is_readable:
            continue
        page_dict = document[unit.unit_index].get_text("dict", sort=True)
        for block in page_dict["blocks"]:
            for line in block.get("lines", []):
                text = normalize_text("".join(s["text"] for s in line["spans"]))
                if not text:
                    continue
                size = max(s["size"] for s in line["spans"])
                sizes.append(size)
                first_lines.setdefault(unit.unit_index, (size, text))
    if not sizes:
        return []
    body = statistics.median(sizes)
    return [
        TocEntry(1, text, index, "inferred")
        for index, (size, text) in sorted(first_lines.items())
        if size >= body * limits.heading_size_ratio
    ]
