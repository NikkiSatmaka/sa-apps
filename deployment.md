# Portal SA — Panduan Deployment Lengkap

Dokumen ini berisi panduan lengkap deployment Portal SA MVP, mencakup dua metode:
1. **Portainer CE** (produksi saat ini) — deploy via Portainer UI tanpa SSH
2. **SSH + Docker Compose** — deploy langsung ke VM via SSH (untuk setup awal atau troubleshooting)

---

## Arsitektur Deployment (Produksi)

```
Cloudflare SSL → VM Reverse Proxy (port 3535) → Frontend Container (Next.js :3000)
                                                      ↓ (API Routes proxy)
                                                 Backend Container (FastAPI :8000)
                                                      ↓
                                                 PostgreSQL Container (:5432)
```

- **Domain**: `https://sa-portal.mov.co.id`
- **Portainer**: CE 2.33.1 LTS (tanpa SSH ke VM)
- **Registry**: GitHub Container Registry (`ghcr.io`)
- **Stack name**: `sa-portal`
- **GitHub repo**: `github.com/apeuta/sa-apps`

## Container & Image

| Service | Image | Port Mapping |
|---------|-------|-------------|
| db | `postgres:18-alpine` | 5433:5432 |
| backend | `ghcr.io/apeuta/sa-portal-backend:latest` | 8555:8000 |
| frontend | `ghcr.io/apeuta/sa-portal-frontend:latest` | 3535:3000 |

---

## Bagian 1: Deploy via Portainer (Produksi)

### Prasyarat

1. Docker Desktop running (lokal, untuk build image)
2. Login ke GHCR:
   ```bash
   docker login ghcr.io
   ```
   - Username: `apeuta`
   - Password: GitHub Personal Access Token (scope: `write:packages`, `read:packages`)

### Build & Push Image

**PENTING**: Selalu gunakan `--no-cache` agar semua file ter-include di image. Tanpa `--no-cache`, Docker bisa menggunakan cache lama yang tidak memiliki file baru (misalnya API route proxy).

```bash
# Frontend
docker buildx build --platform linux/amd64 --no-cache \
  -t ghcr.io/apeuta/sa-portal-frontend:latest \
  --push ./frontend

# Backend
docker buildx build --platform linux/amd64 --no-cache \
  -t ghcr.io/apeuta/sa-portal-backend:latest \
  --push ./backend
```

> **Catatan**: `--platform linux/amd64` diperlukan karena build dilakukan di Mac (ARM) untuk VM (x86_64).

### Script Otomatis

```bash
mise run publish            # backend + frontend (versi ditanya terpisah)
mise run publish frontend   # hanya frontend
```

### Deploy / Update Stack di Portainer

1. Buka Portainer → **Stacks** → pilih stack `sa-portal`
2. Klik tab **Editor**
3. Pastikan image yang digunakan sudah benar (lihat tabel di atas)
4. Klik **Update the stack**
5. **Centang** opsi **"Pull latest image versions"**
6. Klik **Update**

### Jika Portainer Masih Pakai Image Lama (Cache)

Kadang Portainer tidak menarik image terbaru meskipun sudah di-push. Solusi:

1. **Force remove container** di Portainer:
   - Containers → centang container yang ingin di-remove
   - Klik **Remove** → centang **Force remove**
2. Pastikan image terbaru sudah di-push ke GHCR
3. Update stack di Portainer Editor untuk trigger pull ulang

### Membandingkan Image Local vs Portainer

#### Metode 1: Bandingkan Image Digest

```bash
# Di lokal, lihat digest image yang sudah di-push
docker images --digests ghcr.io/apeuta/sa-portal-frontend:latest
```

Bandingkan dengan digest yang ter-deploy di Portainer:
- Buka Portainer → **Images** → cari `ghcr.io/apeuta/sa-portal-frontend:latest`
- Lihat kolom **Digest** atau **ID**

Jika digest/ID berbeda, berarti Portainer belum menggunakan image terbaru.

#### Metode 2: Bandingkan BUILD_ID (Frontend)

Next.js standalone menghasilkan file `BUILD_ID` yang unik setiap build.

```bash
# BUILD_ID dari image lokal terbaru
docker run --rm ghcr.io/apeuta/sa-portal-frontend:latest cat /app/.next/BUILD_ID
```

