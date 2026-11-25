# 07 — Security, AWS Infrastructure and Operations

## 1. Security requirements (P0)

| ID | Control | Acceptance |
|---|---|---|
| SEC-01 | Cognito JWT authentication and ownership check | Two accounts cannot read or list each other's books |
| SEC-02 | Immutable conversation book/version binding | Changing request `book_id` or prompt cannot alter context |
| SEC-03 | Immediate access revocation on deletion | Queries, reader and source access fail once deletion begins |
| SEC-04 | Per-request book/version filter on retrieval | No cross-book vectors accepted even when retriever misbehaves |
| SEC-05 | Private S3 buckets, encryption, short-lived signed URLs | No public S3 access or anonymous raw document download |
| SEC-06 | Least-privilege IAM and secret isolation | Agent cannot read arbitrary storage prefixes or unrelated tables |
| SEC-07 | Uploaded files untrusted, sanitized and bounded | Parser resists corrupt content, oversized files, zip bombs |
| SEC-08 | No unverified output/streamed tokens | Failed support check shows refusal, not model draft |
| SEC-09 | Controlled retention/deletion | All data classes accounted for; purge audit trail |
| SEC-10 | Privacy-safe telemetry | Logs contain no full uploaded book text by default |

## 2. Deployment units (CDK in Python)

- **Frontend:** S3 private website origin + CloudFront Origin Access Control, HTTPS, secure headers and sane CSP.
- **Authentication:** Cognito user pool; SPA OAuth/OIDC authorization-code + PKCE. JWT authorizer at API Gateway and server-side ownership checks.
- **API:** API Gateway HTTP API + thin Lambda Python/FastAPI (Mangum) for JWT/authz, book ownership, quotas and public response contract; orchestration runs in AgentCore Runtime. Strict CORS, input size caps and rate limiting.
- **Upload:** S3 private raw objects, presigned POST with `content-length-range`, short expiry and required content type; server verifies magic bytes and actual object attributes.
- **Async jobs:** SQS with DLQ -> Lambda worker; max retries, idempotency, 15-minute Lambda limit. If large books exceed that, switch ingestion to Step Functions + Fargate rather than silently timing out.
- **Storage:** S3 versioned canonical/private artifacts (careful deletion of prior object versions), DynamoDB PAY_PER_REQUEST for book/job/thread metadata.
- **Retrieval:** Bedrock Knowledge Base + S3 Vectors. Use service role scoped to KB staging prefix and vector index.
- **Agent Runtime:** One Bedrock AgentCore Runtime hosting bounded LangGraph multi-agent subgraphs; Runtime invocations authorized only through trusted backend permissions and revalidated scoped book access.
- **Model:** Region-available Bedrock foundation model (select by measured accuracy/cost); isolate generation and verifier prompts, choose a separate verifier model only if testing justifies it.
- **Monitoring:** CloudWatch metrics, structured JSON logs, correlation/trace IDs, dashboards and alarms; CloudTrail for account audit. No prompt/book contents in ordinary logs.
- **Budget:** AWS Budgets with alert thresholds, token/requests/page/size quotas, daily model spending dashboard; tear down nonessential test infrastructure after tests.

## 3. Regional availability and compatibility gates

Before CDK deploy verify in chosen AWS Region: (a) desired Bedrock generation model, (b) embedding model for KB, (c) Knowledge Bases + S3 Vectors integration, (d) required service quotas, (e) AgentCore Runtime support and quotas. AWS availability changes; don't hard-code unverified Region or exact per-request model prices in the spec.

## 4. Authorization boundary details

- Book IDs are not credentials. Authorization uses `owner_id` from verified user identity.
- A guessed citation URL and chunk ID must return 404 for another user.
- Every signed reader link requires ownership validation; expiry target <= 10 minutes.
- Retrieval `equals(owner_id) AND equals(book_id) AND equals(book_version_id)` is mandatory, and returned hits are post-checked. Metadata filters alone are not the app's only tenant boundary.
- Agent role has no internet research tool and cannot list unrelated raw prefixes. If network egress exists, do not expose arbitrary HTTP tools.
- Back-end validates chapter IDs and selection anchors against canonical source maps.

