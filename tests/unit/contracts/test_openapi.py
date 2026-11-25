"""OpenAPI v1.4 contract tests (BS-001)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

from bookscope_contracts import find_specs_dir, load_openapi, load_schema, unresolved_local_refs
from bookscope_contracts.refs import resolve_pointer

FULL_SUMMARY = "/v1/books/{book_id}/full-summary"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def api() -> dict[str, Any]:
    return load_openapi()


def test_openapi_document_is_valid_openapi_31() -> None:
    spec, base_uri = read_from_filename(str(find_specs_dir() / "06-API-OPENAPI.yaml"))
    validate(spec, base_uri=base_uri)
    assert spec["openapi"] == "3.1.0"


def test_openapi_spec_version_is_frozen_v14(api: dict[str, Any]) -> None:
    assert api["info"]["version"] == "1.4.0"


def test_every_local_ref_in_openapi_resolves(api: dict[str, Any]) -> None:
    unresolved = unresolved_local_refs(api)
    assert unresolved == [], "\n".join(f"{r.ref} at {r.location}" for r in unresolved)


def test_full_summary_route_has_exactly_post_and_get(api: dict[str, Any]) -> None:
    assert FULL_SUMMARY in api["paths"]
    methods = {m for m in api["paths"][FULL_SUMMARY] if m in HTTP_METHODS}
    assert methods == {"post", "get"}


def test_full_summary_post_requires_idempotency_key_header(api: dict[str, Any]) -> None:
    params = api["paths"][FULL_SUMMARY]["post"].get("parameters", [])
    matches = [p for p in params if p.get("name") == "Idempotency-Key"]
    assert len(matches) == 1
    assert matches[0].get("in") == "header"
    assert matches[0].get("required") is True


def test_full_summary_get_returns_full_book_summary_schema(api: dict[str, Any]) -> None:
    body = json.dumps(api["paths"][FULL_SUMMARY]["get"]["responses"])
    assert "#/components/schemas/FullBookSummaryResponse" in body


def test_job_type_enum_includes_full_book_summary(api: dict[str, Any]) -> None:
    job_types = api["components"]["schemas"]["Job"]["properties"]["job_type"]["enum"]
    assert "full_book_summary" in job_types


def test_every_operation_has_unique_operation_id(api: dict[str, Any]) -> None:
    ids = [
        op.get("operationId")
        for path in api["paths"].values()
        for method, op in path.items()
        if method in HTTP_METHODS
    ]
    assert ids, "no operations found"
    assert all(ids), "operation without operationId"
    assert len(ids) == len(set(ids)), "duplicate operationId"


def test_component_refs_name_existing_schemas(api: dict[str, Any]) -> None:
    names = set(api["components"]["schemas"])
    referenced = set(re.findall(r"#/components/schemas/([A-Za-z_]\w*)", json.dumps(api)))
    assert referenced <= names, referenced - names


def _inline_refs(node: Any, root: dict[str, Any], depth: int = 0) -> Any:
    """Inline every local ref (resolved against ``root``) and drop annotation keywords."""
    if depth > 50:
        raise RecursionError("ref cycle")
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            return _inline_refs(resolve_pointer(root, node["$ref"]), root, depth + 1)
        return {
            k: _inline_refs(v, root, depth + 1)
            for k, v in node.items()
            if k not in {"$schema", "$id", "$defs", "title", "description"}
        }
    if isinstance(node, list):
        return [_inline_refs(v, root, depth + 1) for v in node]
    return node


@pytest.mark.parametrize(
    ("component", "schema_name"),
    [
        ("FullBookSummaryResponse", "book-full-summary"),
        ("BookBriefResponse", "book-brief"),
        ("Answer", "answer"),
    ],
)
def test_openapi_component_matches_standalone_schema(
    api: dict[str, Any], component: str, schema_name: str
) -> None:
    standalone = load_schema(schema_name)
    embedded = copy.deepcopy(api["components"]["schemas"][component])
    assert _inline_refs(embedded, api) == _inline_refs(standalone, standalone)
