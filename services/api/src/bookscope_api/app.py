"""FastAPI application factory.

Routes are added only by tickets that implement the contract in ``specs/06-API-OPENAPI.yaml``.
BS-026: full-book summary POST/GET and job polling. Interactive docs stay disabled, and every
route denies requests until real authentication (BS-002) is configured.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bookscope_api import __version__
from bookscope_api.full_summary import (
    ApiProblemError,
    FullSummaryService,
    InMemoryBooks,
    problem_response,
    router,
)


def create_app(full_summary_service: FullSummaryService | None = None) -> FastAPI:
    app = FastAPI(
        title="BookScope AI API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.full_summary_service = full_summary_service or FullSummaryService(InMemoryBooks())

    @app.exception_handler(ApiProblemError)
    async def _problem(_: Request, problem: ApiProblemError) -> JSONResponse:
        return problem_response(problem)

    app.include_router(router)
    return app
