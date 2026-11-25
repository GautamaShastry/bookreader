"""Whole-document checks for local (``#/...``) JSON references.

A local ``$ref`` resolves against the nearest enclosing ``$id`` (JSON Schema 2020-12). The frozen
OpenAPI document and schemas only use document-root-relative refs, so a ref inside a subschema
that declares ``$id`` is resolved against that subschema; otherwise against the document root.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocalRef:
    location: str  # JSON pointer of the object containing the $ref
    ref: str
    base_location: str  # JSON pointer of the resource the ref resolves against


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def iter_local_refs(doc: Any) -> Iterator[LocalRef]:
    """Yield every ``$ref`` string starting with ``#`` in ``doc``."""

    def walk(node: Any, pointer: str, base: str) -> Iterator[LocalRef]:
        if isinstance(node, dict):
            if pointer and isinstance(node.get("$id"), str):
                base = pointer
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#"):
                yield LocalRef(pointer or "#", ref, base or "#")
            for key, value in node.items():
                yield from walk(value, f"{pointer}/{_escape(str(key))}", base)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{pointer}/{index}", base)

    yield from walk(doc, "", "")


def resolve_pointer(doc: Any, pointer: str) -> Any:
    """Resolve a JSON pointer (``#/a/b`` or ``/a/b`` or ``#``) against ``doc``."""
    path = pointer.removeprefix("#")
    if path == "":
        return doc
    node = doc
    for raw in path.lstrip("/").split("/"):
        token = _unescape(raw)
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise KeyError(f"cannot resolve {pointer!r}: missing {token!r}")
    return node


def unresolved_local_refs(doc: Any) -> list[LocalRef]:
    """Return every local ref in ``doc`` that does not resolve."""
    failures = []
    for item in iter_local_refs(doc):
        try:
            base = resolve_pointer(doc, item.base_location)
            resolve_pointer(base, item.ref)
        except KeyError:
            failures.append(item)
    return failures
