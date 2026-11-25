"""FastAPI application factory.

Deliberately exposes no routes in BS-001. Endpoints are added only by tickets that implement the
contract in ``specs/06-API-OPENAPI.yaml``; interactive docs are disabled until auth exists.
"""

from fastapi import FastAPI

from bookscope_api import __version__


def create_app() -> FastAPI:
    return FastAPI(
        title="BookScope AI API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