Bandingkan dengan BUILD_ID dari container yang berjalan di Portainer:
- Buka Portainer → **Containers** → `sa-portal-frontend`
- Klik **Console** → **Connect**
- Jalankan:
  ```bash
  cat /app/.next/BUILD_ID
  ```

Jika BUILD_ID berbeda → Portainer pakai image lama → lakukan force remove.

#### Metode 3: Bandingkan Image ID

```bash
# Di lokal
docker inspect ghcr.io/apeuta/sa-portal-frontend:latest --format='{{.Id}}'
```

Di Portainer:
- **Images** → klik image → lihat **Image ID**

#### Metode 4: Cek Log Startup Backend

Backend sekarang otomatis membuat tabel database saat startup. Cek log:
- Portainer → **Containers** → `sa-portal-backend` → **Logs**
- Cari baris: `Database tables checked/created successfully.`
- Jika tidak ada → backend image belum ter-update

### Seed Data Demo

Setelah deployment berhasil, jalankan script seed untuk mengisi data demo:

1. Portainer → **Containers** → `sa-portal-backend`
2. Klik **Console** → **Connect**
3. Jalankan:
   ```bash
   python -m scripts.seed_demo_data
   ```

Data yang di-seed:
- 7 demo users
- 8 proyek
- 8 dokumen
- 21 activity logs (Juni–Agustus 2026)

### Verifikasi Deployment

1. **Health check backend**:
   - Buka `https://sa-portal.mov.co.id/api/v1/auth/config`
   - Harus return: `{"demo_mode": true, "oauth_configured": true}`

2. **Demo login**:
   - Buka `https://sa-portal.mov.co.id/login`
   - Klik "Login sebagai Lead SA"
   - Harus redirect ke dashboard tanpa error

3. **Utilisasi SA**:
   - Di dashboard Lead SA, pilih seorang personel
   - Harus menampilkan data utilisasi (jika seed data sudah dijalankan)
   - Jika error, akan menampilkan detail pesan error untuk debugging

### Upgrade PostgreSQL 16 → 18

`compose.yaml` kini memakai `postgres:18-alpine`. **Folder data PostgreSQL 16 tidak bisa dibuka oleh PostgreSQL 18** (beda major version). Jika container 18 dijalankan di atas data dir 16, server langsung exit dengan error:

```
FATAL:  database files are incompatible with server
DETAIL:  The data directory was initialized by PostgreSQL version 16, which is not compatible with this version 18.x.
```

Karena itu upgrade **wajib lewat dump/restore** (`pg_dump` → `pg_restore`), bukan sekadar mengganti tag image. Pakai `pg_dump`/`pg_restore` dari image **18** (versi target) saat mengekspor dari server 16 agar format dump kompatibel. Prosedur dump/restore format custom (`-Fc`) menjaga row count, FK, jsonb, dan `alembic_version` identik setelah restore.

> **Catatan**: PostgreSQL 18 memperkenalkan asynchronous I/O (AIO). Default `io_method=worker` aman untuk semua Linux; tuning opsional (mis. `io_uring`) bisa dilakukan belakangan, bukan bagian dari upgrade ini.

> **Peringatan**: jangan `docker compose pull`/redeploy stack dengan image 18 sebelum backup selesai. Jika container db 18 sempat start di atas data dir lama, ia hanya gagal start (data 16 tidak diubah), tetapi stack akan down.

#### A. Lokal (`compose.local.yaml`)

`compose.local.yaml` memakai named volume `postgres-data` (di Compose project `sa-apps`: `sa-apps_postgres-data`). Pada mesin yang pernah menjalankan stack, volume ini **berisi data PostgreSQL 16** dan akan membuat db 18 gagal start dengan error di atas. Pilih salah satu:

**Opsi 1 — data lokal boleh hilang (paling sederhana)**

```bash
docker compose -f compose.yaml -f compose.local.yaml down
docker volume rm sa-apps_postgres-data
docker compose -f compose.yaml -f compose.local.yaml up -d --build
# backend-init menjalankan `alembic upgrade head` + seed demo data otomatis
```

> `down` + `volume rm` menghapus seluruh data lokal. Hanya aman untuk data demo/dev.

