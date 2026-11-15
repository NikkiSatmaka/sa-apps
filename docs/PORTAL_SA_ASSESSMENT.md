# Portal SA: Current-State Assessment

**Snapshot:** 2026-11-15  
**Purpose:** Evidence base for the strategic roadmap, not a security certification or production-readiness sign-off.

## Executive view

Portal SA is a substantial internal application with a clear domain model, real SA work-management features, and unusually strong automated test and coverage guardrails. Its best long-term asset is the combination of a relational domain model, explicit authorization rules, ADRs, and tests that constrain changes.

The main weakness is not lack of code. It is the gap between feature breadth and verified operation as a dependable work system: the main project list is unpaginated, two central frontend screens and two API routers are very large, some background effects are process-local, the live Google Drive suite has never run, and deployment/roadmap documentation contradicts current code. No current user telemetry, live browser evaluation, full accessibility review, production configuration, backup-restore exercise, or security penetration test was examined here. These scores are therefore repository-based engineering judgments, not measurements of user satisfaction or proof of runtime behavior.

The product direction for this assessment is settled: **SA work management first, with pre-sales funnel capabilities for filtering Sales-originated Opportunities and Projects**. An Opportunity entered into Portal SA is represented by the same Project through qualification, SA work, and closure; Sales PIC identifies Sales ownership separately from the record creator.

## Scores

Scale: 1 = materially weak; 5 = usable but important gaps; 10 = strong and well evidenced. Scores are qualitative, non-weighted judgments. Do not average them into a single “readiness” number.

| Aspect | Score | Assessment |
|---|---:|---|
| Product and workflow fit | **7/10** | The model covers intake, qualification, assignment, SA work, activity, documents, collaboration, and handover. Code supports subtasks, workload, role-specific flows, and project comments. Whether these workflows reduce real coordination effort is unmeasured. |
| Frontend workflows and maintainability | **6/10** | There is meaningful workflow coverage and some typed API/domain boundaries, but core screens are highly concentrated: project detail is 633 lines and project creation is 951 lines. The main API helper surface has multiple request paths and `apiCall` returns `any`. Visual usability, responsive behavior, and accessibility were not browser-tested. |
| Backend domain and persistence | **7/10** | PostgreSQL/SQLAlchemy models have relational constraints, Alembic migrations, a separate qualification state, soft deletion, SA assignments, subtasks, comments, and documents. Central authorization policy is explicit. The large routers indicate growing responsibility concentration, not a reason to split into services. |
| API contracts and scale behavior | **5/10** | Pydantic schemas and consistent response envelopes are a good base. `GET /projects` supports status/sort filters but loads the full matching result set; it has no page/limit parameters. The frontend’s `apiCall` boundary is untyped and response-envelope handling remains caller-specific. |
| Security and privacy | **6/10** | Strong foundations include Google OAuth, allowed-domain checks, fail-fast JWT secret validation, HttpOnly refresh cookies, short-lived one-use handoff codes, and centralized per-project authorization. A Google Calendar access token is stored in browser `localStorage`; this increases exposure if script execution is compromised. The rate limiter is in memory. No runtime header review, dependency audit, or penetration test was performed. |
| Integrations and background reliability | **5/10** | Drive provisioning has persisted `pending/provisioned/failed` states and tested fake boundaries. The real-Drive test suite is explicitly documented as never run. The SLA scheduler is single-instance only; email retries run in process-local `asyncio` tasks and can be lost on shutdown. |
| Testing and change control | **8/10** | CI defines backend unit and PostgreSQL 18 integration jobs, frontend type-check/tests/build, total coverage thresholds, and diff coverage gates. The documented thresholds are 90% lines / 80% branches. Those gates are strong regression controls, but they do not substitute for browser-level workflow or live-provider verification. No suite was run for this document. |
| Operations and deployment | **5/10** | Docker Compose includes PostgreSQL, a migration-init service, backend health reporting, and persistent volumes. The deployment guidance requires manual backups and has not demonstrated restore. Current Compose ports/configuration differ from README and deployment instructions; there is no operational evidence here for alerting, restore drills, or production readiness. |
| Product and engineering documentation | **4/10** | The glossary and ADR set preserve useful domain decisions. However, `docs/ROADMAP.md` contradicts its own later phase material and current code, while README and deployment instructions contain stale claims/configuration. The current docs cannot safely serve as one authoritative plan. |

## Aspect details and evidence

### Product and workflow fit

