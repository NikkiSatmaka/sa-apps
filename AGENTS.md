# AGENTS.md

Instruksi untuk AI coding agent di repository ini. File ini dimuat di setiap turn dan setiap sub-agent, jadi isinya hanya aturan yang tidak bisa disimpulkan dari kode, plus pointer ke dokumen rinci. Buka dokumen di pointer hanya saat cabangnya berlaku.

## Bahasa

Proyek ini berbahasa Indonesia. Tulis semua output dalam **bahasa Indonesia**: balasan, markdown, komentar, docstring, commit message, deskripsi PR. **Istilah teknis tetap bahasa Inggris**: nama di kode (field, class, enum, path), istilah engineering (build, deploy, stub, schema, migration, endpoint), istilah proses (branch, commit, merge, pull request, review), dan istilah keamanan (secret, credential, guardrail, prompt-injection).

## Pointer (buka sesuai cabang)

- **Apa yang seharusnya app lakukan** (alur bisnis, struktur data, integrasi) → [`SA Application/Spesifikasi_Teknis_Portal_SA.md`](SA%20Application/Spesifikasi_Teknis_Portal_SA.md), **ground truth produk**. Baca hanya flow/field yang disebut tiket. Bila spec dan kode berbeda, laporkan divergensinya; jangan diam-diam mengikuti salah satunya. `SA Application/Portal Activity Mapping & Report.pdf` adalah referensi tambahan.
- **Fase mana, apa kriteria selesainya** → [`docs/ROADMAP.md`](docs/ROADMAP.md) (indeks), lalu **hanya** berkas `docs/roadmap/fase-<N>.md` yang dikerjakan. Roadmap mengukur realita terhadap spec dan tidak mendefinisikan ulang perilaku produk.
- **Branching, commit, PR, verification gate, migration, keamanan** → [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Ambang cakupan, larangan melemahkan test** → [`CONSTRAINTS.md`](CONSTRAINTS.md).
- **Istilah domain** → [`GLOSSARY.md`](GLOSSARY.md); **keputusan desain** → `docs/adr/` (buka ADR yang menyentuh area kerja).
- **Mengerjakan tiket sebagai agen utama** (membuat worktree, mendelegasikan ke sub-agent, menulis brief) → [`docs/agents/worktree-dan-delegasi.md`](docs/agents/worktree-dan-delegasi.md). Sub-agent implementasi tidak membacanya.
- **Menjalankan test, hemat konteks** → bagian "Verification Gate" di `CONTRIBUTING.md`.
- `.kiro/specs/sa-portal-mvp/` bersifat historis; rencana aktif ada di `docs/ROADMAP.md`.

## Git (wajib)

- **Dilarang commit atau push ke `main`, tanpa pengecualian**, termasuk dokumentasi dan one-liner. Ditegakkan oleh branch protection GitHub dan pre-push hook di `.githooks/`. Jangan `--no-verify`. Hook belum aktif di clone baru: `git config core.hooksPath .githooks`.
- Setiap unit pekerjaan: feature branch dari `origin/main` terbaru (`feat|fix|refactor|docs/<slug>`), dikerjakan di **git worktree** `.worktrees/<slug>` dengan `--no-track`, lalu masuk ke `main` lewat pull request. Di checkout utama agen hanya membaca. Perintah lengkap ada di dokumen worktree di atas.
- Conventional Commits. Commit hanya saat pekerjaan siap. Stage file spesifik; jangan `git add .` atau `-A`.
- Jangan commit secret; tandai file yang mungkin memuatnya (`.env`, credential) dan jangan echo nilainya.
- Jangan ubah git config. Perintah destruktif (force push, `reset --hard`, `clean -f`) hanya dengan izin eksplisit user.

## Test-first (wajib)

Setiap perilaku baru atau berubah punya test yang ditulis lebih dulu dan terbukti merah karena alasan yang benar, lalu kode minimal sampai hijau, lalu refaktor (skill `tdd`). Bug fix dimulai dari test regresi. Perubahan schema wajib migration Alembic dan test migration di PR yang sama. Layanan eksternal (Gemini, Drive, Gmail, Calendar) di-fake di boundary. Pengecualian hanya dokumentasi atau konfigurasi tanpa perilaku; sebut alasannya di PR. Rincian dan pemilihan jenis test: bagian "Test-first" di `CONTRIBUTING.md`; larangan melemahkan test: `CONSTRAINTS.md`.

## Delegasi

Setiap tiket implementasi dikerjakan satu sub-agent (context window baru); agen utama mengurus worktree, brief, verifikasi, PR, dan CI. Sub-agent tidak push, tidak membuka PR, tidak menyentuh stack Compose atau `main`. Pengecualian yang boleh dikerjakan agen utama sendiri: dokumentasi atau konfigurasi tanpa perilaku, koreksi satu-dua baris, dan pekerjaan yang inti kesulitannya keputusan desain bersama user. Isi brief dan format laporan: dokumen worktree di atas.

## Struktur

`backend/` FastAPI (`app/api`, `services`, `models`, `schemas`, `core`) · `frontend/` Next.js App Router (`src/app`, `components`, `lib`, `store`) · toolchain di `mise.toml` (detail di `CONTRIBUTING.md`).

---

## Agent skills

- **Issue tracker**: GitHub Issues pada `NikkiSatmaka/sa-apps` via `gh` CLI. Lihat `docs/agents/issue-tracker.md`.
- **Triage labels**: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Lihat `docs/agents/triage-labels.md`.
- **Domain docs**: single-context (`GLOSSARY.md` + `docs/adr/`). Lihat `docs/agents/domain.md`.

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->
