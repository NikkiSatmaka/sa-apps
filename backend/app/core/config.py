"""
Konfigurasi aplikasi menggunakan Pydantic Settings.
Semua konfigurasi sensitif dibaca dari environment variables.

Format .env untuk list fields:
- ALLOWED_DOMAINS=domain1.com,domain2.com  (comma-separated)
- CORS_ORIGINS=http://localhost:3000,http://example.com  (comma-separated)
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings

# Placeholder lama yang tidak boleh dipakai sebagai secret produksi.
_INSECURE_JWT_PLACEHOLDER = "change-this-secret-key-in-production"
# Nilai ENVIRONMENT yang valid.
_VALID_ENVIRONMENTS = {"development", "staging", "production"}


class Settings(BaseSettings):
    """Konfigurasi utama aplikasi Portal SA."""

    # Aplikasi
    APP_NAME: str = "Portal SA API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Environment — menentukan perilaku runtime (development/staging/production).
    # production memblok demo mode secara hard (lihat demo_mode_enabled).
    ENVIRONMENT: str = "development"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/portal_sa"

    # CORS - comma-separated string, di-parse jadi list.
    # Default dev menyertakan origin frontend lokal. Jangan pakai "*" karena
    # dipasangkan dengan allow_credentials=True (kombinasi invalid/insecure).
    CORS_ORIGINS: str = "http://localhost:3000"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 100

    # SLA Scheduler — background scheduler internal ringan (ADR 0003).
    # Menjalankan process_sla_actions() secara periodik saat backend naik.
    # Default interval 1 jam. Toggle enabled disediakan agar test/tooling bisa
    # mematikan scheduler tanpa mengubah kode. CATATAN: scheduler ini hanya aman
    # untuk MVP single-instance (lihat app/services/sla_scheduler.py).
    SLA_SCHEDULER_ENABLED: bool = True
    SLA_SCHEDULER_INTERVAL_SECONDS: int = 3600

    # Demo Mode — bypass OAuth, login tanpa Google credentials.
    # Opt-in: default False. Hanya aktif saat ENVIRONMENT bukan production
    # (lihat property demo_mode_enabled untuk hard block).
    DEMO_MODE: bool = False

    # Auth
    # JWT_SECRET_KEY tidak punya default aman — WAJIB di-set via environment.
    # Validator di bawah menolak nilai kosong atau placeholder lama agar app
    # refuse-to-start ketimbang berjalan dengan secret yang bisa ditebak.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    JWT_REFRESH_EXPIRE_HOURS: int = 168  # 7 hari untuk refresh token
    ALLOWED_DOMAINS: str = ""  # Comma-separated: "domain1.com,domain2.com"
    ROLE_MAPPING: str = "{}"  # JSON string: {"email@domain.com": "Admin", "*@domain.com": "SA"}

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"  # URL frontend untuk redirect setelah OAuth

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/callback"

    # LLM Provider — Abstraction layer untuk multi-provider AI
    LLM_PROVIDER: str = "gemini"  # Provider aktif: gemini, openai, anthropic
    LLM_MODEL_NAME: str = "gemini-3.8-flash"  # Model default yang digunakan
    LLM_API_ENDPOINT: str = "https://generativelanguage.googleapis.com/v1"
    LLM_TIMEOUT_SECONDS: int = 30  # Timeout per request ke LLM
    LLM_MAX_RETRIES: int = 3  # Jumlah retry saat gagal

    # Guardrails LLM
    LLM_MAX_INPUT_CHARS: int = 20000  # batas karakter input teks
    LLM_MAX_SOURCE_CHARS: int = 60000  # anggaran karakter total sumber untuk generate Requirement
    LLM_MAX_DOCUMENT_BYTES: int = 10_485_760  # 10 MB batas byte dokumen
    GUARDRAIL_PII_DETECTION_ENABLED: bool = True  # toggle PII_Detector

    # API Keys per provider
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Google Drive
    GDRIVE_SERVICE_ACCOUNT_KEY: str = ""

    # Google Calendar
    GCAL_WEBHOOK_ENDPOINT: str = ""

    # Gmail
    # Service account JSON key (sama formatnya dengan GDRIVE_SERVICE_ACCOUNT_KEY).
    GMAIL_CREDENTIALS: str = ""
    # Alamat pengirim email. Untuk service account dengan domain-wide delegation,
    # ini adalah user yang di-impersonate (From). Kosong → pakai service account apa adanya.
    GMAIL_SENDER: str = ""

    @field_validator("ENVIRONMENT")
    @classmethod
    def _normalize_environment(cls, v: str) -> str:
        """Normalisasi ENVIRONMENT ke lowercase dan tolak nilai di luar set valid."""
        normalized = (v or "").strip().lower()
        if normalized not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT tidak valid: harus salah satu dari {sorted(_VALID_ENVIRONMENTS)}."
            )
        return normalized

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        """
        Fail fast jika JWT_SECRET_KEY kosong atau masih memakai placeholder lama.
        Karena Settings() dibuat saat import, validator yang gagal membuat app
        refuse-to-start (ValidationError) ketimbang berjalan dengan secret lemah.
        """
        value = (v or "").strip()
        if not value:
            raise ValueError("JWT_SECRET_KEY wajib di-set via environment (tidak boleh kosong).")
        if value == _INSECURE_JWT_PLACEHOLDER:
            raise ValueError(
                "JWT_SECRET_KEY masih memakai placeholder default yang tidak aman. "
                "Ganti dengan secret acak minimal 32 karakter."
            )
        return value

    @property
    def demo_mode_enabled(self) -> bool:
        """
        True hanya jika DEMO_MODE aktif DAN ENVIRONMENT bukan production.
        Hard block: produksi selalu False apa pun flag DEMO_MODE.
        """
        return self.DEMO_MODE and self.ENVIRONMENT != "production"

    @property
    def allowed_domains_list(self) -> list[str]:
        """Parse ALLOWED_DOMAINS comma-separated string menjadi list."""
        if not self.ALLOWED_DOMAINS:
            return []
        return [d.strip() for d in self.ALLOWED_DOMAINS.split(",") if d.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        """
        Parse CORS_ORIGINS comma-separated string menjadi allow-list konkret.
        Tidak pernah mengembalikan wildcard "*" karena allow_credentials=True
        tak boleh dipasangkan dengan "*". Fallback aman ke localhost:3000.
        """
        origins = [
            o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip() and o.strip() != "*"
        ]
        return origins or ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton instance
settings = Settings()
