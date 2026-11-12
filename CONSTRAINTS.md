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
- **Frontend**: ambang sama (90/80), **ditegakkan di CI** (tiket #71). Job `Frontend —
  tsc, test + cakupan, build` menjalankan `pnpm test:coverage`; ambang dipasang sebagai
  `coverage.thresholds` (`lines: 90`, `branches: 80`) di `frontend/vitest.config.mts` dan
  berlaku pada cakupan **total** (v8). Salah satu di bawah ambang = vitest keluar dengan
  kode ≠ 0 = job merah. Berkas individual di bawah ambang hanya dilaporkan sebagai
  peringatan di Summary (`frontend/scripts/cakupan-ringkasan.mjs`), tidak memblok
  sendirian. Baseline saat gerbang dihidupkan: baris 99,6%, cabang 95,4%.

## 2. Aturan anti-pelemahan

Dilarang, tanpa pengecualian prosedural (bagian 4):

1. Menurunkan ambang cakupan (di dokumen ini, `pyproject.toml`, `coverage.thresholds`
   di `frontend/vitest.config.mts`, maupun CI).
2. Menambah `skip`/`skipif`/`xfail` (backend) atau `it.skip`/`describe.skip`/`it.todo`/
   `it.fails` (frontend) tanpa menautkan issue GitHub terbuka (nomor issue wajib ada di
   alasan/komentar).
3. Menghapus atau melemahkan assertion agar test lolos (mis. mengganti nilai pasti
   dengan `is not None`, membungkus dengan `try/except`, menghapus `assert`).
4. Menambah `# pragma: no cover` tanpa komentar alasan di baris yang sama/sebelumnya,
   atau memperluas `omit` di konfigurasi coverage di luar daftar bagian 3. Frontend: setara untuk
   `/* v8 ignore */` dan `coverage.exclude`.
5. Test bergantung pada urutan, data sisa, waktu nyata (sleep sungguhan), atau
   jaringan. Sleep/retry di test unit wajib di-patch.
6. Test unit menyentuh database dev/Compose. Conftest memaksa `DATABASE_URL` ke
   `127.0.0.1:1`; test integrasi memakai `TEST_DATABASE_URL` sendiri.

7. Menambah atau mengubah perilaku tanpa test yang menyertainya (aturan test-first,
   `AGENTS.md` bagian "Test-first"). Test ditulis lebih dulu dan terbukti gagal sebelum
   kodenya ada. Pengecualian terbatas pada dokumentasi murni dan konfigurasi tanpa
   perilaku, dan alasannya wajib tertulis di deskripsi PR.

Catatan penegakan: gerbang cakupan (bagian 1) hanya memeriksa angka **total**, sehingga
kode tak teruji dalam jumlah kecil bisa lolos tanpa terdeteksi. Aturan 7 karenanya
ditegakkan lewat checklist di template PR dan review sampai gerbang per-perubahan
(cakupan pada baris yang diubah) tersedia.

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

### Pengecualian cakupan frontend (final, dikunci di tiket #71)

| Yang dikecualikan | Alasan |
| ----------------- | ------ |
| `src/**/*.test.{ts,tsx}` | Berkas test itu sendiri, bukan kode produk. |
| `src/test/**` | Utilitas, fixture, dan mock test (MSW, `renderWithProviders`), bukan kode produk. |
| `src/**/*.d.ts` | Deklarasi tipe murni, tanpa kode runtime. |

Konfigurasi ada di `coverage.exclude` pada `frontend/vitest.config.mts`. Hanya tiga baris
di atas; tidak ada pengecualian per-berkas lain. Berkas tanpa test tetap dihitung
(`coverage.include: src/**/*.{ts,tsx}`). Aturan 4 (bagian 2) berlaku sama: perluasan
`exclude` atau penambahan `/* v8 ignore */` tanpa alasan dilarang; entri baru wajib lewat
bagian 4 dan memperbarui tabel ini.

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

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm test                       # suite Vitest sekali jalan
pnpm test:coverage              # + cakupan v8 DAN gerbang (exit != 0 bila baris < 90% / cabang < 80%)
node scripts/cakupan-ringkasan.mjs   # tabel total + berkas di bawah ambang (setelah test:coverage)
pnpm run build
```

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
- Frontend: langkah `Test + gerbang cakupan` mencetak, mis.
  `ERROR: Coverage for lines (85.20%) does not meet global threshold (90%)` (dan/atau
  `branches ... (80%)`). Kolom `Uncovered Line #s` pada tabel teks vitest menunjuk baris
  yang belum teruji; `coverage/index.html` (artifact `cakupan-frontend`) menampilkan
  cabang per berkas. Tambahkan test perilaku; dilarang menurunkan ambang atau menambah
  `exclude`. Test yang gagal juga membuat langkah ini merah, terlepas dari cakupan.
- Pesan "Data cakupan unit atau integrasi tidak lengkap" = job unit/integrasi gagal
  lebih dulu; perbaiki job itu, gerbang akan mengikuti.
