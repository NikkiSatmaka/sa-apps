# Tunda push due date → Calendar ke pasca-MVP; MVP tetap read-only

Fase 3 (fitur 8) semula bertujuan push satu arah: due date proyek (`target_submit`) → event di Google Calendar SA yang di-assign, dengan edit meng-update event dan close/lost menghapusnya. Investigasi kode (sesi grill, 2026-10-26) menemukan integrasi calendar saat itu **read-only** (`CalendarService.fetch_events` saja, scope `calendar.readonly`), dan token OAuth calendar bersifat **ephemeral & dioper per-request oleh user aktif** (`POST /calendar/sync` menerima `access_token` di body; tidak ada token/refresh token tersimpan server-side, tidak ada field-nya di `User`).

**Keputusan (sesi grill, 2026-10-26):** untuk MVP, calendar **tetap read-only** — fitur push TIDAK diimplementasikan sekarang. Alasan: push yang benar secara semantik ("event di calendar SA yang di-assign") mengharuskan server menulis ke calendar SA kapan saja tanpa SA online, yang menuntut penyimpanan refresh token OAuth per-user server-side. Itu permukaan keamanan baru yang signifikan (penyimpanan token sensitif, enkripsi, refresh flow) dan bertentangan dengan arah Fase 0 yang justru menjauhkan token dari tempat mudah bocor. Biaya keamanan itu tidak sepadan untuk MVP calendar.

## Bentuk versi pasca-MVP (intent, belum dibangun)

Saat dikerjakan nanti ("opsi b"):
- Simpan refresh token calendar per-user server-side (enkripsi), sehingga server bisa menulis ke calendar **SA yang di-assign** tanpa SA online.
- Tambah kolom `gcal_duedate_event_id` (nullable) di `Project` — satu event due date per proyek.
- Re-assignment memigrasi event antar-calendar (hapus di SA lama, buat di SA baru) karena token kedua SA tersedia.
- Pada close/lost/selesai: **hapus event yang tanggalnya belum terlewati**; event bertanggal masa lalu **dibiarkan** sebagai jejak. Kosongkan `gcal_duedate_event_id` hanya saat event benar-benar dihapus. Penghapusan yang gagal degrade dengan baik (log warning, jangan gagalkan transisi status proyek).

## Consequences

Roadmap Fase 3 ditandai ditunda (pasca-MVP); `target_submit` tetap ada dan dapat diedit di app, hanya tidak tercermin ke Google Calendar pada MVP. README/spec tidak boleh mengklaim push calendar berfungsi. Pada keputusan awal, kolom `gcal_duedate_event_id` dan penyimpanan token TIDAK ditambahkan untuk menghindari migration/skema yang belum dipakai.

## Update issue #208 (2026-11-16)

Calendar tetap read-only dan tetap memakai scope `calendar.readonly`. Sync kini memakai token akses Google yang disimpan terenkripsi di tabel `calendar_oauth_sessions`; browser hanya menerima cookie HttpOnly berisi ID sesi acak yang terikat ke user aktif. Sesi kedaluwarsa setelah satu jam dan dicabut saat logout atau saat Google menolak token (401/403). Refresh token Google tidak disimpan. Batas sync tetap tujuh hari ke belakang/depan dan maksimal 200 event.
