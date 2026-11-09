#!/usr/bin/env bash
# ============================================
# Build & push image backend dan/atau frontend ke container registry
# ============================================
# Penggunaan (disarankan lewat mise):
#   mise run publish              # prompt versi backend + frontend
#   mise run publish backend      # hanya backend
#   mise run publish frontend     # hanya frontend
#   ./scripts/publish.sh [backend|frontend]
#
# Konfigurasi dibaca dari .env di root repo:
#   IMAGE_REGISTRY       (wajib, mis. docker.io atau ghcr.io)
#   IMAGE_OWNER          (wajib, owner/namespace registry)
#   BACKEND_IMAGE_TAG    (opsional, hanya dipakai sebagai versi saat ini di prompt)
#   FRONTEND_IMAGE_TAG   (opsional, idem)
#
# Versi backend dan frontend ditanyakan terpisah karena siklus rilisnya bisa
# berbeda. Kosongkan jawaban untuk melewati komponen tersebut.
#
# ATURAN PENOMORAN VERSI (WAJIB):
#   Format: vMAJOR.MINOR dengan MINOR selalu DUA digit.
#   - Increment per rilis: +0.01 (mis. v4.81 -> v4.82 -> v4.83 ...).
#   - Saat MINOR mencapai 89 lanjut ke 90 (v4.89 -> v4.90), bukan v4.9.
#   - Saat MINOR mencapai 99 naik major & reset (v4.99 -> v5.00).
#
# Prasyarat: Docker running dan sudah login ke registry
#   (mis. docker login ghcr.io -u <owner>)
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

ENV_FILE="${ENV_FILE:-.env}"

usage() {
  echo "Penggunaan: ./scripts/publish.sh [backend|frontend]"
  echo "Tanpa argumen: backend dan frontend ditanyakan versinya."
}

# --- Baca satu key dari .env tanpa `source` (nilai lain bisa berisi JSON/karakter khusus) ---
env_get() {
  local key="$1" line value
  [ -f "$ENV_FILE" ] || return 0
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  value="${line#*=}"
  value="${value%%[[:space:]]#*}"   # buang komentar inline
  value="${value#\"}"; value="${value%\"}"
  value="${value#\'}"; value="${value%\'}"
  printf '%s' "$value"
}

# --- Pilih komponen ---
BUILD_BACKEND=true
BUILD_FRONTEND=true
case "${1:-}" in
  "")       ;;
  backend)  BUILD_FRONTEND=false ;;
  frontend) BUILD_BACKEND=false ;;
  -h|--help) usage; exit 0 ;;
  *) echo "❌ Argumen tidak dikenal: $1"; usage; exit 1 ;;
esac

# --- Konfigurasi registry dari .env ---
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ File $ENV_FILE tidak ditemukan. Salin dari .env.example dulu."
  exit 1
fi
IMAGE_REGISTRY="$(env_get IMAGE_REGISTRY)"
IMAGE_OWNER="$(env_get IMAGE_OWNER)"
if [ -z "$IMAGE_REGISTRY" ] || [ -z "$IMAGE_OWNER" ]; then
  echo "❌ IMAGE_REGISTRY dan IMAGE_OWNER wajib diisi di $ENV_FILE."
  exit 1
fi
BACKEND_IMAGE="${IMAGE_REGISTRY}/${IMAGE_OWNER}/sa-portal-backend"
FRONTEND_IMAGE="${IMAGE_REGISTRY}/${IMAGE_OWNER}/sa-portal-frontend"

# --- Prompt versi per komponen (kosong = lewati) ---
validate_version() {
  [[ "$1" =~ ^v[0-9]+\.[0-9]{2}$ ]]
}

prompt_version() {
  local name="$1" current="$2" answer
  while true; do
    if [ -n "$current" ]; then
      read -r -p "Versi ${name} (saat ini: ${current}, kosong = lewati): " answer
    else
      read -r -p "Versi ${name} (kosong = lewati): " answer
    fi
    if [ -z "$answer" ] || validate_version "$answer"; then
      printf '%s' "$answer"
      return 0
    fi
    echo "❌ Format tidak valid. Wajib vMAJOR.MINOR dengan MINOR dua digit (v4.81, v4.90, v5.00)." >&2
  done
}

BACKEND_VERSION=""
FRONTEND_VERSION=""
[ "$BUILD_BACKEND" = true ]  && BACKEND_VERSION="$(prompt_version backend "$(env_get BACKEND_IMAGE_TAG)")"
[ "$BUILD_FRONTEND" = true ] && FRONTEND_VERSION="$(prompt_version frontend "$(env_get FRONTEND_IMAGE_TAG)")"

if [ -z "$BACKEND_VERSION" ] && [ -z "$FRONTEND_VERSION" ]; then
  echo "Tidak ada versi yang diisi. Tidak ada yang dirilis."
  exit 0
fi

# --- Cek Docker ---
if ! docker info > /dev/null 2>&1; then
  echo "❌ Docker belum running. Silakan start dulu."
  exit 1
fi

# --- Build & push ---
if [ -n "$BACKEND_VERSION" ]; then
  echo "📦 Building backend ${BACKEND_VERSION}..."
  docker build --platform linux/amd64 -t "${BACKEND_IMAGE}:${BACKEND_VERSION}" ./backend
  echo "📤 Pushing ${BACKEND_IMAGE}:${BACKEND_VERSION}..."
  docker push "${BACKEND_IMAGE}:${BACKEND_VERSION}"
  echo "✅ Backend done"
  echo ""
fi

if [ -n "$FRONTEND_VERSION" ]; then
  echo "📦 Building frontend ${FRONTEND_VERSION} (no-cache)..."
  docker build --platform linux/amd64 --no-cache -t "${FRONTEND_IMAGE}:${FRONTEND_VERSION}" ./frontend
  echo "📤 Pushing ${FRONTEND_IMAGE}:${FRONTEND_VERSION}..."
  docker push "${FRONTEND_IMAGE}:${FRONTEND_VERSION}"
  echo "✅ Frontend done"
  echo ""
fi

echo "========================================"
echo "✅ Publish selesai"
echo "========================================"
echo "📋 Langkah selanjutnya: set tag di .env produksi / stack Portainer, lalu update stack (pull image terbaru):"
[ -n "$BACKEND_VERSION" ]  && echo "   BACKEND_IMAGE_TAG=${BACKEND_VERSION}"
[ -n "$FRONTEND_VERSION" ] && echo "   FRONTEND_IMAGE_TAG=${FRONTEND_VERSION}"
exit 0
