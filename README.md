# Portal SA — Solutions Architect Management Platform

Portal SA adalah Progressive Web App (PWA) untuk manajemen proyek pre-sales dan pencatatan aktivitas harian Solutions Architect. Aplikasi ini menggantikan Redmine dengan fitur AI-powered scoring, integrasi Google Workspace, dan deployment Docker yang portabel.

---

## Fitur Utama

| Modul | Deskripsi |
|-------|-----------|
| **Pre-Sales Request** | Sales submit request proyek + file attachment (MoM/RFP) |
| **AI BANT Scoring** | Gemini AI menganalisis dokumen dan menghitung skor BANT (Budget, Authority, Need, Timeline) |
| **Project Assignment** | Lead SA menugaskan SA ke proyek berdasarkan scoring dan workload |
| **GDrive Auto-Provisioning** | Folder proyek otomatis dibuat di Google Drive dengan permission yang tepat |
| **Document Tracking** | Tracking status deliverables (PropTek, BOQ, Mandays, HLD) dengan state machine |
| **DQ Number Gating** | Akses dokumen dikontrol berdasarkan input DQ Number oleh Sales |
| **SLA Timer** | Countdown 5 hari untuk DQ Number dengan auto-lock folder dan eskalasi |
| **Activity Logger** | Pencatatan aktivitas harian + AI note polishing (discussion points & action items) |
| **Calendar Sync** | Sinkronisasi Google Calendar untuk mapping aktivitas ke proyek |
| **Notification** | In-app notification (selalu aktif) untuk semua event penting. Email via Gmail API aktif bila `GMAIL_CREDENTIALS` dikonfigurasi; tanpa kredensial, email di-skip rapi (graceful fallback) dan in-app tetap jalan. |
| **RAG Recommendation** | Rekomendasi template dari proyek Won serupa |
| **PMO Handover** | Automasi handover folder + notifikasi ke PMO/Delivery setelah Won |
| **Dashboard per Role** | Tampilan berbeda untuk Sales, SA, dan Lead SA (termasuk utilisasi SA per bulan) |
| **Project Collaboration** | Tag kolaborator (viewer/contributor) ke proyek — SA, Sales, Lead SA bisa manage |
| **SA Reassign** | Lead SA bisa reassign SA yang ditugaskan ke proyek lain dari detail proyek |
| **PWA + Offline** | Installable, offline-capable, auto-sync saat kembali online |

---

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Frontend | Next.js 14+ (App Router), TypeScript, Tailwind CSS, Zustand, SWR |
| Backend | FastAPI (Python 3.14+), SQLAlchemy async, Pydantic |
| Database | PostgreSQL 18 |
| AI | Google Gemini API (via LLM Provider abstraction — multi-provider ready) |
| Auth | Google OAuth 2.0 + JWT |
| Integration | Google Drive API, Google Calendar API, Gmail API |
| Deployment | Docker + Docker Compose |

---

## Struktur Project

```
sa-apps/                        # Root repository (= root di VM)
├── backend/                    # FastAPI backend
│   ├── app/
│   │   ├── api/               # API routers (endpoints)
│   │   ├── core/              # Config, database, middleware
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/          # Business logic services
│   │   └── main.py            # FastAPI app entry point
│   ├── alembic/               # Database migrations
│   ├── scripts/               # Seed data & utilities
│   ├── tests/                 # Unit tests
│   ├── Dockerfile             # Multi-stage build (uv + uv.lock)
│   ├── pyproject.toml         # Manifest & dependency (sumber kebenaran)
│   └── uv.lock                # Lockfile (versi di-pin, reproducible)
├── frontend/                   # Next.js PWA frontend
│   ├── src/
│   │   ├── app/               # Pages (App Router)
│   │   ├── components/        # Reusable UI components
│   │   ├── lib/               # API clients, utilities
│   │   └── store/             # Zustand stores
│   ├── public/                # PWA manifest, service worker, icons
│   ├── Dockerfile             # Multi-stage build
│   └── package.json
├── .kiro/specs/sa-portal-mvp/ # Spec documents (requirements, design, tasks)
├── compose.yaml                # Production images and fail-closed migrations
├── deploy.sh                   # Safe image-based deployment helper
├── .env.example                # Template environment variables
└── README.md
```

---

## Quick Start (Lokal dengan Docker)

```bash
# 1. Clone repo
git clone git@github.com:apeuta/sa-apps.git
cd sa-apps

# 2. Configure environment
cp .env.example .env
# Edit .env with the required local values.
```

3. Build and run the opt-in local Compose configuration:

