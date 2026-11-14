<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 5 — Form Pertanyaan Awal (fitur 3)

**Tujuan:** intake kualifikasi terstruktur saat pembuatan opportunity, dan dokumen Requirement turunan AI sebagai baseline Fase 6. **Dipecah dua (keputusan sesi grill, 2026-11-10):** 5A (kuesioner + skor di backend) dan 5B (generate Requirement). Spec: [#24](https://github.com/NikkiSatmaka/sa-apps/issues/24) (5A), [#25](https://github.com/NikkiSatmaka/sa-apps/issues/25) (5B). Tiket: #26–#37.

### Fase 5A — Kuesioner kualifikasi (spec #24)

- [x] 5.1 ✅ **Diputuskan (2026-11-10):** set pertanyaan **tetap** di kode untuk MVP (12 pertanyaan, 6 wajib), jawaban disimpan bersama `schema_version` agar bisa dikonfigurasi admin kelak (backlog pasca-MVP).
- [x] 5.2 Skema jawaban (JSONB di proyek) + rubrik skor deterministik **di backend**; `score-manual` dibatasi sebagai override Lead SA/Admin. Lihat [`docs/adr/0010-bant-score-computed-in-backend.md`](../adr/0010-bant-score-computed-in-backend.md). Tiket #26, #28, #30.
- [x] 5.3 Frontend: `projects/new` menjadi form dua langkah (data dasar + file, lalu kuesioner) dengan satu pengiriman; form manual BANT dihapus; detail/edit proyek menampilkan jawaban dan data legacy. Tiket #26, #29, #32.
- [x] 5.3a Source document: tipe MoM/RFP per file + ekstraksi teks via LLM disimpan di DB (bahan Requirement). Tiket #31.
- ~~5.4 (Opsional AI) pertanyaan klarifikasi yang di-generate AI.~~ **Ditunda pasca-MVP (2026-11-10):** bertanda opsional dan Fase 6 tidak bergantung padanya. Jalan keluar `Need Clarification` ditangani 5A lewat edit kuesioner + re-score (#32).

**Status 5A:** terimplementasi di branch `feat/phase-5a-kuesioner-kualifikasi` (tiket #26, #28–#32); migration 010–012 baru diverifikasi lewat SQL offline (upgrade/downgrade di database nyata belum dijalankan); Gemini di-mock pada test.

**Kriteria selesai 5A:** Sales mengisi kuesioner saat membuat opportunity; skor BANT dihitung backend (rubrik + gabungan AI max per kriteria); `Need Clarification` bisa diperbaiki dan dinilai ulang; Lead SA bisa override dengan alasan tercatat; teks MoM/RFP tersimpan sebagai Source document.

### Fase 5B — Generate dokumen Requirement (spec #25)

- [x] 5.5 **Generate dokumen Requirement (summary turunan AI).** Dokumen `Requirement` BUKAN file yang di-upload user, melainkan **konten turunan**: daftar butir terstruktur (`kategori` + `butir`) yang di-generate Gemini dari **kuesioner + Source document (MoM/RFP)**, disimpan sebagai `Document` dengan `doc_type="Requirement"` (`gdrive_link` nullable lewat CHECK khusus Requirement, `folder_type=Inventory`), muncul di daftar dokumen proyek dan menjadi baseline Fase 6. Di-generate otomatis saat proyek pertama kali lolos gate; di-resummarize saat `source_hash` berubah. **Keputusan (2026-10-19, product owner):** derived content, bukan upload; di-resummarize saat source berubah; hidup di tabel `Document`. **✅ Diputuskan (sesi grill, 2026-10-21):** SA **BOLEH** meng-edit/override hasil generate, ditandai flag `is_overridden`; saat source berubah dan sudah di-override, re-summarize **tidak** menimpa diam-diam — notifikasi dan konfirmasi dulu. Lihat [`docs/adr/0004-requirement-override-blocks-silent-resummarize.md`](../adr/0004-requirement-override-blocks-silent-resummarize.md). Tiket #33–#37.

**Status 5B:** terimplementasi (tiket #33–#37); migration 014–015 baru diverifikasi lewat SQL offline (upgrade/downgrade di database nyata belum dijalankan); Gemini di-mock pada test.

**Kriteria selesai 5B:** proyek yang lolos gate memiliki dokumen Requirement terstruktur yang di-resummarize saat sumber berubah (kecuali sudah di-override, yang memunculkan notifikasi dan konfirmasi).

**Kriteria selesai Fase 5:** 5A dan 5B selesai.

> **Catatan Drive:** persistensi file MoM/RFP ke Google Drive (staging folder lalu dipindah ke `Inventory`) **belum** termasuk Fase 5 dan menunggu verifikasi Drive nyata ([#27](https://github.com/NikkiSatmaka/sa-apps/issues/27)). Untuk sekarang hanya teks ekstraksi yang disimpan di DB.
