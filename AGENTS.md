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

## Delegasi implementasi ke sub-agent (wajib)

Konteks agen utama terbatas dan cepat penuh bila ia sendiri membaca kode, menulis test, dan menjalankan suite. Karena itu **setiap tiket implementasi dikerjakan oleh satu sub-agent** (agen terdelegasi dengan context window baru), sedangkan agen utama mengurus alur dan verifikasi. Aturan ini berlaku untuk semua sesi dan harness.

**Agen utama:**

1. Membaca tiket, ADR, dan spec yang relevan secukupnya untuk menulis brief (bukan untuk mengerjakan tiketnya).
2. Membuat worktree dan branch dari `origin/main` (bagian Worktree di atas), lalu mengirim **satu brief lengkap** ke sub-agent.
3. Setelah sub-agent selesai: memeriksa diff dan ringkasannya, menjalankan sendiri verification gate yang relevan bila ringkasan tidak meyakinkan, membuka PR (deskripsi sesuai template, termasuk tabel perilaku → test), memantau CI, lalu menghapus worktree.
4. Menandai dengan jelas keputusan desain yang diambil sub-agent di luar tiket di deskripsi PR, dan menanyakan ke user bila keputusan itu berdampak luas.

**Brief ke sub-agent harus memuat** (sub-agent tidak melihat percakapan sebelumnya dan tidak bisa bertanya ke user di tengah jalan):

- Nomor dan isi tiket (`gh issue view`), tiket induk, dan blocking-nya; path ADR dan bagian spec yang menjadi ground truth.
- Path worktree dan nama branch; semua perintah dijalankan dengan cwd di worktree itu, dan sub-agent tidak boleh menyentuh checkout utama.
- Aturan `AGENTS.md` yang wajib: test-first dengan **commit merah terpisah** sebelum implementasi, test migration untuk perubahan schema, Conventional Commits, stage file spesifik, tidak ada commit ke `main`, tanpa `--no-verify`.
- Cara menjalankan verifikasi: Postgres 18 sementara (`backend/README.md`, jangan menyentuh stack Docker Compose bersama), `uv run pytest` dan `-m integration`, `pnpm test` / `tsc --noEmit` / `pnpm build`, serta gerbang cakupan. Container sementara harus dihentikan di akhir.
- Batas lingkup: apa yang termasuk tiket dan apa yang bukan (tiket lain yang menyentuh area sama), serta larangan menurunkan ambang cakupan, menambah `skip`/`xfail`, atau melemahkan assertion.
- Bila ada keputusan yang tidak ditentukan tiket, ADR, atau spec: pilih opsi paling konservatif dan **catat** di laporan akhir, jangan mengarang perilaku produk.
- Format laporan akhir: ringkasan perubahan, daftar test baru beserta perilaku yang dilindungi, test lama yang diubah dan alasannya, hasil verifikasi (angka), hal yang belum terverifikasi, dan keputusan di luar tiket.

**Sub-agent tidak boleh:** push, membuka PR, mengubah issue, menyentuh stack Compose atau database bersama, atau mengubah `main`. Itu tugas agen utama setelah laporan diterima.

**Pengecualian (boleh dikerjakan agen utama sendiri):** perubahan dokumentasi atau konfigurasi tanpa perilaku, koreksi satu-dua baris yang sudah jelas, dan pekerjaan yang inti kesulitannya adalah **keputusan desain bersama user** (grill, penentuan ADR/spec). Bila ragu apakah tiket butuh keputusan di tengah jalan, tanyakan ke user sebelum mendelegasikan, bukan sesudahnya.

**Beberapa tiket:** tiket yang saling bergantung (lihat `blocked by`) dikerjakan berurutan dan berbasis `main` setelah PR sebelumnya digabung. Tiket yang independen boleh dikerjakan paralel, masing-masing dengan worktree, branch, dan sub-agent sendiri.

---

## Toolchain

