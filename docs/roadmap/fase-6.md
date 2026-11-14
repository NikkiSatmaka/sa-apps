<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 6 — BoQ Compare vs Requirement (fitur 10) — ⏸ dikerjakan setelah Fase 9 (keputusan 2026-11-13)

**Tujuan:** analisis gap bertenaga AI antara dokumen Requirement dan dokumen BoQ. **Fitur baru dengan kompleksitas tertinggi** — bergantung pada Fase 1.2 (tipe dokumen `Requirement` di enum), **Fase 5.5 (konten Requirement turunan AI di-generate dari MoM/RFP + field Sales)**, dan guardrails dari Fase 7. Catatan model: dokumen Requirement adalah summary turunan (lihat 5.5), bukan upload customer — jadi perbandingan selalu punya baseline terstruktur untuk dibandingkan, meski customer tidak memberi file requirement formal.

- [ ] 6.1 Service: diberi dokumen `Requirement` (summary turunan dari Fase 5.5) dan dokumen BoQ sebuah proyek, kirim keduanya ke Gemini via path multimodal `parse_document` / `structure_text` yang sudah ada.
- [ ] 6.2 Definisikan schema output terstruktur: `covered[]`, `missing[]`, `extra[]`, dan `coverage_percentage`.
- [ ] 6.3 Endpoint `GET/POST /projects/{id}/boq-compare`; persist hasil comparison terbaru untuk proyek.
- [ ] 6.4 Frontend: tampilan comparison yang menunjukkan item covered/missing/extra dan skor coverage, dengan tombol run ulang.
- [ ] 6.5 Handle edge case: Requirement belum di-generate (belum ada MoM/RFP/field Sales), BoQ tidak ada, atau LLM gagal (pakai ulang pola retry scoring engine).

**Kriteria selesai:** memilih Requirement + BoQ untuk sebuah proyek mengembalikan analisis gap terstruktur dengan skor coverage, dirender di UI.
