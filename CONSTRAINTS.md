# CONSTRAINTS.md — Kontrak Kualitas Test

Dokumen ini adalah kontrak kualitas (quality bar) untuk test suite. Berlaku untuk
semua contributor, termasuk agen AI. Konteks: spec induk #49.

## 1. Gerbang cakupan

| Metrik | Ambang minimum | Cakupan |
| ------ | -------------- | ------- |
| Baris (line) | **≥ 90%** | per modul |
| Cabang (branch) | **≥ 80%** | per modul |

- **Backend**: berlaku; diukur dengan `pytest-cov` (lihat bagian 5). Baseline saat
  dokumen ini ditulis: 72% total (4778 statement, 1022 branch). Modul dinaikkan
  bertahap lewat tiket per modul sampai gerbang tercapai, lalu ditegakkan penuh
  oleh tiket gerbang penutup (#70).
- **Frontend**: ambang sama (90/80); pengukuran **menyusul** di tiket tersendiri.

## 2. Aturan anti-pelemahan

Dilarang, tanpa pengecualian prosedural (bagian 4):

1. Menurunkan ambang cakupan (di dokumen ini, `pyproject.toml`, maupun CI).
2. Menambah `skip`/`skipif`/`xfail` tanpa menautkan issue GitHub terbuka (nomor issue
   wajib ada di alasan marker).
3. Menghapus atau melemahkan assertion agar test lolos (mis. mengganti nilai pasti
   dengan `is not None`, membungkus dengan `try/except`, menghapus `assert`).
4. Menambah `# pragma: no cover` tanpa komentar alasan di baris yang sama/sebelumnya,
   atau memperluas `omit` di konfigurasi coverage di luar daftar bagian 3.
5. Test bergantung pada urutan, data sisa, waktu nyata (sleep sungguhan), atau
   jaringan. Sleep/retry di test unit wajib di-patch.
6. Test unit menyentuh database dev/Compose. Conftest memaksa `DATABASE_URL` ke
   `127.0.0.1:1`; test integrasi memakai `TEST_DATABASE_URL` sendiri.

Test menegaskan **perilaku eksternal** (respons API, status akhir, baris tersimpan,
panggilan ke fake, invarian), bukan urutan panggilan internal.

## 3. Pengecualian cakupan

| Yang dikecualikan | Alasan |
| ----------------- | ------ |
| Migration Alembic (`backend/alembic/`) | Kode generated/skrip sekali jalan; kebenarannya diverifikasi oleh test migration integrasi (upgrade/downgrade), bukan cakupan baris. |
| Script seed (`backend/scripts/seed_demo_data.py`) | Utilitas data demo, bukan logika produk. |

Konfigurasi ada di `[tool.coverage.run] omit` pada `backend/pyproject.toml`. Menambah
entri baru wajib lewat prosedur bagian 4 dan memperbarui tabel ini.

## 4. Prosedur penyimpangan

Penyimpangan dari dokumen ini (mis. menurunkan ambang sementara, pengecualian baru)
hanya sah dengan **persetujuan eksplisit pemilik produk**, tercatat di issue/PR
terkait beserta alasan dan batas waktu. Tanpa itu, PR ditolak.

## 5. Menjalankan suite dan laporan cakupan

```bash
cd backend
uv sync
uv run pytest -q -W ignore                              # suite unit
uv run pytest -q -W ignore --cov --cov-report=term-missing   # cakupan baris+cabang per modul
uv run pytest --durations=10                            # audit durasi
```
