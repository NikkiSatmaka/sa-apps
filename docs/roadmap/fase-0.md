<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 0 — Hardening Keamanan & Correctness (bagian dari Guardrails, fitur 11)

**Tujuan:** membuat app aman untuk di-deploy secara nyata dan memperbaiki bug yang merusak fungsionalitas. Ini adalah interpretasi "guardrails auth" dan menjadi prasyarat untuk MVP produksi mana pun.

- [x] 0.1 Default `DEMO_MODE` menjadi `False`; cegah `/auth/demo-login` agar tidak mungkin aktif di build produksi. (`backend/app/core/config.py`, `backend/app/api/auth.py`)
- [x] 0.2 Hapus default `JWT_SECRET_KEY` yang tidak aman; fail fast saat startup jika belum di-set. Selaraskan penamaan `SECRET_KEY` (README) vs `JWT_SECRET_KEY` (kode). (`config.py`, `README.md`)
- [x] 0.3 Berhenti mengirim JWT access/refresh token sebagai query param URL di redirect OAuth callback; pindah ke URL hash (seperti flow calendar yang sudah ada) atau httpOnly cookie. (`frontend/src/app/api/v1/[...path]/route.ts`)
- [x] 0.4 Kunci default CORS dari `*` menjadi allow-list yang digerakkan env. (`config.py`, `main.py`)
- [x] 0.5 Fix bug **B1** (notifikasi `metadata=`), **B3** (health check DB sungguhan — daftarkan `app/api/health.py` yang sudah benar, atau panggil `check_database_health()` di `main.py`), **B5** (putuskan Alembic vs `create_all`), **B6** (migration `project_collaborators`), **B7** (`event_type` reassign melanggar constraint).
- [x] 0.6 **Tutup authz yang hilang.** Pasang `get_current_user` + cek akses proyek ke semua endpoint `scoring.py` (fix **B8**); tambahkan cek role/akses ke `PATCH /projects/{id}` (fix **B9**). Pertimbangkan ekstraksi dependency `require_role(...)` yang reusable, karena cek role saat ini di-copy-paste di tiap handler sebagai `if current_user.role not in (...)`.

**Kriteria selesai:** app menolak start dengan default tidak aman; token tidak pernah muncul di URL/log; jalur notifikasi scoring + assignment/reassignment berfungsi; health check mencerminkan status DB sebenarnya; tidak ada endpoint yang menulis skor BANT, mengubah status, atau mengedit proyek tanpa autentikasi dan cek akses.
