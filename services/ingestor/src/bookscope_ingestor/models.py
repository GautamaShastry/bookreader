"""Typed parser output shared by the PDF (BS-004) and EPUB (BS-005) adapters.

A *source unit* is one physical PDF page or one EPUB spine document: the smallest unit a citation
may point at and that chunks may never cross. Every unit of the input appears exactly once, in
reading order, with an explicit status; nothing is silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

UnitStatus = Literal["readable", "low_confidence", "unreadable"]
TocOrigin = Literal["bookmark", "inferred", "nav", "ncx", "none"]


@dataclass(frozen=True)
class PdfLocator:
    page_index: int  # 0-based physical page
    page_label: str | None  # printed label; informational, never authoritative
    kind: Literal["pdf"] = "pdf"

    def as_json(self) -> dict[str, object]:
        return {"kind": self.kind, "page_index": self.page_index, "page_label": self.page_label}


@dataclass(frozen=True)
class EpubLocator:
    spine_href: str
    anchor_id: str | None
    text_quote: str
    normalized_offset: int | None
    kind: Literal["epub"] = "epub"

    def as_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "spine_href": self.spine_href,
            "anchor_id": self.anchor_id,
            "normalized_offset": self.normalized_offset,
            "text_quote": self.text_quote,
        }


@dataclass(frozen=True)
class TextSpan:
    """A block of text inside a unit; offsets index the unit's ``normalized_text``."""

    start: int
    end: int
    anchor_id: str | None = None  # EPUB element id at/above this block, if any
    heading_level: int | None = None


@dataclass(frozen=True)
class SourceUnit:
    unit_index: int
    status: UnitStatus
    normalized_text: str
    spans: tuple[TextSpan, ...]
    href: str | None = None  # EPUB spine document path inside the package
    page_label: str | None = None
    anchors: tuple[tuple[str, int], ...] = ()  # (anchor_id, normalized offset), EPUB only
    diagnostics: tuple[str, ...] = ()

    @property
    def is_readable(self) -> bool:
        return self.status != "unreadable"


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    unit_index: int
    origin: TocOrigin
    anchor_id: str | None = None
    anchor_resolved: bool = True

    @property
    def inferred(self) -> bool:
        return self.origin == "inferred"


@dataclass(frozen=True)
class ParsedDocument:
    format: Literal["pdf", "epub"]
    sha256: str
    extraction_version: str
    units: tuple[SourceUnit, ...]
    toc: tuple[TocEntry, ...]
    toc_origin: TocOrigin
    title: str | None = None
    diagnostics: tuple[str, ...] = field(default=())

    @property
    def unreadable_units(self) -> tuple[int, ...]:
        return tuple(u.unit_index for u in self.units if u.status == "unreadable")

    def unit(self, index: int) -> SourceUnit:
        return self.units[index]
