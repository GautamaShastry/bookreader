"""Authoritative full-book manifest ("ledger") and its integrity verifier (BS-006).

The ledger is the deterministic traversal order for chapter and full-book summaries (spec 04 v1.4,
spec 14 §2): every source unit appears exactly once with its status; every readable character is
covered by exactly one chunk; unreadable units are listed explicitly (never silently omitted).
``manifest_sha256`` is the SHA-256 of the canonical JSON of the ledger without that field.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from bookscope_ingestor.chunking import (
    CHUNKER_VERSION,
    BookScope,
    Chapter,
    Chunk,
    ChunkingConfig,
    build_chunks,
    build_structure,
    make_chunk_id,
    sha256_text,
)
from bookscope_ingestor.models import ParsedDocument

LEDGER_VERSION = "ledger/1"


class LedgerError(Exception):
    """Integrity failure. Codes: BOOK_LEDGER_GAP, HASH_MISMATCH, SCOPE_MISMATCH, LEDGER_INVALID."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CanonicalBook:
    ledger: dict[str, Any]
    chunks: tuple[Chunk, ...]


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _manifest_hash(ledger: dict[str, Any]) -> str:
    body = {k: v for k, v in ledger.items() if k != "manifest_sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def cache_identity(source_sha256: str, extraction_version: str) -> str:
    """Content identity of derived canonical data: same bytes + same pipeline => same artifacts."""
    material = f"{source_sha256}|{extraction_version}|{CHUNKER_VERSION}|{LEDGER_VERSION}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_canonical_book(
    document: ParsedDocument, scope: BookScope, config: ChunkingConfig | None = None
) -> CanonicalBook:
    config = config or ChunkingConfig()
    chapters, reliable = build_structure(document)
    chunks = build_chunks(document, scope, chapters, config)
    return CanonicalBook(_ledger(document, scope, chapters, chunks, reliable, config), chunks)


def _ledger(
    document: ParsedDocument,
    scope: BookScope,
    chapters: tuple[Chapter, ...],
    chunks: tuple[Chunk, ...],
    reliable: bool,
    config: ChunkingConfig,
) -> dict[str, Any]:
    by_section: dict[str, list[str]] = {}
    for chunk in chunks:
        by_section.setdefault(chunk.section_id, []).append(chunk.chunk_id)
    unit_chapters: dict[int, list[str]] = {}
    chapter_rows: list[dict[str, Any]] = []
    for chapter in chapters:
        sections = []
        for section in chapter.sections:
            unit = document.unit(section.unit_index)
            unit_chapters.setdefault(section.unit_index, [])
            if chapter.chapter_id not in unit_chapters[section.unit_index]:
                unit_chapters[section.unit_index].append(chapter.chapter_id)
            sections.append(
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "unit_index": section.unit_index,
                    "start": section.start,
                    "end": section.end,
                    "status": unit.status,
                    "chunk_ids": by_section.get(section.section_id, []),
                }
            )
        chapter_rows.append(
            {
                "chapter_id": chapter.chapter_id,
                "ordinal": chapter.ordinal,
                "title": chapter.title,
                "inferred": chapter.inferred,
                "unit_indexes": sorted({s.unit_index for s in chapter.sections}),
                "sections": sections,
            }
        )
    units: list[dict[str, Any]] = [
        {
            "unit_index": u.unit_index,
            "status": u.status,
            "char_count": len(u.normalized_text),
            "text_sha256": sha256_text(u.normalized_text),
            "chapter_ids": unit_chapters.get(u.unit_index, []),
            "chunk_ids": [c.chunk_id for c in chunks if c.unit_index == u.unit_index],
            "diagnostics": list(u.diagnostics),
        }
        for u in document.units
    ]
    ledger: dict[str, Any] = {
        "ledger_version": LEDGER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "chunking": {"max_tokens": config.max_tokens, "target_tokens": config.target_tokens},
        "owner_id": scope.owner_id,
        "book_id": scope.book_id,
        "book_version_id": scope.book_version_id,
        "format": document.format,
        "source_sha256": document.sha256,
        "extraction_version": document.extraction_version,
        "cache_identity": cache_identity(document.sha256, document.extraction_version),
        "structure": {"toc_origin": document.toc_origin, "reliable": reliable},
        "chapters": chapter_rows,
        "units": units,
        "chunk_order": [c.chunk_id for c in chunks],
        "totals": {
            "units": len(units),
            "readable_units": sum(u["status"] != "unreadable" for u in units),
            "unreadable_units": sum(u["status"] == "unreadable" for u in units),
            "chapters": len(chapter_rows),
            "sections": sum(len(c["sections"]) for c in chapter_rows),
            "chunks": len(chunks),
            "readable_chars": sum(u["char_count"] for u in units),
        },
    }
    ledger["manifest_sha256"] = _manifest_hash(ledger)
    return ledger


