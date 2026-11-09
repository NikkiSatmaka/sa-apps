# AGENTS.md

Instruksi untuk AI coding agent yang bekerja di repository ini. Dirancang portabel lintas contributor, model, dan harness — ikuti instruksi ini apa pun tool yang Anda jalankan.

File ini melengkapi, bukan menggandakan, dokumen lain. Sumber kebenaran:

- **[`SA Application/Spesifikasi_Teknis_Portal_SA.md`](SA%20Application/Spesifikasi_Teknis_Portal_SA.md)** — **ground truth produk**: alur kerja bisnis (workflow), struktur data, dan integrasi layanan yang app ini maksudkan. Ini menentukan apa yang *seharusnya* dibangun.
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — workflow lengkap: branching, commit, pull request, verification gate, migration, keamanan. **Baca dan ikuti ini.**
- **[`docs/ROADMAP.md`](docs/ROADMAP.md)** — apa yang sedang dibangun, dalam urutan apa, dengan kriteria selesai per fase.
- **[`README.md`](README.md)** — gambaran produk dan setup untuk manusia.

Bagian di bawah hanya memuat aturan khusus agen yang tidak bisa Anda simpulkan dari kode.

---

## Bahasa

- Proyek ini berbahasa Indonesia, ditujukan untuk user berbahasa Indonesia.
- Tulis semua output dalam **bahasa Indonesia**: balasan chat, dokumen markdown, komentar, docstring, commit message, deskripsi PR, dan pesan yang menghadap user.
- **Istilah teknis tetap bahasa Inggris** — nama di dalam kode (field, class, enum, path), istilah engineering (build, deploy, stub, schema, migration, endpoint, state machine), istilah proses (branch, commit, merge, pull request, review), dan istilah keamanan (secret, credential, guardrail, prompt-injection). Jangan terjemahkan istilah ini ke bahasa Indonesia.

---

## Ground truth produk (wajib)

Spesifikasi di **[`SA Application/Spesifikasi_Teknis_Portal_SA.md`](SA%20Application/Spesifikasi_Teknis_Portal_SA.md)** adalah sumber kebenaran untuk *perilaku produk yang dimaksudkan* — alur kerja bisnis (4 flow: Pre-Sales Request & AI Scoring, Dokumen/DQ Gating, Activity Mapping & Project Story, Post-Sales & PMO Handover), struktur data, dan integrasi Google Workspace + Gemini AI.

- Saat ragu tentang **apa** yang seharusnya app lakukan (bukan **bagaimana** kode sekarang bekerja), spec ini menang atas kode, README, dan asumsi Anda.
- `docs/ROADMAP.md` mengukur **realita implementasi terhadap spec ini**: apa yang sudah ✅, partial 🟡, atau belum 🔴. Roadmap tidak boleh mendefinisikan ulang perilaku produk — kalau roadmap dan spec berbeda soal *apa* yang dibangun, spec yang benar dan roadmap harus dikoreksi.
- Saat mengimplementasikan atau mengubah fitur, periksa spec untuk flow/field/integrasi yang relevan sebelum mendesain. Kalau spec dan kode berbeda, laporkan divergensi itu — jangan diam-diam ikut salah satunya.
- Catatan: ada juga `SA Application/Portal Activity Mapping & Report.pdf` sebagai referensi tambahan. File `.md` adalah ground truth tertulis utama; PDF melengkapi.

---

## Git workflow (wajib)

- **Dilarang commit langsung ke `main` — tanpa pengecualian.** Termasuk perubahan dokumentasi dan one-liner. Aturan ini ditegakkan secara mekanis: branch protection GitHub pada `main` (penjaga utama, tidak bisa di-bypass) + pre-push hook lokal di `.githooks/` (umpan balik cepat). Jangan pernah `merge`/`push` ke `main` dari lokal — selesaikan pekerjaan di feature branch, push branch itu, lalu buka PR.
- Jika git belum mengenali hook repo (clone baru tanpa mise), arahkan sekali: `git config core.hooksPath .githooks` (atau `mise run setup-hooks`). Pengguna mise otomatis via `[hooks] enter`. Jangan pakai `--no-verify`.
- Setiap unit pekerjaan: buat feature branch dari `main` terbaru, lalu masuk ke `main` lewat pull request.
- Nama branch mengikuti convention di `CONTRIBUTING.md`: `feat/<slug>`, `fix/<slug>`, `refactor/<slug>`, `docs/<slug>`.
- Commit memakai [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).
- Buat commit hanya ketika pekerjaan siap. Stage file secara spesifik — jangan `git add .` atau `git add -A`.
- Jangan pernah commit secret. Jika sebuah file kemungkinan memuat secret (`.env`, credential, token), tandai sebelum staging dan jangan echo nilainya.
- Jangan ubah git config. Jangan pakai perintah git destruktif (force push, reset --hard, clean -f) tanpa izin eksplisit user.

