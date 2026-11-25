"""Canonical chapters, sections and chunks (BS-006, spec 04 §3).

* A *section* is the part of one chapter inside one source unit (PDF page / EPUB spine document),
  further split at level-2 TOC entries; chunks never cross a unit or a section.
* Chunks are packed paragraph-first (one parser block = one paragraph) up to ``max_tokens``;
  oversized paragraphs are split at sentence, then word, then character boundaries.
* No overlap: consecutive chunks of a unit are separated by exactly the one joining space of the
  normalised text (or nothing, for a forced character split), so every unit can be reconstructed
  exactly from its chunks.
* ``chunk_id = SHA256(book_version_id|section_id|start|end|content_sha256)[:32]`` (spec 04 §3).
* Token counts are an approximation (``ceil(chars / 4)``) until a real tokenizer is benchmarked.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from bookscope_ingestor.models import EpubLocator, ParsedDocument, PdfLocator, SourceUnit, TocEntry

CHUNKER_VERSION = "chunker/1"
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s")


def approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class ChunkingConfig:
    max_tokens: int = 600
    target_tokens: int = 250  # pack until at least this, never beyond max_tokens
    quote_chars: int = 200  # EPUB locator text_quote length

    def __post_init__(self) -> None:
        if not 0 < self.target_tokens <= self.max_tokens:
            raise ValueError("require 0 < target_tokens <= max_tokens")


@dataclass(frozen=True)
class BookScope:
    """Server-derived identity; never taken from a client or a model."""

    owner_id: str
    book_id: str
    book_version_id: str


@dataclass(frozen=True)
class Section:
    section_id: str
    chapter_id: str
    unit_index: int
    start: int
    end: int
    title: str | None


@dataclass(frozen=True)
class Chapter:
    chapter_id: str
    ordinal: int
    title: str
    inferred: bool
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    owner_id: str
    book_id: str
    book_version_id: str
    chapter_id: str
    section_id: str
    heading_path: tuple[str, ...]
    reading_order: int
    unit_index: int
    text: str
    content_sha256: str
    start_offset: int
    end_offset: int
    source_locator: dict[str, Any]
    source_quality: str
    extraction_version: str

    def to_json(self) -> dict[str, Any]:
        """Serialise as ``specs/schemas/source-chunk.schema.json`` (CanonicalSourceChunk)."""
        return {
            "chunk_id": self.chunk_id,
            "owner_id": self.owner_id,
            "book_id": self.book_id,
            "book_version_id": self.book_version_id,
            "chapter_id": self.chapter_id,
            "section_id": self.section_id,
            "heading_path": list(self.heading_path),
            "reading_order": self.reading_order,
            "text": self.text,
            "content_sha256": self.content_sha256,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "source_locator": self.source_locator,
            "source_quality": self.source_quality,
            "extraction_version": self.extraction_version,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], unit_index: int) -> Chunk:
        return cls(
            chunk_id=data["chunk_id"],
            owner_id=data["owner_id"],
            book_id=data["book_id"],
            book_version_id=data["book_version_id"],
            chapter_id=data["chapter_id"],
            section_id=data["section_id"],
            heading_path=tuple(data.get("heading_path", [])),
            reading_order=data["reading_order"],
            unit_index=unit_index,
            text=data["text"],
            content_sha256=data["content_sha256"],
            start_offset=data["start_offset"],
            end_offset=data["end_offset"],
            source_locator=data["source_locator"],
            source_quality=data.get("source_quality", "readable"),
            extraction_version=data.get("extraction_version", ""),
        )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_chunk_id(
    book_version_id: str, section_id: str, start: int, end: int, content_sha256: str
) -> str:
    material = f"{book_version_id}|{section_id}|{start}|{end}|{content_sha256}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


# --- chapters and sections ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Boundary:
    unit_index: int
    offset: int
    title: str
    level: int
    inferred: bool


def _boundary(entry: TocEntry, document: ParsedDocument) -> _Boundary:
    unit = document.unit(entry.unit_index)
    offset = 0
    if entry.anchor_id and entry.anchor_resolved:
        offset = dict(unit.anchors).get(entry.anchor_id, 0)
    return _Boundary(entry.unit_index, offset, entry.title, entry.level, entry.inferred)


def build_structure(document: ParsedDocument) -> tuple[tuple[Chapter, ...], bool]:
    """Return (ordered chapters, structure_reliable).

    Chapters come from level-1 TOC entries in reading order. Text before the first chapter is
    an inferred front-matter chapter. Without a TOC the whole book is one inferred chapter and
    the structure is reported unreliable (full-book summaries must refuse it, spec 14 §2).
    """
    entries = sorted(
        (_boundary(e, document) for e in document.toc),
        key=lambda b: (b.unit_index, b.offset, b.level),
    )
    chapters_at = _dedupe([b for b in entries if b.level == 1])
    sections_at = _dedupe([b for b in entries if b.level == 2])
    reliable = bool(chapters_at) and document.toc_origin in {"bookmark", "nav", "ncx"}
    if not chapters_at or (chapters_at[0].unit_index, chapters_at[0].offset) != (0, 0):
        title = "Front matter" if chapters_at else (document.title or "Document")
        chapters_at.insert(0, _Boundary(0, 0, title, 1, True))

    positions = [(b.unit_index, b.offset) for b in chapters_at]
    chapters: list[Chapter] = []
    for ordinal, boundary in enumerate(chapters_at, start=1):
        chapter_id = f"ch{ordinal:03d}"
        start = positions[ordinal - 1]
        end = positions[ordinal] if ordinal < len(positions) else (len(document.units), 0)
        cuts = [
            (b.unit_index, b.offset, b.title)
            for b in sections_at
            if start < (b.unit_index, b.offset) < end
        ]
        sections = _sections(document, chapter_id, start, end, cuts)
        chapters.append(
            Chapter(chapter_id, ordinal, boundary.title, boundary.inferred, tuple(sections))
        )
    return tuple(chapters), reliable


def _dedupe(boundaries: list[_Boundary]) -> list[_Boundary]:
    seen: set[tuple[int, int]] = set()
    out = []
    for b in boundaries:
        if (b.unit_index, b.offset) not in seen:
            seen.add((b.unit_index, b.offset))
            out.append(b)
    return out


def _sections(
    document: ParsedDocument,
    chapter_id: str,
    start: tuple[int, int],
    end: tuple[int, int],
    cuts: list[tuple[int, int, str]],
) -> list[Section]:
    sections: list[Section] = []
    title: str | None = None
    cut_iter = iter(cuts)
    next_cut = next(cut_iter, None)
    last_unit = end[0] if end[1] > 0 else end[0] - 1
    for unit_index in range(start[0], last_unit + 1):
        unit = document.unit(unit_index)
        lo = start[1] if unit_index == start[0] else 0
        hi = end[1] if unit_index == end[0] else len(unit.normalized_text)
        points = [lo]
        titles = [title]
        while next_cut is not None and next_cut[0] == unit_index:
            points.append(next_cut[1])
            title = next_cut[2]
            titles.append(title)
            next_cut = next(cut_iter, None)
        points.append(hi)
        for i in range(len(points) - 1):
            a, b = _trim(unit.normalized_text, points[i], points[i + 1])
            if a < b or (not unit.normalized_text and i == 0):
                n = len(sections) + 1
                sections.append(
                    Section(f"{chapter_id}.s{n:03d}", chapter_id, unit_index, a, b, titles[i])
                )
    return sections


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a] == " ":
        a += 1
    while b > a and text[b - 1] == " ":
        b -= 1
    return a, b


# --- chunks ---------------------------------------------------------------------------------------


def _pieces(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into pieces <= max_chars: sentence, word, then char boundary."""
    if end - start <= max_chars:
        return [(start, end)]
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_chars:
        window = text[cursor : cursor + max_chars + 1]
        cut = -1
        for match in _SENTENCE_END.finditer(window):
            cut = match.start()
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            pieces.append((cursor, cursor + max_chars))  # forced character split
            cursor += max_chars
            continue
        pieces.append((cursor, cursor + cut))
        cursor += cut + 1  # skip the joining space
    pieces.append((cursor, end))
    return pieces


