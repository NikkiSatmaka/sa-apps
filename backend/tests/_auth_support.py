"""
Helper bersama untuk test auth/core (tiket #55): JWT buatan test, fake Google di boundary HTTP,
dan sesi DB palsu minimal. Berkas ini milik tiket #55 (tidak mengubah conftest bersama).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable

import httpx
from jose import jwt

from app.core.config import settings
from app.services import auth_service as auth_service_module

KELAS_ASLI_ASYNC_CLIENT = httpx.AsyncClient


def buat_token(
    sub: str | uuid.UUID | None = None,
    *,
    tipe: str | None = "access",
    berlaku: timedelta = timedelta(hours=1),
    secret: str | None = None,
    algoritma: str | None = None,
    ekstra: dict[str, Any] | None = None,
) -> str:
    """JWT dengan secret test; `sub=None` tanpa subject, `tipe=None` tanpa claim type."""
    sekarang = datetime.now(timezone.utc)
    payload: dict[str, Any] = {"iat": sekarang, "exp": sekarang + berlaku}
    if sub is not None:
        payload["sub"] = str(sub)
    if tipe is not None:
        payload["type"] = tipe
    payload.update(ekstra or {})
    return jwt.encode(
        payload,
        secret or settings.JWT_SECRET_KEY,
        algorithm=algoritma or settings.JWT_ALGORITHM,
    )


def user_palsu(role: str = "SA", **kw: Any) -> SimpleNamespace:
    """Objek mirip User (tanpa DB) untuk fungsi yang hanya membaca atribut.

    Admin bukan role (ADR 0012): untuk user admin pakai `is_admin=True` pada role fungsional.
    """
    sekarang = datetime.now(timezone.utc)
    persona = role
    if role == "Admin":  # persona admin = SA dengan flag admin (ADR 0012)
        role, kw = "SA", {"is_admin": True, **kw}
    nilai = dict(
        id=uuid.uuid4(),
        email=f"{persona.lower()}@contoh.id",
        name=f"User {persona}",
        role=role,
        is_admin=False,
        google_id=f"g-{uuid.uuid4().hex[:8]}",
        avatar_url=None,
        created_at=sekarang,
        updated_at=sekarang,
    )
    nilai.update(kw)
    return SimpleNamespace(**nilai)


def terapkan_persona(user: Any, role: str) -> Any:
    """Set `role` dan `is_admin` pada objek tiruan (MagicMock/SimpleNamespace).

    Persona "Admin" = SA dengan flag admin (ADR 0012); `is_admin` selalu diisi eksplisit
    agar tiruan tidak mewarisi atribut MagicMock yang truthy.
    """
    user.role, user.is_admin = ("SA", True) if role == "Admin" else (role, False)
    return user


class HasilPalsu:
    """Meniru hasil `session.execute()` untuk `scalar_one_or_none()`."""

    def __init__(self, nilai: Any):
        self._nilai = nilai

    def scalar_one_or_none(self) -> Any:
        return self._nilai


class SesiPalsu:
    """
    Sesi DB palsu untuk unit test: `execute` mengembalikan antrean hasil berurutan
    (terakhir diulang), `add` merekam objek, `commit/refresh` no-op yang dihitung.
    """

    def __init__(self, *hasil: Any):
        self._hasil = list(hasil) or [None]
        self.ditambahkan: list[Any] = []
        self.jumlah_commit = 0

    async def execute(self, _stmt: Any) -> HasilPalsu:
        nilai = self._hasil.pop(0) if len(self._hasil) > 1 else self._hasil[0]
        return HasilPalsu(nilai)

    def add(self, obj: Any) -> None:
        self.ditambahkan.append(obj)

    async def commit(self) -> None:
        self.jumlah_commit += 1

    async def refresh(self, _obj: Any) -> None:
        return None

    async def close(self) -> None:
        return None


def pasang_google(
    monkeypatch,
    *,
    token_status: int = 200,
    token_body: dict[str, Any] | str | None = None,
    profil_status: int = 200,
    profil: dict[str, Any] | None = None,
) -> list[httpx.Request]:
    """
    Ganti `httpx` di `auth_service` dengan klien bertransport `MockTransport` (boundary Google).
    Mengembalikan daftar request yang diterima fake agar test bisa menegaskan apa yang dikirim.
    """
    diterima: list[httpx.Request] = []
    token_body = {"access_token": "google-access-token"} if token_body is None else token_body
    profil = (
        {"id": "g-123", "email": "budi@perusahaan.id", "name": "Budi", "picture": "http://a/b.png"}
        if profil is None
        else profil
    )

    def handler(request: httpx.Request) -> httpx.Response:
        diterima.append(request)
        if str(request.url).startswith(auth_service_module.GOOGLE_TOKEN_URL):
            if isinstance(token_body, str):
                return httpx.Response(token_status, text=token_body)
            return httpx.Response(token_status, json=token_body)
        if str(request.url).startswith(auth_service_module.GOOGLE_USERINFO_URL):
            return httpx.Response(profil_status, json=profil)
        return httpx.Response(404)

    def pabrik(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return KELAS_ASLI_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(auth_service_module, "httpx", SimpleNamespace(AsyncClient=pabrik))
    return diterima


def pasang_google_dengan(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    """Varian bebas: handler buatan test (mis. melempar error transport)."""

    def pabrik(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return KELAS_ASLI_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(auth_service_module, "httpx", SimpleNamespace(AsyncClient=pabrik))
