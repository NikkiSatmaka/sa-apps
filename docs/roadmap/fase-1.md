<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 1 — Menutup Partial yang Mudah (quick wins)

**Tujuan:** menyelesaikan fitur yang sudah 80% jadi dengan perubahan kecil dan berisiko rendah.

- [x] 1.1 **Fitur 2:** persist `estimasi_nilai` — tambah column + migration ke `Project`, simpan saat create, tampilkan di detail/edit. (fix **B4**)
- [x] 1.2 **Fitur 7:** tambahkan `Requirement` ke `DocTypeEnum` dan constraint `CHECK` di DB; perbarui dropdown tipe dokumen di frontend. (`backend/app/schemas/document.py`, `backend/app/models/document.py`, migration, `frontend/src/components/DocumentForm.tsx`)
- [ ] ~~1.3 **Fitur 9:** ganti tombol teks "Edit" dengan ikon pensil/edit di halaman detail proyek.~~ **Dibatalkan (2026-10-19):** premis keliru. Keluhan sebenarnya bukan soal tampilan tombol Edit, melainkan **tidak ada navigasi kembali ke halaman proyek dari subhalaman Dokumen & Activity Log** (halaman Edit sendiri sudah punya tombol "Batal"). Dilacak terpisah di `.agents/tasks/ux-project-subpages-no-back-nav/findings.md` dan dikerjakan di branch tersendiri dari `main`, bukan sebagai bagian Fase 1.

**Kriteria selesai:** nilai opportunity tersimpan dan tampil; Requirement bisa dipilih sebagai tipe dokumen.