**Opsi 2 — data lokal harus dipertahankan**

```bash
# 1. Dump dari db 16 (stack lama masih berjalan dengan image 16)
docker exec sa-portal-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/sa.dump'
docker cp sa-portal-db:/tmp/sa.dump ./sa-local.dump

# 2. Hentikan stack dan hapus volume lama
docker compose -f compose.yaml -f compose.local.yaml down
docker volume rm sa-apps_postgres-data

# 3. Start HANYA db (image 18) dengan volume baru yang kosong
docker compose -f compose.yaml -f compose.local.yaml up -d db

# 4. Restore
docker cp ./sa-local.dump sa-portal-db:/tmp/sa.dump
docker exec sa-portal-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error /tmp/sa.dump'

# 5. Naikkan sisa stack
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

Simpan `sa-local.dump` sampai Anda yakin data benar; jangan commit file dump.

#### B. Produksi (Portainer, bind mount `/opt/docker_srv/sa-portal/postgres-data`)

**Downtime**: aplikasi tidak tersedia dari langkah 2 sampai langkah 7. Perkirakan beberapa menit untuk database kecil; ukur waktu `pg_dump`/`pg_restore` pada langkah 1 untuk memperkirakan jendela maintenance. Jadwalkan di luar jam kerja.

**Risiko**: (1) kehilangan data bila backup tidak valid — selalu verifikasi dump dan simpan data dir lama; (2) stack gagal start bila db 18 menemukan data dir 16; (3) perubahan perilaku minor antar-major (mis. collation/ekstensi) — cek log setelah restore.

1. **Backup** (stack masih berjalan, image 16):

   ```bash
   docker exec sa-portal-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/sa.dump'
   docker cp sa-portal-db:/tmp/sa.dump /opt/docker_srv/sa-portal/backup-pg16-$(date +%F).dump
   # Verifikasi dump terbaca dan catat row count untuk dibandingkan nanti
   docker exec sa-portal-db pg_restore -l /tmp/sa.dump | head
   docker exec sa-portal-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from projects"'
   docker exec sa-portal-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'
   ```

2. **Stop backend dan frontend** di Portainer (stack `sa-portal`) agar tidak ada tulisan baru. Lalu lakukan dump final (ulangi langkah 1 jika ada data berubah sejak backup pertama) dan stop container `sa-portal-db`.

3. **Simpan data dir lama sebagai rollback** (jangan dihapus, jangan di-chmod):

   ```bash
   sudo mv /opt/docker_srv/sa-portal/postgres-data /opt/docker_srv/sa-portal/postgres-data-pg16
   sudo mkdir /opt/docker_srv/sa-portal/postgres-data
   ```

4. **Start PG18 dengan data dir baru (kosong)**: update stack di Portainer ke `compose.yaml` terbaru (image `postgres:18-alpine`), dan start **hanya service `db`** dulu. Container akan menginisialisasi cluster baru memakai `POSTGRES_USER`/`POSTGRES_DB`/`POSTGRES_PASSWORD` dari env stack. Pastikan healthy.

5. **Restore**:

   ```bash
   docker cp /opt/docker_srv/sa-portal/backup-pg16-<tanggal>.dump sa-portal-db:/tmp/sa.dump
   docker exec sa-portal-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error /tmp/sa.dump'
   ```

6. **Verifikasi data**: bandingkan row count dengan langkah 1 dan pastikan versi server 18:

   ```bash
   docker exec sa-portal-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "show server_version; select count(*) from projects; select version_num from alembic_version"'
   ```

7. **Start backend dan frontend**, lalu verifikasi:
   - `alembic current` menunjukkan head: `docker exec sa-portal-backend alembic current` (harus `(head)`).
   - `GET /health` backend healthy, dan jalankan checklist "Verifikasi Deployment" di atas.
   - Cek log `sa-portal-db` dan `sa-portal-backend` tanpa error.

8. **Pembersihan**: simpan `postgres-data-pg16` dan file dump minimal beberapa hari/minggu sampai aplikasi terbukti stabil, baru hapus.

**Rencana rollback** (bila langkah 5–7 gagal): stop stack, kembalikan image db ke `postgres:16-alpine` di stack Portainer, lalu

```bash
sudo mv /opt/docker_srv/sa-portal/postgres-data /opt/docker_srv/sa-portal/postgres-data-pg18-gagal
sudo mv /opt/docker_srv/sa-portal/postgres-data-pg16 /opt/docker_srv/sa-portal/postgres-data
```

lalu start stack. Data yang ditulis setelah langkah 7 (jika backend sempat berjalan di PG18) tidak ada di data dir 16 — itu sebabnya backend baru dinyalakan setelah verifikasi data.

**Catatan healthcheck**: `compose.yaml` memakai `pg_isready -U sa_portal -d sa_portal_db` (hardcoded). Tidak diubah pada upgrade ini; pastikan `POSTGRES_USER`/`POSTGRES_DB` di env tetap bernilai `sa_portal`/`sa_portal_db`.

### Troubleshooting (Portainer)

#### Login Gagal (404)

**Penyebab**: Frontend image tidak menyertakan API route proxy (`/api/v1/[...path]/route.ts`).

**Solusi**: Rebuild frontend dengan `--no-cache`:
```bash
docker buildx build --platform linux/amd64 --no-cache \
  -t ghcr.io/apeuta/sa-portal-frontend:latest \
  --push ./frontend
