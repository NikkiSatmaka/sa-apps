# API Reference — Backend Portal SA

Referensi lengkap API backend Portal SA. Disusun dari router di `backend/app/api/` dan diverifikasi terhadap kode aktual.

## Informasi Umum

- **Base URL / versioning:** semua router didaftarkan dengan prefix `/api/v1` di `main.py` (`app.include_router(..., prefix="/api/v1")`). Jadi path efektif adalah `/api/v1/<path>`. Pengecualian: `GET /health` (didefinisikan langsung di `main.py` tanpa prefix). Catatan: `app/api/health.py` mendefinisikan router `/health` yang **tidak** didaftarkan — endpoint health yang aktif adalah yang di `main.py` dan masih meng-hardcode `"database": "healthy"` (bug B3).
- **Auth scheme:** JWT Bearer. Kirim header `Authorization: Bearer <access_token>`. Token diterbitkan oleh `auth_service` (algoritma `HS256`, access TTL 24 jam, refresh TTL 7 hari). Dependency `get_current_user` memvalidasi token dan memuat user. Payload JWT berisi `sub` (user id), `email`, `role`, `type`.
- **Format response standar:** semua response memakai `{"status": "success|error", "data": ..., "message": "..."}` (`schemas/response.py`). Exception handler (`core/exceptions.py`) menyeragamkan error (401/403/404/422/500) ke format yang sama. Validasi 422 menyertakan `data` berupa array `{field, reason}`.
- **Rate limiting:** `RateLimiterMiddleware` membatasi 100 request/menit per user (fallback ke IP jika belum auth), sliding window in-memory. Path `/health`, `/docs`, `/redoc`, `/openapi.json` dikecualikan. Over-limit → `429` dengan header `Retry-After`.
- **CORS:** default `*` (perlu dikunci untuk produksi — roadmap 0.4).
- **OpenAPI:** `GET /docs` (Swagger UI), `GET /redoc` (ReDoc), `GET /openapi.json` aktif secara default (lihat `main.py`).

> Peringatan auth per-endpoint: beberapa endpoint **tidak** memasang dependency `get_current_user` sehingga dapat diakses tanpa autentikasi. Ditandai eksplisit di bawah.

---

## Health

### `GET /health`
- **Auth:** tidak perlu.
- **Purpose:** health check untuk Docker/monitoring. Mengembalikan status API dan database. **Bug B3:** nilai `database` di-hardcode `"healthy"` di `main.py` (tidak memanggil `check_database_health()`).
- **Response:** `data: {api, database}`.

---

## Authentication (`/api/v1/auth`, tag `Authentication`)