- Toolchain dikelola dengan [mise](https://mise.jdx.dev); versi di-pin di `mise.toml` pada root. Jalankan `mise install` untuk menyamakan versi lokal.
- Saat ini: Python 3.14 (dikelola uv, lihat `backend/.python-version`), Node 26, pnpm 12 (di-pin major) sebagai package manager frontend. PostgreSQL 18 via Docker Compose.
- Docker tetap sumber kebenaran untuk build produksi; jaga `mise.toml` dan Dockerfile selaras saat menaikkan versi. Detail di `CONTRIBUTING.md`.

---

## Test-first (wajib)

Setiap perilaku baru **harus punya test yang ditulis lebih dulu** dan terbukti gagal sebelum kodenya ada. Tujuannya: saat PR masuk ke `main`, sudah jelas dan terbukti apa yang berfungsi dan apa syarat lulusnya. Gunakan skill `tdd` (red → green → refactor).

- **Cakupan aturan:** setiap fungsi, method, endpoint, komponen, aturan bisnis, dan cabang kondisi (`if`/`else`, penanganan error) yang ditambah atau diubah perilakunya.
- **Urutan kerja:** (1) tulis test untuk perilaku yang dimaksud dan jalankan sampai **gagal karena alasan yang benar**; (2) tulis kode seminimal mungkin sampai test hijau; (3) refaktor dengan test tetap hijau. Jangan menulis kode lalu menyusul test sesudahnya. Bila memungkinkan, commit test (merah) sebelum commit implementasi.
- **Bug fix:** mulai dari test regresi yang mereproduksi bug (gagal), baru perbaiki.
- **Refaktor murni (tanpa perubahan perilaku):** test yang ada harus tetap hijau tanpa diubah. Bila perilaku yang akan Anda sentuh belum terlindungi test, tulis test-nya dulu sebelum merefaktor.
- **Perubahan schema:** wajib ada test migration (upgrade, downgrade, dan constraint) di test integrasi.
- **Test perilaku, bukan implementasi:** tegaskan hasil yang terlihat (respons API, status akhir, data tersimpan, teks/peran di UI, efek samping lewat fake), bukan urutan pemanggilan internal.
- **Pilih seam yang tepat:** logika murni → test unit; SQL, constraint, authz per peran, dan migration → test integrasi di Postgres sungguhan; UI → React Testing Library + MSW. Layanan eksternal (Gemini, Drive, Gmail, Calendar) di-fake di boundary, bukan dipanggil sungguhan.
- **Pengecualian:** perubahan dokumentasi murni atau konfigurasi tanpa perilaku. Sebutkan alasannya di deskripsi PR. Kode yang sulit diuji bukan alasan; ubah desainnya agar bisa diuji.
- **Dilarang:** menurunkan ambang cakupan, menambah `skip`/`xfail` tanpa issue, melemahkan atau menghapus assertion agar test lolos, dan menandai pekerjaan selesai bila test baru belum ada. Aturan lengkap: [`CONSTRAINTS.md`](CONSTRAINTS.md) bagian 2.
- **Bukti di PR:** deskripsi PR memuat daftar perilaku baru beserta nama test yang melindunginya (checklist ada di template PR). Reviewer berhak menolak PR yang perilaku barunya tidak punya test.

Gerbang yang ditegakkan CI saat ini: seluruh test lolos dan cakupan **total** baris ≥ 90% / cabang ≥ 80%. Gerbang itu belum menjamin bahwa *setiap perubahan* membawa test-nya sendiri (kode tak teruji dalam jumlah kecil tidak menggeser angka total), jadi aturan di atas tetap menjadi tanggung jawab author dan reviewer sampai gerbang per-perubahan tersedia.

---

## Verification gate

CI otomatis (`.github/workflows/ci.yml`) menjalankan test unit, integrasi, dan frontend beserta gerbang cakupan; ruleset `Core` pada `main` mewajibkan check-nya hijau sebelum merge. Sebelum menandai pekerjaan selesai atau membuka PR, verifikasi sendiri lebih dulu (detail di `CONTRIBUTING.md`):

- **Backend** — test unit dan integrasi lolos (`backend/README.md` menjelaskan cara menjalankannya) dan app bisa di-import/start bersih. Test di `backend/tests/`, setup di `backend/pyproject.toml`.
- **Frontend** — lolos type-check, test, dan build tanpa error. Script di `frontend/package.json`.
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

Issue di-track di GitHub Issues pada `NikkiSatmaka/sa-apps` (via `gh` CLI). Lihat `docs/agents/issue-tracker.md`.

### Triage labels

Label kanonik default: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Lihat `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` di root + `docs/adr/`. Lihat `docs/agents/domain.md`.
