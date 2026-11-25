"""Blank backend/service smoke tests (BS-001). They prove imports and wiring only."""

from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

from bookscope_api.app import create_app

PACKAGES = [
    "bookscope_contracts",
    "bookscope_api",
    "bookscope_api.app",
    "bookscope_ingestor",
    "bookscope_agent_runtime",
]


@pytest.mark.parametrize("module", PACKAGES)
def test_package_imports(module: str) -> None:
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize("module", ["bookscope_ingestor", "bookscope_agent_runtime"])
def test_skeleton_services_declare_no_capabilities(module: str) -> None:
    # Guard against claiming features that are not implemented (parsing, agents, models).
    assert frozenset() == importlib.import_module(module).IMPLEMENTED_CAPABILITIES


def test_api_app_starts_with_no_routes_or_public_docs() -> None:
    app = create_app()
    client = TestClient(app)
    for path in ("/", "/docs", "/redoc", "/openapi.json", "/v1/books"):
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("module", PACKAGES)
def test_imports_do_not_pull_in_aws_or_model_sdks(module: str) -> None:
    importlib.import_module(module)
    forbidden = {"boto3", "botocore", "anthropic", "openai", "langgraph", "langchain"}
    assert forbidden.isdisjoint(sys.modules), forbidden & set(sys.modules)


def test_no_aws_credentials_required() -> None:
    # The suite must pass with no AWS credentials; CI provides none.
    if os.environ.get("CI"):
        assert not os.environ.get("AWS_ACCESS_KEY_ID")
        assert not os.environ.get("AWS_SECRET_ACCESS_KEY")
