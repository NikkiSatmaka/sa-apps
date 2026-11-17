# Portal SA deployment and recovery

This is the operator guide for the checked-in production Compose configuration (`compose.yaml`). Production Compose runs prebuilt container images; it does not build from the source checkout. `compose.local.yaml` is an opt-in development override and must not be used for production.

## Runtime and release path

`compose.yaml` defines:

| Service | Image/runtime | Host access |
|---|---|---|
| `db` | `postgres:18-alpine` | `127.0.0.1:5433` → container `5432` |
| `backend-init` | Same configured backend image as `backend`; one-shot `alembic upgrade head` | Internal only |
| `backend` | `${IMAGE_REGISTRY:-docker.io}/${IMAGE_OWNER:-nikkisatmaka}/sa-portal-backend:${BACKEND_IMAGE_TAG:-latest}` | `127.0.0.1:8555` → container `8000` |
| `frontend` | `${IMAGE_REGISTRY:-docker.io}/${IMAGE_OWNER:-nikkisatmaka}/sa-portal-frontend:${FRONTEND_IMAGE_TAG:-latest}` | Host `3535` → container `3000` |

PostgreSQL data is bind-mounted at `/opt/docker_srv/sa-portal/postgres-data` (PG18 stores its cluster below `18/docker`). Backend data and logs use sibling bind mounts. The named volumes depend on the Compose project/Portainer stack being named `sa-portal`; preserve that name and the host paths. Compose does not publish PostgreSQL or the backend on all host interfaces.

The checked-in release path is `scripts/publish.sh` (also `mise run publish [backend|frontend]`): it builds and pushes each selected image with a separately selected version tag. Set `BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` to the selected tags in the production Compose environment/stack, then update the stack with image pulling enabled. Keep the previous image tags and registry digests, and do not reuse a release tag for different contents; a captured `tag@sha256:digest` reference pins the exact image for recovery. Record which backend and frontend versions were deployed. Do not run `git pull` on a production host to update application code or overwrite its Compose/environment configuration. CI (`.github/workflows/ci.yml` and `browser-e2e.yml`) runs checks; it does not deploy or publish production images.

There is no checked-in production deployment workflow that establishes who has production access or who approves a release. Before operating, identify an authorized operator and approver from the organization's current access-control records. Do not infer either from repository authorship.

## Before each release

1. Confirm the target environment, maintenance/communications plan, current deployed image tags or digests, and a known-good previous image pair. Review the release and its Alembic revisions.
2. Assess migration compatibility against the currently deployed code and intended rollback code. Prefer expand/contract: add backward-compatible schema first, deploy code that works with old and new schema, migrate data if required, then remove obsolete schema in a later release after rollback to old code is no longer needed. An image rollback does **not** reverse a database migration. Treat destructive or non-backward-compatible changes as a separate controlled migration with a tested recovery plan; do not assume `alembic downgrade` is safe.
3. Take a consistent PostgreSQL custom-format backup and verify it is readable. Keep it outside the repository and on storage with access controls and capacity appropriate for sensitive production data:

   ```bash
   umask 077
   mkdir -p /opt/docker_srv/sa-portal/backups
   backup="/opt/docker_srv/sa-portal/backups/sa-portal-$(date -u +%Y%m%dT%H%M%SZ).dump"
   docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup"
   test -s "$backup"
   docker compose exec -T db pg_restore --list - < "$backup" >/dev/null
   ```

   Record the backup path, size, UTC time, deployed image digests, and current Alembic revision in the change record. A successful dump/listing is not a restore test; restore into an isolated PostgreSQL 18 database as described below on a scheduled basis and before high-risk changes. Do not claim a backup is restorable until that exercise has succeeded and its evidence is recorded.
4. Confirm enough disk space for the backup and database operation. Keep the previous database files and backup until the release is accepted under the organization's retention policy; no retention duration is specified here.

## Deploy and smoke check