| Method & Path | Auth | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /auth/config` | tidak perlu | — | `{demo_mode, oauth_configured}` | Status konfigurasi auth untuk menentukan tombol login di frontend. |
| `POST /auth/demo-login` | tidak perlu (gated `DEMO_MODE`) | `{role}` (`Sales`/`SA`/`Lead_SA`/`Admin`) | `LoginResponse` (user + token pair) | Login bypass OAuth untuk demo. Membuat demo user bila belum ada. 403 jika `DEMO_MODE=false`. **Default `DEMO_MODE=true` tidak aman untuk produksi (roadmap 0.1).** |
| `GET /auth/login` | tidak perlu | query `redirect_url` | redirect 3xx ke Google | Mulai OAuth flow. |
| `GET /auth/callback` | tidak perlu | query `code`/`error`/`state` | `LoginResponse` atau redirect | Callback OAuth. Mendukung calendar-auth flow (`state` diawali `calendar_auth|`, token di URL hash). |
| `POST /auth/refresh` | refresh token di body | `{refresh_token}` | `TokenPair` | Terbitkan token pair baru. |
| `POST /auth/logout` | Bearer (header manual) | — | `{message}` | Revoke session (best-effort; blacklist belum ada). |
| `GET /auth/me` | Bearer (header manual) | — | `UserResponse` | Ambil user dari access token. |

> Catatan: `auth` memakai parsing header manual (`_get_token_from_header`) / `auth_service`, bukan dependency `get_current_user`.

---

## Projects (`/api/v1/projects`, tag `Projects`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `POST /projects` | `get_current_user` (Sales/SA/Lead_SA) | multipart form: `project_name`, `customer_name`, `target_submit`, `estimasi_nilai`, `dq_number?`, `files[]` (PDF/DOCX, max 20MB, max 5) | `ProjectResponse` + hasil upload per file | Buat opportunity baru (status `New`), trigger scoring async. **`estimasi_nilai` divalidasi tapi tidak dipersist (B4).** |
| `GET /projects` | `get_current_user` (scoped by role) | query `sales_pic`, `assigned_to`, `status`, `sort` | array ringkasan proyek | Daftar proyek. Lead_SA/Admin lihat semua; Sales/SA lihat proyek terkait + collaborator (scoping server-side). |
| `GET /projects/status-summary` | `get_current_user` (scoped) | query `sales_pic`, `assigned_to` | `[{status, count}]` | Ringkasan jumlah proyek per status. |
| `GET /projects/{project_id}` | `get_current_user` + cek akses (privileged/sales_pic/assigned_sa/collaborator) | — | detail proyek + PIC + collaborators | Detail satu proyek. 403 jika tidak punya akses. |
| `PATCH /projects/{project_id}` | `get_current_user` | body dict (`project_name`, `customer_name`, `dq_number`, `target_submit`, `bant_detail`) | `{id_project, status}` | Update field proyek. **Catatan risiko: tidak ada pengecekan role/akses eksplisit di handler ini.** |
| `DELETE /projects/{project_id}` | `get_current_user` (Lead_SA/Admin) | — | `{id_project}` | Hapus proyek. |

---

## Scoring (`/api/v1/projects`, tag `Scoring`)

> **Peringatan auth:** ketiga endpoint di `scoring.py` **tidak memasang** `get_current_user` — dapat diakses tanpa token.

| Method & Path | Auth | Request | Response | Purpose |
|---|---|---|---|---|
| `POST /projects/{project_id}/score-manual` | tidak ada (seharusnya ada) | `ManualBANTInput` (budget/authority/need/timeline 0-25 + detail opsional) | `BANTResult` | BANT scoring manual. Threshold ≥ 60 → `Pending Assignment`, < 60 → `Need Clarification`. |
| `GET /projects/{project_id}/bant-result` | tidak ada | — | skor + sub-skor + tags + status + feedback | Ambil hasil BANT proyek. |
| `GET /projects/{project_id}/recommendations` | tidak ada | — | daftar proyek Closed-Win serupa (max 5) | RAG recommendation berdasarkan `use_case_tags`. |

---

## Assignment & Utilization (`/api/v1`, tag `Assignment`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /projects/pending-assignment` | Lead_SA/Admin | — | daftar proyek `Pending Assignment` | Proyek siap di-assign. |
| `GET /sa/available` | Lead_SA/Admin | — | daftar SA + jumlah proyek aktif | Ketersediaan/workload SA. |
| `GET /sa/utilization` | Lead_SA/Admin | query `year?`, `sa_id?` | utilisasi jam per SA per bulan | Rekap utilisasi dari activity logs. |
| `GET /utilization/projects` | Lead_SA/Admin | — | jam + personel per proyek | Effort distribution antar proyek. |
| `GET /utilization/summary` | Lead_SA/Admin | query `year?` | agregasi work_type & project_phase | Ringkasan dua dimensi untuk dashboard. |
| `POST /projects/{project_id}/assign` | Lead_SA/Admin | `AssignRequest` (`sa_id`) | `AssignmentResponse` | Assign SA ke proyek `Pending Assignment` → `Assigned`, notifikasi SA, trigger folder provisioning (stub, B2). **Notifikasi gagal karena B1 (`metadata=`).** |
| `POST /projects/{project_id}/reassign` | Lead_SA/Admin | `AssignRequest` (`sa_id`) | detail SA baru | Reassign SA pada proyek `Assigned`/`Ready`/`Pending Assignment`. **`event_type="reassignment"` melanggar CheckConstraint + B1.** |

