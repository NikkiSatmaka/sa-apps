"""
Service untuk autentikasi Google OAuth 2.0.
Menangani OAuth flow, domain validation, JWT management, dan user provisioning.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import VALID_ROLES, settings
from app.models.user import User
from app.schemas.auth import GoogleProfile, TokenPair

# Endpoint Google OAuth
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class AuthServiceError(Exception):
    """Base exception untuk AuthService."""

    def __init__(self, error: str, detail: str):
        self.error = error
        self.detail = detail
        super().__init__(detail)


class DomainNotAllowedError(AuthServiceError):
    """Error ketika domain email tidak diizinkan."""

    def __init__(self, domain: str):
        super().__init__(
            error="domain_not_allowed",
            detail=f"Domain '{domain}' tidak diizinkan untuk login. Hubungi administrator.",
        )


class OAuthError(AuthServiceError):
    """Error dari proses OAuth."""

    def __init__(self, detail: str):
        super().__init__(error="oauth_error", detail=detail)


class TokenError(AuthServiceError):
    """Error terkait JWT token."""

    def __init__(self, detail: str):
        super().__init__(error="token_error", detail=detail)


logger = logging.getLogger(__name__)

DEFAULT_ROLE = "SA"


class AuthService:
    """
    Service utama untuk autentikasi.
    Menangani Google OAuth 2.0 flow, JWT session, dan user management.
    """

    def __init__(self):
        self._role_mapping: Optional[dict] = None

    @property
    def role_mapping(self) -> dict:
        """Parse ROLE_MAPPING dari environment variable (JSON string)."""
        if self._role_mapping is None:
            try:
                dimuat = json.loads(settings.ROLE_MAPPING)
            except (json.JSONDecodeError, TypeError):
                dimuat = {}
            # JSON valid tapi bukan objek (list/string/null) dianggap mapping kosong.
            self._role_mapping = dimuat if isinstance(dimuat, dict) else {}
        return self._role_mapping

    def initiate_oauth(self, state: Optional[str] = None) -> str:
        """
        Generate URL untuk redirect ke Google OAuth consent screen.
        Returns: URL string untuk redirect user ke Google.
        """
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly",
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state

        # urlencode agar state/redirect_uri berisi `&`, `#`, atau spasi tidak menyisipkan
        # parameter OAuth tambahan.
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def handle_callback(
        self, code: str, db: AsyncSession
    ) -> tuple[User, TokenPair]:
        """
        Handle callback dari Google OAuth setelah user consent.
        1. Tukar authorization code dengan access token
        2. Ambil profil user dari Google
        3. Validasi domain email
        4. Buat/update user di database
        5. Generate JWT session tokens

        Returns: Tuple (User, TokenPair)
        Raises: OAuthError, DomainNotAllowedError
        """
        # Tukar code dengan token Google
        google_tokens = await self._exchange_code(code)

        # Ambil profil user dari Google
        profile = await self._get_google_profile(google_tokens["access_token"])

        # Validasi domain
        self.validate_domain(profile.email)

        # Buat atau update user di database
        user = await self.get_or_create_user(db, profile)

        # Generate JWT tokens
        tokens = self._create_token_pair(user)

        return user, tokens

    def validate_domain(self, email: str) -> bool:
        """
        Validasi apakah domain email user ada di whitelist.
        Jika ALLOWED_DOMAINS kosong, semua domain diizinkan.

        Raises: DomainNotAllowedError jika domain tidak diizinkan.
        """
        # Jika whitelist kosong, izinkan semua (untuk development)
        if not settings.allowed_domains_list:
            return True

        domain = email.split("@")[1].lower()
        allowed = [d.lower() for d in settings.allowed_domains_list]

        if domain not in allowed:
            raise DomainNotAllowedError(domain)

        return True

    def _determine_role(self, email: str) -> str:
        """
        Tentukan role user berdasarkan ROLE_MAPPING.
        Format mapping: {"email@domain.com": "Admin", "*@domain.com": "SA"}
        Default role: SA

        Peran di mapping yang tidak ada di VALID_ROLES diabaikan (jatuh ke default) dengan
        peringatan: `Settings` sudah menolaknya saat startup, ini pertahanan berlapis agar peran
        asing tidak melanggar CHECK `chk_users_role` dan membuat login 500.
        """
        mapping = self.role_mapping

        # Cek exact match dulu
        if email.lower() in {k.lower(): v for k, v in mapping.items()}:
            for key, role in mapping.items():
                if key.lower() == email.lower():
                    return self._peran_valid_atau_default(key, role)

        # Cek wildcard pattern (*@domain.com)
        domain = email.split("@")[1].lower()
        wildcard_key = f"*@{domain}"
        for key, role in mapping.items():
            if key.lower() == wildcard_key:
                return self._peran_valid_atau_default(key, role)

        # Default role
        return DEFAULT_ROLE

    @staticmethod
    def _peran_valid_atau_default(kunci: str, peran: object) -> str:
        if isinstance(peran, str) and peran in VALID_ROLES:
            return peran
        logger.warning(
            "ROLE_MAPPING entri %r berisi peran tidak valid %r; memakai default %s. "
            "Perbaiki ROLE_MAPPING (peran valid: %s).",
            kunci,
            peran,
            DEFAULT_ROLE,
            ", ".join(VALID_ROLES),
        )
        return DEFAULT_ROLE

    async def get_or_create_user(
        self, db: AsyncSession, profile: GoogleProfile
    ) -> User:
        """
        Cari user berdasarkan google_id. Jika belum ada, buat baru.
        Jika sudah ada, update informasi profil terbaru dari Google.
        """
        # Cari user berdasarkan google_id
        stmt = select(User).where(User.google_id == profile.google_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Update informasi profil
            user.name = profile.name
            user.avatar_url = profile.avatar_url
            user.email = profile.email
            user.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(user)
        else:
            # Buat user baru
            role = self._determine_role(profile.email)
            user = User(
                id=uuid.uuid4(),
                email=profile.email,
                name=profile.name,
                role=role,
                google_id=profile.google_id,
                avatar_url=profile.avatar_url,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return user

    def _create_token_pair(self, user: User) -> TokenPair:
        """Generate pasangan access token dan refresh token JWT."""
        now = datetime.now(timezone.utc)

        # Access token - TTL 24 jam
        access_expire = now + timedelta(hours=settings.JWT_EXPIRE_HOURS)
        access_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "type": "access",
            "iat": now,
            "exp": access_expire,
        }
        access_token = jwt.encode(
            access_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

        # Refresh token - TTL 7 hari
        refresh_expire = now + timedelta(hours=settings.JWT_REFRESH_EXPIRE_HOURS)
        refresh_payload = {
            "sub": str(user.id),
            "type": "refresh",
            "iat": now,
            "exp": refresh_expire,
        }
        refresh_token = jwt.encode(
            refresh_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_EXPIRE_HOURS * 3600,
        )

    async def refresh_token(self, refresh_token_str: str, db: AsyncSession) -> TokenPair:
        """
        Refresh access token menggunakan refresh token yang masih valid.
        Generates token pair baru.

        Raises: TokenError jika refresh token invalid/expired.
        """
        try:
            payload = jwt.decode(
                refresh_token_str,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            raise TokenError("Refresh token tidak valid atau sudah expired.")

        if payload.get("type") != "refresh":
            raise TokenError("Token bukan tipe refresh.")

        user_id = payload.get("sub")
        if not user_id:
            raise TokenError("Token tidak mengandung informasi user.")

        # Cari user di database
        stmt = select(User).where(User.id == uuid.UUID(user_id))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise TokenError("User tidak ditemukan.")

        # Generate token pair baru
        return self._create_token_pair(user)

    def revoke_session(self, token: str) -> bool:
        """
        Revoke session (logout).
        Untuk MVP, cukup validasi token — client bertanggung jawab menghapus token.
        Di production, bisa implement token blacklist di Redis.

        Returns: True jika token valid dan berhasil di-revoke.
        Raises: TokenError jika token invalid.
        """
        try:
            jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            return True
        except JWTError:
            raise TokenError("Token tidak valid.")

    def verify_access_token(self, token: str) -> dict:
        """
        Verifikasi dan decode access token.
        Returns: Payload dari token.
        Raises: TokenError jika token invalid/expired.
        """
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            raise TokenError("Access token tidak valid atau sudah expired.")

        if payload.get("type") != "access":
            raise TokenError("Token bukan tipe access.")

        return payload

    async def get_current_user(self, token: str, db: AsyncSession) -> User:
        """
        Ambil user dari database berdasarkan access token.
        Raises: TokenError jika token invalid atau user tidak ditemukan.
        """
        payload = self.verify_access_token(token)
        user_id = payload.get("sub")

        stmt = select(User).where(User.id == uuid.UUID(user_id))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise TokenError("User tidak ditemukan.")

        return user

    async def _exchange_code(self, code: str) -> dict:
        """Tukar authorization code dengan access token dari Google."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                },
            )

        if response.status_code != 200:
            raise OAuthError(
                f"Gagal mendapatkan token dari Google: {response.text}"
            )

        return response.json()

    async def _get_google_profile(self, access_token: str) -> GoogleProfile:
        """Ambil profil user dari Google menggunakan access token."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            raise OAuthError("Gagal mendapatkan profil dari Google.")

        data = response.json()
        return GoogleProfile(
            google_id=data["id"],
            email=data["email"],
            name=data.get("name", data["email"]),
            avatar_url=data.get("picture"),
        )


# Singleton instance
auth_service = AuthService()