```

#### Gagal Memuat Data Utilisasi

**Penyebab**: Tabel database (`activity_logs`, dll) belum dibuat.

**Solusi**: Backend sekarang otomatis membuat tabel saat startup. Pastikan backend image sudah ter-update. Cek log backend untuk konfirmasi: `Database tables checked/created successfully.`

#### 502 Bad Gateway

**Penyebab**: Frontend tidak bisa menghubungi backend.

**Solusi**:
- Pastikan `BACKEND_URL` di environment Portainer = `http://backend:8000`
- Pastikan backend container running (cek di Portainer → Containers)
- Cek health check: `curl http://localhost:8555/health` dari VM

#### Image Portainer Tidak Ter-Update

**Penyebab**: Portainer menggunakan cached image.

**Solusi**:
1. Force remove container di Portainer
2. Push ulang image ke GHCR
3. Update stack dengan centang "Pull latest image versions"
4. Verifikasi dengan metode BUILD_ID (lihat di atas)

#### Docker Push Gagal: "owner not found"

**Penyebab**: Username GHCR salah atau belum login.

**Solusi**:
```bash
docker logout ghcr.io
docker login ghcr.io
# Username: aputea
# Password: GitHub PAT (write:packages, read:packages)
```

### Konfigurasi Portainer Stack

File `docker-compose.portainer.yml` ada di `.gitignore` karena berisi credentials. Untuk edit:

1. Portainer → **Stacks** → `sa-portal` → **Editor**
2. Edit YAML langsung di editor
3. Klik **Update the stack**

Environment variables penting:
- `DATABASE_URL` — koneksi ke PostgreSQL
- `SECRET_KEY` — untuk JWT signing
- `DEMO_MODE` — `true` untuk mengaktifkan demo login
- `FRONTEND_URL` — URL frontend (untuk CORS)
- `CORS_ORIGINS` — origin yang diizinkan
- `GOOGLE_REDIRECT_URI` — callback URL untuk Google OAuth
- `ALLOWED_DOMAINS` — domain email yang boleh login
- `BACKEND_URL` — URL backend dari frontend (`http://backend:8000`)

---

## Bagian 2: Deploy via SSH + Docker Compose

> Gunakan metode ini untuk setup awal VM atau troubleshooting yang membutuhkan akses langsung.

### Prasyarat VM

| Item | Minimum |
|------|---------|
| OS | Ubuntu 22.04 LTS |
| CPU | 2 vCPU |
| RAM | 4 GB |
| Disk | 30 GB |
| Port terbuka | 22 (SSH), 80 (HTTP), 443 (HTTPS) |
| Akses | SSH ke VM + IP publik atau domain |

### Demo Mode (Tanpa Domain & Google Credentials)

Portal SA mendukung **Demo Mode** yang memungkinkan Anda menjalankan dan mencoba seluruh UI tanpa:
- Domain
- Google OAuth credentials
- Google Drive / Calendar / Gmail credentials
- LLM API key (Gemini/OpenAI)

