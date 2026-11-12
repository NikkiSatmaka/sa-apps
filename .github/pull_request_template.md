## Ringkasan

<!-- Apa yang berubah dan mengapa. Tautkan issue/spec (Closes #...). -->

## Perilaku baru atau yang diubah, dan test yang melindunginya

<!-- Wajib. Satu baris per perilaku -> nama test (file::test). Untuk bug fix, sebut test regresinya.
     Jika PR hanya dokumentasi atau konfigurasi tanpa perilaku, tulis alasannya di sini dan lewati checklist test. -->

| Perilaku | Test |
| -------- | ---- |
|          |      |

## Checklist

- [ ] Test ditulis **lebih dulu** dan terbukti gagal sebelum kodenya ada (test-first; lihat `AGENTS.md`)
- [ ] Setiap fungsi/method/endpoint/komponen/cabang kondisi yang baru atau berubah punya test perilaku
- [ ] Bug fix punya test regresi yang mereproduksi bug
- [ ] Perubahan schema disertai migration **dan** test migration
- [ ] Tidak ada ambang cakupan yang diturunkan, `skip`/`xfail` baru tanpa issue, atau assertion yang dilemahkan (`CONSTRAINTS.md` bagian 2)
- [ ] Test lama yang diubah dijelaskan di bawah (apa yang berubah dan mengapa perilakunya memang berubah)
- [ ] CI hijau (unit, integrasi, frontend, gerbang cakupan)

## Verifikasi

<!-- Apa yang dijalankan dan hasilnya. Sebutkan juga apa yang BELUM terverifikasi (mis. perilaku di browser, layanan eksternal nyata). -->

## Perubahan perilaku yang perlu diketahui / test lama yang diubah

<!-- Kosongkan bila tidak ada. -->
