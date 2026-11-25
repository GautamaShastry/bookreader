"""Locate and load frozen spec files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

SPECS_DIR_ENV = "BOOKSCOPE_SPECS_DIR"
_MARKER = "MANIFEST.sha256"


def find_specs_dir(start: Path | None = None) -> Path:
    """Return the ``specs/`` directory.

    ``BOOKSCOPE_SPECS_DIR`` wins if set; otherwise walk up from ``start`` (default: this file)
    looking for ``specs/MANIFEST.sha256``.
    """
    override = os.environ.get(SPECS_DIR_ENV)
    if override:
        path = Path(override).resolve()
        if not (path / _MARKER).is_file():
            raise FileNotFoundError(f"{SPECS_DIR_ENV}={override} has no {_MARKER}")
        return path
    starts = [start] if start else [Path(__file__), Path.cwd()]
    for here in (s.resolve() for s in starts):
        for parent in [here, *here.parents]:
            candidate = parent / "specs"
            if (candidate / _MARKER).is_file():
                return candidate
    raise FileNotFoundError(
        f"Could not find specs/{_MARKER} above {', '.join(map(str, starts))}; set {SPECS_DIR_ENV}"
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_openapi(specs_dir: Path | None = None) -> dict[str, Any]:
    path = (specs_dir or find_specs_dir()) / "06-API-OPENAPI.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} did not parse to a mapping")
    return data


def schema_paths(specs_dir: Path | None = None) -> list[Path]:
    return sorted((specs_dir or find_specs_dir()).joinpath("schemas").glob("*.json"))


def load_schema(name: str, specs_dir: Path | None = None) -> dict[str, Any]:
    """Load ``specs/schemas/<name>.schema.json`` (``name`` may include the suffix)."""
    filename = name if name.endswith(".json") else f"{name}.schema.json"
    data = _read_json((specs_dir or find_specs_dir()) / "schemas" / filename)
    if not isinstance(data, dict):
        raise TypeError(f"schema {filename} is not an object")
    return data


def load_example(name: str, specs_dir: Path | None = None) -> Any:
    filename = name if name.endswith(".json") else f"{name}.json"
    return _read_json((specs_dir or find_specs_dir()) / "examples" / filename)
