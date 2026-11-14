# Peta test backend

Baca peta ini sebelum membuka `conftest.py` atau `support_*.py`. Cari nama lewat `grep -n "def <nama>"`; jangan membuka berkas helper utuh.

## Unit (`backend/tests/*.py`, tanpa DB)

- `conftest.py`: set env aman sebelum `app` di-import. `DATABASE_URL` dipaksa ke target yang langsung gagal, jadi test unit tidak bisa menyentuh DB.
- `_auth_support.py`: `buat_token`, `user_palsu(role)`, `terapkan_persona`, `SesiPalsu`/`HasilPalsu` (sesi DB palsu), `pasang_google*` (fake endpoint Google lewat `httpx`).

## Integrasi (`backend/tests/integration/`, Postgres sungguhan, marker `integration` otomatis)

Fondasi di `conftest.py` (`TEST_DATABASE_URL` wajib; tanpa itu test dilewati):

| Fixture | Fungsi |
| ------- | ------ |
| `server_uji`, `database_uji_url` | database sementara `sa_test_<hex>` hasil `alembic upgrade head`, dihapus di akhir sesi |
| `database_kosong_url` | database tanpa migration, untuk test migration |
| `db_session`, `session_factory` | sesi per test; transaksi luar di-rollback, `commit()` jadi savepoint |
| `api` (`KlienApi`) | klien ASGI dengan `get_db` ter-override dan `AsyncSessionLocal` ter-patch; login demo per role |
| `patch_session_factory` | patch `AsyncSessionLocal` di modul yang membuka sesinya sendiri |

Fake boundary (`fakes/`, fixture terdaftar di `fakes/fixtures.py`): `fake_llm`, `fake_drive`, `fake_gmail`, `fake_calendar`. Layanan eksternal tidak pernah dipanggil sungguhan.

Helper pembangun data:

- `model_helpers.py`: `bangun_user/project/document/log/notifikasi/subtask/sla/source_doc/audit/kolaborator`, `simpan`, `ditolak`, `siapkan_proyek`.
- `helpers_t60.py`: `bearer`, `buat_user`, `buat_proyek`, `buat_kolaborator`, `buat_notifikasi`.
- `support_akses.py`: `skenario_akses` (matriks peran × akses).
- `support_assignment.py`: `bangun_dunia`, `bekukan_waktu`, `rekam_background`, `jalankan_provisioning`, `ambil_*`, `daftar_*`.
- `b6_support.py` (dokumen, DQ, workflow, handover) dan `kualifikasi_support.py` (kualifikasi, scoring, proyek): helper dan fixture per area.
- `requirement/conftest.py`: fixture `skenario` untuk siklus hidup Requirement.
- `drive_live/`: memanggil Google Drive **nyata**; hanya jalan bila dikonfigurasi (#27). Jangan jalankan dari agen.

Cara menjalankan: `mise run verify-backend` (lihat `CONTRIBUTING.md`, "Verification Gate").
