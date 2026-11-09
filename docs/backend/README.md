# Dokumentasi Backend Portal SA

Overview teknis backend Portal SA — portal internal pre-sales/Solution Architect. Dokumen ini mengikat tiga referensi detail:

- [ERD.md](./ERD.md) — Entity-Relationship Diagram data model (Mermaid).
- [WORKFLOW.md](./WORKFLOW.md) — State machine + alur domain end-to-end (Mermaid).
- [API.md](./API.md) — Referensi lengkap seluruh endpoint API.

Untuk konteks kontribusi, lihat [`CONTRIBUTING.md`](../../CONTRIBUTING.md); untuk rencana aktif, [`docs/ROADMAP.md`](../ROADMAP.md); untuk referensi developer backend, [`backend/README.md`](../../backend/README.md).

## Tech Stack

| Komponen | Teknologi | Versi (pinned) |
|----------|-----------|----------------|
| Framework API | FastAPI | 0.115.6 |
| Runtime | Python | 3.12 |
| ASGI server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| Driver DB | asyncpg | 0.30.0 |
| Migration | Alembic | 1.14.0 |
| Validasi | Pydantic / pydantic-settings | 2.10.3 / 2.7.0 |
| JWT | python-jose[cryptography] | 3.3.0 |
| Password hashing | passlib[bcrypt] | 1.7.4 |
| Google SDK | google-auth, google-api-python-client | 2.37.0 / 2.155.0 |
| Database | PostgreSQL | 15 |
| Package manager | uv (uv_build backend) | — |
| Dev tools | pytest, pytest-asyncio, ruff, hypothesis | — |

LLM: abstraction layer multi-provider (`llm_provider.py`) dengan adapter aktif `GeminiAdapter` (default model `gemini-1.5-flash`), didaftarkan saat startup di `main.py`.

## Project Layout

```
backend/
├── app/
│   ├── main.py            # entrypoint FastAPI, register router + middleware
│   ├── api/               # router per domain (auth, projects, scoring, ...)
│   ├── services/          # business logic (scoring_engine, sla_timer, handover_service, ...)
│   ├── models/            # model SQLAlchemy (8 tabel)
│   ├── schemas/           # schema Pydantic (request/response + response standar)
│   ├── core/              # config, database, dependencies (auth), exceptions, rate_limiter
│   └── utils/             # guardrails LLM
├── alembic/versions/      # migration (001 initial, 002 handover cols, 003 activity utilization)
├── tests/                 # pytest (condong ke AI/guardrail/provisioning/SLA/scoring)
├── pyproject.toml         # sumber kebenaran dependency (uv)
└── Dockerfile             # multi-stage build (uv, Python 3.12-slim, non-root)
```

Layering: `api` (HTTP + auth + validasi akses) → `services` (business logic + integrasi eksternal) → `models` (persistence). `schemas` dipakai lintas layer untuk kontrak data; `core` menyediakan infrastruktur. Beberapa router (`projects.py`, `assignment.py`) cukup besar dan mencampur logic ke dalam handler — kandidat refactor (roadmap).

## Cara Menjalankan

### Lokal (uv)

```bash
cd backend
uv sync                                   # pasang deps (termasuk dev group)
uv run alembic upgrade head               # terapkan migration
uv run uvicorn app.main:app --reload      # dev server di :8000
uv run pytest                             # test suite
uv run ruff check .                       # lint
```

Dokumentasi interaktif: `http://localhost:8000/docs` (Swagger UI) dan `http://localhost:8000/redoc`.

### Docker Compose (full stack)

Stack di `compose.yaml` (root): service `db` (postgres:18-alpine), `backend` (port host `8555` → container `8000`), `frontend` (port host `3535` → `3000`). Backend punya `HEALTHCHECK` ke `/health`.

```bash
docker compose up -d
```

> Perlu diperhatikan: `compose.yaml` meneruskan env `SECRET_KEY`, sedangkan `config.py` membaca `JWT_SECRET_KEY`. Penamaan ini belum selaras (roadmap 0.2) — set `JWT_SECRET_KEY` agar JWT signing memakai secret yang dimaksud.

## Environment Variables

Dibaca via `pydantic-settings` di `core/config.py` (file `.env`, `case_sensitive=True`).

| Variable | Default | Keterangan |
|----------|---------|------------|
| `APP_NAME` / `APP_VERSION` | `Portal SA API` / `1.0.0` | Metadata app. |
| `DEBUG` | `False` | Mode debug (echo SQL jika true). |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind server. |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/portal_sa` | Koneksi async PostgreSQL. |
| `CORS_ORIGINS` | `*` | Comma-separated allow-list (default `*` — kunci untuk produksi). |
| `RATE_LIMIT_PER_MINUTE` | `100` | Limit rate limiter per user. |
| `DEMO_MODE` | `True` | **Bypass OAuth** — set `False` di produksi (roadmap 0.1). |
| `JWT_SECRET_KEY` | `change-this-...` | **Secret JWT — default tidak aman**, wajib di-override (roadmap 0.2). |
| `JWT_ALGORITHM` | `HS256` | Algoritma signing. |
| `JWT_EXPIRE_HOURS` / `JWT_REFRESH_EXPIRE_HOURS` | `24` / `168` | TTL access/refresh token. |
| `ALLOWED_DOMAINS` | `""` | Whitelist domain email (kosong = izinkan semua). |
| `ROLE_MAPPING` | `"{}"` | JSON mapping email/wildcard → role. Default role `SA`. |
| `FRONTEND_URL` | `http://localhost:3000` | Untuk redirect pasca OAuth. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | `""` | Kredensial Google OAuth. |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/callback` | Callback OAuth. |
| `LLM_PROVIDER` | `gemini` | Provider LLM aktif. |
| `LLM_MODEL_NAME` | `gemini-1.5-flash` | Model default. |
| `LLM_API_ENDPOINT` | `https://generativelanguage.googleapis.com/v1` | Endpoint LLM. |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `30` / `3` | Timeout + retry LLM. |
| `LLM_MAX_INPUT_CHARS` | `20000` | Guardrail batas karakter input teks. |
| `LLM_MAX_DOCUMENT_BYTES` | `10485760` (10 MB) | Guardrail batas byte dokumen. |
| `GUARDRAIL_PII_DETECTION_ENABLED` | `True` | Toggle PII detector. |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API key per provider. |
| `GDRIVE_SERVICE_ACCOUNT_KEY` | `""` | Service account JSON untuk folder provisioning. |
| `GCAL_WEBHOOK_ENDPOINT` | `""` | Endpoint webhook calendar. |
| `GMAIL_CREDENTIALS` | `""` | Kredensial Gmail (email saat ini stub). |

## Catatan Penting

- **Bug yang masih aktif** (lihat ROADMAP): B1 (`metadata=` pada `NotificationLog` → notifikasi assignment/scoring crash), B2 (folder provisioner stub tapi lapor `triggered=True`), B3 (`/health` DB status hardcode), B4 (`estimasi_nilai` tak dipersist), B5 (`create_all` saat startup bersaing dengan Alembic).
- **Risiko keamanan**: endpoint di `scoring.py` tanpa `get_current_user`; `PATCH /projects/{id}` tanpa cek akses; default `DEMO_MODE`/`JWT_SECRET_KEY`/`CORS` tidak aman untuk produksi.
- Analisis lengkap + rekomendasi "backend stuff" (observability, CI, versioning, dll.) ada di laporan investigasi `.agents/tasks/backend-docs-investigation.md`.

> Content was rephrased for compliance with licensing restrictions.