#### Cara Kerja Demo Mode:

1. Set `DEMO_MODE=true` di file `.env`
2. Halaman login akan menampilkan **4 tombol demo login** (Sales, SA, Lead SA, Admin)
3. Klik tombol → langsung masuk tanpa autentikasi Google
4. Semua fitur UI bisa diakses dan di-demo
5. Fitur yang membutuhkan external API (scoring, folder provisioning) akan graceful-fallback

#### Kapan Beralih ke Production Mode:

Setelah Anda siap dengan credentials:
1. Login sebagai **Admin** → buka menu **Settings** (⚙️) → isi credentials
2. Atau edit `.env` langsung di VM: set `DEMO_MODE=false` + isi Google credentials
3. Restart: `docker compose restart backend`

### Step 1: Login dan Buat User Deployment

```bash
# Login ke VM
ssh your-user@your-vm-ip

# Buat user khusus untuk deployment (dengan password)
sudo adduser sa-portal --gecos ""
# Masukkan password yang kuat saat diminta

# Berikan akses sudo
sudo usermod -aG sudo sa-portal
```

### Step 2: Install Docker Engine

```bash
# Update package index
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Tambahkan Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Tambahkan Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker + Compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Tambah user sa-portal ke docker group (agar bisa jalankan docker tanpa sudo)
sudo usermod -aG docker sa-portal

# Install Git
sudo apt-get install -y git

# Verifikasi
docker --version
docker compose version
```

### Step 3: Setup SSH Key untuk GitHub

```bash
# Switch ke user sa-portal
sudo su - sa-portal

# Generate SSH key pair
ssh-keygen -t ed25519 -C "sa-portal@vm"
# Tekan Enter untuk lokasi default, passphrase opsional

# Tampilkan public key — COPY seluruh output
cat ~/.ssh/id_ed25519.pub

# Tambahkan ke GitHub:
# 1. Buka https://github.com/settings/keys
# 2. Klik "New SSH key"
# 3. Title: "SA Portal VM"
# 4. Paste public key
# 5. Klik "Add SSH key"

# Verifikasi koneksi
ssh -T git@github.com
# Output yang diharapkan: "Hi aputea! You've been authenticated..."

# Konfigurasi Git identity
git config --global user.name "SA Portal Deploy"
git config --global user.email "your-email@domain.com"
```

### Step 4: Clone Repository dan Konfigurasi

```bash
# Clone repo
git clone git@github.com:apeuta/sa-apps.git ~/sa-portal
cd ~/sa-portal

# Buat file environment dari template
cp .env.example .env
nano .env
```

#### Environment Variables yang WAJIB diisi:

```env
# === Database ===
POSTGRES_PASSWORD=password_kuat_minimal_16_karakter

# === Backend ===
SECRET_KEY=random_string_32_karakter_untuk_jwt
ENVIRONMENT=development

# === Demo Mode (AKTIFKAN INI UNTUK DEMO TANPA GOOGLE CREDENTIALS) ===
DEMO_MODE=true

# === Frontend ===
NEXT_PUBLIC_API_URL=http://YOUR-VM-IP:8000/api/v1
FRONTEND_URL=http://YOUR-VM-IP:3000

# === CORS ===
CORS_ORIGINS=*
```

> **Catatan:** Dengan `DEMO_MODE=true`, Anda bisa langsung login tanpa Google OAuth.
> Google credentials, LLM API key, dll. bisa dikonfigurasi NANTI melalui Admin Settings di UI.

#### (Opsional) Credentials untuk Fitur Penuh:

Kredensial berikut TIDAK WAJIB untuk demo. Bisa diisi nanti via halaman Admin Settings (`/admin/settings`) setelah login sebagai Admin:

```env
# Google OAuth (opsional — dibutuhkan untuk login via Google)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://YOUR-DOMAIN-OR-IP/api/v1/auth/callback
ALLOWED_DOMAINS=yourdomain.com

# LLM (opsional — dibutuhkan untuk AI scoring & note polishing)
GEMINI_API_KEY=

# Google Drive (opsional — dibutuhkan untuk auto folder provisioning)
GDRIVE_SERVICE_ACCOUNT_KEY=

# Gmail (opsional — dibutuhkan untuk email notification)
GMAIL_CREDENTIALS=
```

