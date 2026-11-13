"""
API penggantian orang pada project (issue #118, ADR 0014).

Hanya Lead_SA atau `is_admin` yang mengganti `product_pic`, `sales_pic`, dan `lead_sa`.
Setiap penggantian masuk audit log (nilai lama, nilai baru, pelaku).
"""

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import PeranUser, adalah_privileged, get_current_user
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.user import User
from app.schemas.response import success_response

router = APIRouter(tags=["Orang Project"])

# field -> (role user yang boleh dipilih, boleh dikosongkan)
_ATURAN_FIELD: dict[str, tuple[PeranUser, bool]] = {
    "product_pic": (PeranUser.PRODUCT, False),
    "sales_pic": (PeranUser.SALES, True),
    "lead_sa": (PeranUser.LEAD_SA, False),
}


def _id_audit() -> str:
    tanggal = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"AUDIT-{tanggal}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _ringkas(user: Optional[User]) -> Optional[dict]:
    if user is None:
        return None
    return {"id": str(user.id), "name": user.name, "email": user.email}


async def _validasi_user(
    db: AsyncSession, field: str, nilai: object, role: PeranUser, errors: list[dict]
) -> Optional[User]:
    """User pilihan harus ada dan berrole `role`; tambah error field bila tidak."""
    try:
        user_id = uuid.UUID(str(nilai))
    except (ValueError, TypeError):
        errors.append({"field": field, "reason": f"{field} harus berupa ID user yang valid."})
        return None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.role != role:
        errors.append(
            {"field": field, "reason": f"User yang dipilih untuk {field} harus berrole {role}."}
        )
        return None
    return user


async def tentukan_lead_sa(
    db: AsyncSession, lead_sa_id: Optional[uuid.UUID], pengassign: User
) -> uuid.UUID:
    """`lead_sa` saat assign: yang dipilih (harus berrole Lead_SA), atau pengassign sendiri."""
    if lead_sa_id is None:
        return pengassign.id
    lead = (await db.execute(select(User).where(User.id == lead_sa_id))).scalar_one_or_none()
    if lead is None or lead.role != PeranUser.LEAD_SA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead SA yang dipilih harus user berrole Lead_SA.",
        )
    return lead.id


@router.patch(
    "/projects/{project_id}/people",
    summary="Ganti Product PIC, Sales PIC, atau Lead SA project",
    description=(
        "Hanya Lead_SA atau Admin. Hanya field yang ada di body yang diproses. `product_pic` "
        "dan `lead_sa` tidak boleh dikosongkan; `sales_pic` boleh `null`. Perubahan dicatat di "
        "audit log."
    ),
)
async def ganti_orang(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat mengganti orang project.",
        )

    project = (
        await db.execute(select(Project).where(Project.id_project == project_id))
    ).scalar_one_or_none()
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body harus berupa objek JSON.")

    errors: list[dict] = []
    baru: dict[str, Optional[uuid.UUID]] = {}
    for field, (role, boleh_kosong) in _ATURAN_FIELD.items():
        if field not in body:
            continue
        if body[field] is None:
            if boleh_kosong:
                baru[field] = None
            else:
                errors.append({"field": field, "reason": f"{field} tidak boleh dikosongkan."})
            continue
        user = await _validasi_user(db, field, body[field], role, errors)
        if user is not None:
            baru[field] = user.id
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    lama = {f: getattr(project, f) for f in baru if getattr(project, f) != baru[f]}
    if lama:
        now = datetime.now(timezone.utc)
        for field in lama:
            setattr(project, field, baru[field])
        project.updated_at = now
        db.add(
            AuditLog(
                id=_id_audit(),
                entity_type="project",
                entity_id=project_id,
                action="people_change",
                performed_by=current_user.id,
                old_value={f: str(v) if v else None for f, v in lama.items()},
                new_value={f: str(baru[f]) if baru[f] else None for f in lama},
                created_at=now,
            )
        )
        await db.commit()

    ids = {project.product_pic, project.sales_pic, project.lead_sa} - {None}
    orang = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()
    }
    return success_response(
        data={
            "id_project": project_id,
            "product_pic": _ringkas(orang.get(project.product_pic)),
            "sales_pic": _ringkas(orang.get(project.sales_pic)),
            "lead_sa": _ringkas(orang.get(project.lead_sa)),
        },
        message="Orang project diperbarui." if lama else "Tidak ada perubahan.",
    )