## 5. Input threat controls

- Validate extension + MIME + magic bytes, compressed and decompressed size, maximum pages/sections/elements, parser wall time and memory.
- Parse EPUB as an untrusted ZIP; detect path traversal (`../`), dangerous filenames, XML entities, giant files and compressed zip bombs. Don't execute embedded JavaScript, external EPUB resources or active PDF content.
- Protect against prompt injection in book body; model context explicitly marks book passage as untrusted data, and tool permissions enforce limitations.
- Scan uploads using a suitable managed malware scanner when available; otherwise document threat gap and keep parser isolated with no broad credentials. Do not claim built-in malware scanning if not configured.

## 6. Privacy and copyright

- User must affirm they have rights to upload content for private analysis; do not bypass DRM.
- Use openly licensed/public-domain books for public portfolio demos. Do not publish uploaded copyrighted books in a demo repo or screenshots containing long book passages.
- Define retention policy with explicit account deletion and asynchronous purge. No permanent plaintext export or open sharing by default.
- Ensure model/data processing and AWS provider policies are reviewed before promising specific data residency or non-training guarantees.

## 7. Deployment order

1. Create dev/staging environments via CDK; set budgets and alarms first.
2. Deploy S3/CloudFront/Cognito/API/DynamoDB/SQS with least-privilege IAM.
3. Provision KB with S3 Vectors and a supported embedding model.
4. Run ingestion canary with openly licensed PDF and DRM-free EPUB; verify metadata filters and source round-trip.
5. Integrate Bedrock generation and verification.
6. Deploy guarded answer endpoint and automated evaluation.
7. Harden security, load test, capture clean demo and publish measured results.

## 8. Observability measurements

Log/tally by stage: parse duration; page count; chunks indexed; KB ingestion sync time/failure; Retrieve p50/p95; model latency and tokens; verifier verdict distribution; refusal rate; false refusal on eval; response p95; 4xx/5xx; DLQ count; daily cloud spend. Tag metrics with environment and operation, **not user text or book title**.

## 9. Operational failure policy

Rate limit -> 429; unavailable model/KB -> 503 with no fabricated answer; timeout -> safe error; bad metadata -> block response + security alert; missing source citation -> `verification_failed`; failed indexing -> book `failed`, retry permitted without duplicate versions; delete errors -> book stays inaccessible `deleting` until reconciled.

## 10. AgentCore deployment decision (v1.1)

**Selected:** AgentCore Runtime for one bounded LangGraph graph containing five logical specialist roles. Public API remains FastAPI-on-Lambda, because it handles auth, authorization, quotas and response serialization, **not** orchestration. Runtime is not exposed to arbitrary public book IDs or open tool invocation. The authenticated caller scope is revalidated by server-owned source tools before every retrieval/canonical read; an agent cannot change scope by modifying its prompt.

Do not create five AgentCore runtimes unless measurements prove independently scaling agent groups is worth the extra deployment/identity complexity. Start with one Runtime and per-agent subgraph telemetry. Summary tasks are asynchronous behind a queue/job status; limit concurrent mapper calls. Use model credentials through managed IAM, not static API keys in agent prompts. Instrument and alert by role: requests, token counts, p50/p95 duration, verification failures and cost.

Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/


## v1.4 budget and security controls

Approved AWS **target** `$50/month`, not a spending hard cap. AWS Budgets notification thresholds `$25 / $40 / $50`, app-level admission stop for new paid jobs when local spending ledger reaches `$40` pending approval, default per-full-book job estimate ceiling `$2.50`, bounded worker concurrency 2. Cost checks include generation, embeddings, retrieval, indexing, runtime, S3 and data transfer. Paid AWS deployment requires approved estimate, compatible Region/model IDs, service quota/cost canary, and a documented destroy/cleanup checklist. Avoid NAT gateways/always-on ECS/OpenSearch/EC2 by default under this budget. Authz/book_version checks also apply to summaries and generated artifacts.
