# Portal SA — Backend

Backend API untuk Portal SA: manajemen proyek pre-sales dan pencatatan aktivitas harian Solutions Architect. Dibangun dengan **FastAPI** (Python 3.12) di atas PostgreSQL.

Untuk gambaran produk, fitur, dan arsitektur menyeluruh, lihat [README root](../README.md). Untuk workflow kontribusi (branching, commit, verification gate, migration), lihat [CONTRIBUTING.md](../CONTRIBUTING.md).

## Struktur

- `app/api` — router FastAPI (satu modul per domain).
- `app/services` — business logic.
- `app/models` — model SQLAlchemy.
- `app/schemas` — schema Pydantic (request/response).
- `app/core` — config, database, middleware, dependencies.
- `alembic/` — migration database (Alembic).
- `tests/` — test suite (pytest).

## Toolchain & dependency

Project ini uv-native. `pyproject.toml` adalah sumber kebenaran dependency, `uv.lock` mem-pin versi exact untuk reproducibility.

```bash
# Pasang semua dependency (termasuk dev group) ke .venv
uv sync

# Hanya runtime (seperti build produksi)
uv sync --no-dev

# Tambah / hapus dependency
uv add <paket>
uv remove <paket>
```

## Development

```bash
# Jalankan test suite (±9 detik; DATABASE_URL dipaksa ke target yang gagal cepat di conftest,
# jadi test unit tidak pernah menyentuh database nyata)
uv run pytest

# Laporan cakupan baris + cabang per modul (konfigurasi di [tool.coverage] pyproject.toml)
uv run pytest --cov --cov-report=term-missing
# Laporan HTML: tambahkan --cov-report=html (hasil di htmlcov/)

# Audit durasi test paling lambat
uv run pytest --durations=10

# Lint
uv run ruff check .

# Jalankan dev server
uv run uvicorn app.main:app --reload
```

## Test integrasi (Postgres nyata)

Test di `tests/integration/` (marker `integration`) berjalan terhadap Postgres 18 sungguhan:
test migration (upgrade/downgrade/data), constraint database, dan jalur API end-to-end. Default
`uv run pytest` **hanya menjalankan test unit** (`addopts = "-m 'not integration'"`); integrasi dipilih
eksplisit dan **dilewati dengan pesan jelas** bila `TEST_DATABASE_URL` tidak di-set.

```bash
# 1. Postgres 18 sementara (terpisah dari stack Compose & database dev; hilang saat dihentikan)
docker run -d --rm --name sa-test-pg -e POSTGRES_PASSWORD=test \
  -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql postgres:18-alpine
docker exec sa-test-pg pg_isready -U postgres   # tunggu "accepting connections"

# 2. Jalankan test integrasi (URL menunjuk SERVER; fixture membuat database acak sa_test_<hex>)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:55432/postgres
uv run pytest -m integration

# 3. Bersihkan
docker rm -f sa-test-pg
```

Cara kerja fixture (`tests/integration/conftest.py`):

- Fixture sesi membuat database `sa_test_<hex>` di server itu, menjalankan `alembic upgrade head`
  (subprocess dengan `DATABASE_URL` diarahkan ke database sementara), dan menghapusnya di akhir.
  Hanya database buatan fixture yang dihapus; `DATABASE_URL` dev/Compose tidak pernah dipakai.
