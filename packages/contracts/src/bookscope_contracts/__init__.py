"""Loaders and validators for the frozen BookScope v1.4 contracts in ``specs/``.

The contracts are read in place from ``specs/`` (never copied) so they cannot drift from the
checksum-verified source of truth.
"""

from bookscope_contracts.loader import (
    SPECS_DIR_ENV,
    find_specs_dir,
    load_example,
    load_openapi,
    load_schema,
    schema_paths,
)
from bookscope_contracts.refs import iter_local_refs, unresolved_local_refs
from bookscope_contracts.validation import (
    SchemaDiagnostic,
    check_schema_file,
    openapi_component_validator,
    schema_validator,
)

__all__ = [
    "SPECS_DIR_ENV",
    "SchemaDiagnostic",
    "check_schema_file",
    "find_specs_dir",
    "iter_local_refs",
    "load_example",
    "load_openapi",
    "load_schema",
    "openapi_component_validator",
    "schema_paths",
    "schema_validator",
    "unresolved_local_refs",
]
