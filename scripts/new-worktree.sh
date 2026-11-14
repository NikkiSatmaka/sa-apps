#!/usr/bin/env bash
# ============================================
# Buat git worktree baru dari origin/main terbaru, siap dikerjakan
# ============================================
# Penggunaan (disarankan lewat mise):
#   mise run new-worktree feat orang-4
#   ./scripts/new-worktree.sh <type> <slug> [--no-install]
#
# type: feat | fix | refactor | docs | chore
# Hasil: branch <type>/<slug> di .worktrees/<slug>, tanpa upstream (--no-track,
# supaya `git push` tidak mengarah ke main). Lalu menyalin file env lokal dari
# checkout utama dan menjalankan `uv sync` (backend) + `pnpm install` (frontend).
# Push pertama: git push -u origin <type>/<slug>
set -euo pipefail

type="${1:-}"
slug="${2:-}"
install=1
[[ "${3:-}" == "--no-install" ]] && install=0

if [[ ! "$type" =~ ^(feat|fix|refactor|docs|chore)$ ]] || [[ ! "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Penggunaan: new-worktree.sh <feat|fix|refactor|docs|chore> <slug-kebab-case> [--no-install]" >&2
  exit 2
fi

# Checkout utama = induk dari git common dir (berlaku juga bila dipanggil dari worktree lain).
main_root="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
dest="$main_root/.worktrees/$slug"
branch="$type/$slug"

if [[ -e "$dest" ]]; then
  echo "Worktree sudah ada: $dest" >&2
  exit 1
fi

git -C "$main_root" fetch origin --quiet
git -C "$main_root" worktree add --no-track -b "$branch" "$dest" origin/main

# File env lokal tidak di-track git; salin bila ada. Jangan di-commit.
for f in .env backend/.env frontend/.env.local; do
  [[ -f "$main_root/$f" ]] && cp "$main_root/$f" "$dest/$f"
done

if [[ "$install" == 1 ]]; then
  (cd "$dest/backend" && uv sync --quiet)
  (cd "$dest/frontend" && pnpm install --frozen-lockfile --silent)
fi

echo "Worktree siap: $dest (branch $branch)"
echo "Push pertama: git push -u origin $branch"