### Worktree (wajib untuk agen)

Checkout utama di root repo milik manusia, dan beberapa agen bisa berjalan paralel di repo yang sama. Kalau semua berbagi satu working tree, satu `git checkout` dari pihak lain diam-diam memindahkan commit Anda ke branch yang salah. Karena itu, setiap agen mengerjakan setiap branch di **git worktree** sendiri. Di checkout utama, agen hanya membaca. Edit, `checkout`, dan commit dilakukan di worktree.

- Buat worktree dari `main` terbaru di `.worktrees/<slug>` (folder ini di-ignore git), lalu jalankan semua perintah dengan cwd di worktree itu:
  ```bash
  git fetch origin
  git worktree add --no-track -b <type>/<slug> .worktrees/<slug> origin/main
  ```
  `--no-track` wajib. Tanpa itu, upstream branch baru menjadi `origin/main`, sehingga `git push` mengarah ke `main` dan ditolak pre-push hook. Push pertama: `git push -u origin <type>/<slug>`.
  Untuk melanjutkan branch yang sudah ada (mis. revisi review PR): `git worktree add .worktrees/<slug> <type>/<slug>`.
- File untracked tidak ikut ke worktree. Jalankan `uv sync` di `backend/` dan `pnpm install` di `frontend/`. Bila perlu, salin `.env`, `backend/.env`, dan `frontend/.env.local` dari checkout utama, tapi jangan di-commit.
- Stack Docker Compose lokal dan DB-nya dipakai bersama oleh semua branch. Verifikasi backend dari worktree lewat pytest, atau panggil app in-process (`httpx.ASGITransport`) ke DB yang sedang jalan. Minta persetujuan user sebelum rebuild atau restart stack: DB mungkin sudah di-migrate oleh branch lain, sehingga `alembic upgrade head` di branch Anda gagal.
- Setelah PR dibuat dan pekerjaan selesai, hapus worktree-nya dengan `git worktree remove .worktrees/<slug>`. Branch-nya tetap ada untuk PR.

---

## Toolchain

- Toolchain dikelola dengan [mise](https://mise.jdx.dev); versi di-pin di `mise.toml` pada root. Jalankan `mise install` untuk menyamakan versi lokal.
- Saat ini: Python 3.12, Node 26, pnpm 12 (di-pin major) sebagai package manager frontend. PostgreSQL 18 via Docker Compose.
- Docker tetap sumber kebenaran untuk build produksi; jaga `mise.toml` dan Dockerfile selaras saat menaikkan versi. Detail di `CONTRIBUTING.md`.

---

## Verification gate

Belum ada CI otomatis. Sebelum menandai pekerjaan selesai atau membuka PR, verifikasi manual (detail di `CONTRIBUTING.md`):

- **Backend** — test suite lolos dan app bisa di-import/start bersih. Test di `backend/tests/`, setup di `backend/pyproject.toml`.
- **Frontend** — lolos type-check dan build tanpa error. Script di `frontend/package.json`.
- **Full stack** — untuk perubahan runtime (migration, env var, service startup), konfirmasi stack naik via Docker Compose dan `/health` healthy.
- Sebuah perubahan belum selesai hanya karena command keluar tanpa error. Verifikasi terhadap perilaku yang dimaksud.

---

## Database

- Perubahan schema wajib disertai migration Alembic di `backend/alembic/versions/` dalam PR yang sama dengan perubahan model SQLAlchemy.
- Jangan andalkan auto-create table saat startup sebagai mekanisme migration.

---

## Struktur proyek (orientasi cepat)

- `backend/` — FastAPI (Python). `app/api` (router), `app/services` (business logic), `app/models` (SQLAlchemy), `app/schemas` (Pydantic), `app/core` (config, database, middleware).
- `frontend/` — Next.js (TypeScript, App Router). `src/app` (page), `src/components`, `src/lib` (API client), `src/store` (Zustand).
- `.kiro/specs/sa-portal-mvp/` — spec asli (requirements, design, tasks). Perlakukan sebagai historis; `docs/ROADMAP.md` adalah rencana aktif.

---

## Pengerjaan overhaul MVP saat ini

Overhaul MVP yang sedang berjalan dikerjakan **satu fase roadmap per branch** (`feat/phase-<N>-<slug>`), satu fase per waktu, diverifikasi terhadap kriteria selesai di `docs/ROADMAP.md`. Update checkbox roadmap di branch yang sama dengan pekerjaannya. Detail di bagian "Workflow Overhaul Saat Ini" pada `CONTRIBUTING.md`.
---

## Agent skills

### Issue tracker

Issue di-track di GitHub Issues pada `apeuta/sa-apps` (via `gh` CLI). Lihat `docs/agents/issue-tracker.md`.

### Triage labels

Label kanonik default: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Lihat `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` di root + `docs/adr/`. Lihat `docs/agents/domain.md`.