- Isolasi per test: transaksi yang di-rollback; `commit()` pada kode produksi menjadi savepoint.
- Klien API (`api`): `httpx.AsyncClient` + `ASGITransport` dengan override `get_db` ke sesi test dan
  `AsyncSessionLocal` di-patch di semua modul `app.*` yang membuka sesinya sendiri
  (`patch_session_factory`). Event startup (scheduler SLA, sweep Requirement) tidak jalan, dan background
  task generate Requirement diganti mock (Gemini nyata tidak pernah dipanggil; fake LLM/Drive/Gmail/Calendar
  ada di tiket #54).
- Keamanan: `TEST_DATABASE_URL` wajib driver `postgresql+asyncpg` dan host lokal (`127.0.0.1`/`localhost`).
  Untuk server uji non-lokal (mis. service CI) set `TEST_DATABASE_ALLOW_REMOTE=1`.

### Fake boundary (Gemini, Drive, Gmail, Calendar)

Fake di `tests/integration/fakes/` menggantikan layanan eksternal pada test integrasi. Fixture
(`fake_llm`, `fake_drive`, `fake_gmail`, `fake_calendar`) terdaftar otomatis di `tests/integration/`,
dibuat baru per test, dan dipulihkan oleh `monkeypatch` (tanpa state sisa). Tidak ada perubahan
kode produksi: semua dipasang pada singleton/registry yang sudah ada.

| Fixture | Dipasang di | Pemrograman | Perekaman |
|---|---|---|---|
| `fake_llm` | `llm_factory` (adapter `fake`, `LLM_PROVIDER=fake`) | `sukses/malformed/error(tipe)/terpotong(jenis, ...)`, `program(jenis, *respons, tetap=)` | `panggilan`, `jumlah(jenis)`, `panggilan_jenis(jenis)` |
| `fake_drive` | method publik `folder_provisioner` | `fail_next(operasi, times=)`, `fail_always(operasi)` | `panggilan`, `folder`, `izin`, `peran(folder, email)` |
| `fake_gmail` | `notification_service.send_email` | `fail_next(times=)`, `fail_always()`, `terkonfigurasi`, `tahan_email()/lepaskan_email()` | `percobaan`, `terkirim`, `gagal`, `await tunggu_percobaan(n)` |
| `fake_calendar` | `calendar_service.fetch_events` | `set_events(*item)`, `fail_next("timeout"/"api")`, `fail_always()` | `access_token_diterima` |

Catatan:

- `fake_llm` jenis panggilan: `complete_text`, `parse_document`, `structure_text`. Panggilan yang belum
  diprogram gagal keras (`AssertionError`). Mode: sukses, `malformed` (structure_text → error
  `invalid_response`; lainnya → teks JSON rusak), `error` (`timeout`/`auth_error`/`invalid_response`/`unknown`),
  `terpotong` (`finish_reason="MAX_TOKENS"`).
- `fake_gmail.send_email` meniru kontrak produksi: gagal = `False`, tidak raise; `EMAIL_RETRY_INTERVAL`
  dinolkan. Email dikirim di background task bersesi sendiri; pada harness satu koneksi, panggil
  `tahan_email()` sebelum request dan `lepaskan_email()` sesudahnya agar tidak bertabrakan dengan sesi request.
- `fake_calendar` menerima item mentah gaya Google (`event_berjadwal`, `event_seharian`) dan memakai
  `_parse_event` asli.
- Contoh: `tests/integration/test_fake_boundary_contoh.py` (lewat API + Postgres) dan
  `tests/test_fakes_boundary.py` (unit perilaku fake).

## Verifikasi Drive live

Suite `tests/integration/drive_live/` (marker `drive_live`, issue #27) membuktikan
`folder_provisioner` dan alur assign → provisioning → lock/unlock SLA → `doc_ready` terhadap
**Google Drive nyata**. Ia memverifikasi hasil lewat klien `googleapiclient` terpisah, bukan dari
nilai kembalian kode produksi. Status: suite ini ditulis tanpa akses kredensial dan **belum pernah
dijalankan** terhadap Drive sungguhan; hasil run pertama dicatat di issue #27.

Keamanan: tanpa `GDRIVE_LIVE_TEST=1` seluruh test live **dideselect** (bukan skip, bukan error),
termasuk di CI (`-m integration`). Folder uji diberi awalan `[LIVE-TEST <uuid>] `, dihapus di akhir
tiap test (juga saat gagal), dan sisa sesi terputus disapu di awal sesi (folder `[LIVE-TEST...` milik
service account itu). Gunakan service account **khusus uji** dan jangan jalankan dua sesi paralel.

```bash
# 1. Siapkan service account + akun uji (menulis backend/.env.drive-live, di-ignore git, mode 0600)
scripts/wizard-google-drive.sh

# 2. Postgres sementara untuk skenario tingkat API (lihat bagian Test integrasi)
docker run -d --rm --name sa-test-pg -e POSTGRES_PASSWORD=test \
  -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql postgres:18-alpine

# 3. Jalankan suite (dari root repo, lalu masuk backend/)
set -a; source backend/.env.drive-live; set +a
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:55432/postgres
cd backend && GDRIVE_LIVE_TEST=1 uv run pytest -m drive_live -v

# 4. Bersihkan Postgres sementara; hapus kunci uji di Cloud Console bila selesai
docker rm -f sa-test-pg
```

Env yang dibaca (semua wajib bila `GDRIVE_LIVE_TEST=1`; kurang → error konfigurasi yang menyebut
namanya): `GDRIVE_SERVICE_ACCOUNT_KEY`, `DRIVE_LIVE_LEAD_EMAIL`, `DRIVE_LIVE_SA_EMAIL`,
`DRIVE_LIVE_SALES_EMAIL`, `DRIVE_LIVE_PMO_EMAIL`, `DRIVE_LIVE_DELIVERY_EMAIL` (lima email wajib akun
Google nyata yang **berbeda satu sama lain** dan bukan service account). Opsional:
`DRIVE_LIVE_TEST_TIMEOUT` (detik, default 120). Skenario API juga butuh `TEST_DATABASE_URL`.
Lihat daftar skenario dengan `GDRIVE_LIVE_TEST=1 uv run pytest --collect-only -m drive_live` (env di atas).

Definisi "akses efektif" yang dipakai assertion: peran tertinggi dari permission user pada folder
itu **atau leluhurnya** (permission folder diwarisi anak); lihat `drive_live/izin.py`. Helper murni
suite (seleksi, konfigurasi, peran efektif, verifikator) diuji di `tests/test_drive_live_helper.py`
dan `tests/test_drive_live_seleksi_proses.py`. Jika hasil live berbeda dari ekspektasi spec,
itu temuan: jangan longgarkan assertion, catat sebagai gap.

## Gerbang cakupan (setara CI)

CI memblok bila cakupan **gabungan unit + integrasi** punya baris < 90% atau cabang < 80%
(CONSTRAINTS.md). Cara menjalankan hal yang sama secara lokal (Postgres sementara dari bagian
di atas harus hidup, `TEST_DATABASE_URL` di-set):

```bash
cd backend
export COVERAGE_FILE=cov-unit.data
uv run pytest -q -W ignore --cov=app --cov-branch --cov-report=
export COVERAGE_FILE=cov-integrasi.data
uv run pytest -q -W ignore -m integration --cov=app --cov-branch --cov-report=

export COVERAGE_FILE=cov-gabungan.data
uv run coverage combine --keep cov-unit.data cov-integrasi.data
uv run coverage report --skip-empty                 # tabel per modul + kolom Missing
uv run coverage json -o coverage.json
uv run python scripts/cakupan_gerbang.py coverage.json   # exit 0 = lolos, 1 = gagal
```

Berkas `cov-*.data`/`coverage.json` adalah artefak lokal; jangan di-commit. Cara membaca
kegagalan: CONSTRAINTS.md bagian 6. Skrip gerbang punya test unit
(`tests/test_cakupan_gerbang.py`).

## Kebijakan akses proyek

Spec: issue #87 (matriks disetujui), ADR 0002 (Backup SA = collaborator). Penolakan selalu **403**
dengan pesan generik, dan terjadi **sebelum** efek samping apa pun (penulisan, notifikasi, LLM,
Drive). Urutan kode status: 404 (proyek tak ada) → 403 (akses) → validasi domain (400/409/422).

**Titik keputusan** (satu-satunya pintu): `app/core/dependencies.py`.
`await ensure_project_access(db, project, user, TingkatAkses.X)` menolak dengan 403 bila tidak
berhak; aturannya satu tabel deklaratif `_ATURAN` (fungsi murni `izinkan`; tiap tingkat = satu `Aturan`
berisi keterangan + hubungan yang diizinkan, Lead_SA/Admin selalu berhak). Hubungan dicocokkan lewat **id**
(`sales_pic`, `assigned_sa`, baris collaborator), bukan lewat peran user, kecuali tingkat yang
memang menggabungkan id dan peran (ditandai di bawah).

| `TingkatAkses` | Lead_SA/Admin | SA ditugaskan | Sales PIC | Collaborator viewer | Collaborator contributor |
|---|---|---|---|---|---|
| `BACA` (detail, SLA, BANT, rekomendasi, daftar dokumen/subtask/collaborator) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `STORY` (baca Story, ringkasan AI; Sales PIC boleh, lihat catatan di bawah) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TULIS` (activity log, map kalender, unggah dokumen, polish ulang) | ✅ | ✅ | ❌ | ❌ | ✅ |
| `UBAH_PROYEK` (PATCH proyek) | ✅ | ✅ | ✅ | ❌ | ✅ |
| `KELOLA` (majukan status dokumen) | ✅ | ✅ | ❌ | ❌ | ❌ |
| `ISI_DQ` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `TAMBAH_KOLABORATOR`, `HAPUS_KOLABORATOR` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `UBAH_STATUS` (workflow; id **dan** peran: Sales untuk PIC, SA untuk yang ditugaskan) | ✅ | ✅ | ✅ | ❌ | ❌ |
| `HANDOVER` (id dan peran SA) | ✅ | ✅ | ❌ | ❌ | ❌ |
| `KELOLA_REQUIREMENT` (id dan peran SA) | ✅ | ✅ | ❌ | ❌ | ❌ |
| `EDIT_KUESIONER` (id dan peran Sales) | ✅ | ❌ | ✅ | ❌ | ❌ |

Catatan `STORY` (keputusan pemilik produk 2026-11-10, membalik spec #87 / issue #74): Sales PIC
**proyek itu** boleh membaca Project Story dan meminta ringkasan AI agar Sales melihat progres.
Story memuat catatan rapat mentah dan versi polish AI, jadi pembukaan ini disengaja. Sales bukan
PIC tetap ditolak, dan Sales PIC tetap tidak boleh menulis activity log/kalender (`TULIS`).

Aturan tambahan di luar tabel: mundurkan status dokumen hanya Lead_SA/Admin; `doc_ready` hanya
Draft → Reviewed; perubahan nilai `dq_number` (juga lewat PATCH proyek) mengikuti `ISI_DQ`;
Sales PIC tanpa DQ melihat daftar kosong di `GET .../documents/solutions`; gating link Solutions
untuk Sales (PIC proyek itu + DQ terisi + Reviewed/Final) satu helper
(`app/services/dq_akses.py::saring_dokumen_terlihat`) yang juga dipakai `GET .../documents`; aturan
dan efek samping DQ (status diizinkan, Sales hanya mengisi yang kosong, timer SLA berhenti,
Ready) satu fungsi (`terapkan_dq`) yang dipakai `PATCH .../dq-number` dan PATCH proyek; status
subtask mensyaratkan pemilik subtask yang masih berhak `TULIS`; polish ulang log
tetap mensyaratkan **kepemilikan log** (orang lain → 404) ditambah akses `TULIS` penulis.

**Pengecualian sah** (daftar `PENGECUALIAN` di `tests/test_penjaga_akses_rute.py`, bernomor
`SAH-n`): role gate murni Lead_SA/`is_admin` (hapus proyek, assign/reassign, provision-folder,
handover-config, score-manual, buat/assign/hapus subtask). Semuanya dikunci
`tests/integration/test_akses_k5_penyelarasan_akhir.py`. Penjaga juga memastikan tidak ada
panggilan titik keputusan di dalam `try/except Exception` yang menelan 403.

### Menambah endpoint baru yang memuat id proyek

1. Muat proyek (404 bila tidak ada), lalu panggil `ensure_project_access(db, project, user,
   TingkatAkses.…)` **sebelum** efek samping. Jangan buat pemeriksa sendiri; bila aturan yang
   dibutuhkan belum ada, tambah `TingkatAkses` baru + entri di `_ATURAN` + baris di
   `tests/test_keputusan_akses.py::MATRIKS`.
2. Jangan panggil di dalam `try/except Exception` (403 akan tertelan jadi 500). Pesan 403 default
   generik; `pesan=` hanya untuk kontrak lama yang sudah terkunci.
3. **Test penjaga** `tests/test_penjaga_akses_rute.py` memindai semua rute yang memuat id proyek
   (path `project_id`/`id_project`/`doc_id`/`id_log`/`id_subtask` atau field body
   `id_project`/`project_id`) dan GAGAL bila tidak mencapai `ensure_project_access`. Bila rute
   benar-benar tidak boleh memakainya (role gate murni dsb.), tambah entri `PENGECUALIAN` dengan
   alasan spesifik + nomor `SAH-n` berikutnya dan test integrasi yang mengunci aturannya.
4. Tulis test integrasi peran × aksi di Postgres (pola: `tests/integration/support_akses.py`,
   `test_akses_k*_*.py`): pihak berhak berhasil; pihak tidak berhak 403 **tanpa efek samping**
   (pakai fixture `komit_sesi_request`; fake LLM/Drive/Gmail tidak terpanggil).

## Migration

Setiap perubahan model SQLAlchemy wajib disertai migration Alembic di `alembic/versions/` dalam PR yang sama.

```bash
# Generate migration dari perubahan model
uv run alembic revision --autogenerate -m "deskripsi"

# Terapkan migration
uv run alembic upgrade head
```

## Verification gate

Sebelum membuka PR: test suite lolos (`uv run pytest`) dan app bisa di-import bersih (`uv run python -c "import app.main"`). Detail di [CONTRIBUTING.md](../CONTRIBUTING.md).
