#!/usr/bin/env bash
#
# Safe image-based deployment helper for the production Compose configuration.
# This does not pull source, build images, stop the stack, or remove volumes.

set -Eeuo pipefail

cd "$(dirname "$0")"

for command in docker curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$command" >&2
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  printf 'ERROR: Docker Compose V2 is required.\n' >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  printf 'ERROR: .env is required; do not replace the deployment environment with a source checkout template.\n' >&2
  exit 1
fi

docker compose config --quiet

backup_dir="${BACKUP_DIR:-/opt/docker_srv/sa-portal/backups}"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
umask 077
backup="$(mktemp "$backup_dir/sa-portal-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX.dump")"

printf 'Creating and validating database backup: %s\n' "$backup"
umask 077
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup"
if [[ ! -s "$backup" ]]; then
  printf 'ERROR: database backup is empty; deployment stopped.\n' >&2
  exit 1
fi
docker compose exec -T db pg_restore --list - < "$backup" >/dev/null

printf 'Pulling configured backend and frontend images; database image is unchanged.\n'
docker compose pull backend-init backend frontend

printf 'Starting services. backend-init must complete successfully before backend starts.\n'
if ! docker compose up -d --no-build db backend-init backend frontend; then
  printf 'ERROR: service startup or migration failed; inspect state below. No rollback or volume cleanup was attempted.\n' >&2
  docker compose ps
  docker compose logs --tail=100 db backend-init backend frontend
  exit 1
fi

printf 'Waiting for backend health check.\n'
healthy=false
for ((attempt = 0; attempt < 30; attempt++)); do
  if curl --fail --silent --show-error http://127.0.0.1:8555/health >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  printf 'ERROR: backend health check failed; inspect migration and service logs. No rollback or volume cleanup was attempted.\n' >&2
  docker compose ps
  docker compose logs --tail=100 db backend-init backend frontend
  exit 1
fi

printf 'Waiting for frontend login route.\n'
frontend_ready=false
for ((attempt = 0; attempt < 30; attempt++)); do
  if curl --fail --silent --show-error --output /dev/null http://127.0.0.1:3535/login; then
    frontend_ready=true
    break
  fi
  sleep 2
done
if [[ "$frontend_ready" != true ]]; then
  printf 'ERROR: frontend login route did not return HTTP 200.\n' >&2
  docker compose ps
  docker compose logs --tail=100 frontend
  exit 1
fi
curl --fail --show-error --output /dev/null --write-out 'Frontend HTTP %{http_code}\n' http://127.0.0.1:3535/login
docker compose exec -T backend alembic current
docker compose ps
docker compose logs --since=10m db backend-init backend frontend

printf 'Deployment checks passed. Backup: %s\n' "$backup"
printf 'Validate the externally routed HTTPS URL and an authorized user workflow before accepting the release.\n'