> **Tips:** Login sebagai **Admin** → buka menu **Settings** (⚙️) di sidebar → isi credentials kapanpun siap.

### Step 5: Build dan Jalankan Aplikasi

```bash
cd ~/sa-portal

# Build dan jalankan semua service (pertama kali butuh 2-3 menit)
docker compose up -d --build

# Verifikasi semua container running
docker compose ps

# Cek health endpoint backend
curl http://localhost:8000/health
# Expected: {"status":"success","data":{"api":"healthy","database":"healthy"}}

# Cek frontend
curl -I http://localhost:3000
# Expected: HTTP/1.1 200 OK

# Lihat logs jika ada masalah
docker compose logs -f --tail=50
```

### Step 6: Setup Nginx Reverse Proxy

Nginx diperlukan agar aplikasi bisa diakses dari luar VM melalui port 80/443 (bukan port 3000/8000 langsung).

#### Install Nginx

```bash
sudo apt-get install -y nginx
```

#### Buat Konfigurasi Site

```bash
sudo nano /etc/nginx/sites-available/sa-portal
```

Isi dengan konfigurasi berikut:

```nginx
# Upstream definitions
upstream frontend {
    server 127.0.0.1:3000;
}

upstream backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;  # Ganti dengan domain atau IP publik

    # === Frontend (Next.js) ===
    location / {
        proxy_pass http://frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Timeout untuk SSR pages
        proxy_read_timeout 30s;
    }

    # === Backend API ===
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # File upload support (5 files x 20MB = 100MB max)
        client_max_body_size 100M;

        # Timeout untuk LLM calls yang lambat
        proxy_read_timeout 60s;
        proxy_connect_timeout 30s;
    }

    # === Swagger Documentation ===
    location /docs {
        proxy_pass http://backend/docs;
        proxy_set_header Host $host;
    }

    location /redoc {
        proxy_pass http://backend/redoc;
        proxy_set_header Host $host;
    }

    location /openapi.json {
        proxy_pass http://backend/openapi.json;
        proxy_set_header Host $host;
    }

    # === Health Check ===
    location /health {
        proxy_pass http://backend/health;
        proxy_set_header Host $host;
    }

    # === Static files caching (PWA assets) ===
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # === Service Worker (jangan cache lama) ===
    location = /sw.js {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        expires -1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # === Manifest (jangan cache lama) ===
    location = /manifest.json {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        expires -1;
        add_header Cache-Control "no-cache";
    }
}
```

#### Aktifkan Konfigurasi

```bash
# Buat symlink ke sites-enabled
sudo ln -s /etc/nginx/sites-available/sa-portal /etc/nginx/sites-enabled/

# Hapus default site
sudo rm -f /etc/nginx/sites-enabled/default

# Test konfigurasi (harus output: "syntax is ok")
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx

# Verifikasi Nginx berjalan
sudo systemctl status nginx
```

### Step 7: Buka Firewall

#### Opsi A: UFW (Ubuntu Firewall)

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
sudo ufw status
```

#### Opsi B: AWS Security Group

Jika VM ada di AWS, buka inbound rules di Security Group:
- Port 22 (SSH) — Source: IP Anda saja
- Port 80 (HTTP) — Source: 0.0.0.0/0
- Port 443 (HTTPS) — Source: 0.0.0.0/0

#### Opsi C: GCP Firewall Rules

```bash
gcloud compute firewall-rules create sa-portal-http \
    --allow tcp:80,tcp:443 \
    --source-ranges 0.0.0.0/0 \
    --target-tags sa-portal
```

### Step 8: (Opsional) Setup HTTPS dengan Let's Encrypt

```bash
# Install Certbot
sudo apt-get install -y certbot python3-certbot-nginx

# Generate SSL certificate
sudo certbot --nginx -d your-domain.com

# Certbot otomatis:
# - Generate certificate
# - Update konfigurasi Nginx (redirect HTTP → HTTPS)
# - Setup auto-renewal via cron/systemd timer

