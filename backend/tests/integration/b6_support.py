"""
Helper bersama test integrasi dokumen, DQ Number, workflow, dan handover (tiket B6, #59).

Membangun "dunia" kecil di Postgres uji: user per peran (lewat demo login, JWT asli), proyek
dengan status/SA/folder tertentu, dan dokumen. Data dibuat langsung lewat sesi test agar skenario
fokus pada endpoint yang diuji, bukan pada jalur pembuatan proyek.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, NotificationLog, Project, User
from tests._auth_support import buat_token
from tests.integration.model_helpers import (
    bangun_document,
    bangun_project,
    bangun_user,
    simpan,
)

API = "/api/v1"
PERAN = ("Sales", "SA", "Lead_SA", "Admin")


@pytest_asyncio.fixture
async def komit_sesi_request(api, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """
    Sesi request melepas savepoint-nya (`commit`) bila endpoint sukses, bukan di-rollback.

    Pada harness satu koneksi (B2), sesi notifikasi yang dibuka endpoint tersarang di dalam
    savepoint sesi request; menutup sesi request tanpa commit akan membatalkan baris
    notifikasi itu, sehingga efek samping notifikasi tak terlihat oleh test. Hal yang sama
    berlaku pada jalur error (mis. notifikasi kegagalan handover sebelum 400). Karena itu sesi
    di-commit di akhir request baik sukses maupun `HTTPException`; endpoint yang menulis lalu
    menolak akan terlihat sebagai perubahan tak terduga oleh assertion "tidak berubah".
    Atomisitas antar test tidak terpengaruh: transaksi luar `db_connection` selalu di-rollback.
    """
    from app.core.database import get_db
    from app.main import app

    async def _get_db_komit() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except HTTPException:
                await session.commit()
                raise
            await session.commit()

    app.dependency_overrides[get_db] = _get_db_komit


@dataclass
class Dunia:
    """User demo per peran beserta header Authorization-nya."""

    user: dict[str, User] = field(default_factory=dict)
    header: dict[str, dict[str, str]] = field(default_factory=dict)


async def siapkan_dunia(api, db: AsyncSession) -> Dunia:
    """Login demo untuk keempat peran; user tersimpan di Postgres uji."""
    dunia = Dunia()
    for peran in PERAN:
        headers = await api.login_demo(peran)
        dunia.header[peran] = headers
        resp = await api.client.get(f"{API}/auth/me", headers=headers)
        assert resp.status_code == 200, resp.text
        dunia.user[peran] = (
            await db.execute(select(User).where(User.id == resp.json()["id"]))
        ).scalar_one()
    return dunia


async def user_baru(db: AsyncSession, peran: str) -> tuple[User, dict[str, str]]:
    """User tambahan (mis. SA/Sales lain) beserta header JWT asli."""
    user = bangun_user(role=peran)
    await simpan(db, user)
    return user, {"Authorization": f"Bearer {buat_token(user.id)}"}


async def buat_proyek(
    db: AsyncSession, dunia: Dunia, *, status: str = "Assigned", sa: bool = True, **o: Any
) -> Project:
    """Proyek milik Sales demo; SA demo ditugaskan bila `sa=True`."""
    kw: dict[str, Any] = {"status": status}
    if sa:
        kw["assigned_sa"] = dunia.user["SA"].id
    kw.update(o)
    proyek = bangun_project(dunia.user["Sales"].id, **kw)
    await simpan(db, proyek)
    return proyek


async def buat_dokumen(
    db: AsyncSession,
    proyek: Project,
    dunia: Dunia,
    *,
    doc_type: str = "PropTek",
    status: str = "Draft",
    **o: Any,
) -> Document:
    kw: dict[str, Any] = {"doc_type": doc_type, "status": status}
    kw.update(o)
    pembuat = kw.pop("created_by", dunia.user["SA"].id)
    dokumen = bangun_document(proyek.id_project, pembuat, **kw)
    await simpan(db, dokumen)
    return dokumen


async def muat(db: AsyncSession, model, **filter_: Any):
    """Baca ulang satu baris dari DB (abaikan identity map)."""
    obj = (await db.execute(select(model).filter_by(**filter_))).scalar_one()
    await db.refresh(obj)
    return obj


async def notifikasi(db: AsyncSession, **filter_: Any) -> list[NotificationLog]:
    hasil = (
        (
            await db.execute(
                select(NotificationLog).filter_by(**filter_).order_by(NotificationLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(hasil)
