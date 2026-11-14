"""
Helper bersama test constraint model (tiket B10). Membangun objek ORM valid minimal dan
menegaskan bahwa Postgres (bukan Python) menolak/menerima baris.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityLog,
    AuditLog,
    Document,
    NotificationLog,
    Project,
    ProjectCollaborator,
    SLATracking,
    SourceDocument,
    Subtask,
    User,
)


def uid() -> str:
    return uuid.uuid4().hex[:12]


def bangun_user(**o: Any) -> User:
    if o.get("role") == "Admin":  # persona admin = SA dengan flag admin (ADR 0012)
        o = {**o, "role": "SA", "is_admin": True}
    n = uid()
    d = {
        "id": uuid.uuid4(),
        "email": f"{n}@portal-sa.local",
        "name": "U",
        "role": "SA",
        "google_id": f"g-{n}",
    }
    d.update(o)
    return User(**d)


def bangun_project(sales_pic: uuid.UUID | None, **o: Any) -> Project:
    """Proyek valid minimal. Bila tidak ditentukan, `product_pic` dan `created_by` memakai
    `sales_pic` (user yang sama), sehingga test lama tetap punya orang yang valid."""
    d = {
        "id_project": f"PRJ-{uid()}",
        "project_name": "Proyek",
        "customer_name": "Cust",
        "sales_pic": sales_pic,
        "target_submit": date(2030, 1, 1),
    }
    d.update(o)
    d.setdefault("product_pic", d["sales_pic"])
    d.setdefault("created_by", d["product_pic"])
    # Setelah Intake, `qualification_state` selalu `Qualified` (ADR 0013).
    if d.get("status", "Intake") != "Intake":
        d.setdefault("qualification_state", "Qualified")
    if d.get("status") == "Lost":
        d.setdefault("lost_reason", "Alasan uji")
    return Project(**d)


def bangun_document(id_project: str, created_by: uuid.UUID | None, **o: Any) -> Document:
    d = {
        "id_doc": f"DOC-{uid()}",
        "id_project": id_project,
        "doc_type": "BOQ",
        "folder_type": "Solutions",
        "gdrive_link": "https://drive.example/x",
        "created_by": created_by,
    }
    d.update(o)
    return Document(**d)


def bangun_log(sa_id: uuid.UUID, id_project: str | None, **o: Any) -> ActivityLog:
    d = {
        "id_log": f"LOG-{uid()}",
        "sa_id": sa_id,
        "work_type": "Project",
        "id_project": id_project,
        "project_phase": "Implementation",
        "subtask_category": "Assessment",
        "duration_hours": Decimal("1.00"),
        "raw_notes": "catatan",
    }
    d.update(o)
    return ActivityLog(**d)


def bangun_notifikasi(user_id: uuid.UUID, **o: Any) -> NotificationLog:
    d = {
        "id": f"NTF-{uid()}",
        "event_type": "assignment",
        "recipient_user_id": user_id,
        "channel": "in-app",
    }
    d.update(o)
    return NotificationLog(**d)


def bangun_subtask(id_project: str, **o: Any) -> Subtask:
    d = {"id_subtask": f"ST-{uid()}", "id_project": id_project, "title": f"Judul {uid()}"}
    d.update(o)
    return Subtask(**d)


def bangun_sla(project_id: str, **o: Any) -> SLATracking:
    from datetime import datetime, timezone

    d = {
        "id": f"SLA-{uid()}",
        "project_id": project_id,
        "started_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    d.update(o)
    return SLATracking(**d)


def bangun_source_doc(id_project: str, **o: Any) -> SourceDocument:
    d = {"id_project": id_project, "filename": "mom.pdf", "doc_type": "MoM", "size_bytes": 10}
    d.update(o)
    return SourceDocument(**d)


def bangun_audit(performed_by: uuid.UUID, **o: Any) -> AuditLog:
    d = {
        "id": f"AUD-{uid()}",
        "entity_type": "project",
        "entity_id": "PRJ-1",
        "action": "create",
        "performed_by": performed_by,
        "new_value": {"a": 1},
    }
    d.update(o)
    return AuditLog(**d)


def bangun_kolaborator(
    id_project: str, user_id: uuid.UUID, added_by: uuid.UUID, **o: Any
) -> ProjectCollaborator:
    d = {"id_project": id_project, "user_id": user_id, "added_by": added_by}
    d.update(o)
    return ProjectCollaborator(**d)


async def simpan(db: AsyncSession, *objek: Any) -> None:
    """Tambahkan dan flush: Postgres memvalidasi di sini."""
    db.add_all(objek)
    await db.flush()


async def ditolak(db: AsyncSession, nama: str, *objek: Any) -> None:
    """`objek` harus ditolak Postgres oleh constraint/index `nama`; sesi tetap bisa dipakai lagi."""
    with pytest.raises(IntegrityError) as err:
        async with db.begin_nested():
            db.add_all(objek)
            await db.flush()
    assert nama in str(err.value), str(err.value)
    # Objek yang gagal tidak boleh tersisa di sesi (savepoint di-rollback).
    for o in objek:
        db.expunge(o) if o in db else None


async def siapkan_proyek(db: AsyncSession) -> tuple[User, Project]:
    user = bangun_user(role="Sales")
    await simpan(db, user)
    proyek = bangun_project(user.id)
    await simpan(db, proyek)
    return user, proyek