---

## Workflow Status (`/api/v1`, tag `Workflow`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `PATCH /projects/{project_id}/status` | `get_current_user` + `_check_project_access` (Sales: proyek sendiri, SA: proyek ditugaskan, Lead_SA/Admin: semua) | `StatusUpdateRequest` (`new_status`) | `StatusTransitionResponse` + audit log | Ubah status proyek dengan validasi state machine linear (`New` … `Closed-Win`). `Lost` hanya Lead_SA/Admin. `Handover Complete` ditolak 400 dan diarahkan ke `POST /handover`. Mencatat `AuditLog`. |

---

## DQ Number (`/api/v1`, tag `DQ Number`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `PATCH /projects/{project_id}/dq-number` | `get_current_user` (Sales/Lead_SA/Admin) | `DQNumberInput` (`dq_number`) | `DQNumberResponse` | Input/update DQ Number. Proyek harus ≥ `Assigned`. DQ pertama → status `Ready` + `stop_timer` SLA. Sales tak bisa edit DQ yang sudah ada. |
| `GET /projects/{project_id}/documents/solutions` | `get_current_user` | — | daftar dokumen Solutions | Dokumen folder Solutions dengan gating: Sales butuh DQ ada + status `Reviewed`/`Final`; SA/Lead_SA selalu lihat semua. |

---

## Documents (`/api/v1`, tag `Documents`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `POST /projects/{project_id}/documents` | `get_current_user` | `DocumentCreate` (`doc_type`, `gdrive_link`, `folder_type`, `notes?`) | `DocumentResponse` | Buat dokumen (status awal `Draft`). |
| `GET /projects/{project_id}/documents` | `get_current_user` | — | daftar dokumen proyek | List dokumen proyek. |
| `PATCH /documents/{doc_id}/status` | `get_current_user` (maju: SA/Lead_SA; mundur: Lead_SA) | `DocumentStatusUpdate` (`new_status`) | `DocumentResponse` | Transisi status dokumen dengan state machine. Loncat `Draft→Final` ditolak. |

---

## Activity Logs (`/api/v1`, tag `Activity Logs`)

| Method & Path | Auth | Request | Response | Purpose |
|---|---|---|---|---|
| `POST /activity-logs` | `get_current_user` | `ActivityLogCreate` (`work_type`, `id_project?`, `project_phase?`, `subtask_category`, `duration_hours`, `raw_notes`, `gcal_event_id?`) | log + status polish | Catat aktivitas; AI polishing otomatis via LLM (guardrail input). |
| `POST /activity-logs/{id_log}/polish` | `get_current_user` (ownership) | — | log terbaru | Re-trigger AI polishing untuk entry yang gagal. |
| `GET /projects/{id_project}/story` | `get_current_user` | query `page`, `page_size` (max 20), `category?`, `date_from?`, `date_to?` | timeline paginated | Project story timeline aktivitas. |
| `POST /projects/{id_project}/summarize` | `get_current_user` | — | `{summary, total_activities, total_hours}` | Ringkasan LLM dari semua activity log (fallback non-LLM bila gagal). |

---

## Calendar (`/api/v1/calendar`, tag `Calendar`)

