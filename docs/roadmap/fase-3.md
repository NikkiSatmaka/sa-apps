<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 3 — Integrasi Due Date dengan Calendar (fitur 8) — ⏸️ DITUNDA (pasca-MVP)

**Status:** **Ditunda keluar dari MVP (keputusan sesi grill, 2026-10-26).** Calendar tetap **read-only** untuk MVP (fitur sync/map event yang sudah ada). Push due date → Calendar tidak diimplementasikan sekarang karena push yang benar ("event di calendar SA yang di-assign") menuntut penyimpanan refresh token OAuth per-user server-side — permukaan keamanan baru yang signifikan dan bertentangan dengan arah Fase 0. Lihat [`docs/adr/0007-defer-calendar-push-to-post-mvp.md`](../adr/0007-defer-calendar-push-to-post-mvp.md). Dilacak sebagai spec deferral di issue tracker.

**Tujuan (saat dikerjakan nanti, "opsi b"):** menghubungkan `target_submit` dengan Google Calendar via push satu arah ke calendar SA yang di-assign, dengan token per-user tersimpan server-side.

- [ ] 3.1 **✅ Diputuskan (sesi grill, 2026-10-21):** push **SATU ARAH** — due date proyek (`target_submit`) → event calendar SA yang di-assign. Edit due date meng-update event tertaut; proyek close/lost menghapus event. Bukan sync dua arah. **(Ditunda pasca-MVP per keputusan 2026-10-26.)**
- [ ] 3.2 Perluas `CalendarService` dengan create/update event; simpan refresh token calendar per-user server-side agar server bisa menulis ke calendar SA tanpa SA online. Tambah kolom `gcal_duedate_event_id` di `Project`.
- [ ] 3.3 Saat due date di-edit, update event tertaut; saat proyek close/lost/selesai, **hapus event yang tanggalnya belum terlewati** (event bertanggal masa lalu dibiarkan sebagai jejak), kosongkan `gcal_duedate_event_id` hanya saat event benar-benar dihapus; penghapusan gagal degrade dengan baik (log, jangan gagalkan transisi status).
- [ ] 3.4 Re-assignment memigrasi event antar-calendar (hapus di SA lama, buat di SA baru). Handle kasus tanpa token calendar dengan baik.

**Kriteria selesai (pasca-MVP):** meng-set atau meng-edit due date proyek tercermin di Google Calendar SA yang di-assign; ketiadaan token degrade dengan baik; re-assignment memindahkan event.
