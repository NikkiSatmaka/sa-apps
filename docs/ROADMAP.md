# Portal SA Strategic Roadmap

**Purpose:** The concise strategic source for improving Portal SA. This is an ordered direction, not a dated delivery promise or a production-readiness certification. Detailed repository evidence and limitations live in [the current-state assessment](PORTAL_SA_ASSESSMENT.md); durable domain and architecture rationale belongs in the glossary, ADRs, and implementation issues.

## Product direction

Portal SA is an SA work-management tracker first. It also supports pre-sales work by filtering Sales-originated Opportunities and Projects. An Opportunity becomes the same Project when it enters Portal SA; do not introduce a separate lead entity without evidence that the lifecycle needs one.

Sales and Product Manager (PM) share the requester experience in this portal, while their domain responsibilities and ownership fields remain distinct. Prioritize SA ownership, remaining work, and progress visibility over new funnel breadth or generic dashboard work.

## Outcomes and evidence

Improve:

- Visibility into who owns each project and what work remains.
- Freshness of project progress and assignment queues.
- Avoidable status-chasing outside the tracker.

These are intended outcomes, not measured results. The assessment scores are qualitative repository-based judgments, not user-satisfaction or runtime measurements; do not average them into a single readiness score. Collect the agreed four-week representative baseline before setting numeric targets ([baseline](https://github.com/NikkiSatmaka/sa-apps/issues/189), [targets](https://github.com/NikkiSatmaka/sa-apps/issues/190)).

## Ordered portfolio

### 1. Prove safe, operable use

First implementation slice: stop persistently storing Google Calendar OAuth access tokens in browser `localStorage`; prefer the protected server-side session, with memory-only browser storage as the fallback. This is a focused response to a known credential-exposure risk, not approval to expand Calendar synchronization.

Then close the evidence gaps required for sustained internal use:

- Add required browser E2E checks for critical role-specific workflows; verify responsive behavior and WCAG 2.1 AA.
- Verify the real Google Drive workflow, including its failure path, in a controlled environment.
- Exercise database backup restoration; document compatible migrations, image rollback and database forward-repair, deployment smoke checks, and operational ownership.
- Reconcile deployment instructions with current configuration before relying on them as runbooks.

These are missing proofs, not evidence that the corresponding features are broken. Existing unit, integration, coverage, type-check, and build gates remain in place.

### 2. Make best-effort work visible and safe to recover

Integrations and background effects remain best-effort and must not silently appear successful. Persist status, attempts, timestamps, outcomes, and actionable failures; show failures against the affected project or action; provide safe manual retry or repair. Do not promise eventual success or replay after restart unless the operation is made safe and idempotent. Apply this consistently to Drive, email, SLA side effects, and Calendar actions.

Keep the core project workflow usable when an integration fails. Preserve the current single-backend-instance boundary until scheduling and side effects are safe across instances; a broker, microservices, and high-availability target are not justified now.

### 3. Prepare data and API seams for growth

Add capped, deterministic pagination to project lists using the simple page/page-size contract. Migrate every consumer—including project pickers—before making a page limit the default. Paginate comments when their volume warrants it. Introduce typed response and error contracts as API features are touched. Keep authorization centralized and covered by role/relationship tests.

### 4. Reduce maintenance cost incrementally

Split large frontend workflows and backend routers around cohesive responsibilities, preserving behavior and adding tests/browser evidence at the seams. Do not use line counts as targets and do not undertake a wholesale rewrite. Keep the PostgreSQL relational model and modular-monolith deployment unless observed scale or team boundaries justify a different choice.

## Deferred decisions

- Numeric outcome targets follow the representative usage baseline; no values are assumed before measurement ([baseline](https://github.com/NikkiSatmaka/sa-apps/issues/189), [targets](https://github.com/NikkiSatmaka/sa-apps/issues/190)).
- A permanent retention and deletion schedule for database records, backups, customer documents, and derived data remains future policy work ([retention decision](https://github.com/NikkiSatmaka/sa-apps/issues/191)).
- The usage or availability trigger for stronger delivery guarantees or support beyond one backend instance remains unspecified; revisit when representative usage and deployment needs provide evidence.

## Source of truth

This document owns the concise strategic order. The [assessment](PORTAL_SA_ASSESSMENT.md) owns current-state scores, evidence, and limitations. ADRs own durable architectural rationale; implementation issues own concrete changes and acceptance evidence. The former feature/phase plan is retained as [`ROADMAP-LEGACY.md`](ROADMAP-LEGACY.md), and its linked phase files are historical material, not current commitments; review or retire them separately before treating their details as active.

Strategy and sequencing decisions are recorded in [Portal SA strategic roadmap and assessment](https://github.com/NikkiSatmaka/sa-apps/issues/176).