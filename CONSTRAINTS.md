# CONSTRAINTS.md — Kontrak Kualitas Test

Dokumen ini adalah kontrak kualitas (quality bar) untuk test suite. Berlaku untuk
semua contributor, termasuk agen AI. Konteks: spec induk #49.

## 1. Gerbang cakupan

| Metrik | Ambang minimum | Cakupan |
| ------ | -------------- | ------- |
| Baris (line) | **≥ 90%** | per modul |
| Cabang (branch) | **≥ 80%** | per modul |

- **Backend**: berlaku dan **ditegakkan di CI** (tiket #70). Job `Backend — ringkasan
  cakupan gabungan` menggabungkan data unit + integrasi (`coverage combine`) lalu
  `backend/scripts/cakupan_gerbang.py` memeriksa dua ambang TERPISAH pada cakupan
  **total**: baris ≥ 90% dan cabang ≥ 80%. Salah satu di bawah ambang = job merah
  (PR diblok bila job dijadikan required check). Modul individual di bawah ambang
  dilaporkan sebagai peringatan (`::warning`), tidak memblok sendirian. Baseline saat
  gerbang dihidupkan: baris 99,9%, cabang 99,1% (satu modul di bawah 80% cabang:
  `app/core/config.py`, 5/8 cabang — peringatan, bukan pelanggaran). Baseline awal
  sebelum tiket B2–B11: 72%.
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

**Daftar ini final untuk backend** (dikunci di tiket #70): hanya dua baris di atas.
Tidak ada `# pragma: no cover` tersembunyi yang dibenarkan tanpa alasan (aturan 4).
**Daftar pengecualian frontend ditambahkan oleh tiket F9** (pengukuran frontend belum
masuk gerbang ini).

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
uv run pytest -q -W ignore -m integration --cov --cov-branch   # suite integrasi (butuh TEST_DATABASE_URL)
```

Gerbang lokal yang setara CI: lihat `backend/README.md` bagian "Gerbang cakupan".

## 6. Membaca kegagalan gerbang

Langkah CI `Gerbang cakupan (baris >= 90%, cabang >= 80%)` mencetak, mis.:

```
GERBANG CAKUPAN GAGAL — ambang dilanggar:
  - TOTAL: cakupan CABANG 78.40% < 80% (...)
```

- `BARIS` = statement yang tidak dieksekusi; `CABANG` = percabangan (`if`/`else`,
  `try`/`except`, loop) yang salah satu arahnya tidak pernah ditempuh. Keduanya
  diperiksa terpisah; melanggar salah satu sudah menggagalkan job.
- Cari penyebabnya: tab **Summary** run memuat tabel cakupan per modul; log langkah
  `Gabungkan` memuat `coverage report` dengan kolom `Missing` (nomor baris; `12->15`
  berarti cabang dari baris 12 ke 15 tak pernah ditempuh). Baris `::warning` menunjuk
  modul yang paling lemah.
- Perbaiki dengan **menambah test perilaku** untuk kode yang tak tercakup. Dilarang
  menurunkan ambang, menambah `omit`/`pragma: no cover`, atau melemahkan test (bagian 2).
- Pesan "Data cakupan unit atau integrasi tidak lengkap" = job unit/integrasi gagal
  lebih dulu; perbaiki job itu, gerbang akan mengikuti.
