"""BS-026: full-book summary API, job idempotency and fail-closed publication (no model calls)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Header
from fastapi.testclient import TestClient

from bookscope_agent_runtime.fake_full_summary import fake_full_summary
from bookscope_api.app import create_app
from bookscope_api.full_summary import (
    BookRecord,
    FullSummaryService,
    InMemoryBooks,
    get_current_owner,
)
from bookscope_contracts import openapi_component_validator
from bookscope_contracts.full_summary import LedgerView
from bookscope_eval.fixtures import FIXTURES_DIR, load_manifest
from bookscope_ingestor.chunking import BookScope
from bookscope_ingestor.ledger import build_canonical_book
from bookscope_ingestor.pdf import parse_pdf

OWNER = "owner-alice"
INTRUDER = "owner-mallory"
FIXTURE = next(f for f in load_manifest()["fixtures"] if f["fixture_id"] == "pdf-three-chapters")
BOOK_ID = FIXTURE["book_id"]
VERSION = FIXTURE["book_version_id"]
JOB = openapi_component_validator("Job")
ERROR = openapi_component_validator("ApiError")
SUMMARY = openapi_component_validator("FullBookSummaryResponse")


def _canonical() -> tuple[LedgerView, str]:
    document = parse_pdf((FIXTURES_DIR / FIXTURE["path"]).read_bytes())
    book = build_canonical_book(document, BookScope(OWNER, BOOK_ID, VERSION))
    return LedgerView.from_canonical_ledger(book.ledger), book.ledger["manifest_sha256"]


LEDGER, MANIFEST_SHA = _canonical()


class FixedEstimator:
    def __init__(self, usd: float | None) -> None:
        self.usd = usd

    def estimate_usd(self, ledger: LedgerView) -> float | None:
        return self.usd


def _record(**changes: Any) -> BookRecord:
    base = BookRecord(BOOK_ID, OWNER, "ready", VERSION, LEDGER, MANIFEST_SHA, True)
    return dataclasses.replace(base, **changes)


def _executor(ledger: LedgerView, job_id: str) -> dict[str, Any]:
    return fake_full_summary(ledger, updated_at="2026-11-25T00:00:00Z", job_id=job_id)


def _books(service: FullSummaryService) -> InMemoryBooks:
    assert isinstance(service.books, InMemoryBooks)
    return service.books


@pytest.fixture
def service() -> FullSummaryService:
    books = InMemoryBooks()
    books.add(_record())
    return FullSummaryService(books, estimator=FixedEstimator(0.40))


@pytest.fixture
def client(service: FullSummaryService) -> Iterator[TestClient]:
    app = create_app(service)

    def owner(x_test_owner: str = Header()) -> str:
        return x_test_owner

    app.dependency_overrides[get_current_owner] = owner
    with TestClient(app) as test_client:
        yield test_client


def _post(
    client: TestClient, key: str | None = "key-00000001", owner: str = OWNER, book: str = BOOK_ID
) -> Any:
    headers = {"X-Test-Owner": owner}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(f"/v1/books/{book}/full-summary", headers=headers)


def _get(client: TestClient, owner: str = OWNER, book: str = BOOK_ID) -> Any:
    return client.get(f"/v1/books/{book}/full-summary", headers={"X-Test-Owner": owner})


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    ERROR.validate(body)
    assert body["code"] == code
    assert "harbor" not in response.text.lower()  # no book text in errors


# --- authentication and authorization -----------------------------------------------------------


def test_without_identity_provider_every_route_is_401(service: FullSummaryService) -> None:
    with TestClient(create_app(service)) as raw:
        for response in (
            raw.post(
                f"/v1/books/{BOOK_ID}/full-summary", headers={"Idempotency-Key": "key-00000001"}
            ),
            raw.get(f"/v1/books/{BOOK_ID}/full-summary"),
            raw.get("/v1/jobs/00000000-0000-4000-8000-000000000000"),
        ):
            _error(response, 401, "UNAUTHENTICATED")
    assert service.jobs == {}


def test_other_owner_gets_404_for_book_and_job(client: TestClient) -> None:
    job_id = _post(client).json()["job_id"]
    _error(_post(client, owner=INTRUDER, key="key-intruder1"), 404, "BOOK_NOT_FOUND")
    _error(_get(client, owner=INTRUDER), 404, "BOOK_NOT_FOUND")
    _error(
        client.get(f"/v1/jobs/{job_id}", headers={"X-Test-Owner": INTRUDER}), 404, "JOB_NOT_FOUND"
    )


def test_malformed_ids_are_404_not_500(client: TestClient) -> None:
    _error(_post(client, book="not-a-uuid"), 404, "BOOK_NOT_FOUND")
    _error(client.get("/v1/jobs/not-a-uuid", headers={"X-Test-Owner": OWNER}), 404, "JOB_NOT_FOUND")


# --- POST validation and admission ---------------------------------------------------------------


def test_missing_idempotency_key_is_rejected(
    client: TestClient, service: FullSummaryService
) -> None:
    _error(_post(client, key=None), 422, "IDEMPOTENCY_KEY_REQUIRED")
    _error(_post(client, key="short"), 422, "IDEMPOTENCY_KEY_INVALID")
    assert service.jobs == {}


@pytest.mark.parametrize(
    ("changes", "status", "code"),
    [
        ({"status": "indexing"}, 409, "BOOK_NOT_READY"),
        ({"status": "deleting"}, 404, "BOOK_NOT_FOUND"),
        ({"structure_reliable": False}, 422, "INVALID_SOURCE_INVENTORY"),
        ({"ledger": None}, 422, "INVALID_SOURCE_INVENTORY"),
        ({"active_version_id": "55555555-5555-4555-8555-555555555555"}, 409, "VERSION_CHANGED"),
    ],
)
def test_book_state_gates(
    client: TestClient, service: FullSummaryService, changes: dict[str, Any], status: int, code: str
) -> None:
    _books(service).add(_record(**changes))
    _error(_post(client), status, code)
    assert service.jobs == {}


def test_budget_preflight_refuses_before_queueing(
    client: TestClient, service: FullSummaryService
) -> None:
    service.estimator = FixedEstimator(2.51)
    _error(_post(client), 429, "COST_BUDGET_EXCEEDED")
    assert service.jobs == {}
    assert service.queue == []
    assert service.executor_calls == 0


def test_unconfigured_pricing_fails_closed(client: TestClient, service: FullSummaryService) -> None:
    service.estimator = FixedEstimator(None)
    _error(_post(client), 503, "COST_PREFLIGHT_UNAVAILABLE")
    assert service.jobs == {}


def test_inflight_limit_per_owner(client: TestClient, service: FullSummaryService) -> None:
    other_book = "66666666-6666-4666-8666-666666666666"
    third_book = "77777777-7777-4777-8777-777777777777"
    for book_id in (other_book, third_book):
        _books(service).add(_record(book_id=book_id))
    assert _post(client).status_code == 202
    assert _post(client, key="key-00000002", book=other_book).status_code == 202
    _error(_post(client, key="key-00000003", book=third_book), 429, "RATE_LIMITED")


# --- idempotency and no-inference guarantees ---------------------------------------------------


def test_post_queues_job_without_running_anything(
    client: TestClient, service: FullSummaryService
) -> None:
    response = _post(client)
    assert response.status_code == 202
    body = response.json()
    JOB.validate(body)
    assert body["job_type"] == "full_book_summary"
    assert body["status"] == "queued"
    assert service.executor_calls == 0
    assert response.headers["Cache-Control"] == "no-store"


def test_duplicate_submissions_collapse_to_one_job(
    client: TestClient, service: FullSummaryService
) -> None:
    first = _post(client).json()["job_id"]
    assert _post(client).json()["job_id"] == first  # same key
    assert _post(client, key="key-different").json()["job_id"] == first  # same work in flight
    assert len(service.jobs) == 1
    assert service.queue == [first]


def test_idempotency_key_cannot_be_reused_for_another_book(
    client: TestClient, service: FullSummaryService
) -> None:
    other = "88888888-8888-4888-8888-888888888888"
    _books(service).add(_record(book_id=other))
    assert _post(client).status_code == 202
    _error(_post(client, book=other), 422, "IDEMPOTENCY_KEY_REUSED")


def test_completed_job_is_reused_not_regenerated(
    client: TestClient, service: FullSummaryService
) -> None:
    first = _post(client).json()["job_id"]
    service.run_next(_executor)
    assert _post(client, key="key-after-done").json()["job_id"] == first
    assert service.queue == []
    assert service.executor_calls == 1


# --- GET: state, publication and fail-closed behaviour --------------------------------------


def test_get_before_any_job_is_unavailable_without_inference(
    client: TestClient, service: FullSummaryService
) -> None:
    response = _get(client)
    assert response.status_code == 200
    body = response.json()
    SUMMARY.validate(body)
    assert body["status"] == "unavailable"
    assert body["overview_claims"] == []
    assert service.executor_calls == 0


def test_full_lifecycle_queued_then_ready(client: TestClient, service: FullSummaryService) -> None:
    job_id = _post(client).json()["job_id"]
    queued = _get(client).json()
    assert (queued["status"], queued["job_id"], queued["citations"]) == ("queued", job_id, [])
    job = service.run_next(_executor)
    assert job is not None
    assert job.status == "completed"
    ready = _get(client).json()
    SUMMARY.validate(ready)
    assert ready["status"] == "ready"
    assert ready["coverage"]["completeness_label"] == "complete"
    assert [s["chapter_id"] for s in ready["chapter_summaries"]] == [
        c.chapter_id for c in LEDGER.chapters
    ]
    calls = service.executor_calls
    for _ in range(3):
        assert _get(client).json() == ready  # cached: no new work
    assert service.executor_calls == calls
    polled = client.get(f"/v1/jobs/{job_id}", headers={"X-Test-Owner": OWNER}).json()
    JOB.validate(polled)
    assert polled["status"] == "completed"


def test_partial_result_is_published_as_partial(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)

    def one_chapter_fails(ledger: LedgerView, job_id: str) -> dict[str, Any]:
        return fake_full_summary(
            ledger, updated_at="2026-11-25T00:00:00Z", job_id=job_id, failed_chapters={"ch002"}
        )

    job = service.run_next(one_chapter_fails)
    assert job is not None
    assert job.status == "partial"
    body = _get(client).json()
    assert body["status"] == "partial"
    assert body["coverage"]["failed_chapter_ids"] == ["ch002"]


def test_false_ready_from_worker_is_never_published(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)

    def lying(ledger: LedgerView, job_id: str) -> dict[str, Any]:
        body = fake_full_summary(
            ledger, updated_at="2026-11-25T00:00:00Z", job_id=job_id, failed_chapters={"ch003"}
        )
        body["status"] = "ready"
        body["coverage"]["completeness_label"] = "complete"
        return body

    job = service.run_next(lying)
    assert job is not None
    assert (job.status, job.error_code) == ("failed", "PUBLICATION_REJECTED")
    body = _get(client).json()
    assert body["status"] == "failed"
    assert body["overview_claims"] == []
    assert body["error_code"] == "PUBLICATION_REJECTED"


def test_worker_citing_foreign_source_is_rejected(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)

    def injected(ledger: LedgerView, job_id: str) -> dict[str, Any]:
        body = fake_full_summary(ledger, updated_at="2026-11-25T00:00:00Z", job_id=job_id)
        body["overview_claims"][0]["source_ids"].append("chunk-from-another-book")
        body["citations"].append({"source_id": "chunk-from-another-book", "chapter_id": "ch001"})
        return body

    job = service.run_next(injected)
    assert job is not None
    assert job.error_code == "PUBLICATION_REJECTED"


def test_worker_exception_fails_job_safely(client: TestClient, service: FullSummaryService) -> None:
    _post(client)

    def crash(ledger: LedgerView, job_id: str) -> dict[str, Any]:
        raise RuntimeError("model provider 5xx")

    job = service.run_next(crash)
    assert job is not None
    assert (job.status, job.error_code) == ("failed", "WORKER_FAILED")
    assert _get(client).json()["status"] == "failed"


def test_deletion_before_worker_runs_cancels_and_revokes(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)
    _books(service).add(_record(status="deleting"))
    job = service.run_next(_executor)
    assert job is not None
    assert (job.status, job.phase, job.error_code) == ("failed", "cancelled", "BOOK_UNAVAILABLE")
    assert service.executor_calls == 0
    assert service.results == {}
    _error(_get(client), 404, "BOOK_NOT_FOUND")


def test_result_is_bound_to_active_version(client: TestClient, service: FullSummaryService) -> None:
    _post(client)
    service.run_next(_executor)
    assert _get(client).json()["status"] == "ready"
    new_version = "99999999-9999-4999-8999-999999999999"
    new_ledger = dataclasses.replace(LEDGER, book_version_id=new_version)
    _books(service).add(
        _record(active_version_id=new_version, ledger=new_ledger, manifest_sha256="f" * 64)
    )
    body = _get(client).json()
    assert body["status"] == "unavailable"
    assert body["book_version_id"] == new_version


def test_version_change_while_queued_cancels_job(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)
    _books(service).add(_record(manifest_sha256="e" * 64))
    job = service.run_next(_executor)
    assert job is not None
    assert job.error_code == "VERSION_CHANGED"
    assert service.executor_calls == 0


def test_tampered_stored_result_is_not_served(
    client: TestClient, service: FullSummaryService
) -> None:
    _post(client)
    service.run_next(_executor)
    stored = next(iter(service.results.values()))
    stored["coverage"]["failed_chapter_ids"] = ["ch001"]
    _error(_get(client), 503, "PUBLICATION_GATE")
