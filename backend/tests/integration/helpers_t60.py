"""
Helper test integrasi tiket B7 (#60): notifikasi, kalender, kolaborator, admin, activity log.

Berkas ini milik tiket #60 dan tidak menimpa conftest bersama. User/proyek dibuat langsung di
Postgres uji (rollback per test), token JWT dibuat dengan secret test sehingga alur
`get_current_user` produksi tetap dipakai.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectCollaborator, User
from tests._auth_support import buat_token
from tests.integration.model_helpers import (
    bangun_notifikasi,
    bangun_project,
    bangun_user,
    uid,
)

API = "/api/v1"


def bearer(user: User) -> dict[str, str]:
    """Header Authorization (access token asli) untuk `user`."""
    return {"Authorization": f"Bearer {buat_token(user.id)}"}


async def buat_user(db: AsyncSession, role: str = "SA", **o: Any) -> User:
    user = bangun_user(role=role, name=o.pop("name", f"{role} {uid()}"), **o)
    db.add(user)
    await db.commit()
    return user


async def buat_proyek(
    db: AsyncSession,
    sales: User,
    *,
    assigned_sa: User | None = None,
    status: str = "Assigned",
    **o: Any,
) -> Project:
    proyek = bangun_project(
        sales.id,
        assigned_sa=assigned_sa.id if assigned_sa else None,
        status=status,
        **o,
    )
    db.add(proyek)
    await db.commit()
    return proyek


async def buat_kolaborator(
    db: AsyncSession, proyek: Project, user: User, added_by: User, role: str = "viewer"
) -> ProjectCollaborator:
    kolab = ProjectCollaborator(
        id_project=proyek.id_project, user_id=user.id, role=role, added_by=added_by.id
    )
    db.add(kolab)
    await db.commit()
    return kolab


async def buat_notifikasi(
    db: AsyncSession,
    user: User,
    *,
    menit_lalu: int = 0,
    **o: Any,
):
    """Notifikasi dengan `created_at` terkendali (tanpa bergantung pada jam nyata)."""
    dasar = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    notif = bangun_notifikasi(user.id, created_at=dasar - timedelta(minutes=menit_lalu), **o)
    db.add(notif)
    await db.commit()
    return notif


def id_unik() -> str:
    return uuid.uuid4().hex[:8]
