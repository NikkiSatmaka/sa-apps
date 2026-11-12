#!/usr/bin/env bash
#
# Wizard: menyiapkan service account Google Drive dan akun uji untuk verifikasi
# Drive NYATA (issue #27; backend/tests/integration/drive_live). Dihasilkan dengan
# skill /wizard.
#
# Menulis HANYA ke backend/.env.drive-live (harus di-ignore git, mode 0600). Tidak
# menyentuh .env utama. Kunci service account tidak pernah dicetak ke layar.
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1 && tput clear 2>/dev/null; then return 0; fi
  printf '\033[2J\033[3J\033[H'
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else false; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any, with write_env's single
# quotes or a plain dotenv double-quoted value undone.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line value sq="'\\''"; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  value="${line#*=}"
  if [[ "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; value="${value//"$sq"/\'}"
  elif [[ "$value" == \"*\" ]]; then
    value="${value:1:${#value}-2}"
    [[ "$value" == *[\\\$\"]* ]] && return 1   # escapes, $ or ": can't decode safely; ask again
  fi
  printf '%s' "$value"
}

# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret), edited
# with Readline. Fails at EOF with no input.
ask() {
  local key="$1" prompt="$2" current input s=$'\001' e=$'\002' p rc=0
  current=$(_existing "$key" || true)
  # Readline needs the colour codes wrapped in \001..\002 to place the cursor.
  p="  $s$BOLD$e$prompt$s$RESET$e "
  [[ -n "$current" ]] && p+="$s$DIM$e[Enter keeps current]$s$RESET$e "
  read -e -r -p "$p" input || rc=1
  if (( rc )) && [[ -z "$input" ]]; then return 1; fi
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask_secret KEY "Prompt" is like ask, but input is hidden.
ask_secret() {
  local key="$1" prompt="$2" current input rc=0
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || rc=1
  printf '\n'
  if (( rc )) && [[ -z "$input" ]]; then return 1; fi
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE upserts KEY='VALUE' into ENV_FILE (replaces any existing
# line) and sets $KEY. Idempotent. Creates ENV_FILE at mode 0600; writes through
# a symlink and keeps an existing file's mode.
write_env() {
  local key="$1" value="$2" tmp sq="'\\''"
  [[ -e "$ENV_FILE" ]] || (umask 077 && : > "$ENV_FILE")
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf "%s='%s'\n" "$key" "${value//\'/$sq}" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  printf -v "$key" '%s' "$value"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE sets a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES: author this section. One stage() per step the human takes.
# Replace the example below. Set TOTAL_STAGES to match the stages you write.
# Keep every stage inside run_wizard and the last line as is: bash then parses
# the whole file before the first prompt, so an edit mid-run can't break it.
# ──────────────────────────────────────────────────────────────────────────

run_wizard() {

TOTAL_STAGES=7

# File env khusus uji Drive. Jangan ke .env utama; berkas ini harus di-ignore git.
ENV_FILE="${ENV_FILE:-backend/.env.drive-live}"

banner "Portal SA — siapkan Google Drive untuk verifikasi live"

# ── 1. Pengaman: pastikan berkas kunci tidak mungkin ter-commit ───────────
stage "Pengaman: berkas kunci harus di-ignore git"
say "Kunci service account setara password. Sebelum apa pun, pastikan berkas"
say "penyimpannya tidak bisa masuk commit."
mkdir -p "$(dirname "$ENV_FILE")"
[[ -e "$ENV_FILE" ]] || (umask 077 && : > "$ENV_FILE")
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git check-ignore -q "$ENV_FILE"; then
    say "✓ $ENV_FILE sudah di-ignore git."
  else
    warn "$ENV_FILE BELUM di-ignore git."
    say "Wizard akan menambahkannya ke .git/info/exclude (khusus klon ini, tidak mengubah repo)."
    if confirm "Tambahkan sekarang?"; then
      printf '%s\n' "$ENV_FILE" >> "$(git rev-parse --git-path info/exclude)"
      if git check-ignore -q "$ENV_FILE"; then
        say "✓ sekarang di-ignore."
      else
        warn "masih tidak di-ignore; wizard dihentikan."
        exit 1
      fi
    else
      warn "Dibatalkan: kunci tidak boleh disimpan di berkas yang bisa ter-commit."
      exit 1
    fi
  fi
else
  warn "Bukan repo git; lewati pemeriksaan. Pastikan $ENV_FILE tidak masuk version control."
fi
note "Rute kunci: Google Cloud Console → berkas JSON unduhan → $ENV_FILE (mode 0600)."
pause

# ── 2. Proyek Google Cloud ────────────────────────────────────────────────
stage "Google Cloud: pilih atau buat proyek"
say "Pakai proyek KHUSUS uji (bukan proyek produksi) agar mudah dibersihkan."
open_url "https://console.cloud.google.com/projectcreate"
step "Buat proyek baru, mis. 'sa-portal-drive-test' (atau pilih proyek uji yang ada)."
step "Salin Project ID-nya (bukan nama): tampil di pemilih proyek dan di Dashboard."
ask GCP_PROJECT_ID "Tempel Project ID:"
if [[ ! "$GCP_PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  warn "Format Project ID tidak lazim ($GCP_PROJECT_ID)."
  confirm "Lanjut juga?" || exit 1
fi

# ── 3. Aktifkan Google Drive API ──────────────────────────────────────────
stage "Google Cloud: aktifkan Google Drive API"
open_url "https://console.cloud.google.com/apis/library/drive.googleapis.com?project=${GCP_PROJECT_ID}"
step "Klik 'Enable' (Aktifkan). Bila tombolnya 'Manage', API sudah aktif."
pause "Sudah aktif? Tekan Enter"

# ── 4. Service account ────────────────────────────────────────────────────
stage "Google Cloud: buat service account"
open_url "https://console.cloud.google.com/iam-admin/serviceaccounts/create?project=${GCP_PROJECT_ID}"
step "Service account name: sa-portal-drive-test"
step "Klik 'Create and continue'. JANGAN beri role apa pun (lewati langkah roles)."
step "Klik 'Done'."
step "Di daftar service account, salin kolom 'Email' (berakhiran .iam.gserviceaccount.com)."
ask SERVICE_ACCOUNT_EMAIL "Tempel email service account:"
if [[ "$SERVICE_ACCOUNT_EMAIL" != *.iam.gserviceaccount.com ]]; then
  warn "Bukan email service account (harus berakhiran .iam.gserviceaccount.com)."
  exit 1
fi
write_env DRIVE_LIVE_SERVICE_ACCOUNT_EMAIL "$SERVICE_ACCOUNT_EMAIL"

# ── 5. Kunci JSON ─────────────────────────────────────────────────────────
stage "Google Cloud: buat kunci JSON"
open_url "https://console.cloud.google.com/iam-admin/serviceaccounts/details/${SERVICE_ACCOUNT_EMAIL}/keys?project=${GCP_PROJECT_ID}"
step "Add key → Create new key → JSON → Create. Berkas .json terunduh otomatis."
warn "Jangan kirim berkas itu lewat chat/email, dan jangan taruh di dalam folder repo."
ask KEY_FILE "Path berkas JSON yang terunduh (mis. ~/Downloads/xxxx.json):"
KEY_FILE="${KEY_FILE/#\~/$HOME}"
if [[ ! -f "$KEY_FILE" ]]; then
  warn "Berkas tidak ditemukan: $KEY_FILE"
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 dibutuhkan untuk memadatkan JSON."
  exit 1
fi
if ! KEY_ONE_LINE=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("type") == "service_account", "bukan kunci service account"
for k in ("client_email", "private_key", "project_id"):
    assert d.get(k), "field " + k + " kosong"
print(json.dumps(d, separators=(",", ":")))
' "$KEY_FILE"); then
  warn "Berkas bukan kunci service account yang valid."
  exit 1
fi
KEY_EMAIL=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["client_email"])' "$KEY_FILE")
if [[ "$KEY_EMAIL" != "$SERVICE_ACCOUNT_EMAIL" ]]; then
  warn "Kunci milik $KEY_EMAIL, bukan $SERVICE_ACCOUNT_EMAIL."
  confirm "Tetap pakai kunci ini?" || exit 1
fi
write_env GDRIVE_SERVICE_ACCOUNT_KEY "$KEY_ONE_LINE"
unset KEY_ONE_LINE
say "Kunci tersimpan di $ENV_FILE (tidak ditampilkan)."
if confirm "Hapus berkas unduhan $KEY_FILE sekarang? (salinan di $ENV_FILE tetap ada)"; then
  rm -f -- "$KEY_FILE"
  say "✓ berkas unduhan dihapus."
fi

# ── 6. Akun Google uji ────────────────────────────────────────────────────
stage "Akun Google untuk peran uji"
say "Verifikasi memberi izin Drive ke 5 alamat. Semuanya HARUS akun Google yang nyata"
say "(Gmail atau Workspace). Alamat demo '*@portal-sa.local' pasti ditolak Google."
say "Alamat harus BERBEDA satu sama lain. Alias '+tag' pada Gmail dihitung akun yang sama,"
say "jadi jangan dipakai untuk membedakan peran."
note "Akun ini hanya diberi izin ke folder uji; mereka tidak perlu login."
ask LEAD_EMAIL     "Email Lead SA      :"
ask SA_EMAIL       "Email SA           :"
ask SALES_EMAIL    "Email Sales PIC    :"
ask PMO_EMAIL      "Email PMO Lead     :"
ask DELIVERY_EMAIL "Email Delivery Lead:"
_all=("$LEAD_EMAIL" "$SA_EMAIL" "$SALES_EMAIL" "$PMO_EMAIL" "$DELIVERY_EMAIL")
for e in "${_all[@]}"; do
  if [[ ! "$e" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
    warn "Format email tidak valid: $e"
    exit 1
  fi
  if [[ "$e" == *@portal-sa.local ]]; then
    warn "Alamat demo tidak bisa dipakai: $e"
    exit 1
  fi
done
_unik=$(printf '%s\n' "${_all[@]}" | tr '[:upper:]' '[:lower:]' | sort -u | wc -l)
if [[ "$_unik" -ne 5 ]]; then
  warn "Ada alamat yang sama; kelima peran harus memakai alamat berbeda."
  exit 1
fi
write_env DRIVE_LIVE_LEAD_EMAIL "$LEAD_EMAIL"
write_env DRIVE_LIVE_SA_EMAIL "$SA_EMAIL"
write_env DRIVE_LIVE_SALES_EMAIL "$SALES_EMAIL"
write_env DRIVE_LIVE_PMO_EMAIL "$PMO_EMAIL"
write_env DRIVE_LIVE_DELIVERY_EMAIL "$DELIVERY_EMAIL"

# ── 7. Kebijakan berbagi (khusus Workspace) ───────────────────────────────
stage "Workspace: kebijakan berbagi ke luar organisasi (opsional)"
say "Hanya relevan bila email uji memakai domain yang berbeda dari domain Workspace"
say "pemilik proyek Google Cloud. Bila semuanya Gmail biasa tanpa Workspace, lewati."
step "Admin console → Apps → Google Workspace → Drive and Docs → Sharing settings."
step "Pastikan berbagi ke pengguna di luar organisasi diizinkan (atau domain-nya masuk allowlist)."
if confirm "Buka Admin console sekarang?"; then
  open_url "https://admin.google.com/"
fi
pause "Selesai atau dilewati? Tekan Enter"

finish
say "Langkah berikutnya (dari root repo):"
say "  set -a; source $ENV_FILE; set +a"
say "  cd backend && GDRIVE_LIVE_TEST=1 uv run pytest -m drive_live -v"
note "Setelah selesai: hapus kunci uji di Cloud Console (service account → Keys → Delete)"
note "dan kosongkan $ENV_FILE. Kunci PRODUKSI harus kunci terpisah, diisi lewat Portainer."
}

run_wizard "$@"; exit
