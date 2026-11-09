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
| **RAG Recommendation** | Rekomendasi template dari proyek Closed-Win serupa |
| **PMO Handover** | Automasi handover folder + notifikasi ke PMO/Delivery setelah Closed-Win |
| **Dashboard per Role** | Tampilan berbeda untuk Sales, SA, dan Lead SA (termasuk utilisasi SA per bulan) |
| **Project Collaboration** | Tag kolaborator (viewer/contributor) ke proyek — SA, Sales, Lead SA bisa manage |
| **SA Reassign** | Lead SA bisa reassign SA yang ditugaskan ke proyek lain dari detail proyek |
| **PWA + Offline** | Installable, offline-capable, auto-sync saat kembali online |

---

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Frontend | Next.js 14+ (App Router), TypeScript, Tailwind CSS, Zustand, SWR |
| Backend | FastAPI (Python 3.12+), SQLAlchemy async, Pydantic |
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
├── compose.yaml                # Orchestration (3 services)
├── deploy.sh                   # Script deployment otomatis
├── .env.example                # Template environment variables
└── README.md
```

---

## Quick Start (Lokal dengan Docker)

```bash
# 1. Clone repo
git clone git@github.com:apeuta/sa-apps.git
cd sa-apps

# 2. Konfigurasi environment
cp .env.example .env
# Edit .env — isi minimal: POSTGRES_PASSWORD, JWT_SECRET_KEY, GOOGLE_CLIENT_ID/SECRET, GEMINI_API_KEY

# 3. Build dan jalankan
docker compose up -d --build

# 4. Verifikasi
curl http://localhost:8000/health
# Output: {"status":"success","data":{"api":"healthy","database":"healthy"}}
```

Akses:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Deployment di Ubuntu VM

### Prasyarat
- Ubuntu 22.04+, minimal 2 vCPU / 4GB RAM / 30GB disk
- Domain atau IP publik (untuk akses dari luar)
- Port 80 dan 443 terbuka di firewall/security group

### Step-by-step

```bash
# 1. Install Docker
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git

# 2. Buat user deployment
sudo adduser sa-portal --gecos ""
sudo usermod -aG docker sa-portal
sudo su - sa-portal

# 3. Clone dan konfigurasi
git clone git@github.com:apeuta/sa-apps.git ~/sa-portal
cd ~/sa-portal
cp .env.example .env
nano .env  # Isi semua credentials

# 4. Jalankan aplikasi
docker compose up -d --build

# 5. Setup Nginx reverse proxy (agar bisa diakses via port 80/443)
# Lihat section "Setup Nginx" di bawah
```

### Setup Nginx (Akses dari Luar VM)

```bash
# Install Nginx
sudo apt-get install -y nginx

# Buat konfigurasi
sudo nano /etc/nginx/sites-available/sa-portal
```

Isi file konfigurasi:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # Ganti dengan domain atau IP publik VM

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 100M;  # Untuk file upload max 20MB x 5 files
    }

    # Swagger / ReDoc
    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
        proxy_set_header Host $host;
    }
    location /redoc {
        proxy_pass http://127.0.0.1:8000/redoc;
        proxy_set_header Host $host;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8000/openapi.json;
        proxy_set_header Host $host;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }
}
```

Aktifkan konfigurasi:

```bash
sudo ln -s /etc/nginx/sites-available/sa-portal /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### Setup SSL dengan Let's Encrypt (HTTPS)

```bash
# Install Certbot
sudo apt-get install -y certbot python3-certbot-nginx

# Generate SSL certificate (ganti dengan domain Anda)
sudo certbot --nginx -d your-domain.com

# Auto-renewal sudah diatur otomatis oleh certbot
sudo certbot renew --dry-run  # Test renewal
```

### Buka Firewall

```bash
# UFW (Ubuntu default firewall)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
sudo ufw status

# Jika pakai AWS Security Group:
# - Buka Inbound Rule port 80 (HTTP) dan 443 (HTTPS) dari 0.0.0.0/0
# - Port 22 (SSH) dari IP Anda saja
```

### Update .env untuk Produksi

Setelah Nginx dan SSL aktif, update `.env`:

```env
# Ganti localhost dengan domain/IP publik
GOOGLE_REDIRECT_URI=https://your-domain.com/api/v1/auth/callback
NEXT_PUBLIC_API_URL=https://your-domain.com/api/v1
FRONTEND_URL=https://your-domain.com
```

Restart aplikasi:
```bash
docker compose down
docker compose up -d --build
```

---

## Update Deployment

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal
git pull origin main
docker compose down
docker compose up -d --build
docker compose logs -f --tail=50  # Monitor startup
```

Atau gunakan script otomatis:
```bash
./deploy.sh
```

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
- **Admin Settings** — Kategori Aktivitas (CRUD) + User & Role Management
- **UI Cleanup** — Semua emoji dihapus, teks "Belum..." ditampilkan bold merah, menu Dokumen dihapus dari sidebar

---

## Kontributor

- Solutions Architect Team
