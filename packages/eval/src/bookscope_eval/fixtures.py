"""Validate the EV-001 fixture manifest and evaluation cases.

Checks are deterministic and model-independent:

* JSON Schema validity of the manifest and of every ``eval_cases.jsonl`` line;
* fixture file exists, is inside the fixtures directory and matches its SHA-256 and size;
* license metadata is present and verified;
* unique fixture, book-version, source, chapter, quote and case IDs;
* every chapter/quote/case source ID resolves to a declared source unit of the same fixture;
* rejected fixtures declare no source units; accepted fixtures declare at least one readable unit.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

FIXTURES_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures"


@dataclass(frozen=True)
class Problem:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def _schema(name: str, fixtures_dir: Path) -> Draft202012Validator:
    schema = json.loads((fixtures_dir / "schemas" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_manifest(fixtures_dir: Path = FIXTURES_DIR) -> dict[str, Any]:
    data = json.loads((fixtures_dir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("manifest.json is not an object")
    return data


def load_cases(path: Path) -> list[tuple[int, Any]]:
    """Return ``(line_number, parsed_or_raw)`` for every non-blank JSONL line."""
    rows: list[tuple[int, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append((number, json.loads(line)))
        except json.JSONDecodeError as exc:
            rows.append((number, _InvalidJson(str(exc))))
    return rows


@dataclass(frozen=True)
class _InvalidJson:
    error: str


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def validate_manifest(manifest: Any, fixtures_dir: Path = FIXTURES_DIR) -> list[Problem]:
    problems = [
        Problem("manifest" + "".join(f"/{p}" for p in e.absolute_path), e.message)
        for e in _schema("fixture-manifest.schema.json", fixtures_dir).iter_errors(manifest)
    ]
    if problems:
        return problems  # structural errors make the semantic checks unreliable

    fixtures: list[dict[str, Any]] = manifest["fixtures"]
    for label, key in (("fixture_id", "fixture_id"), ("book_version_id", "book_version_id")):
        for dup in _duplicates(f[key] for f in fixtures):
            problems.append(Problem("manifest", f"duplicate {label} {dup!r}"))
    all_units = [u["source_id"] for f in fixtures for u in f["source_units"]]
    for dup in _duplicates(all_units):
        problems.append(Problem("manifest", f"duplicate source_id {dup!r}"))
    for dup in _duplicates(c["chapter_id"] for f in fixtures for c in f["chapters"]):
        problems.append(Problem("manifest", f"duplicate chapter_id {dup!r}"))
    for dup in _duplicates(q["quote_id"] for f in fixtures for q in f["quotes"]):
        problems.append(Problem("manifest", f"duplicate quote_id {dup!r}"))

    root = fixtures_dir.resolve()
    for f in fixtures:
        where = f"fixture {f['fixture_id']}"
        path = (fixtures_dir / f["path"]).resolve()
        if not path.is_relative_to(root):
            problems.append(Problem(where, f"path escapes fixtures dir: {f['path']}"))
            continue
        if not path.is_file():
            problems.append(Problem(where, f"file missing: {f['path']}"))
        else:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != f["sha256"]:
                problems.append(Problem(where, f"sha256 mismatch for {f['path']}"))
            if len(data) != f["size_bytes"]:
                problems.append(Problem(where, f"size mismatch for {f['path']}"))
        if not path.name.endswith("." + f["format"]):
            problems.append(Problem(where, "file extension does not match format"))

        own = {u["source_id"] for u in f["source_units"]}
        for sid in own:
            if not sid.startswith(f["fixture_id"] + ":"):
                problems.append(Problem(where, f"source_id {sid!r} not prefixed by fixture_id"))
        accepted = f["expected_outcome"]["status"] == "accepted"
        if accepted and not any(u["status"] == "readable" for u in f["source_units"]):
            problems.append(Problem(where, "accepted fixture has no readable source unit"))
        if not accepted and (f["source_units"] or f["chapters"] or f["quotes"]):
            problems.append(
                Problem(where, "rejected fixture must not declare units/chapters/quotes")
            )
        if f["format"] == "pdf":
            indexes = [u.get("page_index") for u in f["source_units"]]
            if indexes != list(range(len(indexes))):
                problems.append(Problem(where, "PDF page_index values must be 0..n-1 in order"))
        for chapter in f["chapters"]:
            for sid in chapter["source_ids"]:
                if sid not in own:
                    problems.append(
                        Problem(where, f"chapter {chapter['chapter_id']} cites unknown {sid!r}")
                    )
        for quote in f["quotes"]:
            for sid in quote["expected_source_ids"]:
                if sid not in own:
                    problems.append(
                        Problem(where, f"quote {quote['quote_id']} cites unknown {sid!r}")
                    )
            if quote["ambiguous"] != (len(quote["expected_source_ids"]) > 1):
                problems.append(Problem(where, f"quote {quote['quote_id']} ambiguity flag wrong"))
        covered = [sid for c in f["chapters"] for sid in c["source_ids"]]
        if accepted and sorted(covered) != sorted(own):
            problems.append(
                Problem(where, "chapters must account for every source unit exactly once")
            )
    return problems


def validate_cases(
    rows: list[tuple[int, Any]], manifest: dict[str, Any], fixtures_dir: Path = FIXTURES_DIR
) -> list[Problem]:
    validator = _schema("eval-case.schema.json", fixtures_dir)
    versions = {f["book_version_id"]: f for f in manifest["fixtures"]}
    problems: list[Problem] = []
    seen: Counter[str] = Counter()
    for number, row in rows:
        where = f"eval_cases.jsonl:{number}"
        if isinstance(row, _InvalidJson):
            problems.append(Problem(where, f"invalid JSON: {row.error}"))
            continue
        errors = list(validator.iter_errors(row))
        problems += [
            Problem(where + "".join(f"/{p}" for p in e.absolute_path), e.message) for e in errors
        ]
        if errors:
            continue
        seen[row["case_id"]] += 1
        fixture = versions.get(row["book_version_id"])
        if fixture is None:
            problems.append(Problem(where, f"unknown book_version_id {row['book_version_id']}"))
            continue
        if fixture["expected_outcome"]["status"] != "accepted":
            problems.append(
                Problem(where, "case targets a fixture that is expected to be rejected")
            )
        own = {u["source_id"]: u for u in fixture["source_units"]}
        for sid in row["gold_source_ids"]:
            unit = own.get(sid)
            if unit is None:
                problems.append(
                    Problem(where, f"gold source {sid!r} not in {fixture['fixture_id']}")
                )
            elif unit["status"] != "readable":
                problems.append(Problem(where, f"gold source {sid!r} is unreadable"))
    for dup in sorted(c for c, n in seen.items() if n > 1):
        problems.append(Problem("eval_cases.jsonl", f"duplicate case_id {dup!r}"))
    return problems


def manifest_sha256(fixtures_dir: Path = FIXTURES_DIR) -> str:
    return hashlib.sha256((fixtures_dir / "manifest.json").read_bytes()).hexdigest()