The app is no longer just a sales intake form. The repository describes SA assignment, activity logging, workload, collaboration, documents, and handover; the backend has an assignable `ProjectAssignment` relation and a lifecycle status plus a separate `qualification_state`. The permission model distinguishes read, write, status transitions, handover, and team management. This is a credible foundation for the agreed tracker-first product direction.

The evidence establishes that features and domain rules exist, not that the SA team uses them consistently or that they reduce status-chasing. Establish a usage baseline before setting numeric success targets. Use the current Opportunity/Project terminology consistently; do not introduce a separate “lead” entity unless the lifecycle decision justifies it.

Evidence: [README product overview](../README.md#L1-L25), [status model](../backend/app/core/status.py#L1-L71), [additional SA assignment](../backend/app/models/project_assignment.py#L1-L55), [project access policy](../backend/app/core/dependencies.py#L305-L398), [project listing and filters](../backend/app/api/projects.py#L328-L383).

### Frontend

The frontend implements role-aware intake, project details, status actions, assignment, document flows, project stories, and dashboards. Project creation handles a questionnaire, file upload, field errors, and per-role PIC selection; project detail composes project state, access checks, handover/assignment actions, documents, and activity summaries. The default SWR `fetcher` centralizes authenticated GETs, while mutations also use `apiRequest` and `apiCall`.

The maintainability risk is concentrated complexity rather than a lack of components: `projects/[id]/page.tsx` (633 lines) and `projects/new/page.tsx` (951 lines) own broad state and workflow behavior. The API helper has three request functions with different 401 behavior, and `apiCall` has an `any` return. The existing offline queue can queue generic JSON submissions, but project creation uses multipart `createProject` through `apiCall`; the README’s broad offline claim needs an end-to-end proof for real user submissions. No visual, keyboard, screen-reader, mobile, or real-user evaluation was done, so this score should not be read as a UI usability grade.

Evidence: [project detail](../frontend/src/app/%28protected%29/projects/%5Bid%5D/page.tsx), [project creation](../frontend/src/app/%28protected%29/projects/new/page.tsx), [API transport helpers](../frontend/src/lib/fetcher.ts#L98-L220), [project create client](../frontend/src/lib/api/projects.ts#L79-L89), [offline queue helper](../frontend/src/lib/offline-queue.ts#L241-L276).

### Backend, data, and APIs

The persistence model is appropriate for the current relational workflow: a Project is related to Users, additional SA assignments, collaborators, subtasks, documents, comments, activity logs, and notifications. Database check constraints enforce project and qualification states; foreign keys and indexes appear in the related models and integration tests. Alembic owns schema evolution, and Compose runs migrations in a separate init service before the API starts.

The main scaling constraint is the project list: `GET /projects` applies optional filters and sorting, then materializes every match and builds the response in memory. It has no pagination or total/count contract. Project comments are also returned as a full list. These are acceptable only while data volume remains small; pagination and stable response contracts should precede growth, not a premature database or service rewrite. Two API routers, `projects.py` (1,185 lines) and `assignment.py` (1,098 lines), have become large; modularize around stable use cases and preserve the current modular-monolith deployment.

Evidence: [Project model constraints and soft-delete filter](../backend/app/models/project.py#L240-L315), [ProjectAssignment](../backend/app/models/project_assignment.py#L17-L54), [project list endpoint](../backend/app/api/projects.py#L328-L413), [comment list endpoint](../backend/app/api/project_comments.py#L71-L96), [database engine/session](../backend/app/core/database.py#L13-L54), [Compose migration gate](../compose.yaml#L33-L60).

### Security and privacy

Positive evidence: production settings reject an empty or placeholder JWT key; OAuth refresh credentials use an HttpOnly cookie with `Secure` in production and `SameSite=Lax`; refresh tokens are rotated and stored by hash; one-time handoff codes are hashed and expire; project-level authorization is centralized; upload size/count and file types are constrained. These are meaningful controls, not proof of a complete threat model.

Material risk: Calendar OAuth access tokens are written to `localStorage` and then sent directly from the browser to Google Calendar. That token is distinct from the app’s HttpOnly refresh cookie; script injection could expose the Calendar credential. Decide whether the current scope and browser storage are acceptable, or move the credential handling server-side. The in-memory rate limiter is per process, so it is not a shared limit if the API is replicated. Project reads are intentionally open to every authenticated user under the recorded product decision; confirm that this remains appropriate for customer and pre-sales data. Data retention, security headers, dependency advisories, and deletion/backup behavior were not fully assessed.

Evidence: [refresh-cookie and origin checks](../backend/app/api/auth.py#L40-L60), [refresh-token rotation](../backend/app/services/auth_service.py#L339-L397), [JWT secret guard](../backend/app/core/config.py#L159-L175), [Calendar token storage](../frontend/src/components/CalendarSync.tsx#L206-L219), [in-memory rate limiter](../backend/app/core/rate_limiter.py#L61-L85), [authorization matrix](../backend/app/core/dependencies.py#L305-L398).

### Integrations and reliability

The code has explicit Drive provisioning status and separate live tests, while test integration fakes cover Drive, Gmail, Calendar, and LLM boundaries. The live Drive suite documentation says it has **never been run against real Google Drive**. This is a verification gap, not evidence that Drive is broken.

The SLA scheduler runs as one asyncio task in the API process and documents that multiple backend instances would duplicate actions. Email delivery uses retries but schedules them with `asyncio.create_task`; a process stop can interrupt pending work. These choices are defensible for a single-instance internal MVP only if their limits are explicit and tested. Before promising reliable notifications or scale-out, establish retry/recovery and duplicate-delivery behavior. A durable queue/outbox is a strategic option when the business requires delivery across process restarts; avoid adding distributed infrastructure before that requirement is real.

Evidence: [SLA scheduler limit](../backend/app/services/sla_scheduler.py#L1-L19), [email background scheduling](../backend/app/services/notification_service.py#L157-L198), [Drive live-test status](../backend/README.md#L117-L128), [Compose deployment shape](../compose.yaml#L5-L113).

### Testing, operations, and documentation

CI is stronger than the app’s “MVP” label suggests: backend unit and PostgreSQL integration jobs, frontend type-check, Vitest coverage, production build, and diff-coverage constraints are defined. The baseline percentages in `CONSTRAINTS.md` are historical recorded baselines, not a current test run. CI does not establish user workflow usability or real-provider correctness; the live Drive suite is excluded unless explicitly configured.

Operational docs need reconciliation before being used as a runbook. Current Compose maps the frontend to host port 3535 and backend to 127.0.0.1:8555. README and `docs/DEPLOYMENT.md` still give 3000/8000 examples; the deployment guide also shows `SECRET_KEY` and `CORS_ORIGINS=*`, while current settings use `JWT_SECRET_KEY` and an explicit CORS origin list. Compose documents manual database backup before deploy and notes that image rollback does not roll back schema. A backup/restore drill and observed health monitoring are not evidenced here.

The roadmap’s feature table says Product/admin/multi-SA and the two-field status model are not implemented, while the same document records later phases and decisions for them; current code includes those roles, assignments, and status fields. README’s “MVP Ready” status is a statement, not a readiness test. Treat the roadmap and deployment docs as needing reconciliation, not as current truth.

Evidence: [CI workflow](../.github/workflows/ci.yml#L32-L62), [frontend CI checks](../.github/workflows/ci.yml#L295-L363), [quality thresholds](../CONSTRAINTS.md#L6-L28), [Compose ports and backup note](../compose.yaml#L33-L113), [current settings validation](../backend/app/core/config.py#L159-L201), [roadmap contradictions](ROADMAP.md#L26-L45), [README readiness claim](../README.md#L329-L331), [deployment guide](DEPLOYMENT.md#L135-L157).

## Long-term strategic direction

1. **Make product truth coherent before adding more surface area.** Keep the tracker dominant and pre-sales filtering supportive. Reconcile the Opportunity-to-Project lifecycle, user outcomes, and a single roadmap source; preserve durable choices in ADRs and keep the glossary domain-only.
2. **Prove safe daily use before scaling architecture.** Verify the core project workflow, role boundaries, live integrations that are part of the workflow, backup restoration, and operational ownership. Start with the internal-team usage baseline; set numeric targets after observing it.
3. **Invest in leverage at stable seams.** Gradually split oversized frontend workflows and API routers by responsibility; introduce typed API contracts and pagination. Keep a modular monolith and relational database unless measured scale or team boundaries justify a larger architectural move.
4. **Make reliability proportional to business cost.** Document single-instance limits now. Add durable background work, shared rate limiting, or multi-instance scheduling when availability, delivery guarantees, or deployment growth make process-local behavior unacceptable.
5. **Close the feedback loop.** Add browser-level workflow and accessibility evidence alongside the existing unit/integration suite, measure the accepted product outcomes without collecting unnecessary personal data, and use operational signals to reorder the roadmap.

## Verification boundary

This assessment reviewed repository source, tests/configuration, CI definitions, and documentation. It did **not** run the test suites, launch the app in a browser, exercise production credentials, run the live Drive test, test backup restoration, review a live deployment, or perform a penetration/dependency audit. Scores and risk statements should be revisited when those proofs or real usage data become available.
