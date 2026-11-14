"""
Agregasi workload Lead_SA (issue #127, spec §2.5).

Definisi (keputusan konservatif, lihat `app.core.status.STATUS_TIDAK_AKTIF`):
- Project aktif: tidak soft-deleted dan status bukan Closed, Lost, On Hold.
- Subtask aktif: status `open` atau `in_progress` pada project aktif.
- Jam terlog minggu ini: jumlah `ActivityLog.duration_hours` SA itu sejak Senin 00:00 UTC
  (konsisten dengan `/sa/utilization` yang mengelompokkan `created_at` dalam UTC).
- Project dengan banyak SA (SA utama + `ProjectAssignments`) dihitung untuk tiap SA, sekali per SA.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status as status_konst
from app.core.dependencies import PERAN_DAPAT_DITUGASKAN
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.subtask import Subtask
from app.models.user import User
from app.schemas.workload import BebanSA

STATUS_SUBTASK_AKTIF = ("open", "in_progress")


def _proyek_aktif():
    return (
        Project.deleted_at.is_(None),
        Project.status.notin_(status_konst.STATUS_TIDAK_AKTIF),
    )


def awal_minggu(sekarang: datetime) -> datetime:
    """Senin 00:00 pada zona waktu `sekarang` (UTC) untuk minggu kalender yang memuatnya."""
    hari = sekarang.replace(hour=0, minute=0, second=0, microsecond=0)
    return hari - timedelta(days=hari.weekday())


async def hitung_beban(db: AsyncSession, sekarang: datetime) -> list[BebanSA]:
    """Beban tiap SA dan Lead_SA, diurutkan menurut nama."""
    pengguna = (
        (
            await db.execute(
                select(User).where(User.role.in_(PERAN_DAPAT_DITUGASKAN)).order_by(User.name, User.id)
            )
        )
        .scalars()
        .all()
    )

    utama = await db.execute(
        select(Project.assigned_sa, Project.id_project).where(
            Project.assigned_sa.is_not(None), *_proyek_aktif()
        )
    )
    tambahan = await db.execute(
        select(ProjectAssignment.user_id, ProjectAssignment.id_project)
        .join(Project, Project.id_project == ProjectAssignment.id_project)
        .where(*_proyek_aktif())
    )
    proyek_per_user: dict = {}
    for user_id, id_project in (*utama.all(), *tambahan.all()):
        proyek_per_user.setdefault(user_id, set()).add(id_project)

    subtask = await db.execute(
        select(Subtask.assigned_sa, func.count())
        .join(Project, Project.id_project == Subtask.id_project)
        .where(
            Subtask.assigned_sa.is_not(None),
            Subtask.status.in_(STATUS_SUBTASK_AKTIF),
            *_proyek_aktif(),
        )
        .group_by(Subtask.assigned_sa)
    )
    subtask_per_user = dict(subtask.all())

    mulai = awal_minggu(sekarang)
    jam = await db.execute(
        select(ActivityLog.sa_id, func.coalesce(func.sum(ActivityLog.duration_hours), 0))
        .where(ActivityLog.created_at >= mulai, ActivityLog.created_at < mulai + timedelta(days=7))
        .group_by(ActivityLog.sa_id)
    )
    jam_per_user = dict(jam.all())

    return [
        BebanSA(
            user_id=u.id,
            name=u.name,
            email=u.email,
            role=str(u.role),
            project_aktif=len(proyek_per_user.get(u.id, ())),
            subtask_aktif=subtask_per_user.get(u.id, 0),
            jam_minggu_ini=float(jam_per_user.get(u.id, 0)),
        )
        for u in pengguna
    ]
