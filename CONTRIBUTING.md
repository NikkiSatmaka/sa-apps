# Berkontribusi ke Portal SA

Panduan ini menjelaskan cara kita bekerja di repository ini: branching, commit, pull request, dan verifikasi yang diharapkan sebelum apa pun di-merge. Baca ini sebelum membuka PR.

Untuk *apa* yang sedang kita bangun dan dalam urutan apa, lihat [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Toolchain

Repo ini memakai [mise](https://mise.jdx.dev) untuk mengelola versi toolchain agar konsisten lintas contributor. Versi di-pin di `mise.toml` pada root repo.

Setup sekali:

1. Install mise — lihat [panduan instalasi mise](https://mise.jdx.dev/getting-started.html).
2. Dari root repo, jalankan `mise install` untuk memasang versi tool yang di-pin.

Tool yang dikelola saat ini:

| Tool | Versi (pin) |
|------|-------------|
| Node.js | 26 |
| pnpm | 12 |
| uv | 0.13 |

Versi di-pin ke major agar selaras dengan Dockerfile. **Docker tetap menjadi sumber kebenaran untuk build produksi** (`python:3.12-slim`, `node:26-alpine`); mise menyediakan toolchain lokal yang setara untuk development. Ketika Anda menaikkan versi tool, perbarui `mise.toml` dan Dockerfile terkait bersamaan agar tidak drift.

Python **tidak** dikelola mise. Interpreter dikelola uv dan versinya mengikuti `backend/.python-version` (3.12); `uv sync` di `backend/` mengunduhnya otomatis. Saat menaikkan versi Python, ubah `backend/.python-version` dan Dockerfile bersamaan.

pnpm adalah package manager untuk `frontend/` (lockfile `pnpm-lock.yaml`). Dikelola via mise untuk development lokal; di Docker dipasang eksplisit via `npm i -g pnpm@12` (tanpa corepack, versi di-pin sama dengan mise).

PostgreSQL (versi 16) dijalankan via Docker Compose, bukan mise.

### Environment variables

mise **tidak** mengelola environment variables di repo ini — hanya runtime. Env di-handle sesuai konteks:

- **Docker Compose** membaca `.env` di root (dari `.env.example`) untuk mengisi variable service di `compose.yaml`. Ini jalur development utama (`docker compose up`), dan jalur yang mengisi `NEXT_PUBLIC_*` serta `BACKEND_URL`/`FRONTEND_URL` untuk frontend.
- **Frontend lokal (`next dev`)** jalan tanpa env file: `NEXT_PUBLIC_API_URL` punya fallback `"/api/v1"` di setiap call site. Kalau perlu override lokal, buat sendiri `frontend/.env.local` (di-ignore git) — tidak ada template yang di-commit karena nilai default sudah tercakup fallback dan root `.env`.

Pemisahan ini disengaja: secret backend (DB password, API key, OAuth secret) tidak boleh bocor ke environment build frontend, dan beberapa nilai (`DATABASE_URL`, `BACKEND_URL`) memakai hostname internal jaringan Docker yang tidak valid di shell lokal. Jangan inject `.env` root ke seluruh repo via mise. `.env` dan `.env.local` di-ignore git — jangan commit; perbarui file `*.example` saat menambah variable.

> mise tasks (mis. `mise run test`/`lint`) belum dikonfigurasi — akan ditambahkan kemudian.

### Full stack lokal (Docker Compose)

`compose.yaml` adalah file produksi/VM: ia memakai prebuilt remote image dan named volume (`postgres-data`, `backend-data`, `backend-logs`). Nama volume final diawali nama stack/project, jadi nama stack di Portainer harus tetap `sa-portal` agar data lama terbaca. Untuk menjalankan full stack di mesin lokal, pakai override `compose.local.yaml` yang di-track git. Override ini build dari source lokal dan menambah seed demo, jadi stack naik di mana pun Docker tersedia (Linux, Windows/WSL, macOS).

Override ini **opt-in**: namanya sengaja bukan `compose.override.yaml` agar Docker Compose tidak meng-auto-merge-nya. Panggil eksplisit dengan `-f` dari root repo:

```bash
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

`docker compose up` polos (tanpa `-f`) tetap memakai `compose.yaml` saja — inilah yang dipakai host produksi/VM, sehingga override lokal tidak pernah bocor ke sana. Nama `compose.override.yaml` di-ignore git dan dicadangkan untuk override personal auto-merge per developer.

---

## Model Branching

- `main` adalah branch integrasi. `main` harus selalu bisa di-build dan deployable.
- **Dilarang commit langsung ke `main` — tanpa pengecualian.** Setiap perubahan, termasuk perubahan dokumentasi dan one-liner, masuk melalui feature branch dan pull request. Ini berlaku untuk semua contributor, baik manusia maupun agen AI.
- Buat feature branch dari `main` terbaru untuk setiap unit pekerjaan:

  ```
  feat/<slug-singkat>        # fitur baru
  fix/<slug-singkat>         # perbaikan bug
  refactor/<slug-singkat>    # perubahan internal, tanpa perubahan perilaku
  docs/<slug-singkat>        # dokumentasi saja
  ```

- Jaga satu branch tetap pada satu unit pekerjaan yang bisa di-review. Rebase atau merge `main` terbaru ke branch Anda sebelum membuka PR untuk meminimalkan conflict.

---

## Penegakan "Tanpa Direct Commit ke `main`"

Aturan "dilarang commit langsung ke `main`" ditegakkan di dua lapis — bukan sekadar imbauan di dokumen. Ini penting agar berlaku **agnostik terhadap tool**: siapa pun yang bekerja di repo ini, manusia maupun coding agent apa pun, tunduk pada mekanisme yang sama.

**Lapis 1 — Branch protection di GitHub (penjaga utama, tidak bisa di-bypass).**
Proteksi pada branch `main` di sisi server menolak direct push dan mewajibkan merge lewat PR. Karena hidup di remote, lapis ini tidak bisa dilewati dari sisi klien (termasuk dengan `--no-verify`). Mengaktifkannya butuh akses admin repo; lihat perintah `gh` di bawah.

**Lapis 2 — Pre-push hook lokal (umpan balik cepat).**
`.githooks/pre-push` menolak push langsung ke `main`/`master` di mesin lokal, sebelum menabrak server. Hook ini di-version di dalam repo (`.githooks/`), jadi dipakai siapa pun yang clone — asalkan git diarahkan ke sana lewat `core.hooksPath`:

- **Pengguna mise:** otomatis via `[hooks] enter` di `mise.toml` saat masuk direktori repo.
- **Tanpa mise:** jalankan sekali per clone — `mise run setup-hooks`, atau langsung:

  ```
  git config core.hooksPath .githooks
  ```

Lapis 2 bisa di-bypass dengan `git push --no-verify`; karena itu lapis 1 adalah penjaga yang sebenarnya. Dokumen (`AGENTS.md`/`CONTRIBUTING.md`) adalah sumber niat, bukan penegakan.

**Mengaktifkan branch protection (perlu akses admin repo):**

```
gh api -X PUT repos/<owner>/<repo>/branches/main/protection \
  --input - <<'JSON'
{
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "required_status_checks": null,
  "enforce_admins": true,
  "restrictions": null
}
JSON
```

Setelah CI tersedia, isi `required_status_checks` dengan nama check-nya agar PR wajib hijau sebelum merge.

---

## Konvensi Commit

Kita memakai [Conventional Commits](https://www.conventionalcommits.org/). Setiap pesan commit diawali dengan tipe:

- `feat:` — fitur baru
- `fix:` — perbaikan bug
- `refactor:` — perubahan kode yang bukan perbaikan bug maupun penambahan fitur
- `docs:` — dokumentasi saja
- `chore:` — tooling, dependency, konfigurasi build

Tulis pesan dalam bentuk imperatif ("tambah", "perbaiki", "perbarui" — bukan "menambahkan"/"memperbaiki"). Jaga baris subjek tetap ringkas; gunakan body untuk menjelaskan alasan ketika tidak jelas.

Stage file secara spesifik daripada semuanya sekaligus, agar perubahan yang tidak terkait tidak ikut dalam satu commit. Jangan pernah commit secret — API key, credential OAuth, atau apa pun yang semestinya ada di `.env` (lihat `.env.example` untuk apa yang diharapkan dikonfigurasi per environment).

---

## Proses Pull Request

1. Push feature branch Anda dan buka PR yang menargetkan `main`.
2. Jaga judul PR tetap ringkas (gaya conventional-commit) dan gunakan deskripsi untuk meringkas:
   - apa yang berubah dan mengapa,
   - apa yang telah diverifikasi (build, test, pengecekan manual),
   - apa pun yang sengaja ditinggalkan atau terblokir.
3. Sebuah PR harus lolos verification gate (di bawah) sebelum ditandai siap di-review.
4. Minimal satu review sebelum merge. Tanggapi feedback review dengan commit baru (hindari force-push menimpa review yang sedang berjalan); squash saat merge jika history-nya noisy.
5. Hapus branch setelah merge.

---

## Verification Gate

Belum ada CI otomatis (**CI direncanakan** — lihat daftar lintas-fitur di [`docs/ROADMAP.md`](docs/ROADMAP.md)). Sampai itu ada, verifikasi dilakukan manual dan menjadi tanggung jawab author sebelum meminta review:

- **Backend** — test suite lolos dan app bisa di-import/start dengan bersih. Setup test dan dependency ada di `backend/pyproject.toml`; test ada di `backend/tests/`.
- **Frontend** — proyek lolos type-check dan build tanpa error (`pnpm install`, lalu `pnpm run lint` dan `pnpm run build`). Script ada di `frontend/package.json`.
- **Full stack** — jika perubahan memengaruhi runtime wiring (migration, env var, service startup), konfirmasi stack bisa naik via Docker Compose dan endpoint `/health` melaporkan healthy.
- **Pengecekan sesuai scope** — verifikasi perubahan terhadap perilaku yang dimaksud, bukan sekadar command keluar tanpa error. Untuk perubahan UI, cek perilakunya di browser; untuk perubahan logika, jalankan code path terkait atau test-nya.

Sebuah perubahan belum "selesai" hanya karena command berjalan tanpa error. Perubahan selesai ketika terbukti memenuhi tujuannya.

---

## Migrasi Database

Perubahan schema melewati migration Alembic di `backend/alembic/versions/`. Ketika Anda mengubah model SQLAlchemy, tambahkan migration yang bersesuaian dalam PR yang sama agar schema dan model tetap sejalan. Jangan mengandalkan auto-create table saat startup sebagai mekanisme migration.

---

## Rilis & Penomoran Versi

Image Docker dirilis ke registry via `mise run publish [backend|frontend]` (wrapper `scripts/publish.sh`) lalu di-deploy di Portainer. Registry dan owner dibaca dari `IMAGE_REGISTRY`/`IMAGE_OWNER` di `.env`; versi backend dan frontend ditanyakan terpisah (kosongkan untuk melewati) dan dilacak lewat `BACKEND_IMAGE_TAG`/`FRONTEND_IMAGE_TAG`.

**Aturan penomoran versi (wajib):**

- Format: `vMAJOR.MINOR` dengan **MINOR selalu dua digit** (`v4.81`, `v4.90`, `v5.00`).
- Increment per rilis: **+0.01** (`v4.81` → `v4.82` → `v4.83` …).
- Saat MINOR mencapai 89 lanjut ke 90 (`v4.89` → `v4.90`), bukan `v4.9`.
- Saat MINOR mencapai 99 naik major dan reset (`v4.99` → `v5.00`).
- Tidak valid: `v4.9` (minor satu digit), `v4.100` (tiga digit).

`scripts/publish.sh` memvalidasi format ini dan menolak tag yang tidak sesuai. Backend dan frontend memiliki versi sendiri-sendiri dan tidak harus sama.

---

## Ekspektasi Keamanan

- Simpan semua secret di environment variable; jangan pernah hardcode. `.env` di-ignore git — perbarui `.env.example` (hanya key, tanpa nilai asli) ketika Anda menambah variable baru.
- Perlakukan apa pun yang menangani auth, token, CORS, atau credential eksternal sebagai security-sensitive: catat di deskripsi PR apa yang Anda verifikasi.
- Tandai setiap dependency pihak ketiga baru di PR, di-pin ke versi yang exact.

---

<!-- BEGIN: current-overhaul-workflow (sementara — hapus ketika overhaul MVP selesai) -->
## Workflow Overhaul Saat Ini (sementara)

_Ditambahkan 2026-10-12. Bagian ini mendokumentasikan proses untuk overhaul MVP yang sedang berjalan, dilacak di [`docs/ROADMAP.md`](docs/ROADMAP.md). Hapus bagian ini begitu overhaul mendarat._

Overhaul dikerjakan **satu fase roadmap per branch**:

- Nama branch: `feat/phase-<N>-<slug>` (mis. `feat/phase-0-security-hardening`), di-branch dari `main` terbaru.
- Scope: satu fase per branch — bisa di-review dan di-revert sebagai satu unit. Fase berikutnya di-branch hanya setelah fase sebelumnya di-merge ke `main`.
- Setiap fase diverifikasi terhadap **kriteria selesai**-nya di `docs/ROADMAP.md` sebelum PR dibuka.
- Checkbox roadmap (`- [ ]` → `- [x]`) di-update di branch yang sama dengan pekerjaan yang di-track-nya, agar roadmap tetap menjadi progress tracker yang hidup.
- Pacing: satu fase per waktu. Sebuah fase diselesaikan dan di-review sebelum fase berikutnya dimulai. Fase yang independen (sesuai diagram dependency di roadmap) hanya di-parallelize atas kesepakatan eksplisit.

Fase yang membuat perubahan besar atau runtime-sensitive (mis. perubahan default keamanan, model subtask, document comparison) dikembangkan secara terisolasi agar `main` tetap bisa dipakai sepanjang waktu.
<!-- END: current-overhaul-workflow -->
