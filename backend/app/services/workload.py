"""
Agregasi workload Lead_SA (issue #127, spec §2.5).

Definisi (keputusan konservatif, lihat `app.core.status.STATUS_TIDAK_AKTIF`):
- Project aktif: tidak soft-deleted dan status bukan Closed, Lost, On Hold.
- Subtask aktif: status `open` atau `in_progress` pada project aktif.
- Jam terlog minggu ini: jumlah `ActivityLog.duration_hours` SA itu sejak Senin 00:00 UTC
  (konsisten dengan `/sa/utilization` yang mengelompokkan `created_at` dalam UTC).
- Jatuh tempo: subtask aktif ber-`due_date` dan project berstatus `STATUS_PANTAU_TARGET_SUBMIT`
  (`target_submit`) yang `due <= hari ini + HARI_PERINGATAN_DUE`; "hari ini" memakai tanggal UTC.
- Project dengan banyak SA (SA utama + `ProjectAssignments`) dihitung untuk tiap SA, sekali per SA.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status as status_konst
from app.core.dependencies import PERAN_DAPAT_DITUGASKAN
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.subtask import Subtask
from app.models.user import User
from app.schemas.workload import (
    BebanSA,
    JatuhTempoResponse,
    ProjectJatuhTempo,
    SubtaskJatuhTempo,
)

STATUS_SUBTASK_AKTIF = ("open", "in_progress")

# Subtask/project "mendekati due date" bila jatuh tempo dalam N hari ke depan (termasuk hari ini).
HARI_PERINGATAN_DUE = 3

# `target_submit` hanya relevan sampai proposal diserahkan: sesudah `Submitted` tidak lagi dipantau.
STATUS_PANTAU_TARGET_SUBMIT = (
    status_konst.INTAKE,
    status_konst.AWAITING_ASSIGNMENT,
    status_konst.ASSIGNED,
    status_konst.IN_PROGRESS,
)


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


async def hitung_jatuh_tempo(db: AsyncSession, hari_ini: date) -> JatuhTempoResponse:
    """Subtask dan project yang lewat atau mendekati due date, urut due date naik."""
    batas = hari_ini + timedelta(days=HARI_PERINGATAN_DUE)

    baris_subtask = await db.execute(
        select(Subtask, Project.project_name, User.name)
        .join(Project, Project.id_project == Subtask.id_project)
        .outerjoin(User, User.id == Subtask.assigned_sa)
        .where(
            Subtask.due_date.is_not(None),
            Subtask.due_date <= batas,
            Subtask.status.in_(STATUS_SUBTASK_AKTIF),
            *_proyek_aktif(),
        )
        .order_by(Subtask.due_date, Subtask.id_subtask)
    )
    subtask = [
        SubtaskJatuhTempo(
            id_subtask=st.id_subtask,
            id_project=st.id_project,
            project_name=nama_proyek,
            title=st.title,
            status=st.status,
            assigned_sa=st.assigned_sa,
            assigned_sa_name=nama_sa,
            due_date=st.due_date,
            hari_lagi=(st.due_date - hari_ini).days,
            terlambat=st.due_date < hari_ini,
        )
        for st, nama_proyek, nama_sa in baris_subtask.all()
    ]

    baris_project = await db.execute(
        select(Project)
        .where(
            Project.target_submit <= batas,
            Project.status.in_(STATUS_PANTAU_TARGET_SUBMIT),
            *_proyek_aktif(),
        )
        .order_by(Project.target_submit, Project.id_project)
    )
    project = [
        ProjectJatuhTempo(
            id_project=p.id_project,
            project_name=p.project_name,
            customer_name=p.customer_name,
            status=p.status,
            target_submit=p.target_submit,
            hari_lagi=(p.target_submit - hari_ini).days,
            terlambat=p.target_submit < hari_ini,
        )
        for p in baris_project.scalars().all()
    ]
    return JatuhTempoResponse(hari_peringatan=HARI_PERINGATAN_DUE, subtask=subtask, project=project)