| Method & Path | Auth | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /calendar/auth-url` | tidak perlu | — | `{auth_url}` | Generate URL OAuth khusus scope `calendar.readonly`. 503 jika OAuth belum dikonfigurasi. |
| `POST /calendar/sync` | `get_current_user` | `CalendarSyncRequest` (`access_token`) | daftar events (7 hari ±) | Fetch events Google Calendar (read-only). Timeout → 504, API error → 502. |
| `POST /calendar/map` | `get_current_user` | `CalendarMapRequest` | `CalendarMapResponse` | Petakan satu event ke proyek sebagai activity log. Event sudah dipetakan → 409 (unique `gcal_event_id`). |

---

## SLA Timer (`/api/v1`, tag `SLA Timer`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /projects/{project_id}/sla-status` | `get_current_user` | — | `{status, days_elapsed, is_locked, is_active}` | Status SLA proyek (badge green/yellow/red). 404 jika tracker belum ada. |
| `POST /sla/process` | `get_current_user` (Admin/Lead_SA) | — | statistik proses | Trigger SLA processing semua proyek aktif (reminder H+3, eskalasi + lock H+5). Untuk cron/manual. |

---

## Notifications (`/api/v1/notifications`, tag `Notifications`)

| Method & Path | Auth | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /notifications` | `get_current_user` | query `page`, `per_page` (max 20) | notifikasi in-app paginated | Riwayat notifikasi user (terbaru dulu). |
| `PATCH /notifications/{notification_id}/read` | `get_current_user` (ownership) | — | `{id, status}` | Tandai notifikasi dibaca. 404 jika bukan milik user. |
| `GET /notifications/unread-count` | `get_current_user` | — | `{unread_count}` | Jumlah notifikasi belum dibaca (badge). |

---

## Handover (`/api/v1`, tag `Handover`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /projects/{project_id}/handover-status` | SA ditugaskan/Lead_SA/Admin (Sales ditolak) | — | `{ready, missing_items, pmo_email, delivery_email, project_status, hld_status}` | Cek kesiapan handover. |
| `POST /projects/{project_id}/handover-config` | Lead_SA/Admin | `HandoverConfigInput` (`pmo_email`, `delivery_email`) | config tersimpan | Set email PMO/Delivery Lead. |
| `POST /projects/{project_id}/handover` | SA ditugaskan/Lead_SA/Admin | — | detail handover | Trigger handover: prasyarat `Closed-Win` + HLD `Final` + email PMO/Delivery + folder GDrive. Provision `Final_Deliverables`, notifikasi (in-app + email bila punya akun; email langsung bila tidak, dicatat di audit `penerima_email_langsung`), status `Handover Complete`, audit log. GDrive gagal → 400, status tetap `Closed-Win`, SA/Lead_SA diberi notifikasi. Satu-satunya jalan ke `Handover Complete` (`PATCH /status` menolaknya, 400). |

---

## Collaborators (`/api/v1/projects`, tag `Collaborators`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /projects/{project_id}/collaborators` | akses proyek (privileged/sales_pic/assigned_sa/collaborator) | — | daftar kolaborator | List kolaborator proyek. |
| `POST /projects/{project_id}/collaborators` | SA/Sales/Lead_SA/Admin | `CollaboratorAddRequest` (`user_id`, `role`) | kolaborator baru | Tambah kolaborator (`viewer`/`contributor`). Sales hanya bisa tag Sales, SA hanya tag SA; contributor harus SA. 409 jika duplikat. |
| `DELETE /projects/{project_id}/collaborators/{user_id}` | Lead_SA/Admin/sales_pic/assigned_sa | — | — | Hapus kolaborator. |
| `GET /projects/users/search` | `get_current_user` | query `q` (min 2), `limit` | daftar user | Autocomplete user untuk tambah kolaborator. |

> Catatan routing: `GET /projects/users/search` berada di bawah prefix `/projects` sehingga path-nya `/api/v1/projects/users/search`.

---

## Admin (`/api/v1/admin`, tag `Admin`)

| Method & Path | Auth / Role | Request | Response | Purpose |
|---|---|---|---|---|
| `GET /admin/users` | Admin | — | daftar semua user | User management. |
| `PATCH /admin/users/{user_id}/role` | Admin | `{role}` | user ter-update | Ubah role user (`Sales`/`SA`/`Lead_SA`/`Admin`). |

> Content was rephrased for compliance with licensing restrictions.
