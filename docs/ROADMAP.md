# Portal SA — Roadmap Fitur MVP

Dokumen pelacakan untuk fitur yang dibutuhkan agar mencapai MVP yang layak. Status dinilai berdasarkan kode aktual (bukan klaim spec) pada **2026-10-12**. Coverage roadmap direkonsiliasi terhadap ground truth produk (`SA Application/Spesifikasi_Teknis_Portal_SA.md`) pada **2026-10-20**; audit rekonsiliasi: `.agents/tasks/roadmap-spec-reconcile-2026-10-20/findings.md`.

> **Asumsi yang dipakai menyusun roadmap ini** (dipilih sebagai default; ubah fase terkait jika ada yang keliru):
> - **Form pertanyaan awal** = hybrid: kuesioner kualifikasi statis yang diisi Sales saat membuat opportunity, dengan opsi pertanyaan klarifikasi yang di-generate AI untuk area BANT yang lemah.
> - **Subtask** = subtask yang benar-benar bisa ditugaskan: Lead SA (atau template proyek) dan SA yang ditugaskan di proyek membuat subtask per proyek; SA melihatnya sebagai to-do list dengan status (open → in progress → done) dan mencatat aktivitas terhadap subtask tertentu.
> - **BoQ compare vs Requirement** = analisis gap AI **+ skor coverage**: pilih dokumen Requirement dan dokumen BoQ, Gemini mengembalikan item yang covered / missing / extra beserta persentase coverage.
> - **Guardrails** = hardening auth/keamanan dulu (default yang tidak aman untuk produksi), baru keamanan input/output LLM.
> - **Urutan pengerjaan** = keamanan dulu, lalu menutup fitur yang partial, baru fitur baru.

