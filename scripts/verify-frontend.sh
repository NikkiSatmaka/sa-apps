#!/usr/bin/env bash
# ============================================
# Verifikasi frontend dengan output ringkas (hemat konteks)
# ============================================
# Penggunaan (disarankan lewat mise):
#   mise run verify-frontend                 # tsc + test (tanpa cakupan)
#   mise run verify-frontend src/x.test.tsx  # tsc + hanya test yang disebut
#   mise run verify-frontend --full          # tsc + test:coverage (gerbang) + cakupan diff + build, setara CI
#
# Gerbang cakupan diff (#98) memakai diff-cover dari lingkungan backend (`uv sync` di backend/)
# dan membandingkan dengan DIFF_BASE (default origin/main; `git fetch origin` dulu).
#
# Berhenti di langkah pertama yang gagal. Output penuh ditulis ke log; layar
# hanya menampilkan ekor kegagalan.
set -uo pipefail

full=0
if [[ "${1:-}" == "--full" ]]; then full=1; shift; fi

cd "$(dirname "$0")/../frontend"
log="$(mktemp -t verify-frontend.XXXXXX.log)"

step() { # step <judul> <perintah...>
  local title="$1"; shift
  if "$@" >"$log" 2>&1; then
    echo "OK   $title"
  else
    echo "GAGAL $title"
    tail -n 60 "$log"
    echo "--- Log penuh: $log"
    exit 1
  fi
}

step "tsc --noEmit" pnpm exec tsc --noEmit
if [[ $full == 1 ]]; then
  step "test:coverage (gerbang 90/80)" pnpm test:coverage
  step "cakupan diff (baris diubah >= 90%)" uv run --directory ../backend \
    python -m scripts.gerbang_cakupan_diff --base "${DIFF_BASE:-origin/main}" \
    --sisi frontend --frontend-lcov ../frontend/coverage/lcov.info
  head -n 3 "$log" # ringkasan angka diff (log langkah terakhir)
  NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api/v1}" step "build" pnpm run build
else
  step "test" pnpm exec vitest run "$@"
fi
