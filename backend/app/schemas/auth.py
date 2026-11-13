"""
Pydantic schemas untuk autentikasi dan OAuth flow.
Mendefinisikan request/response models untuk endpoint auth.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class TokenPair(BaseModel):
    """Pasangan access token dan refresh token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # detik sampai access token expired


class GoogleProfile(BaseModel):
    """Profil user dari Google OAuth."""

    google_id: str
    email: str
    name: str
    avatar_url: Optional[str] = None


class UserResponse(BaseModel):
    """Response data user untuk client."""

    id: uuid.UUID
    email: str
    name: str
    role: str
    is_admin: bool
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Response setelah login berhasil."""

    user: UserResponse
    tokens: TokenPair


class RefreshRequest(BaseModel):
    """Request untuk refresh token."""

    refresh_token: str


class OAuthError(BaseModel):
    """Error response dari OAuth flow."""

    error: str
    detail: str