Update only the selected image tags in the existing deployment configuration, preserving secrets, volume paths, stack name, and other runtime settings. Pull the selected images and update services using the established Portainer stack update or `./deploy.sh` only from the authorized deployment directory after confirming its Compose configuration, `.env`, project name, and host volume paths match the running stack. Otherwise, use the established Portainer stack update; do not apply a fresh source checkout's configuration. Never replace production `.env` with `.env.example`. The helper pulls prebuilt images only; the Compose dependency graph waits for a healthy database, runs `backend-init`, and starts `backend` only when the migration command exits successfully. A migration failure must leave the backend from this deployment stopped; inspect logs and resolve it rather than bypassing `backend-init`.

After services start, perform and record these checks from the VM:

```bash
docker compose ps
curl --fail --show-error http://127.0.0.1:8555/health
curl --fail --show-error --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:3535/login
docker compose exec -T backend alembic current
docker compose logs --since=10m db backend-init backend frontend
```

Health must report both API and database healthy; the frontend login route must return HTTP 200; Alembic must show the expected revision; and logs must not show startup, migration, or database errors. Then validate the externally routed HTTPS URL and one authorized user workflow in the deployed environment. Do not put credentials, tokens, or customer data in deployment evidence.

## Recovery decision

**Image rollback:** If the issue is isolated to application code and the current schema remains compatible with the previous application image, restore the previous backend and frontend tags/digests in deployment configuration and update the stack. Keep the migrated database in place. Confirm the backend starts, health is green, and the affected workflow works. Never assume an image rollback can undo schema or data changes.

**Database forward repair:** If the new schema migration succeeded but the previous code is incompatible, or the problem is caused by migration/data transition, keep the database at its migrated revision and deploy a corrected forward migration/application image. Use the pre-deploy backup only if a controlled recovery decision explicitly accepts losing writes made after that backup. Do not run an improvised downgrade or restore over the live database; stop writes, take and verify a fresh copy, and have the authorized operator/approver execute a reviewed recovery plan.

If a migration fails, preserve logs and database state, leave the backend stopped, and diagnose the failing revision. Fix forward with a reviewed migration or restore a verified backup into a separately validated recovery target before deciding whether to switch traffic. A restore can discard post-backup writes; reconcile that loss explicitly before any production cutover.

## Backup restore exercise

Run this exercise on an isolated recovery/test host or isolated PostgreSQL 18 instance, never against the production `db` service. Use compatible extensions/settings. Obtain a verified backup through the approved protected channel. The example creates a separate database in an isolated Compose `db` service; use a unique test name and remove only that test database after recording results:

```bash
read -r -p "Path to the verified backup recorded in the change record: " backup
test -s "$backup"
docker compose exec -T db pg_restore --list - < "$backup" >/dev/null
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" sa_restore_check'
docker compose exec -T db pg_restore -U sa_portal -d sa_restore_check --no-owner --exit-on-error - < "$backup"
docker compose exec -T db psql -U sa_portal -d sa_restore_check -v ON_ERROR_STOP=1 \
  -c 'select count(*) from projects' \
  -c 'select version_num from alembic_version'
docker compose exec -T db psql -U sa_portal -d sa_restore_check -v ON_ERROR_STOP=1 -c 'drop database sa_restore_check'
```

Use the actual configured database role (the Compose template defaults to `sa_portal`) if it differs. Compare representative row counts and the recorded Alembic revision with the source backup; check required tables, constraints, indexes, and application-level reads. Record PostgreSQL version, backup identifier, restore duration, validation results, and operator. This procedure has not been run against production as part of this repository change; successful execution requires a controlled environment and authorized data access.

## Operational responsibility and evidence

The person performing the release is responsible for recording exact image tags/digests, backup verification, migration compatibility assessment, smoke-check results, and any rollback/repair decision in the approved operational record. A separately authorized service/product owner must approve production-impacting operations, restoration, and traffic cutover according to the organization's access policy. Confirm actual named owners, approver, backup destination/access policy, maintenance window, and escalation path from current organizational records before production work; the repository does not establish them.

Repository evidence: production image/volume/service wiring and fail-closed migration ordering are in `compose.yaml`; image builds and tag selection are in `scripts/publish.sh`; Compose is explicitly the image-based production path in `CONTRIBUTING.md`; CI workflows run tests and browser checks but do not deploy. No production restore, deployment, smoke check, ownership mapping, or recovery exercise is asserted by this guide.
