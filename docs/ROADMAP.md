# Portal SA — Roadmap Fitur MVP

Dokumen pelacakan untuk fitur yang dibutuhkan agar mencapai MVP yang layak. Status dinilai berdasarkan kode aktual (bukan klaim spec) pada **2026-10-12**. Coverage roadmap direkonsiliasi terhadap ground truth produk (`SA Application/Spesifikasi_Teknis_Portal_SA.md`) pada **2026-10-20**; audit rekonsiliasi: `.agents/tasks/roadmap-spec-reconcile-2026-10-20/findings.md`.

> **Asumsi yang dipakai menyusun roadmap ini** (dipilih sebagai default; ubah fase terkait jika ada yang keliru):
> - **Form pertanyaan awal** = hybrid: kuesioner kualifikasi statis yang diisi Sales saat membuat opportunity, dengan opsi pertanyaan klarifikasi yang di-generate AI untuk area BANT yang lemah.
> - **Subtask** = subtask yang benar-benar bisa ditugaskan: Lead SA (atau template proyek) membuat subtask per proyek; SA melihatnya sebagai to-do list dengan status (open → in progress → done) dan mencatat aktivitas terhadap subtask tertentu.
> - **BoQ compare vs Requirement** = analisis gap AI **+ skor coverage**: pilih dokumen Requirement dan dokumen BoQ, Gemini mengembalikan item yang covered / missing / extra beserta persentase coverage.
> - **Guardrails** = hardening auth/keamanan dulu (default yang tidak aman untuk produksi), baru keamanan input/output LLM.
> - **Urutan pengerjaan** = keamanan dulu, lalu menutup fitur yang partial, baru fitur baru.

---

## Legenda Status

| Simbol | Arti |
|--------|------|
| ✅ Selesai | Terimplementasi dan berfungsi |
| 🟡 Partial | Ada tapi belum lengkap, masih stub, atau bug |
| 🔴 Belum ada | Belum diimplementasikan dalam bentuk apa pun |

---

## Ringkasan Status Fitur

