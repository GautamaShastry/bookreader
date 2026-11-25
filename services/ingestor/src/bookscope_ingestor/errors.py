"""Ingestion error classification.

The code vocabulary is fixed by ``tests/fixtures/schemas/fixture-manifest.schema.json`` (EV-001);
a unit test keeps the two identical. Codes are stable API values for ``Book.failure_code``.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    PDF_BAD_SIGNATURE = "PDF_BAD_SIGNATURE"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_CORRUPT = "PDF_CORRUPT"
    PDF_NO_TEXT = "PDF_NO_TEXT"
    PDF_TOO_LARGE = "PDF_TOO_LARGE"
    PDF_TOO_MANY_PAGES = "PDF_TOO_MANY_PAGES"
    EPUB_BAD_CONTAINER = "EPUB_BAD_CONTAINER"
    EPUB_TOO_LARGE = "EPUB_TOO_LARGE"
    EPUB_UNSAFE_PATH = "EPUB_UNSAFE_PATH"
    EPUB_EXPANSION_LIMIT = "EPUB_EXPANSION_LIMIT"
    EPUB_MALFORMED_PACKAGE = "EPUB_MALFORMED_PACKAGE"
    EPUB_MISSING_SPINE = "EPUB_MISSING_SPINE"
    EPUB_ENCRYPTED = "EPUB_ENCRYPTED"
    EPUB_FORBIDDEN_XML = "EPUB_FORBIDDEN_XML"
    EPUB_NO_TEXT = "EPUB_NO_TEXT"


class IngestError(Exception):
    """A document was rejected. ``code`` is safe to show; ``detail`` never contains book text."""

    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