```bash
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

4. Verify the backend:

```bash
curl http://localhost:8555/health
```

Access:
- **Frontend**: http://localhost:3535
- **Backend API**: http://localhost:8555
- **Swagger Docs**: http://localhost:8555/docs
- **ReDoc**: http://localhost:8555/redoc

---

## Deployment

`compose.yaml` is the production image-based configuration; it does not build application images from source. For current service ports, image publishing, migration ordering, backup/restore, rollback and smoke-check procedures, follow the authoritative [deployment and recovery guide](deployment.md).

For local development, use the explicit opt-in `compose.local.yaml` override documented in `CONTRIBUTING.md`. Do not use `docker compose down -v` or prune volumes to troubleshoot a database; those operations can delete persistent data. `./deploy.sh` now backs up and validates the database dump before pulling configured application images, then relies on Compose's fail-closed `backend-init` migration dependency.

---

## Environment Variables

Lihat `.env.example` untuk daftar lengkap. Yang **wajib** dikonfigurasi:

| Variable | Deskripsi |
|----------|-----------|
| `POSTGRES_PASSWORD` | Password database PostgreSQL |
| `JWT_SECRET_KEY` | JWT signing key (random string 32+ karakter) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL |
| `FRONTEND_URL` | URL frontend untuk redirect setelah OAuth Calendar |
| `ALLOWED_DOMAINS` | Domain email yang diizinkan login |
| `GEMINI_API_KEY` | Google Gemini API key |
| `NEXT_PUBLIC_API_URL` | URL backend API (dari sisi browser) |

Opsional (fitur terkait nonaktif secara graceful bila kosong):

| Variable | Deskripsi |
|----------|-----------|
| `GDRIVE_SERVICE_ACCOUNT_KEY` | JSON key service account Google Drive (satu baris) untuk provisioning folder proyek. Kosong → provisioning folder berstatus `failed`, aplikasi tetap jalan. Kunci produksi terpisah dari kunci uji; jangan di-commit. Lihat [deployment.md](deployment.md), bagian Google Drive. |
| `GMAIL_CREDENTIALS` | JSON key service account untuk email notifikasi (kosong → email di-skip, in-app tetap jalan) |
---

## Seed Demo Data

Untuk mengisi data contoh (users, projects, documents, activity logs):

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed_demo_data
```

Script ini idempotent — aman dijalankan berkali-kali. Data demo mencakup:
- 7 users (2 Sales, 3 SA, 1 Lead_SA, 1 Admin)
- 8 proyek dengan berbagai status dan detail BANT lengkap (MRR, PIC, kebutuhan teknis)
- 8 dokumen (PropTek, BOQ, HLD)
- 21 activity logs tersebar Juni-Agustus 2026 (untuk demo utilisasi)

---

## API Documentation

Setelah aplikasi berjalan:
- **Swagger UI**: `/docs` — Interactive API explorer
- **ReDoc**: `/redoc` — Readable API documentation
- **OpenAPI Spec**: `/openapi.json` — Machine-readable spec

---

## Status

**v4.2** — MVP Ready dengan fitur kolaborasi, LLM integration, dan calendar OAuth. Siap deploy.

---

## Changelog Terbaru

### v4.2 — Kolaborasi, LLM Integration, Calendar OAuth

**Fitur Baru:**
- **Fitur Kolaborasi** — SA/Sales bisa menambahkan kolaborator (viewer atau contributor) ke proyek. Contributor bisa menambah Activity Log. Model `ProjectCollaborator` dengan endpoint CRUD lengkap.
- **SA Reassign** — Lead SA bisa reassign SA yang sedang bertugas ke SA lain langsung dari detail proyek.
- **AI Note Polishing (Action Items)** — Activity log kini menampilkan action items hasil polishing AI (discussion points + action items dengan PIC).
- **LLM-Powered Summarize** — Tombol "Summarize" di Project Story menggunakan Gemini AI untuk generate ringkasan aktivitas proyek.
- **LLM BANT Scoring** — Scoring engine di backend menggunakan Gemini untuk analisis kelengkapan data BANT dari dokumen.
- **Calendar OAuth Flow** — Sinkronisasi Google Calendar menggunakan OAuth terpisah dengan token di URL hash (tidak dikirim ke server).
- **BANT Pass/Fail Display** — Frontend hanya menampilkan "BANT Passed" atau "BANT not passed" (skor numerik disembunyikan, dihitung di backend).
- **Detail BANT Tetap Ditampilkan** — Informasi dasar proyek (Budget MRR, PIC Customer, Kebutuhan Teknis, Target Timeline) tetap ditampilkan sebagai info proyek.
- **Publish Script** — Script `scripts/publish.sh` untuk build & push image Docker, dijalankan via `mise run publish [backend|frontend]` (versi ditanya per komponen).

**Bug Fixes:**
- **Calendar Sync 502** — Implementasi frontend Google OAuth token exchange untuk calendar sync (sebelumnya error 502).
- **Missing `FRONTEND_URL`** — Menambahkan field `FRONTEND_URL` ke Settings class yang dibutuhkan endpoint `/calendar/auth-url`.
- **TypeScript Type Errors** — Fix type mismatch `role: string` ke `"viewer" | "contributor"` di interface ProjectDetail.
- **TypeScript Null Handling** — Fix `boolean | null` tidak assignable ke `boolean | undefined` di atribut `disabled` (optional chaining).
- **Missing `uuid` Import** — Fix import `uuid` yang hilang di `assignment.py`.
- **OAuth Callback Redirect** — Fix redirect URL setelah Google OAuth callback agar kembali ke frontend dashboard.
- **Auto-Create DB Tables** — Tabel database otomatis dibuat saat startup jika belum ada (memudahkan deployment baru).

### v4.1 — Dashboard & UI Enhancements

- **Assign SA dari Detail Proyek** — Lead SA bisa assign SA langsung dari halaman detail proyek (berstatus Pending Assignment)
- **Edit Proyek** — Tombol Edit di halaman detail proyek untuk update nama, customer, DQ, BANT detail
- **Detail BANT Deskriptif** — Tampilkan nominal MRR, nama/jabatan/email PIC, kebutuhan teknis, timeline (bukan skor numerik)
- **Search & Filter Proyek** — Search bar + dropdown filter status di halaman listing proyek
- **Utilisasi SA per Bulan** — Tabel jam kerja per SA per bulan dengan filter tahun dan per individu
- **Effort per Proyek** — Tabel total jam + personel SA per proyek di dashboard Lead SA
- **Pengguna (Admin)** — User & Role Management
- **UI Cleanup** — Semua emoji dihapus, teks "Belum..." ditampilkan bold merah, menu Dokumen dihapus dari sidebar

---

## Kontributor

- Solutions Architect Team
