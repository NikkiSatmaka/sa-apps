# Panduan Deployment Portal SA MVP di Ubuntu VM

Dokumen ini berisi panduan lengkap untuk men-deploy Portal SA dari GitHub ke Ubuntu VM menggunakan Docker, termasuk setup Nginx agar aplikasi bisa diakses dari luar.

---

## Prasyarat

| Item | Minimum |
|------|---------|
| OS | Ubuntu 22.04 LTS |
| CPU | 2 vCPU |
| RAM | 4 GB |
| Disk | 30 GB |
| Port terbuka | 22 (SSH), 80 (HTTP), 443 (HTTPS) |
| Akses | SSH ke VM + IP publik atau domain |

---

## Demo Mode (Tanpa Domain & Google Credentials)

Portal SA mendukung **Demo Mode** yang memungkinkan Anda menjalankan dan mencoba seluruh UI tanpa perlu:
- Domain
- Google OAuth credentials
- Google Drive / Calendar / Gmail credentials
- LLM API key (Gemini/OpenAI)

### Cara Kerja Demo Mode:

1. Set `DEMO_MODE=true` di file `.env`
2. Halaman login akan menampilkan **4 tombol demo login** (Sales, SA, Lead SA, Admin)
3. Klik tombol → langsung masuk tanpa autentikasi Google
4. Semua fitur UI bisa diakses dan di-demo
5. Fitur yang membutuhkan external API (scoring, folder provisioning) akan graceful-fallback

### Kapan Beralih ke Production Mode:

Setelah Anda siap dengan credentials:
1. Edit `.env` langsung di VM: set `DEMO_MODE=false` + isi Google credentials
2. Restart: `docker compose restart backend`

---

## Step 1: Login dan Buat User Deployment

```bash
# Login ke VM
ssh your-user@your-vm-ip

# Buat user khusus untuk deployment (dengan password)
sudo adduser sa-portal --gecos ""
# Masukkan password yang kuat saat diminta

# Berikan akses sudo
sudo usermod -aG sudo sa-portal
```

---

## Step 2: Install Docker Engine

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

---

## Step 3: Setup SSH Key untuk GitHub

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
# Output yang diharapkan: "Hi apeuta! You've been authenticated..."

# Konfigurasi Git identity
git config --global user.name "SA Portal Deploy"
git config --global user.email "your-email@domain.com"
```

---

## Step 4: Clone Repository dan Konfigurasi

```bash
# Clone repo
git clone git@github.com:apeuta/sa-apps.git ~/sa-portal
cd ~/sa-portal

# Buat file environment dari template
cp .env.example .env
nano .env
```

### Environment Variables yang WAJIB diisi:

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
> Google credentials, LLM API key, dll. bisa dikonfigurasi NANTI lewat `.env`/Portainer (tidak ada halaman pengaturan di UI).

### (Opsional) Credentials untuk Fitur Penuh:

Kredensial berikut TIDAK WAJIB untuk demo. Bisa diisi nanti lewat `.env`/Portainer:

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

> **Tips:** Isi credentials di `.env`/Portainer kapanpun siap, lalu restart backend.

---

## Step 5: Build dan Jalankan Aplikasi

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

---

## Step 6: Setup Nginx Reverse Proxy

Nginx diperlukan agar aplikasi bisa diakses dari luar VM melalui port 80/443 (bukan port 3000/8000 langsung).

### Install Nginx

```bash
sudo apt-get install -y nginx
```

### Buat Konfigurasi Site

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

### Aktifkan Konfigurasi

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

---

## Step 7: Buka Firewall

### Opsi A: UFW (Ubuntu Firewall)

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
sudo ufw status
```

### Opsi B: AWS Security Group

Jika VM ada di AWS, buka inbound rules di Security Group:
- Port 22 (SSH) — Source: IP Anda saja
- Port 80 (HTTP) — Source: 0.0.0.0/0
- Port 443 (HTTPS) — Source: 0.0.0.0/0

### Opsi C: GCP Firewall Rules

```bash
gcloud compute firewall-rules create sa-portal-http \
    --allow tcp:80,tcp:443 \
    --source-ranges 0.0.0.0/0 \
    --target-tags sa-portal
```

---

## Step 8: (Opsional) Setup HTTPS dengan Let's Encrypt

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

---

## Step 9: Verifikasi Deployment

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

## Update Deployment (Setelah Ada Perubahan Code)

### Manual

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal
git pull origin main
docker compose down
docker compose up -d --build
docker compose logs -f --tail=20  # Monitor startup
```

### Menggunakan Script

```bash
ssh sa-portal@your-vm-ip
cd ~/sa-portal
./deploy.sh
```

---

## Troubleshooting

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

## Arsitektur Deployment

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
- [ ] Health check return `{"api":"healthy","database":"healthy"}`
- [ ] Nginx terkonfigurasi dan running
- [ ] Firewall/Security Group port 80/443 terbuka
- [ ] Aplikasi bisa diakses dari browser luar VM
- [ ] (Opsional) SSL/HTTPS via Let's Encrypt aktif
- [ ] (Opsional) Google OAuth callback URL sudah pakai domain final