> **Arah produk dikoreksi (2026-11-13, sesi grill).** Portal SA adalah **ticketing / project tracker khusus SA**, bukan hanya funnel pre-sales. Keputusan: role `Product` dan flag `is_admin`, orang per project yang bisa diganti, multi-SA, model status dua field, dan inti tracker (subtask kaya, komentar, workload). Dilacak di **Fase 8A–8C dan Fase 9** (di bawah); ADR [0012](adr/0012-role-fungsional-tunggal-dan-flag-admin.md)–[0015](adr/0015-matriks-akses-drive-dan-gate-dq.md). **Fase 6 (BoQ compare) dikerjakan setelah Fase 9.** Nama status di bagian lama dokumen ini (`Closed-Win`, `Handover Complete`, `Ready`, `Pending Assignment`, dst.) adalah nama lama; peta ke nama baru ada di ADR 0013.

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
| 3 | Form pertanyaan awal | 🔴 Belum ada | Dipecah jadi Kuesioner kualifikasi (Fase 5A, spec #24) dan generate Requirement (Fase 5B, spec #25); belum ada kode |
| 4 | BANT scoring | ✅ Selesai | AI + manual keduanya berfungsi |
| 5 | Kualifikasi & assignment oleh Lead SA | ✅ Selesai | Folder provisioner di-wire end-to-end (#45): assign men-schedule provisioning, persist `gdrive_folder_id` + `gdrive_solutions_folder_id` + status pending/provisioned/failed, badge dashboard + endpoint re-provision. Tidak ada step qualify terpisah — gate BANT ≥ 60% otomatis sudah memenuhi spec (Fase 2.3) |
| 6 | Staff mengikuti subtask / respons subtask via activity log | ✅ Selesai | Entity `Subtask` assignable end-to-end: seeding auto-assign ke SA proyek (T1), activity log memajukan `open → in_progress` dengan validasi scope (T2, ADR 0008), dan section Subtask di `projects/[id]` dengan kontrol per-role + badge status + ringkasan "N/M selesai" (T3). `done` selalu eksplisit via tombol "Tandai selesai" |
| 7 | Input dokumen (Requirement, BoQ, Mandays, PropTek, HLD) | 🟡 Partial | Tipe "Requirement" belum ada (hanya RFP/PropTek/BOQ/Mandays/MoM/HLD) |
| 8 | Due date + integrasi calendar | 🟡 Partial | `target_submit` ada; calendar read-only, tidak ada push due date |
| 9 | Edit due date / ikon pensil edit | 🟡 Partial | Alur edit berfungsi; masih tombol teks, bukan ikon pensil |
| 10 | BoQ compare vs Requirement | 🔴 Belum ada | Tidak ada fitur perbandingan; dokumen Requirement (summary turunan AI) belum di-generate — tipe `Requirement` sudah ada di enum (Fase 1.2), tapi kontennya belum disintesis |
| 11 | Guardrails | ✅ Selesai | Guardrail LLM terpusat (size clamp, PII flag-and-log, mitigasi prompt-injection, validasi output) di tiga Call_Site; hardening default auth dilacak di fitur 1 / Fase 0 |
| 12 | SLA DQ Number & gating (Flow 2) | 🟡 Partial | **Baru ditambahkan 2026-10-20** (rekonsiliasi spec). Kode SLA ada (`backend/app/services/sla_timer.py`, `backend/app/api/sla.py`) dan read-gating DQ ada (`backend/app/api/dq_number.py`), **tapi tidak di-wire end-to-end**: SLA timer tidak pernah di-start (B11), tidak ada scheduler (B12), sehingga auto-lock folder Solutions / reminder H+3 / eskalasi H+5 mati end-to-end. Dilacak di Fase 2A. |
| 13 | Role Product, flag `is_admin`, orang per project, multi-SA | 🔴 Belum ada | Fase 8A, 8B. Spec §2.0, §2.5; ADR 0012, 0014 |
| 14 | Model status dua field | 🔴 Belum ada | Fase 8C. Spec §2.0; ADR 0013 |
| 15 | Inti tracker: subtask kaya, komentar, "tugas saya", workload, dashboard requester | 🔴 Belum ada | Fase 9. Spec §2.5 |

> **Catatan penomoran:** fitur 1–11 dipertahankan apa adanya. Fitur **12 (SLA DQ Number & gating)** ditambahkan pada 2026-10-20 setelah audit rekonsiliasi menemukan Flow 2 (salah satu dari 4 flow inti spec) tidak punya "rumah" di daftar fitur, sehingga bug wiring SLA tidak punya tempat tercatat.

---

## Bug

Daftar bug lintas-fitur (B1–B14+): [`roadmap/bug.md`](roadmap/bug.md). Buka bila tiket menyebut nomor `B<n>`.

---

## Berkas per Fase

Rincian tiap fase (checkbox, kriteria selesai) ada di berkas sendiri. Buka hanya berkas fase yang dikerjakan.

| Fase |
|------|
| [Fase 0 — Hardening Keamanan & Correctness (bagian dari Guardrails, fitur 11)](roadmap/fase-0.md) |
| [Fase 1 — Menutup Partial yang Mudah (quick wins)](roadmap/fase-1.md) |
| [Fase 2 — Folder Provisioning & Assignment (fitur 5)](roadmap/fase-2.md) |
| [Fase 2A — SLA DQ Number & Gating end-to-end (fitur 12)](roadmap/fase-2a.md) |
| [Fase 3 — Integrasi Due Date dengan Calendar (fitur 8) — ⏸️ DITUNDA (pasca-MVP)](roadmap/fase-3.md) |
| [Fase 4 — Subtask yang Bisa Di-assign (fitur 6)](roadmap/fase-4.md) |
| [Fase 5 — Form Pertanyaan Awal (fitur 3)](roadmap/fase-5.md) |
| [Fase 6 — BoQ Compare vs Requirement (fitur 10) — ⏸ dikerjakan setelah Fase 9 (keputusan 2026-11-13)](roadmap/fase-6.md) |
| [Fase 7 — Guardrails LLM (fitur 11, sisanya)](roadmap/fase-7.md) |
| [Fase 8A — Role dan Akses (fitur 13)](roadmap/fase-8a.md) |
| [Fase 8B — Orang per Project dan Multi-SA (fitur 13)](roadmap/fase-8b.md) |
| [Fase 8C — Model Status (fitur 14)](roadmap/fase-8c.md) |
| [Fase 9 — Inti Tracker dan Workload (fitur 15)](roadmap/fase-9.md) |

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
Fase 5A (kuesioner) → 5B (Requirement) ──┘  ← 5B butuh Source document dari 5A
      │
Fase 7 (guardrails LLM)          ← sebelum Fase 6 (penggunaan LLM yang berat dokumen)
      │
#27 verifikasi Drive nyata      ← sebelum 8B (perubahan permission)
      │
Fase 8A (role) → 8B (orang & multi-SA) → 8C (status)   ← berurutan; menyentuh `_ATURAN` dan `workflow.py`
      │
Fase 9 (inti tracker & workload)
      │
Fase 6 (BoQ vs Requirement)      ← ditunda ke akhir; butuh tipe Requirement (1.2) + konten Requirement turunan (5B / 5.5) + guardrails (7)
```

> Catatan dependensi: dokumen Requirement adalah **konten turunan AI** (di-generate di Fase 5.5 dari MoM/RFP + field Sales), bukan upload customer. Karena itu Fase 6 kini bergantung pada Fase 5, bukan hanya pada penambahan tipe enum di Fase 1.2.

---

## Rekomendasi Lintas-Fitur (tidak memblokir MVP, tapi layak dilacak)

- [ ] **Verifikasi Google Drive nyata — prioritas naik, dikerjakan sebelum Fase 8B (keputusan 2026-11-13; kriteria permission mengikuti ADR 0015)** ([#27](https://github.com/NikkiSatmaka/sa-apps/issues/27)): `GDRIVE_SERVICE_ACCOUNT_KEY` belum dikonfigurasi/didokumentasikan; seluruh pekerjaan Drive Fase 2/2A baru terbukti lewat mock. Gerbang untuk persistensi MoM/RFP ke Drive.
- [x] Tambah CI (test backend + frontend, gerbang cakupan 90/80) — selesai (spec #49/#50; PR #84, #85). Lint belum ada: `next lint` rusak di Next 16 dan backend punya banyak temuan `ruff` lama; dilacak terpisah. Job CI dijadikan *required check* lewat ruleset `Core` pada `main`.
- [x] Tambah test frontend — selesai (Vitest + RTL + MSW, 1029 test, cakupan 99,6% baris / 95,4% cabang). Playwright E2E belum: tahap terpisah dengan penyedia LLM palsu di backend.
- [x] Perluas coverage test backend — selesai (2484 test unit + integrasi di Postgres 18, cakupan gabungan 99,9% baris / 99,1% cabang). Temuan dari pengerjaan ini dilacak sebagai issue #72–#83.
- [ ] **Email/Gmail sebagai trigger (spec §4.C)** — dilacak sebagai gap requirement nyata di Fase 2A.5 (lihat bawah), bukan sekadar catatan lintas-fitur. Butir ini tetap sebagai pengingat untuk menyinkronkan README setelah implementasi.
- [ ] **Follow-up README (TIDAK dikerjakan di PR rekonsiliasi ini):** README mengklaim email Gmail berfungsi ("in-app notification + email (Gmail API) untuk semua event penting"), padahal `send_email` masih stub. Koreksi README ditunda sebagai follow-up terpisah; jangan diam-diam membiarkan klaim menyesatkan ini.
- [ ] Selaraskan gap README-vs-realita (email Gmail, httpOnly cookie, penamaan `SECRET_KEY`, status DB `/health`).
- [ ] **Halaman pengaturan admin (konfigurasi runtime lewat UI) — DIHAPUS, diimplementasi ulang SETELAH rangkaian refinement ini selesai** ([#81](https://github.com/NikkiSatmaka/sa-apps/issues/81)). Halaman lama menyimpan kredensial asli (API key, service account) di `localStorage` browser dan tidak pernah dipakai backend; tombol "Test Koneksi" hanya simulasi. Prasyarat implementasi ulang: (1) kebijakan akses proyek/peran selesai (issue #73–#75), (2) endpoint backend khusus Admin dengan penyimpanan secret terenkripsi di server dan tanpa mengembalikan nilai secret ke klien, (3) keputusan apakah konfigurasi runtime memang perlu lewat UI atau cukup tetap di env var/Portainer. Sampai itu, konfigurasi dilakukan lewat `.env`/Portainer.
- [ ] Pecah router besar (`projects.py` ~702 line, `assignment.py` ~681 line).
- [ ] Ekstrak helper generator ID yang terduplikasi ke package `utils/` yang kosong.

---

## Keputusan yang Dibutuhkan dari Product Owner

Beberapa item di bawah sudah **diputuskan pada sesi grill 2026-10-21** (ditandai ✅); sisanya masih asumsi default yang menggerakkan roadmap — konfirmasi atau koreksi.

1. **Form pertanyaan awal (Fase 5):** set tetap vs bisa dikonfigurasi admin? **✅ Diputuskan (sesi grill, 2026-11-10):** set tetap di kode untuk MVP dengan `schema_version`; konfigurasi admin jadi backlog pasca-MVP.
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

- [x] **D1. Enum `Projects.status` kode ≠ spec.** Spec awal = `New, Assigned, Pending DQ, Ready, Closed-Win, Lost`. Kode (`backend/app/models/project.py`, CheckConstraint `chk_projects_status` ~line 141–143) = `New, Pending Assignment, Assigned, Ready, Closed-Win, Handover Complete, Lost, Need Clarification, Scoring Pending, Manual Review Required`. **✅ Diputuskan (sesi grill, 2026-10-21):** enum **kode** menjadi ground truth baru untuk status operasional, **dan** `Pending DQ` **dipertahankan** (dikembalikan) karena milik Flow 2 (SLA DQ gating). Spec dikoreksi agar memuat set kode + `Pending DQ`. Lihat [`docs/adr/0001-status-enum-code-is-ground-truth.md`](adr/0001-status-enum-code-is-ground-truth.md). **Diperbarui 2026-11-10 (issue #79):** `Pending DQ` justru **dihapus** dari spec dan ADR; DQ kosong cukup ditandai `dq_number` null, bukan status.
- [x] **D2. Taksonomi `ActivityLogs.subtask_category` kode ≠ contoh spec.** Spec mencontohkan subtask seperti `"Create HLD"`, `"Peer Review"`, `"Meeting Pre-Implementation"`. Kode memakai enum berbeda total (`Assessment, Internal Meeting, Customer Meeting, Principal Meeting, Commercial Document, Technical Document, Document Review, Training, Self-Lab, Self-Learning, Exam, Internal Presentation, External Presentation`). **✅ Diputuskan (sesi grill, 2026-10-21):** dua konsep dipisahkan — `Subtask` = work item yang bisa ditugaskan (status `open → in_progress → done`, contoh "Create HLD", "Peer Review"); `ActivityCategory` = taksonomi pengelompokan `ActivityLog` (enum kode di atas = ground truth). Spec dikoreksi untuk membedakan keduanya eksplisit. Lihat [`GLOSSARY.md`](../GLOSSARY.md). Kaitkan dengan Fase 4 (subtask yang bisa di-assign).
- [x] **D3. Pre-filled OLA/Mandays (Flow 1 langkah 2) — belum diimplementasi, belum dilacak.** Spec menyebut AI juga menyusun pre-filled OLA/Mandays internal untuk SA dari hasil parsing. **✅ Diputuskan (sesi grill, 2026-10-21):** **ditunda keluar dari MVP** (backlog pasca-MVP). Deskripsi fitur tetap ada di spec sebagai *intent*, dengan catatan bahwa implementasinya di luar scope MVP; tidak ada item roadmap MVP untuk ini.
- [x] **D4. Akses Backup SA ke Project Story (Flow 3 langkah 4) — belum dipetakan eksplisit.** Spec: Project Story harus dapat diakses Backup SA untuk handover saat SA cuti. **✅ Diputuskan (sesi grill, 2026-10-21):** dipenuhi oleh fitur **Project Collaboration** — "Backup SA" = collaborator dengan akses baca Project Story, **bukan** entity/peran baru. Spec dikoreksi untuk menyatakan pemetaan ini eksplisit. Lihat [`docs/adr/0002-backup-sa-via-project-collaboration.md`](adr/0002-backup-sa-via-project-collaboration.md).
- [x] **D6. Role dan orang per project.** Spec lama hanya punya `Sales`, `SA`, `Lead_SA`, `Admin`, satu `sales_pic` wajib, dan satu `assigned_sa`. **✅ Diputuskan (2026-11-13):** role `Product`, flag `is_admin`, `product_pic` wajib/`sales_pic` opsional/`lead_sa`/`created_by`, multi-SA. Spec dikoreksi (§2.0, §2.5, §3). Lihat ADR [0012](adr/0012-role-fungsional-tunggal-dan-flag-admin.md) dan [0014](adr/0014-orang-per-project-dan-multi-sa.md). Dikerjakan di Fase 8A–8B.
- [x] **D7. Model status.** **✅ Diputuskan (2026-11-13):** dua field (`status` + `qualification_state`) dengan nama baru; menggantikan D1/ADR 0001. Lihat [ADR 0013](adr/0013-model-status-dua-field.md). Dikerjakan di Fase 8C.
- [x] **D8. Akses Drive Sales dan Product.** **✅ Diputuskan (2026-11-13):** gate DQ tetap; Sales dan Product Viewer `Inventory` dan Viewer `Solutions` setelah DQ terisi; PMO/Delivery satu-satunya pengecualian. Lihat [ADR 0015](adr/0015-matriks-akses-drive-dan-gate-dq.md).
- [x] **D5. Hak baca proyek.** Spec #87 membatasi baca ke pihak terkait. **✅ Diputuskan 2026-11-10:** semua proyek dapat dibaca semua pengguna terautentikasi; hanya akses tulis yang dibatasi. Lihat [`docs/adr/0011-baca-proyek-terbuka-tulis-dibatasi.md`](adr/0011-baca-proyek-terbuka-tulis-dibatasi.md).