def reconstruct_unit(chunks: Iterable[Chunk], unit_index: int) -> str:
    """Rebuild a unit's normalised text from its chunks using their offsets."""
    parts: list[str] = []
    cursor: int | None = None
    for chunk in sorted(
        (c for c in chunks if c.unit_index == unit_index), key=lambda c: c.start_offset
    ):
        if cursor is not None:
            parts.append(" " * (chunk.start_offset - cursor))
        parts.append(chunk.text)
        cursor = chunk.end_offset
    return "".join(parts)


def verify_canonical_book(book: CanonicalBook, scope: BookScope) -> None:
    """Raise LedgerError unless ledger + chunks are complete, untampered and in ``scope``."""
    ledger, chunks = book.ledger, book.chunks
    if ledger.get("manifest_sha256") != _manifest_hash(ledger):
        raise LedgerError("HASH_MISMATCH", "ledger manifest_sha256 does not match its contents")
    for key in ("owner_id", "book_id", "book_version_id"):
        if ledger.get(key) != getattr(scope, key):
            raise LedgerError("SCOPE_MISMATCH", f"ledger {key} is not the authorized scope")

    order = ledger["chunk_order"]
    duplicates = [cid for cid, n in Counter(order).items() if n > 1]
    if duplicates:
        raise LedgerError("LEDGER_INVALID", f"chunk listed twice: {duplicates[0]}")
    by_id = {c.chunk_id: c for c in chunks}
    if len(by_id) != len(chunks):
        raise LedgerError("LEDGER_INVALID", "duplicate chunk objects")
    missing = [cid for cid in order if cid not in by_id]
    if missing:
        raise LedgerError("BOOK_LEDGER_GAP", f"chunk missing: {missing[0]}")
    extra = sorted(set(by_id) - set(order))
    if extra:
        raise LedgerError("LEDGER_INVALID", f"chunk not in ledger: {extra[0]}")

    for position, cid in enumerate(order):
        chunk = by_id[cid]
        for key in ("owner_id", "book_id", "book_version_id"):
            if getattr(chunk, key) != getattr(scope, key):
                raise LedgerError("SCOPE_MISMATCH", f"chunk {cid} has foreign {key}")
        if sha256_text(chunk.text) != chunk.content_sha256:
            raise LedgerError("HASH_MISMATCH", f"chunk {cid} text does not match content_sha256")
        expected_id = make_chunk_id(
            chunk.book_version_id,
            chunk.section_id,
            chunk.start_offset,
            chunk.end_offset,
            chunk.content_sha256,
        )
        if expected_id != cid:
            raise LedgerError(
                "HASH_MISMATCH", f"chunk {cid} id does not match its content/position"
            )
        if chunk.reading_order != position:
            raise LedgerError(
                "LEDGER_INVALID", f"chunk {cid} reading_order {chunk.reading_order} != {position}"
            )

    sections = {s["section_id"]: (c, s) for c in ledger["chapters"] for s in c["sections"]}
    listed_units: list[int] = []
    for chapter in ledger["chapters"]:
        for section in chapter["sections"]:
            listed_units.append(section["unit_index"])
            for cid in section["chunk_ids"]:
                filed = by_id.get(cid)
                if filed is None:
                    raise LedgerError(
                        "BOOK_LEDGER_GAP", f"section {section['section_id']} chunk missing"
                    )
                if (
                    filed.section_id != section["section_id"]
                    or filed.chapter_id != chapter["chapter_id"]
                ):
                    raise LedgerError(
                        "LEDGER_INVALID", f"chunk {cid} filed under wrong section/chapter"
                    )
                if filed.unit_index != section["unit_index"] or not (
                    section["start"] <= filed.start_offset < filed.end_offset <= section["end"]
                ):
                    raise LedgerError(
                        "LEDGER_INVALID", f"chunk {cid} crosses its section/unit boundary"
                    )
    if set(sections) != {c.section_id for c in chunks} | {
        s for s, (_, row) in sections.items() if not row["chunk_ids"]
    }:
        raise LedgerError("LEDGER_INVALID", "chunk references an unknown section")

    units = ledger["units"]
    if [u["unit_index"] for u in units] != list(range(len(units))):
        raise LedgerError("BOOK_LEDGER_GAP", "source units are not 0..n-1")
    if set(listed_units) != set(range(len(units))):
        missing_units = sorted(set(range(len(units))) - set(listed_units))
        raise LedgerError("BOOK_LEDGER_GAP", f"unit(s) {missing_units} not assigned to any chapter")
    for unit in units:
        index = unit["unit_index"]
        if unit["status"] == "unreadable":
            if unit["chunk_ids"]:
                raise LedgerError("LEDGER_INVALID", f"unreadable unit {index} has chunks")
            continue
        rebuilt = reconstruct_unit(chunks, index)
        if len(rebuilt) != unit["char_count"] or sha256_text(rebuilt) != unit["text_sha256"]:
            raise LedgerError("BOOK_LEDGER_GAP", f"unit {index} is not fully covered by its chunks")
