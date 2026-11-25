"""Full-book summary API and job workflow (BS-026, spec 14; OpenAPI ``requestFullBookSummary``,
``getFullBookSummary``, ``getJob``).

* ``POST /v1/books/{book_id}/full-summary`` authorizes the owner, requires ``Idempotency-Key``, a
  READY book with a reliable chapter inventory, and a cost preflight under the per-job allowance;
  it queues work and returns ``202 Job``. It never runs the summarizer or any model.
* Duplicate submissions collapse: the same key returns the same job, and any in-flight or finished
  job for the same owner/version/spec/manifest is reused.
* ``GET`` never starts work: it returns a published result bound to the owner's active version and
  manifest, or the job state, with no claims until publication.
* Every response body passes ``check_full_summary`` against the ledger before leaving the server;
  a failing body is replaced by a safe error (fail closed).

Authentication (Cognito, BS-002) is not implemented: ``get_current_owner`` denies every request
until a verified identity provider is wired in. Tests override it.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from bookscope_contracts.full_summary import LedgerView, check_full_summary

SUMMARY_SPEC_VERSION = "1.4.0"
DEFAULT_ALLOWANCE_USD = 2.50
JOB_TYPE = "full_book_summary"

Executor = Callable[[LedgerView, str], dict[str, Any]]  # (ledger, job_id) -> response


class ApiProblemError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BookRecord:
    book_id: str
    owner_id: str
    status: str  # Book.status enum from the OpenAPI contract
    active_version_id: str
    ledger: LedgerView | None
    manifest_sha256: str
    structure_reliable: bool


class BookRepository(Protocol):
    def get(self, owner_id: str, book_id: str) -> BookRecord | None: ...


class CostEstimator(Protocol):
    def estimate_usd(self, ledger: LedgerView) -> float | None:
        """Upper-bound USD estimate for a full-book job, or None if pricing is unavailable."""


class UnconfiguredCostEstimator:
    """Default: no reviewed pricing catalog, so every paid job is refused (fail closed)."""

    def estimate_usd(self, ledger: LedgerView) -> float | None:
        return None


@dataclass
class InMemoryBooks:
    records: dict[tuple[str, str], BookRecord] = field(default_factory=dict)

    def add(self, record: BookRecord) -> None:
        self.records[(record.owner_id, record.book_id)] = record

    def get(self, owner_id: str, book_id: str) -> BookRecord | None:
        return self.records.get((owner_id, book_id))


@dataclass
class Job:
    job_id: str
    owner_id: str
    book_id: str
    book_version_id: str
    manifest_sha256: str
    status: str = "queued"  # Job.status: queued|running|completed|partial|failed
    phase: str = "queued"
    error_code: str | None = None
    sequence: int = 0

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.owner_id,
            self.book_id,
            self.book_version_id,
            SUMMARY_SPEC_VERSION,
            self.manifest_sha256,
        )

    def to_api(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": JOB_TYPE,
            "book_id": self.book_id,
            "status": self.status,
            "phase": self.phase,
            "error_code": self.error_code,
            "result": {"book_version_id": self.book_version_id},
        }


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FullSummaryService:
    books: BookRepository
    estimator: CostEstimator = field(default_factory=UnconfiguredCostEstimator)
    allowance_usd: float = DEFAULT_ALLOWANCE_USD
    max_inflight_per_owner: int = 2
    jobs: dict[str, Job] = field(default_factory=dict)
    idempotency: dict[tuple[str, str], str] = field(default_factory=dict)
    results: dict[tuple[str, str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)
    executor_calls: int = 0
    _sequence: itertools.count[int] = field(default_factory=itertools.count)

    # --- request path (no model, no executor) ----------------------------------------------

    def _book(self, owner_id: str, book_id: str) -> BookRecord:
        record = self.books.get(owner_id, book_id)
        if (
            record is None
            or record.owner_id != owner_id
            or record.status in {"deleting", "deleted"}
        ):
            raise ApiProblemError(404, "BOOK_NOT_FOUND", "Book unavailable or not owned.")
        if record.status != "ready":
            raise ApiProblemError(409, "BOOK_NOT_READY", "Book is not ready.")
        return record

    def request(self, owner_id: str, book_id: str, idempotency_key: str | None) -> Job:
        if idempotency_key is None:
            raise ApiProblemError(
                422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required."
            )
        if not 8 <= len(idempotency_key) <= 128:
            raise ApiProblemError(
                422, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 8-128 chars."
            )
        record = self._book(owner_id, book_id)
        if record.ledger is None or not record.structure_reliable or not record.ledger.chapters:
            raise ApiProblemError(
                422, "INVALID_SOURCE_INVENTORY", "Book has no reliable chapter inventory."
            )
        if record.ledger.book_version_id != record.active_version_id:
            raise ApiProblemError(409, "VERSION_CHANGED", "Book version changed.")

        existing_id = self.idempotency.get((owner_id, idempotency_key))
        if existing_id is not None:
            job = self.jobs[existing_id]
            if job.book_id != book_id:
                raise ApiProblemError(
                    422, "IDEMPOTENCY_KEY_REUSED", "Key already used for another book."
                )
            return job
        identity = (
            owner_id,
            book_id,
            record.active_version_id,
            SUMMARY_SPEC_VERSION,
            record.manifest_sha256,
        )
        for job in sorted(self.jobs.values(), key=lambda j: -j.sequence):
            if job.identity == identity and job.status != "failed":
                self.idempotency[(owner_id, idempotency_key)] = job.job_id
                return job

        estimate = self.estimator.estimate_usd(record.ledger)
        if estimate is None:
            raise ApiProblemError(503, "COST_PREFLIGHT_UNAVAILABLE", "Cost preflight unavailable.")
        if estimate > self.allowance_usd:
            raise ApiProblemError(
                429,
                "COST_BUDGET_EXCEEDED",
                f"Estimated cost exceeds the per-job allowance of ${self.allowance_usd:.2f}.",
            )
        inflight = sum(
            1
            for j in self.jobs.values()
            if j.owner_id == owner_id and j.status in {"queued", "running"}
        )
        if inflight >= self.max_inflight_per_owner:
            raise ApiProblemError(429, "RATE_LIMITED", "Too many summary jobs in progress.")

        job = Job(
            job_id=str(uuid.uuid4()),
            owner_id=owner_id,
            book_id=book_id,
            book_version_id=record.active_version_id,
            manifest_sha256=record.manifest_sha256,
            sequence=next(self._sequence),
        )
        self.jobs[job.job_id] = job
        self.idempotency[(owner_id, idempotency_key)] = job.job_id
        self.queue.append(job.job_id)
        return job

    def get_job(self, owner_id: str, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise ApiProblemError(404, "JOB_NOT_FOUND", "Job not found.")
        return job

    def read(self, owner_id: str, book_id: str) -> dict[str, Any]:
        record = self._book(owner_id, book_id)
        if record.ledger is None:
            raise ApiProblemError(422, "INVALID_SOURCE_INVENTORY", "Book has no chapter inventory.")
        identity = (
            owner_id,
            book_id,
            record.active_version_id,
            SUMMARY_SPEC_VERSION,
            record.manifest_sha256,
        )
        published = self.results.get(identity)
        if published is not None:
            response = published
        else:
            latest = max(
                (j for j in self.jobs.values() if j.identity == identity),
                key=lambda j: j.sequence,
                default=None,
            )
            response = self._state_response(record, latest)
        violations = check_full_summary(response, record.ledger)
        if violations:
            raise ApiProblemError(503, "PUBLICATION_GATE", "Summary failed publication checks.")
        return response

    def _state_response(self, record: BookRecord, job: Job | None) -> dict[str, Any]:
        if record.ledger is None:
            raise ApiProblemError(422, "INVALID_SOURCE_INVENTORY", "Book has no chapter inventory.")
        status, error = "unavailable", None
        if job is not None:
            status = {"queued": "queued", "running": "generating"}.get(job.status, "failed")
            if status == "failed":
                error = job.error_code or "JOB_FAILED"
        return {
            "book_id": record.book_id,
            "book_version_id": record.active_version_id,
            "summary_spec_version": SUMMARY_SPEC_VERSION,
            "status": status,
            "overview_claims": [],
            "chapter_summaries": [],
            "coverage": {
                "chapters_expected": len(record.ledger.chapters),
                "chapters_accounted": 0,
                "chapters_completed": 0,
                "failed_chapter_ids": [],
                "source_units_expected": record.ledger.source_units,
                "source_units_accounted": 0,
                "completeness_label": "unavailable",
            },
            "citations": [],
            "updated_at": _now(),
            "job_id": job.job_id if job else None,
            "error_code": error,
        }

    # --- worker path ------------------------------------------------------------------------

    def run_next(self, executor: Executor) -> Job | None:
        """Process one queued job. Re-authorizes the book first; never publishes an invalid body."""
        if not self.queue:
            return None
        job = self.jobs[self.queue.pop(0)]
        record = self.books.get(job.owner_id, job.book_id)
        if record is None or record.status != "ready" or record.ledger is None:
            job.status, job.phase, job.error_code = "failed", "cancelled", "BOOK_UNAVAILABLE"
            return job
        if (record.active_version_id, record.manifest_sha256) != (
            job.book_version_id,
            job.manifest_sha256,
        ):
            job.status, job.phase, job.error_code = "failed", "cancelled", "VERSION_CHANGED"
            return job
        job.status, job.phase = "running", "generating"
        self.executor_calls += 1
        try:
            response = executor(record.ledger, job.job_id)
        except Exception:
            job.status, job.phase, job.error_code = "failed", "failed", "WORKER_FAILED"
            return job
        if check_full_summary(response, record.ledger):
            job.status, job.phase, job.error_code = "failed", "rejected", "PUBLICATION_REJECTED"
            return job
        if response["status"] == "failed":
            job.status, job.phase = "failed", "failed"
            job.error_code = response.get("error_code") or "JOB_FAILED"
            return job
        self.results[job.identity] = response
        job.status = "completed" if response["status"] == "ready" else "partial"
        job.phase = "published"
        job.error_code = response.get("error_code")
        return job


# --- HTTP layer ---------------------------------------------------------------------------------


def get_current_owner() -> str:
    """Verified owner id from the identity provider. Not implemented (BS-002): deny all."""
    raise ApiProblemError(401, "UNAUTHENTICATED", "Authentication is required.")


def get_service(request: Request) -> FullSummaryService:
    service: FullSummaryService = request.app.state.full_summary_service
    return service


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def problem_response(problem: ApiProblemError) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content={
            "code": problem.code,
            "message": problem.message,
            "correlation_id": str(uuid.uuid4()),
        },
        headers={"Cache-Control": "no-store"},
    )


router = APIRouter()
Owner = Annotated[str, Depends(get_current_owner)]
Service = Annotated[FullSummaryService, Depends(get_service)]


@router.post("/v1/books/{book_id}/full-summary", status_code=202)
def request_full_book_summary(
    book_id: str,
    owner_id: Owner,
    service: Service,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    if not _valid_uuid(book_id):
        raise ApiProblemError(404, "BOOK_NOT_FOUND", "Book unavailable or not owned.")
    job = service.request(owner_id, book_id, idempotency_key)
    return JSONResponse(
        status_code=202, content=job.to_api(), headers={"Cache-Control": "no-store"}
    )


@router.get("/v1/books/{book_id}/full-summary")
def get_full_book_summary(book_id: str, owner_id: Owner, service: Service) -> JSONResponse:
    if not _valid_uuid(book_id):
        raise ApiProblemError(404, "BOOK_NOT_FOUND", "Book unavailable or not owned.")
    body = service.read(owner_id, book_id)
    return JSONResponse(content=body, headers={"Cache-Control": "private, no-store"})


@router.get("/v1/jobs/{job_id}")
def get_job(job_id: str, owner_id: Owner, service: Service) -> JSONResponse:
    if not _valid_uuid(job_id):
        raise ApiProblemError(404, "JOB_NOT_FOUND", "Job not found.")
    return JSONResponse(
        content=service.get_job(owner_id, job_id).to_api(), headers={"Cache-Control": "no-store"}
    )