# Test auto-renewal
sudo certbot renew --dry-run
```

Setelah SSL aktif, update `.env`:

```bash
cd ~/sa-portal
nano .env
```

Ubah semua URL ke HTTPS:

```env
GOOGLE_REDIRECT_URI=https://your-domain.com/api/v1/auth/callback
NEXT_PUBLIC_API_URL=https://your-domain.com/api/v1
FRONTEND_URL=https://your-domain.com
CORS_ORIGINS=["https://your-domain.com"]
```

Restart aplikasi:
```bash
docker compose down && docker compose up -d --build
```

### Verifikasi Deployment (SSH)

```bash
# Dari luar VM (laptop/browser):
curl http://your-domain.com/health
# Expected: {"status":"success","data":{"api":"healthy","database":"healthy"}}

# Buka di browser:
# Frontend:    http://your-domain.com
# Swagger:     http://your-domain.com/docs
# ReDoc:       http://your-domain.com/redoc
```

---

## Bagian 3: Update & Housekeeping

### Update via Portainer

1. Build & push image terbaru (lihat Bagian 1)
2. Portainer → Stacks → `sa-portal` → Editor
3. Update the stack → centang "Pull latest image versions"
4. Verifikasi dengan BUILD_ID jika perlu

### Update via SSH

#### Manual

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal
git pull origin main
docker compose down
docker compose up -d --build
docker compose logs -f --tail=20  # Monitor startup
```

#### Menggunakan Script

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal
./deploy.sh
```

### Deploy Fresh (Reset Total)

Gunakan ini jika ingin mulai dari nol atau ada perubahan schema database:

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal

# Hentikan semua container + hapus volume database
docker compose down -v --remove-orphans

# Hapus semua image/cache Docker yang tidak dipakai
docker system prune -af --volumes

# Pull kode terbaru
git pull origin main

# Pastikan .env ada di root
ls .env || cp .env.example .env
# Edit jika perlu: nano .env

# Build dan deploy
docker compose up -d --build

# Tunggu DB ready (~15 detik), lalu setup schema + seed
sleep 15
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed_demo_data

# Verifikasi
docker compose ps
curl http://localhost:8000/health
```

### Update Code Tanpa Reset Database

Gunakan ini untuk deploy perubahan kode biasa (tanpa perubahan schema):

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal

git pull origin main
docker compose down
docker compose up -d --build

# Monitor startup
docker compose logs -f --tail=20
```

### Housekeeping Berkala (Hemat Disk)

```bash
# Cek penggunaan disk Docker
docker system df

# Hapus image lama yang tidak dipakai (aman, hanya unused)
docker image prune -af

# Hapus build cache
docker builder prune -af

# Truncate log container yang membengkak
sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log

# Cek disk space VM secara keseluruhan
df -h
```

### Reset Database Saja (Tanpa Rebuild Image)

```bash
cd ~/sa-portal

# Stop backend saja
docker compose stop backend

# Hapus dan recreate database
docker compose rm -sf database
docker volume rm sa-portal-pgdata
docker compose up -d database

# Tunggu DB ready
sleep 10

# Start backend + jalankan migration dan seed
docker compose up -d backend
sleep 5
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed_demo_data

# Start frontend
docker compose up -d frontend
```

### Backup Database

```bash
# Export database ke file SQL
docker compose exec database pg_dump -U sa_portal_user -d sa_portal > backup_$(date +%Y%m%d).sql

# Restore dari backup
cat backup_20260827.sql | docker compose exec -T database psql -U sa_portal_user -d sa_portal
```

### Monitor Resource VM

```bash
# CPU dan memory usage
htop

# Disk usage per folder
du -sh ~/sa-portal/*

# Docker resource usage per container
docker stats --no-stream

# Cek log size per container
sudo du -sh /var/lib/docker/containers/*/
```

---

## Troubleshooting Umum (SSH)

### Container tidak start

```bash
# Lihat logs per service
docker compose logs backend --tail=50
docker compose logs frontend --tail=50
docker compose logs database --tail=50

# Restart service tertentu
docker compose restart backend
```

### Database connection error

```bash
# Cek apakah database container running
docker compose ps database

# Masuk ke container database
docker compose exec database psql -U sa_portal_user -d sa_portal

# Jalankan migration manual jika perlu
docker compose exec backend alembic upgrade head
```

### Port sudah dipakai

```bash
# Cek proses yang pakai port 3000/8000
sudo lsof -i :3000
sudo lsof -i :8000

