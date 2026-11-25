"""Safe DRM-free EPUB 2/3 adapter (BS-005): each spine document becomes one ordered source unit.

Security (spec 04 §1, spec 07 §5): the file is an untrusted ZIP.

* size, entry count, per-entry and total uncompressed size and compression ratio are bounded,
  and enforced while reading (declared sizes are not trusted);
* entry names that are absolute, contain ``..``, backslashes, drive letters or control characters
  are rejected (ZIP slip), even though nothing is ever extracted to disk;
* every XML document is parsed with defusedxml: entity declarations and external references are
  rejected;
* ``META-INF/encryption.xml`` encrypting anything other than fonts, or ``META-INF/rights.xml``,
  means DRM and is rejected; no DRM circumvention;
* scripts, styles and other active content are never extracted; nothing external is fetched.

Locators: ``spine_href`` (path inside the package) + element ``anchor_id`` + exact normalised
quote; a TOC anchor that does not exist is flagged ``anchor_resolved=False``, never guessed.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from bookscope_ingestor.errors import ErrorCode, IngestError
from bookscope_ingestor.locate import QuoteMatch, find_quote
from bookscope_ingestor.models import (
    EpubLocator,
    ParsedDocument,
    SourceUnit,
    TextSpan,
    TocEntry,
    TocOrigin,
    UnitStatus,
)
from bookscope_ingestor.normalize import normalize_text

MiB = 1024 * 1024
EXTRACTION_VERSION = "epub-defusedxml/1"
FONT_OBFUSCATION = {
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
}
XHTML_TYPES = {"application/xhtml+xml", "text/html"}
SKIP_TAGS = {"script", "style", "head", "noscript", "template", "object", "embed", "iframe"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "aside", "header", "footer", "nav", "main", "blockquote",
    "pre", "li", "ul", "ol", "dl", "dt", "dd", "table", "tr", "td", "th", "caption", "figure",
    "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "body", "hr", "br",
}  # fmt: skip
_UNSAFE_NAME = re.compile(r"(^/)|(^[A-Za-z]:)|\\|[\x00-\x1f]")


@dataclass(frozen=True)
class EpubLimits:
    max_bytes: int = 25 * MiB
    max_entries: int = 2_000
    max_entry_bytes: int = 32 * MiB
    max_total_bytes: int = 128 * MiB
    max_ratio: float = 100.0
    ratio_floor_bytes: int = 1 * MiB  # ratio only checked above this uncompressed size


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


class _Package:
    """Bounded, read-only access to ZIP members."""

    def __init__(self, data: bytes, limits: EpubLimits) -> None:
        self.limits = limits
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, ValueError) as exc:
            raise IngestError(ErrorCode.EPUB_BAD_CONTAINER, "not a ZIP archive") from exc
        infos = self.zip.infolist()
        if len(infos) > limits.max_entries:
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, f"{len(infos)} entries")
        declared_total = 0
        for info in infos:
            name = info.filename
            parts = name.split("/")
            if _UNSAFE_NAME.search(name) or ".." in parts:
                raise IngestError(ErrorCode.EPUB_UNSAFE_PATH, "unsafe entry name")
            if info.flag_bits & 0x1:
                raise IngestError(ErrorCode.EPUB_ENCRYPTED, "ZIP-level encryption")
            declared_total += info.file_size
            self._check_size(info.file_size, info.compress_size)
        if declared_total > limits.max_total_bytes:
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, "declared total size too large")
        self.names = {i.filename for i in infos}
        self.first = infos[0] if infos else None
        self._read_total = 0

    def _check_size(self, size: int, compressed: int) -> None:
        if size > self.limits.max_entry_bytes:
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, "entry too large")
        if size > self.limits.ratio_floor_bytes and size > self.limits.max_ratio * max(
            compressed, 1
        ):
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, "compression ratio too high")

    def read(self, name: str) -> bytes:
        if name not in self.names:
            raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "referenced file missing")
        try:
            with self.zip.open(name) as handle:
                data = handle.read(self.limits.max_entry_bytes + 1)
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
            raise IngestError(ErrorCode.EPUB_BAD_CONTAINER, "unreadable ZIP entry") from exc
        if len(data) > self.limits.max_entry_bytes:
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, "entry exceeds limit when read")
        self._read_total += len(data)
        if self._read_total > self.limits.max_total_bytes:
            raise IngestError(ErrorCode.EPUB_EXPANSION_LIMIT, "total read exceeds limit")
        return data

    def xml(self, name: str) -> Element:
        return parse_xml(self.read(name))


def parse_xml(data: bytes) -> Element:
    try:
        return fromstring(data, forbid_dtd=False, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise IngestError(ErrorCode.EPUB_FORBIDDEN_XML, type(exc).__name__) from exc
    except ParseError as exc:
        raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "XML is not well-formed") from exc


def _resolve(base_dir: str, href: str) -> tuple[str, str | None]:
    """Resolve a relative href inside the package to (path, fragment)."""
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return "", None  # external resource: never fetched, never part of the book
    path = posixpath.normpath(posixpath.join(base_dir, unquote(parts.path))) if parts.path else ""
    return path, (unquote(parts.fragment) or None)


@dataclass(frozen=True)
class _ManifestItem:
    path: str
    media_type: str
    properties: frozenset[str]


def parse_epub(data: bytes, limits: EpubLimits = EpubLimits()) -> ParsedDocument:
    if len(data) > limits.max_bytes:
        raise IngestError(ErrorCode.EPUB_TOO_LARGE, f"{len(data)} bytes > {limits.max_bytes}")
    package = _Package(data, limits)
    _check_mimetype(package)
    _check_drm(package)
    opf_path = _rootfile(package)
    opf = package.xml(opf_path)
    opf_dir = posixpath.dirname(opf_path)
    items = _manifest(opf, opf_dir)
    spine_ids, ncx_id = _spine(opf)
    spine: list[_ManifestItem] = []
    for idref in spine_ids:
        if idref not in items:
            raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "spine references unknown item")
        spine.append(items[idref])

    units = tuple(_unit(package, item, index) for index, item in enumerate(spine))
    if not any(u.is_readable for u in units):
        raise IngestError(ErrorCode.EPUB_NO_TEXT, "no spine document has extractable text")

    by_path = {u.href: u for u in units}
    toc: list[TocEntry] = []
    origin: TocOrigin = "none"
    nav = next((i for i in items.values() if "nav" in i.properties), None)
    if nav is not None:
        toc, origin = _nav_toc(package, nav.path, by_path), "nav"
    if not toc and ncx_id and ncx_id in items:
        toc, origin = _ncx_toc(package, items[ncx_id].path, by_path), "ncx"
    if not toc:
        origin = "none"
    diagnostics = tuple(
        f"unresolved_toc_anchor:{entry.unit_index}:{entry.anchor_id}"
        for entry in toc
        if not entry.anchor_resolved
    )
    return ParsedDocument(
        format="epub",
        sha256=hashlib.sha256(data).hexdigest(),
        extraction_version=EXTRACTION_VERSION,
        units=units,
        toc=tuple(toc),
        toc_origin=origin,
        title=_title(opf),
        diagnostics=diagnostics,
    )


def _check_mimetype(package: _Package) -> None:
    first = package.first
    if first is None or first.filename != "mimetype":
        raise IngestError(ErrorCode.EPUB_BAD_CONTAINER, "first entry must be 'mimetype'")
    if package.read("mimetype").strip() != b"application/epub+zip":
        raise IngestError(ErrorCode.EPUB_BAD_CONTAINER, "wrong mimetype")


def _check_drm(package: _Package) -> None:
    if "META-INF/rights.xml" in package.names:
        raise IngestError(ErrorCode.EPUB_ENCRYPTED, "rights.xml present (DRM)")
    if "META-INF/encryption.xml" not in package.names:
        return
    root = package.xml("META-INF/encryption.xml")
    for element in root.iter():
        is_method = _local(element.tag) == "encryptionmethod"
        if is_method and element.get("Algorithm") not in FONT_OBFUSCATION:
            raise IngestError(ErrorCode.EPUB_ENCRYPTED, "content is encrypted (DRM)")


def _rootfile(package: _Package) -> str:
    if "META-INF/container.xml" not in package.names:
        raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "missing META-INF/container.xml")
    container = package.xml("META-INF/container.xml")
    for element in container.iter():
        if _local(element.tag) == "rootfile" and element.get("full-path"):
            path, _ = _resolve("", element.get("full-path", ""))
            if path:
                return path
    raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "container.xml has no rootfile")


def _manifest(opf: Element, opf_dir: str) -> dict[str, _ManifestItem]:
    items: dict[str, _ManifestItem] = {}
    for element in opf.iter():
        if _local(element.tag) != "item":
            continue
        item_id, href = element.get("id"), element.get("href")
        if not item_id or not href:
            raise IngestError(ErrorCode.EPUB_MALFORMED_PACKAGE, "manifest item without id/href")
        path, _ = _resolve(opf_dir, href)
        items[item_id] = _ManifestItem(
            path=path,
            media_type=element.get("media-type", ""),
            properties=frozenset(element.get("properties", "").split()),
        )
    return items


def _spine(opf: Element) -> tuple[list[str], str | None]:
    spine = next((e for e in opf.iter() if _local(e.tag) == "spine"), None)
    if spine is None:
        raise IngestError(ErrorCode.EPUB_MISSING_SPINE, "no <spine>")
    idrefs = [e.get("idref", "") for e in spine if _local(e.tag) == "itemref"]
    if not idrefs:
        raise IngestError(ErrorCode.EPUB_MISSING_SPINE, "empty <spine>")
    return idrefs, spine.get("toc")


def _title(opf: Element) -> str | None:
    for element in opf.iter():
        if _local(element.tag) == "title" and element.text:
            return normalize_text(element.text) or None
    return None


class _TextBuilder:
    """Collect normalised block text, block spans and anchor offsets from an XHTML tree."""

    def __init__(self) -> None:
        self.blocks: list[tuple[str, int | None]] = []  # (raw text, heading level)
        self.current: list[str] = []
        self.level: int | None = None
        self.anchor_blocks: list[tuple[str, int]] = []  # (anchor id, block index)

    def flush(self) -> None:
        text = normalize_text("".join(self.current))
        if text:
            self.blocks.append((text, self.level))
        self.current, self.level = [], None

    def walk(self, element: Element) -> None:
        tag = _local(element.tag)
        if tag in SKIP_TAGS:
            return
        is_block = tag in BLOCK_TAGS
        if is_block:
            self.flush()
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self.level = int(tag[1])
        anchor = element.get("id")
        if anchor:
            self.anchor_blocks.append((anchor, len(self.blocks)))
        if element.text:
            self.current.append(element.text)
        for child in element:
            self.walk(child)
            if child.tail:
                self.current.append(child.tail)
        if is_block:
            self.flush()

    def build(self) -> tuple[str, tuple[TextSpan, ...], tuple[tuple[str, int], ...]]:
        self.flush()
        spans: list[TextSpan] = []
        starts: list[int] = []
        cursor = 0
        for i, (text, level) in enumerate(self.blocks):
            if i:
                cursor += 1
            starts.append(cursor)
            spans.append(TextSpan(cursor, cursor + len(text), heading_level=level))
            cursor += len(text)
        end = cursor
        anchors: list[tuple[str, int]] = []
        seen: set[str] = set()
        for anchor_id, block_index in self.anchor_blocks:
            if anchor_id in seen:
                continue
            seen.add(anchor_id)
            offset = starts[block_index] if block_index < len(starts) else end
            anchors.append((anchor_id, offset))
        final_spans = tuple(
            TextSpan(
                s.start,
                s.end,
                anchor_id=_anchor_at(anchors, s.start),
                heading_level=s.heading_level,
            )
            for s in spans
        )
        return " ".join(t for t, _ in self.blocks), final_spans, tuple(anchors)


def _anchor_at(anchors: list[tuple[str, int]], offset: int) -> str | None:
    best = None
    for anchor_id, anchor_offset in anchors:
        if anchor_offset <= offset:
            best = anchor_id
    return best


def _unit(package: _Package, item: _ManifestItem, index: int) -> SourceUnit:
    status: UnitStatus = "readable"
    diagnostics: list[str] = []
    if item.media_type not in XHTML_TYPES:
        return SourceUnit(
            unit_index=index, status="unreadable", normalized_text="", spans=(), href=item.path,
            diagnostics=(f"non_text_spine_item:{item.media_type}",),
        )  # fmt: skip
    raw = package.read(item.path)
    try:
        root = parse_xml(raw)
    except IngestError as exc:
        if exc.code is ErrorCode.EPUB_FORBIDDEN_XML:
            raise
        return SourceUnit(
            unit_index=index, status="unreadable", normalized_text="", spans=(), href=item.path,
            diagnostics=("malformed_xhtml",),
        )  # fmt: skip
    body = next((e for e in root.iter() if _local(e.tag) == "body"), root)
    builder = _TextBuilder()
    builder.walk(body)
    text, spans, anchors = builder.build()
    if not text:
        status = "unreadable"
        diagnostics.append("no_extractable_text")
    return SourceUnit(
        unit_index=index,
        status=status,
        normalized_text=text,
        spans=spans,
        href=item.path,
        anchors=anchors,
        diagnostics=tuple(diagnostics),
    )


def _toc_entry(
    level: int,
    title: str,
    href: str,
    base_dir: str,
    by_path: dict[str | None, SourceUnit],
    origin: TocOrigin,
) -> TocEntry | None:
    path, fragment = _resolve(base_dir, href)
    unit = by_path.get(path)
    clean = normalize_text(title)
    if unit is None or not clean:
        return None
    resolved = fragment is None or fragment in dict(unit.anchors)
    return TocEntry(
        level, clean, unit.unit_index, origin, anchor_id=fragment, anchor_resolved=resolved
    )


def _nav_toc(
    package: _Package, nav_path: str, by_path: dict[str | None, SourceUnit]
) -> list[TocEntry]:
    root = package.xml(nav_path)
    base = posixpath.dirname(nav_path)
    navs = [e for e in root.iter() if _local(e.tag) == "nav"]
    toc_nav = next(
        (n for n in navs if any(_local(k) == "type" and v == "toc" for k, v in n.attrib.items())),
        navs[0] if navs else None,
    )
    if toc_nav is None:
        return []
    entries: list[TocEntry] = []

    def walk(element: Element, depth: int) -> None:
        for child in element:
            tag = _local(child.tag)
            if tag == "li":
                link = next((e for e in child if _local(e.tag) == "a"), None)
                if link is not None and link.get("href"):
                    entry = _toc_entry(
                        depth, "".join(link.itertext()), link.get("href", ""), base, by_path, "nav"
                    )
                    if entry:
                        entries.append(entry)
                walk(child, depth + 1)
            elif tag == "ol":
                walk(child, depth)

    walk(toc_nav, 0)
    return [
        TocEntry(max(e.level, 1), e.title, e.unit_index, e.origin, e.anchor_id, e.anchor_resolved)
        for e in entries
    ]


def _ncx_toc(
    package: _Package, ncx_path: str, by_path: dict[str | None, SourceUnit]
) -> list[TocEntry]:
    root = package.xml(ncx_path)
    base = posixpath.dirname(ncx_path)
    entries: list[TocEntry] = []

    def walk(element: Element, depth: int) -> None:
        for child in element:
            if _local(child.tag) != "navpoint":
                continue
            label = next((e for e in child.iter() if _local(e.tag) == "text"), None)
            content = next((e for e in child if _local(e.tag) == "content"), None)
            if label is not None and content is not None:
                entry = _toc_entry(
                    depth, label.text or "", content.get("src", ""), base, by_path, "ncx"
                )
                if entry:
                    entries.append(entry)
            walk(child, depth + 1)

    nav_map = next((e for e in root.iter() if _local(e.tag) == "navmap"), None)
    if nav_map is not None:
        walk(nav_map, 1)
    return entries


def locator_for(document: ParsedDocument, match: QuoteMatch) -> EpubLocator:
    """Locator for a quote match: spine document + nearest preceding anchor + exact quote."""
    unit = document.unit(match.unit_index)
    if unit.href is None:
        raise ValueError("not an EPUB unit")
    return EpubLocator(
        spine_href=unit.href,
        anchor_id=_anchor_at(list(unit.anchors), match.start),
        text_quote=unit.normalized_text[match.start : match.end],
        normalized_offset=match.start,
    )


def verified_locator(document: ParsedDocument, quote: str) -> EpubLocator | None:
    """A displayable verified locator, or None when the quote is missing or ambiguous."""
    resolution = find_quote(document, quote)
    if resolution.status != "unique":
        return None
    return locator_for(document, resolution.matches[0])
