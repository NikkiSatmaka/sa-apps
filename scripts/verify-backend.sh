#!/usr/bin/env bash
# ============================================
# Verifikasi backend dengan output ringkas (hemat konteks)
# ============================================
# Penggunaan (disarankan lewat mise):
#   mise run verify-backend                         # suite unit
#   mise run verify-backend tests/test_x.py::test_y # satu test (loop merah/hijau)
#   mise run verify-backend --integration [target]  # suite integrasi di Postgres 18 sementara
#   mise run verify-backend --full                  # unit + integrasi + cakupan gabungan + cakupan diff (gerbang CI)
#
# --full juga menjalankan gerbang cakupan diff (#98) terhadap DIFF_BASE (default origin/main;
# jalankan `git fetch origin` dulu agar base terbaru). Perubahan belum di-commit ikut dinilai.
#
# Output penuh ditulis ke log; layar hanya menampilkan ringkasan atau ekor kegagalan.
# Postgres sementara memakai nama dan port acak, jadi aman dijalankan paralel dari
# beberapa worktree dan tidak menyentuh stack Docker Compose bersama.
set -uo pipefail

mode=unit
case "${1:-}" in
  --integration) mode=integration; shift ;;
  --full) mode=full; shift ;;
esac

cd "$(dirname "$0")/../backend"
log="$(mktemp -t verify-backend.XXXXXX.log)"
pg=""

cleanup() { [[ -n "$pg" ]] && docker stop "$pg" >/dev/null 2>&1; true; }
trap cleanup EXIT

start_pg() {
  pg="sa-test-pg-$$"
  docker run -d --rm --name "$pg" -e POSTGRES_PASSWORD=test \
    -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql postgres:18-alpine >/dev/null || return 1
  for _ in $(seq 1 60); do
    docker exec "$pg" pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
  done
  port="$(docker port "$pg" 5432/tcp | head -1 | sed 's/.*://')"
  export TEST_DATABASE_URL="postgresql+asyncpg://postgres:test@127.0.0.1:${port}/postgres"
}

run() { # run <pytest args...>; ringkas hasil
  uv run pytest -q -W ignore --tb=short -p no:cacheprovider "$@" >"$log" 2>&1
  local rc=$?
  if [[ $rc -eq 0 ]]; then
    tail -n 3 "$log"
  else
    tail -n 60 "$log"
    echo "--- GAGAL (exit $rc). Log penuh: $log"
  fi
  return $rc
}

case "$mode" in
  unit)
    run "$@"; exit $? ;;
  integration)
    start_pg || { echo "Gagal menjalankan Postgres sementara (docker aktif?)"; exit 1; }
    run -m integration "$@"; exit $? ;;
  full)
    start_pg || { echo "Gagal menjalankan Postgres sementara (docker aktif?)"; exit 1; }
    export COVERAGE_FILE=coverage-unit.data
    run --cov=app --cov-branch || exit $?
    export COVERAGE_FILE=coverage-integration.data
    run -m integration --cov=app --cov-branch || exit $?
    # Gerbang gabungan yang sama dengan job CI `cakupan-gabungan` (baris >= 90%, cabang >= 80%).
    export COVERAGE_FILE=coverage-gabungan.data
    uv run coverage combine --keep coverage-unit.data coverage-integration.data >/dev/null 2>&1
    uv run coverage json -o coverage.json >/dev/null 2>&1
    uv run python scripts/cakupan_gerbang.py coverage.json
    total=$?
    # Gerbang cakupan diff, setara job CI `cakupan-diff` untuk sisi backend.
    uv run coverage xml -o coverage.xml >/dev/null 2>&1
    uv run python -m scripts.gerbang_cakupan_diff --base "${DIFF_BASE:-origin/main}" \
      --sisi backend --backend-xml coverage.xml
    diff=$?
    exit $(( total != 0 ? total : diff )) ;;
esac