def _paragraphs(unit: SourceUnit, section: Section) -> list[tuple[int, int]]:
    paragraphs = []
    for span in unit.spans:
        a, b = max(span.start, section.start), min(span.end, section.end)
        if a < b:
            paragraphs.append(_trim(unit.normalized_text, a, b))
    covered = sum(b - a for a, b in paragraphs)
    if not paragraphs or covered == 0:
        return [(section.start, section.end)] if section.start < section.end else []
    return paragraphs


def _locator(
    document: ParsedDocument, unit: SourceUnit, start: int, text: str, cfg: ChunkingConfig
) -> dict[str, Any]:
    if document.format == "pdf":
        return PdfLocator(page_index=unit.unit_index, page_label=unit.page_label).as_json()
    anchor = None
    for anchor_id, offset in unit.anchors:
        if offset <= start:
            anchor = anchor_id
    return EpubLocator(
        spine_href=unit.href or "",
        anchor_id=anchor,
        text_quote=text[: cfg.quote_chars],
        normalized_offset=start,
    ).as_json()


def build_chunks(
    document: ParsedDocument,
    scope: BookScope,
    chapters: tuple[Chapter, ...],
    config: ChunkingConfig | None = None,
) -> tuple[Chunk, ...]:
    config = config or ChunkingConfig()
    max_chars = config.max_tokens * 4
    target_chars = config.target_tokens * 4
    chunks: list[Chunk] = []
    for chapter in chapters:
        for section in chapter.sections:
            unit = document.unit(section.unit_index)
            if not unit.is_readable or section.start >= section.end:
                continue
            pieces: list[tuple[int, int]] = []
            for a, b in _paragraphs(unit, section):
                pieces.extend(_pieces(unit.normalized_text, a, b, max_chars))
            groups: list[tuple[int, int]] = []
            for a, b in pieces:
                if groups:
                    ga, gb = groups[-1]
                    joined = b - ga
                    if gb - ga < target_chars and joined <= max_chars and a >= gb:
                        groups[-1] = (ga, b)
                        continue
                groups.append((a, b))
            heading = (chapter.title,) + ((section.title,) if section.title else ())
            for a, b in groups:
                text = unit.normalized_text[a:b]
                digest = sha256_text(text)
                chunks.append(
                    Chunk(
                        chunk_id=make_chunk_id(
                            scope.book_version_id, section.section_id, a, b, digest
                        ),
                        owner_id=scope.owner_id,
                        book_id=scope.book_id,
                        book_version_id=scope.book_version_id,
                        chapter_id=chapter.chapter_id,
                        section_id=section.section_id,
                        heading_path=heading,
                        reading_order=len(chunks),
                        unit_index=unit.unit_index,
                        text=text,
                        content_sha256=digest,
                        start_offset=a,
                        end_offset=b,
                        source_locator=_locator(document, unit, a, text, config),
                        source_quality="low_confidence"
                        if unit.status == "low_confidence"
                        else "readable",
                        extraction_version=document.extraction_version,
                    )
                )
    return tuple(chunks)
