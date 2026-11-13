"""
API endpoints untuk autentikasi Google OAuth 2.0.
Menangani login, callback, refresh token, logout, get current user, dan demo login.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginResponse,
    OAuthError,
    RefreshRequest,
    TokenPair,
    UserResponse,
)
from app.services.auth_service import (
    AuthServiceError,
    DomainNotAllowedError,
    TokenError,
    auth_service,
)
from app.services.auth_service import (
    OAuthError as ServiceOAuthError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/config", summary="Auth Configuration Status")
async def get_auth_config():
    """
    Mengembalikan konfigurasi auth yang aktif.
    Dipanggil frontend saat halaman login dimuat untuk menentukan
    tombol mana yang ditampilkan (demo / Google OAuth).
    Tidak memerlukan autentikasi.
    """
    oauth_configured = bool(
        settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
        and len(settings.GOOGLE_CLIENT_ID) > 10
    )
    return {
        # Pakai demo_mode_enabled agar indikator yang dilihat frontend konsisten
        # dengan perilaku runtime (hard block produksi).
        "demo_mode": settings.demo_mode_enabled,
        "oauth_configured": oauth_configured,
    }


# === Demo Mode ===
# Konfigurasi demo users — setiap role punya email dan nama tetap
DEMO_USERS = {
    "Sales": {
        "email": "demo-sales@portal-sa.local",
        "name": "Demo Sales",
        "google_id": "demo-google-id-sales",
    },
    "SA": {
        "email": "demo-sa@portal-sa.local",
        "name": "Demo SA",
        "google_id": "demo-google-id-sa",
    },
    "Lead_SA": {
        "email": "demo-lead@portal-sa.local",
        "name": "Demo Lead SA",
        "google_id": "demo-google-id-lead-sa",
    },
    "Product": {
        "email": "demo-product@portal-sa.local",
        "name": "Demo Product",
        "google_id": "demo-google-id-product",
    },
    # Persona Admin = SA dengan flag admin (admin menempel pada satu role fungsional, ADR 0012).
    "Admin": {
        "email": "demo-admin@portal-sa.local",
        "name": "Demo Admin",
        "google_id": "demo-google-id-admin",
        "role": "SA",
        "is_admin": True,
    },
}


def _origin(url: str) -> tuple[str, str]:
    """(scheme, host:port) dari sebuah URL, untuk membandingkan origin."""
    parsed = urlparse(url)
    return parsed.scheme.lower(), parsed.netloc.lower()


def _frontend_url_diizinkan(url: str) -> bool:
    """True hanya bila `url` bermuatan origin yang sama dengan FRONTEND_URL."""
    asal = _origin(url)
    return bool(asal[0] and asal[1]) and asal == _origin(settings.FRONTEND_URL)


class DemoLoginRequest(BaseModel):
    """Request body untuk demo login."""

    role: Literal["Sales", "Product", "SA", "Lead_SA", "Admin"]


@router.post("/demo-login", summary="Demo Login (bypass OAuth)")
async def demo_login(
    body: DemoLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login tanpa Google OAuth untuk development/demo.
    Hanya aktif jika DEMO_MODE=true DAN ENVIRONMENT bukan production.
    Membuat demo user di database jika belum ada (INSERT IF NOT EXISTS).
    Mengembalikan JWT token yang identik formatnya dengan OAuth flow.
    """
    # Cek apakah demo mode aktif. demo_mode_enabled hard-block produksi:
    # di ENVIRONMENT=production selalu False meski DEMO_MODE=true.
    if not settings.demo_mode_enabled:
        raise HTTPException(
            status_code=403,
            detail="Demo mode tidak aktif. Gunakan Google OAuth untuk login.",
        )

    # Ambil konfigurasi demo user berdasarkan role
    demo_config = DEMO_USERS[body.role]

    # Cari user di database berdasarkan email (INSERT IF NOT EXISTS)
    stmt = select(User).where(User.email == demo_config["email"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Buat demo user baru di database — gunakan deterministic UUID berdasarkan email
        import hashlib

        user_id = uuid.UUID(hashlib.md5(demo_config["email"].encode()).hexdigest())
        user = User(
            id=user_id,
            email=demo_config["email"],
            name=demo_config["name"],
            role=demo_config.get("role", body.role),
            is_admin=demo_config.get("is_admin", False),
            google_id=demo_config["google_id"],
            avatar_url=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate JWT token pair — menggunakan method yang sama dengan OAuth flow
    tokens = auth_service._create_token_pair(user)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens,
    )


def _get_token_from_header(request: Request) -> str:
    """Ekstrak Bearer token dari Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header tidak ditemukan atau format salah.",
        )
    return auth_header[7:]  # Hapus "Bearer " prefix


@router.get("/login", summary="Initiate Google OAuth Login")
async def login(redirect_url: str = Query(default=None, description="URL redirect setelah login")):
    """
    Memulai OAuth flow dengan redirect ke Google consent screen.
    Client akan di-redirect ke Google untuk login.
    """
    # Gunakan redirect_url sebagai state (opsional)
    oauth_url = auth_service.initiate_oauth(state=redirect_url)
    return RedirectResponse(url=oauth_url)


@router.get("/callback", summary="Handle Google OAuth Callback")
async def callback(
    code: str = Query(default=None, description="Authorization code dari Google"),
    error: str = Query(default=None, description="Error dari Google jika consent dibatalkan"),
    state: str = Query(default=None, description="State parameter (redirect URL)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle callback dari Google setelah user melakukan consent.
    Mendukung 2 flow:
    - Login biasa: state kosong atau URL redirect biasa
    - Calendar auth: state diawali 'calendar_auth|' → tukar code, redirect ke frontend dengan token
    """
    # Handle jika user membatalkan consent
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Login dibatalkan oleh user: {error}",
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Authorization code tidak ditemukan.",
        )

    # === Calendar Auth Flow ===
    # State format: "calendar_auth|{frontend_url}"
    if state and state.startswith("calendar_auth|"):
        frontend_url = state.split("|", 1)[1] if "|" in state else "/"
        # State datang dari client (lewat /auth/login?redirect_url=...). Tanpa pengecekan,
        # token Google bisa diarahkan ke origin penyerang (open redirect), jadi tolak
        # sebelum kode OAuth ditukar.
        if not _frontend_url_diizinkan(frontend_url):
            raise HTTPException(
                status_code=400,
                detail="State tidak valid: URL tujuan harus berada di origin frontend.",
            )
        try:
            google_tokens = await auth_service._exchange_code(code)
            gcal_token = google_tokens.get("access_token", "")
            # Redirect ke frontend dengan token di URL hash (tidak dikirim ke server)
            redirect_url = f"{frontend_url}#gcal_token={gcal_token}"
            return RedirectResponse(url=redirect_url)
        except Exception as e:
            logger.error(f"Calendar OAuth token exchange failed: {e}")
            redirect_url = f"{frontend_url}#gcal_error=token_exchange_failed"
            return RedirectResponse(url=redirect_url)

    # === Normal Login Flow ===
    try:
        user, tokens = await auth_service.handle_callback(code, db)
    except DomainNotAllowedError as e:
        raise HTTPException(status_code=403, detail=e.detail)
    except ServiceOAuthError as e:
        raise HTTPException(status_code=502, detail=e.detail)
    except AuthServiceError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens,
    )


@router.post("/refresh", summary="Refresh Access Token", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh access token menggunakan refresh token yang masih valid.
    Mengembalikan token pair baru (access + refresh).
    """
    try:
        tokens = await auth_service.refresh_token(body.refresh_token, db)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=e.detail)

    return tokens


@router.post("/logout", summary="Logout / Revoke Session")
async def logout(request: Request):
    """
    Revoke session user (logout).
    Client harus menghapus token dari storage setelah endpoint ini dipanggil.
    """
    token = _get_token_from_header(request)

    try:
        auth_service.revoke_session(token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=e.detail)

    return {"message": "Logout berhasil."}


@router.get("/me", summary="Get Current User", response_model=UserResponse)
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil informasi user yang sedang login berdasarkan access token.
    Endpoint ini juga berfungsi sebagai validasi session aktif.
    """
    token = _get_token_from_header(request)

    try:
        user = await auth_service.get_current_user(token, db)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=e.detail)

    return UserResponse.model_validate(user)
