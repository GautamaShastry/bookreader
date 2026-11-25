"""Canonical artifact storage behind an S3-like interface (BS-006). No AWS calls.

Objects are immutable: writing the same key twice with identical bytes is an idempotent no-op;
different bytes raise ``ObjectConflictError`` (a duplicate SQS delivery can never mutate a
published version). Keys are always derived from the server-authorized scope, never from client
input, and every load re-verifies the ledger, so a foreign or tampered artifact is rejected.
"""

from __future__ import annotations

import json
from typing import Protocol

from bookscope_ingestor.chunking import BookScope, Chunk
from bookscope_ingestor.ledger import (
    CanonicalBook,
    LedgerError,
    canonical_json,
    verify_canonical_book,
)


class ObjectConflictError(Exception):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> bool:
        """Store immutable bytes; return True if written, False if identical bytes existed."""

    def get(self, key: str) -> bytes: ...

    def list(self, prefix: str) -> list[str]: ...


class InMemoryObjectStore:
    """Mock S3 with write-once semantics, for tests and local runs."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0

    def put(self, key: str, data: bytes) -> bool:
        self.put_calls += 1
        existing = self.objects.get(key)
        if existing is not None:
            if existing != data:
                raise ObjectConflictError(f"refusing to overwrite immutable object {key}")
            return False
        self.objects[key] = data
        return True

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise KeyError(f"no such object: {key}") from exc

    def list(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


def book_prefix(scope: BookScope) -> str:
    for value in (scope.owner_id, scope.book_id, scope.book_version_id):
        if not value or "/" in value or value in {".", ".."}:
            raise ValueError("invalid scope component for storage key")
    return f"canonical/{scope.owner_id}/{scope.book_id}/{scope.book_version_id}/"


def persist_canonical_book(store: ObjectStore, book: CanonicalBook, scope: BookScope) -> int:
    """Verify then write chunks and ledger (ledger last). Returns the number of new objects."""
    verify_canonical_book(book, scope)
    prefix = book_prefix(scope)
    written = 0
    for chunk in book.chunks:
        payload = {**chunk.to_json(), "unit_index": chunk.unit_index}
        written += store.put(f"{prefix}chunks/{chunk.chunk_id}.json", canonical_json(payload))
    written += store.put(f"{prefix}ledger.json", canonical_json(book.ledger))
    return written


def load_canonical_book(store: ObjectStore, scope: BookScope) -> CanonicalBook:
    """Load and fully verify a book version for ``scope``; raises LedgerError on any problem."""
    prefix = book_prefix(scope)
    try:
        ledger = json.loads(store.get(f"{prefix}ledger.json"))
    except KeyError as exc:
        raise LedgerError("BOOK_LEDGER_GAP", "no ledger for this book version") from exc
    chunks = []
    for chunk_id in ledger.get("chunk_order", []):
        try:
            data = json.loads(store.get(f"{prefix}chunks/{chunk_id}.json"))
        except KeyError as exc:
            raise LedgerError("BOOK_LEDGER_GAP", f"chunk missing: {chunk_id}") from exc
        chunks.append(Chunk.from_json(data, unit_index=data["unit_index"]))
    book = CanonicalBook(ledger, tuple(chunks))
    verify_canonical_book(book, scope)
    return book