# Kill proses jika perlu
sudo kill -9 <PID>
```

### Nginx 502 Bad Gateway

```bash
# Pastikan Docker containers running
docker compose ps

# Cek apakah backend merespons
curl http://127.0.0.1:8000/health

# Cek Nginx error log
sudo tail -f /var/log/nginx/error.log
```

### Disk penuh (Docker images menumpuk)

```bash
# Bersihkan image dan container yang tidak dipakai
docker system prune -a --volumes

# Cek penggunaan disk Docker
docker system df
```

---

## Arsitektur Deployment (SSH + Nginx)

```
┌─────────────────────────────────────────────────────┐
│                    Internet                           │
└────────────────────────┬────────────────────────────┘
                         │
                    Port 80/443
                         │
┌────────────────────────▼────────────────────────────┐
│                   Nginx (Reverse Proxy)               │
│  ┌───────────────────────────────────────────────┐  │
│  │  /         → localhost:3000 (Frontend)         │  │
│  │  /api/     → localhost:8000 (Backend)          │  │
│  │  /docs     → localhost:8000/docs (Swagger)     │  │
│  │  /health   → localhost:8000/health             │  │
│  └───────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                Docker Compose                         │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Frontend │  │ Backend  │  │    PostgreSQL     │  │
│  │ Next.js  │  │ FastAPI  │  │    Port 5432      │  │
│  │ :3000    │──│ :8000    │──│                   │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
│                                    │                 │
│                              ┌─────▼─────┐          │
│                              │  pgdata   │          │
│                              │ (volume)  │          │
│                              └───────────┘          │
└──────────────────────────────────────────────────────┘
```

---

## Checklist Deployment

- [ ] Docker + Docker Compose terinstall
- [ ] User `sa-portal` dibuat dengan akses docker
- [ ] SSH key terdaftar di GitHub
- [ ] Repository berhasil di-clone
- [ ] File `.env` sudah dikonfigurasi dengan credentials yang benar
- [ ] `docker compose up -d --build` berhasil
- [ ] Database tables otomatis dibuat saat backend startup
- [ ] Seed data dijalankan (`python -m scripts.seed_demo_data`)
- [ ] Health check return `{"api":"healthy","database":"healthy"}`
- [ ] Nginx terkonfigurasi dan running (jika pakai SSH method)
- [ ] Firewall/Security Group port 80/443 terbuka
- [ ] Aplikasi bisa diakses dari browser luar VM
- [ ] (Opsional) SSL/HTTPS via Let's Encrypt aktif
- [ ] (Opsional) Google OAuth callback URL sudah pakai domain final

---

## Catatan Penting

1. **File `.env` ada di root repo** (`~/sa-portal/.env`), bukan di subfolder
2. **compose.yaml ada di root repo** — semua command Docker dijalankan dari `~/sa-portal/`
3. **Seed data bersifat idempotent** — aman dijalankan berkali-kali (skip jika data sudah ada)
4. **Backend otomatis membuat tabel** saat startup — tidak perlu `alembic upgrade head` manual untuk deployment baru
5. **Volume `sa-portal-pgdata`** menyimpan data database — jangan hapus kecuali mau reset total
6. **`NEXT_PUBLIC_*` variables** di-bake saat build Docker — harus rebuild image jika berubah
7. **Selalu gunakan `--no-cache`** saat rebuild image untuk memastikan semua file ter-include

---

## Ringkasan Perintah Cepat

```bash
# 1. Login GHCR
docker login ghcr.io

# 2. Build & push frontend
docker buildx build --platform linux/amd64 --no-cache \
  -t ghcr.io/apeuta/sa-portal-frontend:latest --push ./frontend

# 3. Build & push backend
docker buildx build --platform linux/amd64 --no-cache \
  -t ghcr.io/apeuta/sa-portal-backend:latest --push ./backend

# 4. Cek BUILD_ID lokal
docker run --rm ghcr.io/apeuta/sa-portal-frontend:latest cat /app/.next/BUILD_ID

# 5. Update stack di Portainer, lalu verifikasi BUILD_ID container

# 6. Seed demo data (via Portainer console backend)
python -m scripts.seed_demo_data
```
