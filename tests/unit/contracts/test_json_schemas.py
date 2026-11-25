"""JSON Schema and example contract tests (BS-001)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from bookscope_contracts import (
    check_schema_file,
    find_specs_dir,
    load_example,
    load_schema,
    openapi_component_validator,
    schema_paths,
    schema_validator,
)

SCHEMA_FILES = schema_paths()


def test_expected_schema_set_is_present() -> None:
    assert {p.name for p in SCHEMA_FILES} == {
        "agent-contract.schema.json",
        "answer.schema.json",
        "book-brief.schema.json",
        "book-full-summary.schema.json",
        "source-chunk.schema.json",
    }


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_draft_2020_12_with_resolving_refs(path: Path) -> None:
    diagnostics = check_schema_file(path)
    assert diagnostics == [], "\n".join(map(str, diagnostics))


# --- positive examples -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("example", "schema_name", "component"),
    [
        ("book-full-summary-example", "book-full-summary", "FullBookSummaryResponse"),
        ("book-brief-example", "book-brief", "BookBriefResponse"),
        ("answer-example", "answer", "Answer"),
    ],
)
def test_example_validates_against_schema_and_openapi(
    example: str, schema_name: str, component: str
) -> None:
    instance = load_example(example)
    schema_validator(schema_name).validate(instance)
    openapi_component_validator(component).validate(instance)


def test_evidence_handoff_example_validates_as_evidence_bundle() -> None:
    schema = load_schema("agent-contract")
    registry: Registry[Any] = Registry().with_resource(
        schema["$id"], Resource.from_contents(schema)
    )
    validator = Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/EvidenceBundle"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    validator.validate(load_example("agent-evidence-handoff"))


@pytest.mark.parametrize(
    "path",
    sorted((find_specs_dir() / "examples").glob("*.jsonl")),
    ids=lambda p: p.name,
)
def test_jsonl_seed_files_parse_one_object_per_line(path: Path) -> None:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, f"{path.name} is empty"
    for number, line in enumerate(lines, start=1):
        assert isinstance(json.loads(line), dict), f"{path.name}:{number} is not an object"


def test_bedrock_metadata_example_parses() -> None:
    # Illustrative AWS KB sidecar shape; the frozen specs define no schema for it.
    assert isinstance(load_example("bedrock-chunk.metadata"), dict)


# --- negative full-book summary cases (must be rejected by both copies of the contract) -------

Mutation = Callable[[dict[str, Any]], None]


def _set(key: str, value: Any) -> Mutation:
    def apply(doc: dict[str, Any]) -> None:
        doc[key] = value

    return apply


def _drop(key: str) -> Mutation:
    def apply(doc: dict[str, Any]) -> None:
        del doc[key]

    return apply


def _empty_overview_source_ids(doc: dict[str, Any]) -> None:
    doc["overview_claims"][0]["source_ids"] = []


def _missing_overview_source_ids(doc: dict[str, Any]) -> None:
    del doc["overview_claims"][0]["source_ids"]


def _empty_chapter_claim_source_ids(doc: dict[str, Any]) -> None:
    doc["chapter_summaries"][0]["claims"][0]["source_ids"] = []


def _citation_without_source_id(doc: dict[str, Any]) -> None:
    del doc["citations"][0]["source_id"]


def _citation_with_empty_source_id(doc: dict[str, Any]) -> None:
    doc["citations"][0]["source_id"] = ""


def _bad_chapter_state(doc: dict[str, Any]) -> None:
    doc["chapter_summaries"][0]["state"] = "skipped"


def _bad_completeness_label(doc: dict[str, Any]) -> None:
    doc["coverage"]["completeness_label"] = "mostly_complete"


def _negative_unit_count(doc: dict[str, Any]) -> None:
    doc["coverage"]["source_units_accounted"] = -1


NEGATIVE_CASES: dict[str, Mutation] = {
    "invalid_book_id_uuid": _set("book_id", "invalid"),
    "invalid_book_version_id_uuid": _set("book_version_id", "not-a-uuid"),
    "invalid_job_id_uuid": _set("job_id", "job-123"),
    "unknown_status": _set("status", "unapproved"),
    "status_wrong_type": _set("status", 1),
    "missing_status": _drop("status"),
    "missing_citations": _drop("citations"),
    "missing_coverage": _drop("coverage"),
    "empty_overview_source_ids": _empty_overview_source_ids,
    "missing_overview_source_ids": _missing_overview_source_ids,
    "empty_chapter_claim_source_ids": _empty_chapter_claim_source_ids,
    "citation_without_source_id": _citation_without_source_id,
    "citation_with_empty_source_id": _citation_with_empty_source_id,
    "unknown_chapter_state": _bad_chapter_state,
    "unknown_completeness_label": _bad_completeness_label,
    "negative_unit_count": _negative_unit_count,
    "unexpected_top_level_field": _set("is_comprehensive", True),
    "invalid_updated_at": _set("updated_at", "yesterday"),
}


@pytest.fixture(scope="module")
def full_summary_validators() -> list[Draft202012Validator]:
    return [
        schema_validator("book-full-summary"),
        openapi_component_validator("FullBookSummaryResponse"),
    ]


@pytest.mark.parametrize("case", sorted(NEGATIVE_CASES))
def test_malformed_full_summary_is_rejected(
    case: str, full_summary_validators: list[Draft202012Validator]
) -> None:
    doc = copy.deepcopy(load_example("book-full-summary-example"))
    NEGATIVE_CASES[case](doc)
    for validator in full_summary_validators:
        assert list(validator.iter_errors(doc)), f"{case} unexpectedly passed {validator.schema}"