| # | Fitur | Status | Gap utama |
|---|-------|--------|-----------|
| 1 | Halaman login | ✅ Selesai | Demo mode opt-in + hard block produksi; token OAuth di URL hash (bukan query); default produksi aman (JWT secret fail-fast, CORS allow-list); authz `scoring.py` & `PATCH /projects/{id}` beres (B8/B9, Fase 0.6) |
| 2 | Request Sales / buat opportunity | ✅ Selesai | — |
| 3 | Form pertanyaan awal | 🔴 Belum ada | Tidak ada konsep kuesioner intake |
| 4 | BANT scoring | ✅ Selesai | AI + manual keduanya berfungsi |
| 5 | Kualifikasi & assignment oleh Lead SA | ✅ Selesai | Folder provisioner di-wire end-to-end (#45): assign men-schedule provisioning, persist `gdrive_folder_id` + `gdrive_solutions_folder_id` + status pending/provisioned/failed, badge dashboard + endpoint re-provision. Tidak ada step qualify terpisah — gate BANT ≥ 60% otomatis sudah memenuhi spec (Fase 2.3) |
| 6 | Staff mengikuti subtask / respons subtask via activity log | ✅ Selesai | Entity `Subtask` assignable end-to-end: seeding auto-assign ke SA proyek (T1), activity log memajukan `open → in_progress` dengan validasi scope (T2, ADR 0008), dan section Subtask di `projects/[id]` dengan kontrol per-role + badge status + ringkasan "N/M selesai" (T3). `done` selalu eksplisit via tombol "Tandai selesai" |
| 7 | Input dokumen (Requirement, BoQ, Mandays, PropTek, HLD) | 🟡 Partial | Tipe "Requirement" belum ada (hanya RFP/PropTek/BOQ/Mandays/MoM/HLD) |
| 8 | Due date + integrasi calendar | 🟡 Partial | `target_submit` ada; calendar read-only, tidak ada push due date |
| 9 | Edit due date / ikon pensil edit | 🟡 Partial | Alur edit berfungsi; masih tombol teks, bukan ikon pensil |
| 10 | BoQ compare vs Requirement | 🔴 Belum ada | Tidak ada fitur perbandingan; dokumen Requirement (summary turunan AI) belum di-generate — tipe `Requirement` sudah ada di enum (Fase 1.2), tapi kontennya belum disintesis |
| 11 | Guardrails | ✅ Selesai | Guardrail LLM terpusat (size clamp, PII flag-and-log, mitigasi prompt-injection, validasi output) di tiga Call_Site; hardening default auth dilacak di fitur 1 / Fase 0 |
| 12 | SLA DQ Number & gating (Flow 2) | 🟡 Partial | **Baru ditambahkan 2026-10-20** (rekonsiliasi spec). Kode SLA ada (`backend/app/services/sla_timer.py`, `backend/app/api/sla.py`) dan read-gating DQ ada (`backend/app/api/dq_number.py`), **tapi tidak di-wire end-to-end**: SLA timer tidak pernah di-start (B11), tidak ada scheduler (B12), sehingga auto-lock folder Solutions / reminder H+3 / eskalasi H+5 mati end-to-end. Dilacak di Fase 2A. |

> **Catatan penomoran:** fitur 1–11 dipertahankan apa adanya. Fitur **12 (SLA DQ Number & gating)** ditambahkan pada 2026-10-20 setelah audit rekonsiliasi menemukan Flow 2 (salah satu dari 4 flow inti spec) tidak punya "rumah" di daftar fitur, sehingga bug wiring SLA tidak punya tempat tercatat.

---

## Bug yang Harus Diperbaiki (terlepas dari fitur)

Ditemukan saat asesmen dan sebaiknya diperbaiki lebih awal — ini merusak fungsionalitas yang sudah ada.

- [x] **B1. Crash `metadata=` pada `NotificationLog`** — `backend/app/services/scoring_engine.py` ~line 623 mengirim `metadata=` ke constructor model, padahal atributnya `notification_metadata` (`metadata` reserved oleh SQLAlchemy). Ini raise saat runtime, merusak notifikasi scoring ke Lead SA dan jalur notifikasi manual-review. _Fix: ganti jadi `notification_metadata=`._
- [x] **B2. Folder provisioner tidak pernah dipanggil** — `backend/app/api/assignment.py` `_trigger_folder_provisioner` (~line 54) adalah stub `pass` dengan TODO, padahal response melaporkan `folder_provisioning_triggered=True`. Service `FolderProvisioner` sudah diimplementasikan penuh tapi tidak pernah di-wire. (Ditangani di Fase 2 / fitur 5.) _Fix (#45): stub diganti pemanggilan nyata `provision_project_folder` dengan persist kedua id + status provisioning; `folder_provisioning_triggered` jadi reflektif (bukan hardcode)._
- [x] **B3. `/health` melaporkan status DB palsu** — `backend/app/main.py` mengembalikan `"database": "healthy"` yang di-hardcode, bukan memanggil `check_database_health()` yang sudah ada. Membatalkan fungsi Docker health check.
- [x] **B4. `estimasi_nilai` tidak dipersist** — `create_project` memvalidasi dan mengembalikannya tapi tidak ada kolom di model `Project`, jadi nilai opportunity hilang. (Ditangani di Fase 1 / fitur 2.) _Fix: tambah kolom `Numeric(14,2)` nullable di model `Project` + migration `005`, simpan saat create, tampilkan di detail/list, dan bisa diedit via `PATCH` dengan validasi range sama._
- [x] **B10. `bant_detail` tidak tersimpan saat edit** — `PATCH /projects/{id}` memutasi dict `bant_detail` secara in-place, tapi kolom `JSONB` tanpa `MutableDict` membuat SQLAlchemy tidak mendeteksi perubahan sehingga `commit()` melewatinya (response 200 tapi data tidak berubah). _Fix: bungkus kolom `bant_detail` dengan `MutableDict.as_mutable(JSONB)` di model `Project` sehingga mutasi in-place terlacak._
- [x] **B5. `create_all` saat startup melewati Alembic** — `main.py` membuat tabel otomatis, bersaing dengan migrasi Alembic. Pilih satu mekanisme untuk menghindari schema drift.
- [x] **B6. `project_collaborators` tanpa migration** — tabel ini hanya terdefinisi sebagai model SQLAlchemy; tidak ada migration Alembic yang membuatnya (hanya terbentuk lewat `create_all` saat startup). Melanggar aturan AGENTS.md "jangan andalkan auto-create table sebagai mekanisme migration" dan merupakan manifestasi konkret dari B5. _Fix: tambahkan migration Alembic untuk `project_collaborators` (termasuk FK `ON DELETE CASCADE` dan `UniqueConstraint(id_project, user_id)`)._
- [x] **B7. `event_type="reassignment"` melanggar CheckConstraint** — `backend/app/api/assignment.py` `reassign_sa_to_project` membuat `NotificationLog(event_type="reassignment", ...)`, padahal nilai itu tidak termasuk dalam `chk_notification_logs_event_type` (`assignment`, `status_change`, `sla_reminder`, `sla_escalation`, `handover`, `doc_ready`). Bahkan setelah B1 diperbaiki, INSERT reassign tetap ditolak DB. _Fix: ganti ke `assignment`, atau tambahkan `reassignment` ke enum + migration._
- [x] **B8. Router `scoring.py` tanpa autentikasi** — seluruh endpoint di `backend/app/api/scoring.py` (`POST /projects/{id}/score-manual`, `GET /projects/{id}/bant-result`, `GET /projects/{id}/recommendations`) tidak memasang dependency `get_current_user`. Siapa pun yang bisa menjangkau API dapat menulis skor BANT dan mengubah status proyek (lewat `apply_threshold`). Risiko authz nyata. _Fix: pasang `get_current_user` + cek akses proyek di semua endpoint scoring._
- [x] **B9. `PATCH /projects/{id}` tanpa cek role/akses** — `backend/app/api/projects.py` `update_project` tidak melakukan cek role atau akses proyek, sehingga user terautentikasi mana pun bisa mengedit `project_name`/`customer_name`/`dq_number`/`bant_detail` proyek apa pun. _Fix: tambahkan cek akses proyek berbasis role, konsisten dengan endpoint project lainnya._
- [x] **B11. `sla_timer.start_timer` tidak pernah dipanggil** — `start_timer` hanya terdefinisi di `backend/app/services/sla_timer.py` (~line 91) dan tidak dipanggil dari mana pun. `assign_sa_to_project` (`backend/app/api/assignment.py`) men-set `project.assigned_at` (~line 583) lalu insert notifikasi + menjadwalkan folder provisioner, **tapi tidak memanggil `sla_timer.start_timer()`**. Akibatnya tidak ada row `SLATracking` yang pernah dibuat lewat jalur normal, sehingga seluruh Flow 2 SLA (reminder H+3, eskalasi H+5, auto-lock folder Solutions) **mati total end-to-end** walau kodenya lengkap. _Fix: wire `start_timer(...)` di `assign_sa_to_project` setelah `assigned_at` di-set._ (Dilacak di Fase 2A / fitur 12.) _Terverifikasi 2026-11-10: `assign_sa_to_project` kini memanggil `sla_timer.start_timer(...)` (`backend/app/api/assignment.py` ~line 728), diikat `test_sla_assignment_wiring.py`._
- [x] **B12. Tidak ada scheduler untuk `process_sla_actions()`** — `process_sla_actions()` hanya terpanggil via endpoint manual `POST /sla/process` (`backend/app/api/sla.py`, `process_sla` ~line 77, memanggil `sla_timer.process_sla_actions()` ~line 101), yang butuh trigger manual Admin/Lead_SA. Spec Flow 2 menyiratkan otomasi berbasis waktu (H+3 reminder, H+5 eskalasi). Tidak ada background scheduler/cron di `backend/app/main.py`. _Opsi: tambah background scheduler, atau dokumentasikan secara eksplisit bahwa cron eksternal memanggil `POST /sla/process` secara periodik._ (Dilacak di Fase 2A / fitur 12.) _Terverifikasi 2026-11-10: `SLAScheduler` (`backend/app/services/sla_scheduler.py`) dijalankan saat startup di `backend/app/main.py` (toggle `SLA_SCHEDULER_ENABLED`, ADR 0003), diikat `test_sla_scheduler.py`._
- [x] **B13. Event `doc_ready` tidak pernah di-emit (Flow 2, cabang "<5 hari")** — spec: saat dokumen menjadi `Reviewed`, link Drive terbuka otomatis untuk Sales + email pemberitahuan. Realita: `update_document_status` (`backend/app/api/documents.py`) menjalankan transisi Draft→Reviewed→Final dengan benar **tapi tidak meng-emit notifikasi `doc_ready` ke Sales dan tidak membuka permission Drive Solutions** saat `Reviewed`. `NotificationEventType.DOC_READY` terdefinisi di `backend/app/services/notification_service.py` (~line 47, dipakai hanya di map subject ~line 405) tetapi tidak pernah di-emit. _Fix: emit `DOC_READY` + buka permission Solutions untuk Sales pada transisi ke `Reviewed` (saat DQ sudah terisi)._ (Dilacak di Fase 2A / fitur 12.) _Terverifikasi 2026-11-10: `_handle_doc_ready` (`backend/app/api/documents.py`) emit `DOC_READY` + buka akses Solutions saat transisi ke `Reviewed` dengan DQ terisi, diikat `test_doc_ready.py`._
- [x] **B14. Closed-Win tidak memicu notifikasi wajib HLD (Flow 4 langkah 1)** — spec: saat proyek menjadi `Closed-Win`, SA menerima notifikasi wajib "create HLD". Realita: `update_project_status` (`backend/app/api/workflow.py`, ~line 125 — bukan `backend/app/workflow.py`) hanya menulis audit log `status_change` pada transisi ke `Closed-Win`; tidak ada emit notifikasi mandatory-HLD ke SA. _Fix: emit notifikasi "wajib buat HLD" dari `update_project_status` saat masuk status `Closed-Win`._ (Dilacak di Fase 4 / fitur 6 — berkaitan dengan post-sales handover.)

---

## Fase 0 — Hardening Keamanan & Correctness (bagian dari Guardrails, fitur 11)

**Tujuan:** membuat app aman untuk di-deploy secara nyata dan memperbaiki bug yang merusak fungsionalitas. Ini adalah interpretasi "guardrails auth" dan menjadi prasyarat untuk MVP produksi mana pun.

- [x] 0.1 Default `DEMO_MODE` menjadi `False`; cegah `/auth/demo-login` agar tidak mungkin aktif di build produksi. (`backend/app/core/config.py`, `backend/app/api/auth.py`)
- [x] 0.2 Hapus default `JWT_SECRET_KEY` yang tidak aman; fail fast saat startup jika belum di-set. Selaraskan penamaan `SECRET_KEY` (README) vs `JWT_SECRET_KEY` (kode). (`config.py`, `README.md`)
- [x] 0.3 Berhenti mengirim JWT access/refresh token sebagai query param URL di redirect OAuth callback; pindah ke URL hash (seperti flow calendar yang sudah ada) atau httpOnly cookie. (`frontend/src/app/api/v1/[...path]/route.ts`)
- [x] 0.4 Kunci default CORS dari `*` menjadi allow-list yang digerakkan env. (`config.py`, `main.py`)
- [x] 0.5 Fix bug **B1** (notifikasi `metadata=`), **B3** (health check DB sungguhan — daftarkan `app/api/health.py` yang sudah benar, atau panggil `check_database_health()` di `main.py`), **B5** (putuskan Alembic vs `create_all`), **B6** (migration `project_collaborators`), **B7** (`event_type` reassign melanggar constraint).
- [x] 0.6 **Tutup authz yang hilang.** Pasang `get_current_user` + cek akses proyek ke semua endpoint `scoring.py` (fix **B8**); tambahkan cek role/akses ke `PATCH /projects/{id}` (fix **B9**). Pertimbangkan ekstraksi dependency `require_role(...)` yang reusable, karena cek role saat ini di-copy-paste di tiap handler sebagai `if current_user.role not in (...)`.

**Kriteria selesai:** app menolak start dengan default tidak aman; token tidak pernah muncul di URL/log; jalur notifikasi scoring + assignment/reassignment berfungsi; health check mencerminkan status DB sebenarnya; tidak ada endpoint yang menulis skor BANT, mengubah status, atau mengedit proyek tanpa autentikasi dan cek akses.

---

## Fase 1 — Menutup Partial yang Mudah (quick wins)

**Tujuan:** menyelesaikan fitur yang sudah 80% jadi dengan perubahan kecil dan berisiko rendah.

- [x] 1.1 **Fitur 2:** persist `estimasi_nilai` — tambah column + migration ke `Project`, simpan saat create, tampilkan di detail/edit. (fix **B4**)
- [x] 1.2 **Fitur 7:** tambahkan `Requirement` ke `DocTypeEnum` dan constraint `CHECK` di DB; perbarui dropdown tipe dokumen di frontend. (`backend/app/schemas/document.py`, `backend/app/models/document.py`, migration, `frontend/src/components/DocumentForm.tsx`)
- [ ] ~~1.3 **Fitur 9:** ganti tombol teks "Edit" dengan ikon pensil/edit di halaman detail proyek.~~ **Dibatalkan (2026-10-19):** premis keliru. Keluhan sebenarnya bukan soal tampilan tombol Edit, melainkan **tidak ada navigasi kembali ke halaman proyek dari subhalaman Dokumen & Activity Log** (halaman Edit sendiri sudah punya tombol "Batal"). Dilacak terpisah di `.agents/tasks/ux-project-subpages-no-back-nav/findings.md` dan dikerjakan di branch tersendiri dari `main`, bukan sebagai bagian Fase 1.

**Kriteria selesai:** nilai opportunity tersimpan dan tampil; Requirement bisa dipilih sebagai tipe dokumen.

---

## Fase 2 — Folder Provisioning & Assignment (fitur 5)

**Tujuan:** men-wire provisioner yang sudah dibangun dan memperjelas alur Lead SA.

- [x] 2.1 Ganti stub `_trigger_folder_provisioner` dengan pemanggilan nyata ke `FolderProvisioner.provision_project_folder`, termasuk handling retry/`Provisioning Failed` yang sudah didukung service. (fix **B2**) **Mendarat (#45):** `_trigger_folder_provisioner` membuka session baru via `AsyncSessionLocal()`, set `folder_provisioning_status='pending'`, panggil `provision_project_folder`, lalu persist `gdrive_folder_id` (master) + `gdrive_solutions_folder_id` + status `'provisioned'`; `FolderProvisioningError` (setelah retry internal service) → status `'failed'`, graceful (tidak menggagalkan transisi).
- [x] 2.2 Hanya laporkan `folder_provisioning_triggered=True` saat provisioning benar-benar di-schedule; ekspos status provisioning di proyek agar badge "Folder Pending" berfungsi. **Mendarat (#45):** `AssignmentResponse.folder_provisioning_triggered` kini mencerminkan apakah task benar-benar dijadwalkan (variabel `folder_scheduled`, bukan hardcode `True`); `folder_provisioning_status` diekspos di response list/detail proyek + payload card, dan badge dashboard Lead_SA membacanya (pending/provisioned/failed).
- [x] 2.3 **Fakta spec (bukan asumsi terbuka):** BANT ≥ 60% adalah gatekeeper kualifikasi — spec Flow 1 langkah 3 menetapkannya eksplisit, dan kode sudah mengimplementasikannya (`scoring_engine.apply_threshold()`: `score >= 60` → `Pending Assignment` + notifikasi Lead_SA; `< 60` → `Need Clarification`). Threshold ini **tidak** perlu dikonfirmasi lagi. **✅ Diputuskan (sesi grill, 2026-10-21):** **TIDAK** ada step "qualify" manual terpisah di atas gate otomatis — gate BANT ≥ 60% otomatis sudah memenuhi spec. Tidak perlu status/endpoint tambahan untuk ini.
- [x] 2.4 Verifikasi end-to-end: assign → folder Drive dibuat dengan permission yang benar (Editor SA/Lead, Viewer Sales di Inventory) → `gdrive_folder_id` tersimpan. **Mendarat (#45):** diikat test (`backend/tests/test_assignment_folder_provisioning.py`, `test_reprovision_endpoint.py`, `test_folder_provisioner.py`): jalur sukses mem-persist `gdrive_folder_id` + `gdrive_solutions_folder_id` (ADR 0005) + status `'provisioned'`, jalur gagal → `'failed'` graceful; permission folder diverifikasi di test `FolderProvisioner` (semua I/O Drive di-mock di boundary). Endpoint re-provision `POST /projects/{id}/provision-folder` dengan null-guard idempotency (ADR 0006) + role-guard Lead_SA/Admin.

**Kriteria selesai:** meng-assign SA benar-benar membuat tree folder Drive dengan permission yang benar, dengan state pending/failed yang terlihat.

---

## Fase 2A — SLA DQ Number & Gating end-to-end (fitur 12)

**Tujuan:** menyalakan Flow 2 (Dokumen, DQ Number & Gating) dari spec. Kode SLA (`backend/app/services/sla_timer.py`, `backend/app/api/sla.py`) dan read-gating DQ (`backend/app/api/dq_number.py`) sudah ada tapi tidak pernah berjalan karena tidak di-wire. **Ini wiring, bukan fitur baru dari nol** — effort rendah-menengah, tapi dampaknya besar (salah satu dari 4 flow inti). Bergantung pada Fase 2 (folder provisioning, B2) karena auto-lock folder Solutions butuh `gdrive_folder_id` yang terisi.

> **Catatan (#45, kontrak Solutions id):** auto-lock/unlock SLA (2A.1–2A.4) baru benar end-to-end **setelah** kontrak Solutions id mendarat. Sebelumnya consumer (SLA lock/unlock, unlock `doc_ready`, dan `Final_Deliverables` handover) menyasar id folder **master** (`gdrive_folder_id`), sehingga Flow 2 laten salah folder. Kini consumer memakai `gdrive_solutions_folder_id` (ADR 0005), jadi lock/unlock benar-benar mengenai folder Solutions. Cabang **email** eskalasi SLA tetap belum tuntas — lihat 2A.5.

- [x] 2A.1 Wire `sla_timer.start_timer(...)` di `assign_sa_to_project` (`backend/app/api/assignment.py`) setelah `assigned_at` di-set. (fix **B11**) Tanpa ini tidak ada row `SLATracking`, seluruh SLA mati.
- [x] 2A.2 Jalankan `process_sla_actions()` secara otomatis berbasis waktu. (fix **B12**) **✅ Diputuskan (sesi grill, 2026-10-21):** pakai **background scheduler internal ringan** yang jalan saat startup backend untuk MVP single-instance (bukan cron eksternal). **Catatan:** pilihan ini tidak aman untuk multi-instance (tiap instance akan menduplikasi aksi SLA); saat scale-out pindah ke cron eksternal / leader-election. Lihat [`docs/adr/0003-sla-internal-scheduler-for-mvp.md`](adr/0003-sla-internal-scheduler-for-mvp.md).
- [x] 2A.3 Emit `doc_ready` + buka permission Drive Solutions untuk Sales saat dokumen menjadi `Reviewed` dengan DQ terisi (cabang "<5 hari"). (fix **B13**) Sitasi: `backend/app/api/documents.py`, `backend/app/services/notification_service.py`. In-app sudah jalan; cabang email mengikuti T1 (2A.5).
- [x] 2A.4 Verifikasi end-to-end: assign → timer start → (DQ belum diinput >5 hari) reminder H+3 + eskalasi H+5 + auto-lock Solutions; (dokumen Reviewed <5 hari) link Solutions terbuka untuk Sales + email. Diikat test E2E `backend/tests/test_flow2_e2e.py` (T5): kedua cabang + input DQ setelah lock → stop timer + auto-unlock, plus auto-lock di-skip graceful saat `gdrive_folder_id` kosong. Catatan (historis, ditutup oleh 2A.5): cabang **email** eskalasi SLA belum terbukti karena `_send_sla_reminder`/`_send_sla_escalation` menulis `NotificationLog` `in-app` langsung, tidak lewat `notification_service.send_notification` (jalur email) — lihat 2A.5.
- [x] 2A.5 **Email/Gmail sebagai trigger (gap requirement, spec §4.C).** **Mendarat (#21):** T1 mengganti stub `send_email()` dengan Gmail API nyata; kini `_send_sla_reminder`/`_send_sla_escalation` (`backend/app/services/sla_timer.py`) tetap menulis `NotificationLog` in-app dalam transaksinya **dan** memicu email lewat `notification_service.dispatch_email_for_user` (reminder H+3 ke Sales; eskalasi H+5 ke Lead_SA/Admin + pemberitahuan lock ke Sales). Graceful: no-op tanpa Gmail, kegagalan email tidak menggagalkan `process_sla_actions`. Diikat `backend/tests/test_sla_email_trigger.py`. Catatan: terverifikasi dengan Gmail API di-mock; pengiriman nyata butuh `GMAIL_CREDENTIALS` + domain-wide delegation di environment.

**Kriteria selesai:** assignment benar-benar memulai SLA timer; reminder/eskalasi/auto-lock berjalan otomatis berbasis waktu (atau via cron terdokumentasi); dokumen `Reviewed` membuka akses Solutions untuk Sales dan memicu `doc_ready`; email trigger benar-benar terkirim via Gmail API (bukan stub).

---

## Fase 3 — Integrasi Due Date dengan Calendar (fitur 8) — ⏸️ DITUNDA (pasca-MVP)

**Status:** **Ditunda keluar dari MVP (keputusan sesi grill, 2026-10-26).** Calendar tetap **read-only** untuk MVP (fitur sync/map event yang sudah ada). Push due date → Calendar tidak diimplementasikan sekarang karena push yang benar ("event di calendar SA yang di-assign") menuntut penyimpanan refresh token OAuth per-user server-side — permukaan keamanan baru yang signifikan dan bertentangan dengan arah Fase 0. Lihat [`docs/adr/0007-defer-calendar-push-to-post-mvp.md`](adr/0007-defer-calendar-push-to-post-mvp.md). Dilacak sebagai spec deferral di issue tracker.

**Tujuan (saat dikerjakan nanti, "opsi b"):** menghubungkan `target_submit` dengan Google Calendar via push satu arah ke calendar SA yang di-assign, dengan token per-user tersimpan server-side.

- [ ] 3.1 **✅ Diputuskan (sesi grill, 2026-10-21):** push **SATU ARAH** — due date proyek (`target_submit`) → event calendar SA yang di-assign. Edit due date meng-update event tertaut; proyek close/lost menghapus event. Bukan sync dua arah. **(Ditunda pasca-MVP per keputusan 2026-10-26.)**
- [ ] 3.2 Perluas `CalendarService` dengan create/update event; simpan refresh token calendar per-user server-side agar server bisa menulis ke calendar SA tanpa SA online. Tambah kolom `gcal_duedate_event_id` di `Project`.
- [ ] 3.3 Saat due date di-edit, update event tertaut; saat proyek close/lost/selesai, **hapus event yang tanggalnya belum terlewati** (event bertanggal masa lalu dibiarkan sebagai jejak), kosongkan `gcal_duedate_event_id` hanya saat event benar-benar dihapus; penghapusan gagal degrade dengan baik (log, jangan gagalkan transisi status).
- [ ] 3.4 Re-assignment memigrasi event antar-calendar (hapus di SA lama, buat di SA baru). Handle kasus tanpa token calendar dengan baik.

**Kriteria selesai (pasca-MVP):** meng-set atau meng-edit due date proyek tercermin di Google Calendar SA yang di-assign; ketiadaan token degrade dengan baik; re-assignment memindahkan event.

---

## Fase 4 — Subtask yang Bisa Di-assign (fitur 6)

**Tujuan:** mengubah "subtask" dari kategori activity-log bebas pilih menjadi work item yang nyata dan bisa di-track. **Ini perubahan model** — effort lebih besar.

- [x] 4.1 Tambah entity `Subtask`: `id`, `id_project`, `title`/`category`, `assigned_sa`, `status` (open → in_progress → done), timestamp. Migration + model + schema.
- [x] 4.2 Endpoint: buat subtask (Lead SA / template), list per proyek, update status, assign/reassign ke SA.
- [x] 4.3 Tautkan `ActivityLog` ke subtask (FK `id_subtask` opsional) agar mencatat aktivitas bisa memajukan/menutup subtask ("respons subtask"). **Mendarat (T2):** activity log pertama terhadap subtask `open` memajukannya ke `in_progress` dengan validasi scope `id_project`; `done` selalu eksplisit (ADR 0008).
- [x] 4.4 **✅ Diputuskan (sesi grill, 2026-10-21):** **YA** — meng-assign proyek otomatis men-seed checklist subtask default (mis. Requirement → BoQ → PropTek → HLD) dari template. Lead SA tetap bisa menambah/menghapus subtask secara manual. **Mendarat (T1):** keempat subtask default langsung ditugaskan ke SA proyek (`assigned_sa`), seeding idempoten pada re-assign.
- [x] 4.5 Frontend: tampilan to-do list subtask yang di-assign ke SA; UX mencatat aktivitas terhadap subtask; manajemen subtask untuk Lead SA. **Mendarat (T3):** section Subtask di `projects/[id]` (`frontend/src/components/SubtaskSection.tsx`) dengan kontrol per-role — SA melihat to-do list miliknya + tombol "Tandai selesai"; Lead_SA/Admin bisa tambah/hapus/assign-ulang; badge status per item + ringkasan "N/M selesai" di header.

**Kriteria selesai:** SA melihat to-do list subtask, mencatat aktivitas terhadap salah satunya, dan subtask berubah status.

---

## Fase 5 — Form Pertanyaan Awal (fitur 3)

**Tujuan:** intake kualifikasi terstruktur saat pembuatan opportunity.

- [ ] 5.1 **Perlu keputusan:** set pertanyaan tetap vs template yang bisa dikonfigurasi admin. Asumsi default: hybrid — kuesioner inti tetap dulu, bisa dikonfigurasi admin nanti.
- [ ] 5.2 Definisikan schema pertanyaan; simpan jawaban sebagai structured data di proyek (JSONB) atau tabel khusus.
- [ ] 5.3 Frontend: render kuesioner sebagai step dalam flow "opportunity baru" Sales (`projects/new`).
- [ ] 5.4 (Opsional AI) kirim jawaban + dokumen upload ke Gemini untuk men-generate pertanyaan klarifikasi area BANT yang lemah, ditampilkan ke Sales (terhubung dengan status "Need Clarification" yang sudah ada).
- [ ] 5.5 **Generate dokumen Requirement (summary turunan AI).** Dokumen `Requirement` BUKAN file yang di-upload user, melainkan **konten turunan**: ringkasan terstruktur kebutuhan customer yang di-generate Gemini dari **source of truth = dokumen MoM/RFP yang di-upload + penjelasan Sales di field form** (kuesioner 5.x + estimasi/kebutuhan yang diisi saat buat opportunity). Hasilnya **disimpan sebagai `Document` dengan `doc_type="Requirement"`** (reuse tabel dokumen; `gdrive_link` boleh null / konten disimpan sebagai teks ter-generate), sehingga muncul di daftar dokumen proyek dan menjadi baseline perbandingan Fase 6. **Keputusan diambil (2026-10-19, product owner):** derived content, bukan upload; di-generate dari MoM/RFP + field Sales; **di-resummarize** saat source berubah (bukan snapshot sekali jadi); hidup di tabel `Document`. **✅ Diputuskan (sesi grill, 2026-10-21):** SA **BOLEH** meng-edit/override hasil generate, ditandai flag `is_overridden`. Saat source berubah dan konten sudah di-override, re-summarize **tidak** menimpa diam-diam — sistem memberi notifikasi dan minta konfirmasi dulu. Lihat [`docs/adr/0004-requirement-override-blocks-silent-resummarize.md`](adr/0004-requirement-override-blocks-silent-resummarize.md).

**Kriteria selesai:** Sales menjawab kuesioner terstruktur saat membuat opportunity; jawaban tersimpan dan terlihat di proyek; sistem men-generate dokumen `Requirement` turunan dari MoM/RFP + field Sales dan menyimpannya sebagai `Document` proyek, yang di-resummarize saat source berubah.

---

## Fase 6 — BoQ Compare vs Requirement (fitur 10)

**Tujuan:** analisis gap bertenaga AI antara dokumen Requirement dan dokumen BoQ. **Fitur baru dengan kompleksitas tertinggi** — bergantung pada Fase 1.2 (tipe dokumen `Requirement` di enum), **Fase 5.5 (konten Requirement turunan AI di-generate dari MoM/RFP + field Sales)**, dan guardrails dari Fase 7. Catatan model: dokumen Requirement adalah summary turunan (lihat 5.5), bukan upload customer — jadi perbandingan selalu punya baseline terstruktur untuk dibandingkan, meski customer tidak memberi file requirement formal.

- [ ] 6.1 Service: diberi dokumen `Requirement` (summary turunan dari Fase 5.5) dan dokumen BoQ sebuah proyek, kirim keduanya ke Gemini via path multimodal `parse_document` / `structure_text` yang sudah ada.
- [ ] 6.2 Definisikan schema output terstruktur: `covered[]`, `missing[]`, `extra[]`, dan `coverage_percentage`.
- [ ] 6.3 Endpoint `GET/POST /projects/{id}/boq-compare`; persist hasil comparison terbaru untuk proyek.
- [ ] 6.4 Frontend: tampilan comparison yang menunjukkan item covered/missing/extra dan skor coverage, dengan tombol run ulang.
- [ ] 6.5 Handle edge case: Requirement belum di-generate (belum ada MoM/RFP/field Sales), BoQ tidak ada, atau LLM gagal (pakai ulang pola retry scoring engine).

**Kriteria selesai:** memilih Requirement + BoQ untuk sebuah proyek mengembalikan analisis gap terstruktur dengan skor coverage, dirender di UI.

---

## Fase 7 — Guardrails LLM (fitur 11, sisanya)

**Tujuan:** lapisan keamanan di sekitar semua pemanggilan Gemini. (Hardening auth sudah dikerjakan di Fase 0.) Sebaiknya mendarat sebelum/bersama Fase 6 karena fitur itu mengirim dokumen utuh ke LLM.

- [x] 7.1 Input safety: batas ukuran/konten dan mitigasi prompt-injection sebelum pemanggilan di `scoring_engine.py` / `activity_logger.py` / `activity_logs.py` (size/byte clamp + delimiter-wrap + neutralize).
- [x] 7.2 Output validation: paksa schema JSON yang diharapkan pada response terstruktur; tolak/retry pada output malformed atau di luar kontrak (`validate_llm_json` + Pydantic contracts).
- [x] 7.3 **Keputusan diambil:** handling PII memakai flag-and-log untuk MVP (regex Indonesia-centric, tanpa redaction, tanpa nilai mentah di log); redaction ditunda.
- [x] 7.4 Sentralisasi guardrails dalam satu module `backend/app/utils/guardrails.py` yang dilewati setiap Call_Site LLM.

**Kriteria selesai:** tidak ada konten user yang sampai ke Gemini tanpa melewati guardrail input; semua output terstruktur tervalidasi schema.

---

## Usulan Urutan Pengerjaan (urutan dependensi)

```
Fase 0 (keamanan + bug fix)      ← kerjakan dulu; membuka deployment yang aman
      │
Fase 1 (partial mudah)           ← quick win, termasuk tipe dokumen Requirement
      │
Fase 2 (folder provisioning)     ← men-wire kode yang sudah ada
      │
Fase 2A (SLA DQ gating e2e)      ← wire SLA/doc_ready/email; butuh Fase 2 (gdrive_folder_id untuk auto-lock)
      │
Fase 3 (due date calendar)   ──┐  ← ⏸️ DITUNDA pasca-MVP (ADR 0007)
Fase 4 (subtask assignable)  ──┤  ← independen, bisa diparalelkan
Fase 5 (form pertanyaan awal)──┘
      │
Fase 7 (guardrails LLM)          ← sebelum Fase 6 (penggunaan LLM yang berat dokumen)
      │
Fase 6 (BoQ vs Requirement)      ← terakhir; butuh tipe Requirement (1.2) + konten Requirement turunan (5.5) + guardrails (7)
```

> Catatan dependensi: dokumen Requirement adalah **konten turunan AI** (di-generate di Fase 5.5 dari MoM/RFP + field Sales), bukan upload customer. Karena itu Fase 6 kini bergantung pada Fase 5, bukan hanya pada penambahan tipe enum di Fase 1.2.

---

## Rekomendasi Lintas-Fitur (tidak memblokir MVP, tapi layak dilacak)

- [ ] Tambah CI (lint + test backend) — belum ada hari ini.
- [ ] Tambah test frontend — belum ada hari ini.
- [ ] Perluas coverage test backend ke auth, state machine dokumen, handover, notifikasi (saat ini condong ke AI/provisioning/SLA/scoring).
- [ ] **Email/Gmail sebagai trigger (spec §4.C)** — dilacak sebagai gap requirement nyata di Fase 2A.5 (lihat bawah), bukan sekadar catatan lintas-fitur. Butir ini tetap sebagai pengingat untuk menyinkronkan README setelah implementasi.
- [ ] **Follow-up README (TIDAK dikerjakan di PR rekonsiliasi ini):** README mengklaim email Gmail berfungsi ("in-app notification + email (Gmail API) untuk semua event penting"), padahal `send_email` masih stub. Koreksi README ditunda sebagai follow-up terpisah; jangan diam-diam membiarkan klaim menyesatkan ini.
- [ ] Selaraskan gap README-vs-realita (email Gmail, httpOnly cookie, penamaan `SECRET_KEY`, status DB `/health`).
- [ ] Pecah router besar (`projects.py` ~702 line, `assignment.py` ~681 line).
- [ ] Ekstrak helper generator ID yang terduplikasi ke package `utils/` yang kosong.

---

## Keputusan yang Dibutuhkan dari Product Owner

Beberapa item di bawah sudah **diputuskan pada sesi grill 2026-10-21** (ditandai ✅); sisanya masih asumsi default yang menggerakkan roadmap — konfirmasi atau koreksi.

1. **Form pertanyaan awal (Fase 5):** set tetap vs bisa dikonfigurasi admin? _(diasumsikan: hybrid, tetap dulu)_
2. **Subtask (Fase 4):** subtask yang benar-benar bisa ditugaskan vs tetap model kategori? _(diasumsikan: subtask nyata)_
3. **Seeding subtask (4.4):** auto-seed checklist default saat assignment? **✅ Diputuskan (sesi grill, 2026-10-21):** YA — auto-seed checklist subtask default saat assignment (mis. Requirement → BoQ → PropTek → HLD); Lead SA tetap bisa tambah/hapus manual.
4. **BoQ compare (Fase 6):** analisis gap AI dengan skor coverage vs side-by-side biasa? _(diasumsikan: AI + skor)_
5. **Step qualify (2.3):** threshold BANT ≥ 60% sebagai gate **sudah ditetapkan spec Flow 1 langkah 3 (fakta spec, bukan asumsi)** dan sudah terimplementasi. **✅ Diputuskan (sesi grill, 2026-10-21):** TIDAK ada step "qualify" manual Lead SA terpisah di atas gate otomatis — gate BANT ≥ 60% otomatis sudah memenuhi spec.
6. **Calendar (3.1):** push due date satu arah vs sync dua arah? **✅ Diputuskan (sesi grill, 2026-10-21):** push SATU ARAH — due date proyek → event calendar SA yang di-assign; edit due date meng-update event; proyek close/lost menghapus event. **✅ Diputuskan (sesi grill, 2026-10-26):** push **DITUNDA keluar dari MVP** — MVP tetap calendar read-only; push butuh token OAuth per-user tersimpan server-side (permukaan keamanan baru). Lihat [`docs/adr/0007-defer-calendar-push-to-post-mvp.md`](adr/0007-defer-calendar-push-to-post-mvp.md).
7. **PII (7.3):** flag vs redact? _(diasumsikan: flag untuk MVP)_
8. **Dokumen Requirement (Fase 5.5 / 6):** upload file vs konten turunan AI? **✅ Diputuskan 2026-10-19:** konten turunan — summary AI dari MoM/RFP + field Sales, disimpan sebagai `Document` (`doc_type="Requirement"`), di-resummarize saat source berubah. **✅ Diputuskan (sesi grill, 2026-10-21):** SA BOLEH override hasil generate, ditandai flag `is_overridden`; saat source berubah dan konten sudah di-override, re-summarize TIDAK menimpa diam-diam — beri notifikasi & minta konfirmasi dulu. (Bagian "terbuka" pada keputusan ini kini tertutup.) Lihat [`docs/adr/0004-requirement-override-blocks-silent-resummarize.md`](adr/0004-requirement-override-blocks-silent-resummarize.md).

**Keputusan scheduler SLA (Fase 2A.2 / B12):** **✅ Diputuskan (sesi grill, 2026-10-21):** background scheduler internal ringan saat startup backend untuk MVP single-instance (bukan cron eksternal); tidak aman untuk multi-instance — pindah ke cron eksternal / leader-election saat scale-out. Lihat [`docs/adr/0003-sla-internal-scheduler-for-mvp.md`](adr/0003-sla-internal-scheduler-for-mvp.md).

---

## Divergensi Spec vs Kode yang Perlu Diputuskan

Ditemukan saat rekonsiliasi 2026-10-20. Per aturan ground truth (`spec = intent`, `code = reality`, `roadmap = jarak`), divergensi ini **harus diputuskan secara eksplisit** — bukan dibiarkan diam-diam mengikuti salah satu. **Keempat divergensi (D1–D4) telah diputuskan pada sesi grill 2026-10-21; spec sudah dikoreksi sesuai keputusan.**

- [x] **D1. Enum `Projects.status` kode ≠ spec.** Spec awal = `New, Assigned, Pending DQ, Ready, Closed-Win, Lost`. Kode (`backend/app/models/project.py`, CheckConstraint `chk_projects_status` ~line 141–143) = `New, Pending Assignment, Assigned, Ready, Closed-Win, Handover Complete, Lost, Need Clarification, Scoring Pending, Manual Review Required`. **✅ Diputuskan (sesi grill, 2026-10-21):** enum **kode** menjadi ground truth baru untuk status operasional, **dan** `Pending DQ` **dipertahankan** (dikembalikan) karena milik Flow 2 (SLA DQ gating). Spec dikoreksi agar memuat set kode + `Pending DQ`. Lihat [`docs/adr/0001-status-enum-code-is-ground-truth-keep-pending-dq.md`](adr/0001-status-enum-code-is-ground-truth-keep-pending-dq.md).
- [x] **D2. Taksonomi `ActivityLogs.subtask_category` kode ≠ contoh spec.** Spec mencontohkan subtask seperti `"Create HLD"`, `"Peer Review"`, `"Meeting Pre-Implementation"`. Kode memakai enum berbeda total (`Assessment, Internal Meeting, Customer Meeting, Principal Meeting, Commercial Document, Technical Document, Document Review, Training, Self-Lab, Self-Learning, Exam, Internal Presentation, External Presentation`). **✅ Diputuskan (sesi grill, 2026-10-21):** dua konsep dipisahkan — `Subtask` = work item yang bisa ditugaskan (status `open → in_progress → done`, contoh "Create HLD", "Peer Review"); `ActivityCategory` = taksonomi pengelompokan `ActivityLog` (enum kode di atas = ground truth). Spec dikoreksi untuk membedakan keduanya eksplisit. Lihat [`GLOSSARY.md`](../GLOSSARY.md). Kaitkan dengan Fase 4 (subtask yang bisa di-assign).
- [x] **D3. Pre-filled OLA/Mandays (Flow 1 langkah 2) — belum diimplementasi, belum dilacak.** Spec menyebut AI juga menyusun pre-filled OLA/Mandays internal untuk SA dari hasil parsing. **✅ Diputuskan (sesi grill, 2026-10-21):** **ditunda keluar dari MVP** (backlog pasca-MVP). Deskripsi fitur tetap ada di spec sebagai *intent*, dengan catatan bahwa implementasinya di luar scope MVP; tidak ada item roadmap MVP untuk ini.
- [x] **D4. Akses Backup SA ke Project Story (Flow 3 langkah 4) — belum dipetakan eksplisit.** Spec: Project Story harus dapat diakses Backup SA untuk handover saat SA cuti. **✅ Diputuskan (sesi grill, 2026-10-21):** dipenuhi oleh fitur **Project Collaboration** — "Backup SA" = collaborator dengan akses baca Project Story, **bukan** entity/peran baru. Spec dikoreksi untuk menyatakan pemetaan ini eksplisit. Lihat [`docs/adr/0002-backup-sa-via-project-collaboration.md`](adr/0002-backup-sa-via-project-collaboration.md).
