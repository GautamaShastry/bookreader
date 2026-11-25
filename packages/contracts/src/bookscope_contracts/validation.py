"""Schema validators and the malformed-schema diagnostic used by CI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from bookscope_contracts.loader import load_openapi, load_schema
from bookscope_contracts.refs import unresolved_local_refs

_OPENAPI_URI = "urn:bookscope:openapi"


@dataclass(frozen=True)
class SchemaDiagnostic:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def schema_validator(name: str) -> Draft202012Validator:
    """Validator (with format checking) for a frozen ``specs/schemas`` schema."""
    return Draft202012Validator(load_schema(name), format_checker=FormatChecker())


def openapi_component_validator(component: str) -> Draft202012Validator:
    """Validator for ``#/components/schemas/<component>`` resolved inside the OpenAPI document."""
    api = load_openapi()
    if component not in api.get("components", {}).get("schemas", {}):
        raise KeyError(f"OpenAPI has no components.schemas.{component}")
    registry: Registry[Any] = Registry().with_resource(
        _OPENAPI_URI, Resource.from_contents(api, default_specification=DRAFT202012)
    )
    return Draft202012Validator(
        {"$ref": f"{_OPENAPI_URI}#/components/schemas/{component}"},
        registry=registry,
        format_checker=FormatChecker(),
    )


def check_schema_file(path: Path) -> list[SchemaDiagnostic]:
    """Return every problem with a JSON Schema file (empty list means valid)."""
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [SchemaDiagnostic(path, f"cannot load JSON: {exc}")]
    diagnostics: list[SchemaDiagnostic] = []
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        diagnostics.append(SchemaDiagnostic(path, f"invalid JSON Schema at {where}: {exc.message}"))
    for ref in unresolved_local_refs(schema):
        diagnostics.append(SchemaDiagnostic(path, f"unresolved $ref {ref.ref!r} at {ref.location}"))
    return diagnostics
