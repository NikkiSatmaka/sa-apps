"""
API endpoints untuk assignment SA ke proyek oleh Lead_SA.
Menangani penugasan SA, daftar proyek pending, dan ketersediaan SA.
"""

import logging
import random
import string
import uuid
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orang import tentukan_lead_sa
from app.core.database import get_db
from app.core.dependencies import (
    PERAN_DAPAT_DITUGASKAN,
    PeranUser,
    adalah_privileged,
    get_current_user,
)
from app.models.activity_log import ActivityLog
from app.models.notification_log import NotificationLog
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.subtask import Subtask
from app.models.user import User
from app.schemas.assignment import (
    AssignmentResponse,
    AssignRequest,
    ProjectBrief,
    SAAvailability,
)
from app.schemas.response import success_response
from app.services.folder_provisioner import (
    FolderProvisioningError,
    folder_provisioner,
)
from app.services.sla_timer import sla_timer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Assignment"])

# Checklist default yang di-seed otomatis saat proyek di-assign ke SA.
DEFAULT_SUBTASK_TEMPLATE = ["Requirement", "BoQ", "PropTek", "HLD"]


def _generate_subtask_id() -> str:
    """Generate ID subtask unik dengan format SUB-{YYYYMMDD}-{random 6 chars}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"SUB-{date_part}-{random_part}"


async def _seed_default_subtasks(db: AsyncSession, project_id: str, assigned_sa: uuid.UUID) -> None:
    """
    Seed checklist subtask default untuk proyek bila belum ada subtask apa pun.

    Subtask hasil seeding langsung ditugaskan ke SA proyek (`assigned_sa`), sehingga
    begitu SA membuka proyek, to-do list miliknya sudah terisi tanpa Lead SA perlu
    mendistribusikan tiap item. Lead SA tetap bisa memindah sebagian ke SA lain lewat
    endpoint assign subtask.

    Idempoten: jika proyek sudah punya minimal satu subtask (mis. re-assign),
    seeding dilewati sehingga tidak terjadi duplikasi.
    """
    count_result = await db.execute(
        select(func.count()).select_from(Subtask).where(Subtask.id_project == project_id)
    )
    existing = count_result.scalar() or 0
    if existing > 0:
        return

    for title in DEFAULT_SUBTASK_TEMPLATE:
        db.add(
            Subtask(
                id_subtask=_generate_subtask_id(),
                id_project=project_id,
                title=title,
                status="open",
                assigned_sa=assigned_sa,
            )
        )


def _generate_notification_id() -> str:
    """Generate ID notifikasi unik dengan format NOTIF-{timestamp}-{random}."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"NOTIF-{ts}-{random_part}"


def _require_lead_sa(current_user: User) -> None:
    """Validasi bahwa user saat ini Lead_SA atau admin (`is_admin`)."""
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat melakukan operasi ini.",
        )


async def _trigger_folder_provisioner(
    project_id: str,
    sa_email: str,
    lead_sa_email: str,
    sales_email: str,
) -> None:
    """
    Background task: trigger Folder_Provisioner setelah assignment.
    Membuat folder proyek di Google Drive secara async lalu mem-persist
    id folder (master + Solutions) dan status provisioning ke proyek.

    Membuka session baru via AsyncSessionLocal() karena request session sudah
    ditutup saat background task berjalan (pola projects.py::_trigger_scoring_engine).

    Alur status (ADR 0005):
    - set folder_provisioning_status='pending' sebelum memanggil provisioner;
    - sukses  -> persist gdrive_folder_id + gdrive_solutions_folder_id,
                 status='provisioned';
    - gagal (FolderProvisioningError setelah retry internal) -> status='failed'.

    Side-effect ini graceful: error tidak di-re-raise keluar dari task.

    Args:
        project_id: ID proyek yang baru di-assign.
        sa_email: Email SA yang ditugaskan.
        lead_sa_email: Email Lead_SA yang melakukan assignment.
        sales_email: Email Sales PIC proyek.
    """
    from app.core.database import AsyncSessionLocal

    logger.info(
        f"[FolderProvisioner] Trigger provisioning untuk proyek {project_id} "
        f"(SA: {sa_email}, Lead: {lead_sa_email})"
    )
    try:
        async with AsyncSessionLocal() as db:
            # Muat proyek dari session baru
            project_result = await db.execute(
                select(Project).where(Project.id_project == project_id)
            )
            project = project_result.scalar_one_or_none()

            if project is None:
                logger.error(
                    f"[FolderProvisioner] Proyek {project_id} tidak ditemukan, skip provisioning."
                )
                return

            # Tandai pending sebelum memanggil provisioner
            project.folder_provisioning_status = "pending"
            await db.commit()

            try:
                result = await folder_provisioner.provision_project_folder(
                    project,
                    sa_email,
                    lead_sa_email,
                    sales_email,
                )
            except FolderProvisioningError as e:
                project.folder_provisioning_status = "failed"
                await db.commit()
                logger.error(
                    f"[FolderProvisioner] Gagal provision folder proyek "
                    f"{project_id} setelah retry: {e}"
                )
                return

            # Sukses — persist kedua id folder + status provisioned
            project.gdrive_folder_id = result.master
            project.gdrive_solutions_folder_id = result.solutions
            project.folder_provisioning_status = "provisioned"
            await db.commit()

            logger.info(
                f"[FolderProvisioner] Folder proyek {project_id} berhasil "
                f"di-provision (master={result.master}, solutions={result.solutions})."
            )
    except Exception as e:  # noqa: BLE001 - background task tidak boleh meledak keluar
        logger.error(
            f"[FolderProvisioner] Error tidak terduga saat provisioning proyek {project_id}: {e}"
        )


async def _pindahkan_akses_drive_sa(
    master_folder_id: str, sa_lama_email: Optional[str], sa_baru_email: str
) -> None:
    """
    Background task: pindahkan akses Editor folder master dari SA lama ke SA baru (reassign, #77).

    Tidak memakai database, sehingga tidak butuh sesi sendiri. Graceful: kegagalan Drive (setelah
    retry internal) hanya dicatat; reassign di portal sudah tersimpan dan akses dapat dirapikan
    manual atau lewat provisioning ulang.
    """
    try:
        await folder_provisioner.reassign_sa_access(
            master_folder_id, sa_lama_email, sa_baru_email
        )
    except Exception as e:  # noqa: BLE001 - background task tidak boleh meledak keluar
        logger.error(
            f"[FolderProvisioner] Gagal memindahkan akses SA pada folder {master_folder_id} "
            f"({sa_lama_email or '-'} -> {sa_baru_email}): {e}"
        )


@router.get(
    "/projects/pending-assignment",
    summary="Daftar proyek yang menunggu assignment",
    description=(
        "Menampilkan proyek-proyek berstatus 'Pending Assignment' "
        "yang siap ditugaskan ke SA. Hanya untuk Lead_SA."
    ),
)
async def get_pending_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar proyek yang berstatus 'Pending Assignment'.
    Hanya Lead_SA yang bisa mengakses endpoint ini.
    """
    _require_lead_sa(current_user)

    # Query proyek dengan status "Pending Assignment"
    result = await db.execute(
        select(Project)
        .where(Project.status == "Pending Assignment")
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    # Format response
    projects_data = [
        ProjectBrief(
            id_project=p.id_project,
            project_name=p.project_name,
            customer_name=p.customer_name,
            status=p.status,
            bant_score=p.bant_score,
            use_case_tags=p.use_case_tags,
            assigned_sa=p.assigned_sa,
            assigned_at=p.assigned_at,
            target_submit=p.target_submit,
            gdrive_folder_id=p.gdrive_folder_id,
            folder_provisioning_status=p.folder_provisioning_status,
        ).model_dump(mode="json")
        for p in projects
    ]

    return success_response(
        data=projects_data,
        message=f"Ditemukan {len(projects_data)} proyek menunggu assignment.",
    )


@router.get(
    "/sa/available",
    summary="Daftar SA yang tersedia dengan workload",
    description=(
        "Menampilkan semua SA yang terdaftar di sistem beserta "
        "jumlah proyek aktif masing-masing. Hanya untuk Lead_SA."
    ),
)
async def get_available_sa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar SA beserta jumlah proyek aktif (status bukan terminal).
    Hanya Lead_SA yang bisa mengakses endpoint ini.
    """
    _require_lead_sa(current_user)

    # Status terminal — proyek yang sudah selesai/tidak aktif
    terminal_statuses = ("Closed-Win", "Handover Complete", "Lost")

    # Query semua kandidat SA: user berrole SA atau Lead_SA (ADR 0012)
    sa_result = await db.execute(select(User).where(User.role.in_(PERAN_DAPAT_DITUGASKAN)).order_by(User.name))
    sa_users = sa_result.scalars().all()

    # Hitung jumlah proyek aktif per SA menggunakan subquery
    active_count_subquery = (
        select(
            Project.assigned_sa,
            func.count(Project.id_project).label("active_count"),
        )
        .where(Project.status.notin_(terminal_statuses))
        .where(Project.assigned_sa.isnot(None))
        .group_by(Project.assigned_sa)
    )
    active_count_result = await db.execute(active_count_subquery)
    active_counts = {row[0]: row[1] for row in active_count_result.all()}

    # Format response
    sa_data = [
        SAAvailability(
            id=sa.id,
            name=sa.name,
            email=sa.email,
            role=str(sa.role),
            active_project_count=active_counts.get(sa.id, 0),
        ).model_dump(mode="json")
        for sa in sa_users
    ]

    return success_response(
        data=sa_data,
        message=f"Ditemukan {len(sa_data)} SA tersedia.",
    )


@router.get(
    "/sa/utilization",
    summary="Utilisasi SA per bulan",
    description=(
        "Menampilkan total jam kerja (dari activity logs) per SA per bulan. "
        "Mendukung filter per tahun dan per individu SA. Hanya untuk Lead_SA."
    ),
)
async def get_sa_utilization(
    year: int | None = None,
    sa_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil data utilisasi SA per bulan berdasarkan activity logs.

    Mengembalikan:
    - Total jam per SA per bulan (berdasarkan created_at di ActivityLog)
    - Jika year tidak diisi, default tahun berjalan
    - Jika sa_id diisi, filter untuk SA tertentu saja

    Response format:
    {
      "year": 2026,
      "monthly_data": [
        {
          "sa_id": "...",
          "sa_name": "...",
          "months": {
            "1": 40.5, "2": 35.0, ... "12": 0
          },
          "total_hours": 320.5
        }
      ],
      "summary": {
        "months": {"1": 80.5, "2": 70.0, ...},
        "total_hours": 640.5,
        "sa_count": 3
      }
    }
    """
    _require_lead_sa(current_user)

    from datetime import date as date_type
    from datetime import datetime as dt_type

    try:
        # Default tahun berjalan
        target_year = year or date_type.today().year

        # Query semua SA & Lead_SA (keduanya mencatat aktivitas), atau filter per sa_id
        sa_query = select(User).where(User.role.in_(["SA", "Lead_SA"])).order_by(User.name)
        if sa_id:
            try:
                sa_uuid = uuid.UUID(sa_id)
                sa_query = sa_query.where(User.id == sa_uuid)
            except ValueError:
                pass

        sa_result = await db.execute(sa_query)
        sa_users = sa_result.scalars().all()

        # Fetch activity logs lalu group di Python
        year_start = dt_type(target_year, 1, 1, tzinfo=timezone.utc)
        year_end = dt_type(target_year + 1, 1, 1, tzinfo=timezone.utc)

        log_query = (
            select(ActivityLog)
            .where(ActivityLog.created_at >= year_start)
            .where(ActivityLog.created_at < year_end)
        )
        if sa_id:
            try:
                sa_uuid = uuid.UUID(sa_id)
                log_query = log_query.where(ActivityLog.sa_id == sa_uuid)
            except ValueError:
                pass

        log_result = await db.execute(log_query)
        logs = log_result.scalars().all()

        # Group by SA + bulan di Python
        sa_monthly: dict[uuid.UUID, dict[int, float]] = {}
        for log in logs:
            sid = log.sa_id
            month = log.created_at.month
            hours = float(log.duration_hours)
            if sid not in sa_monthly:
                sa_monthly[sid] = {}
            sa_monthly[sid][month] = sa_monthly[sid].get(month, 0.0) + hours

        # Format response per SA
        monthly_data = []
        summary_months: dict[int, float] = {m: 0.0 for m in range(1, 13)}

        for sa in sa_users:
            months_data = sa_monthly.get(sa.id, {})
            sa_months = {str(m): round(months_data.get(m, 0.0), 2) for m in range(1, 13)}
            sa_total = sum(months_data.values())

            monthly_data.append(
                {
                    "sa_id": str(sa.id),
                    "sa_name": sa.name,
                    "months": sa_months,
                    "total_hours": round(sa_total, 2),
                }
            )

            for m in range(1, 13):
                summary_months[m] += months_data.get(m, 0.0)

        summary = {
            "months": {str(m): round(v, 2) for m, v in summary_months.items()},
            "total_hours": round(sum(summary_months.values()), 2),
            "sa_count": len(sa_users),
        }

        return success_response(
            data={"year": target_year, "monthly_data": monthly_data, "summary": summary},
            message=f"Data utilisasi SA untuk tahun {target_year}.",
        )

    except Exception as e:
        logger.error(f"Error di /sa/utilization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get(
    "/utilization/projects",
    summary="Utilisasi per proyek",
    description=(
        "Menampilkan total jam kerja per proyek beserta personel SA. "
        "Berguna untuk melihat effort distribution antar proyek. Hanya untuk Lead_SA."
    ),
)
async def get_project_utilization(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil data utilisasi per proyek:
    - Total jam kerja yang sudah di-log per proyek
    - Siapa saja SA yang mengerjakan (dari activity logs)
    - Status proyek saat ini

    Response:
    [
      {
        "id_project": "PRJ-001",
        "project_name": "...",
        "customer_name": "...",
        "status": "Assigned",
        "total_hours": 16.5,
        "sa_personnel": [{"sa_id": "...", "sa_name": "...", "hours": 10.0}, ...]
      }
    ]
    """
    _require_lead_sa(current_user)

    # Query: total jam per proyek
    # Subquery: jam per SA per proyek
    sa_hours_query = select(
        ActivityLog.id_project,
        ActivityLog.sa_id,
        func.sum(ActivityLog.duration_hours).label("hours"),
    ).group_by(ActivityLog.id_project, ActivityLog.sa_id)
    sa_hours_result = await db.execute(sa_hours_query)
    sa_hours_rows = sa_hours_result.all()

    # Build lookup: {project_id: [{sa_id, hours}, ...]}
    project_sa_map: dict[str, list[dict]] = {}
    for row in sa_hours_rows:
        pid = row[0]
        if pid not in project_sa_map:
            project_sa_map[pid] = []
        project_sa_map[pid].append({"sa_id": row[1], "hours": float(row[2])})

    # Query semua proyek yang punya activity logs
    project_ids = list(project_sa_map.keys())
    if not project_ids:
        return success_response(data=[], message="Belum ada data activity log.")

    projects_result = await db.execute(select(Project).where(Project.id_project.in_(project_ids)))
    projects = {p.id_project: p for p in projects_result.scalars().all()}

    # Query semua SA users untuk nama
    all_sa_ids = set()
    for entries in project_sa_map.values():
        for entry in entries:
            all_sa_ids.add(entry["sa_id"])

    sa_users_result = await db.execute(select(User).where(User.id.in_(list(all_sa_ids))))
    sa_name_map = {u.id: u.name for u in sa_users_result.scalars().all()}

    # Build response
    result_data = []
    for pid, sa_entries in project_sa_map.items():
        project = projects.get(pid)
        if not project:
            continue

        total_hours = sum(e["hours"] for e in sa_entries)
        personnel = [
            {
                "sa_id": str(e["sa_id"]),
                "sa_name": sa_name_map.get(e["sa_id"], "Unknown"),
                "hours": round(e["hours"], 2),
            }
            for e in sa_entries
        ]
        # Sort personnel by hours descending
        personnel.sort(key=lambda x: x["hours"], reverse=True)

        result_data.append(
            {
                "id_project": pid,
                "project_name": project.project_name,
                "customer_name": project.customer_name,
                "status": project.status,
                "total_hours": round(total_hours, 2),
                "sa_personnel": personnel,
            }
        )

    # Sort by total_hours descending
    result_data.sort(key=lambda x: x["total_hours"], reverse=True)

    return success_response(
        data=result_data,
        message=f"Data utilisasi untuk {len(result_data)} proyek.",
    )


@router.get(
    "/utilization/summary",
    summary="Ringkasan utilisasi per work_type & fase proyek",
    description=(
        "Agregasi jam kerja (activity logs) per bulan: Project vs Non-Project, "
        "serta breakdown fase proyek (Pre/Implementation/Post). Hanya untuk Lead_SA. "
        "Mencakup aktivitas SA dan Lead_SA."
    ),
)
async def get_utilization_summary(
    year: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ringkasan utilisasi dua dimensi untuk dashboard Lead SA.

    Response:
    {
      "year": 2026,
      "work_type": {
        "months": {"1": {"Project": 10.0, "Non-Project": 2.0}, ...},
        "totals": {"Project": 120.0, "Non-Project": 24.0},
        "grand_total": 144.0
      },
      "project_phase": {
        "totals": {"Pre-Implementation": 100.0, "Implementation": 15.0, "Post-Implementation": 5.0},
        "total": 120.0
      }
    }
    """
    _require_lead_sa(current_user)

    from datetime import date as date_type
    from datetime import datetime as dt_type

    target_year = year or date_type.today().year
    year_start = dt_type(target_year, 1, 1, tzinfo=timezone.utc)
    year_end = dt_type(target_year + 1, 1, 1, tzinfo=timezone.utc)

    log_result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.created_at >= year_start)
        .where(ActivityLog.created_at < year_end)
    )
    logs = log_result.scalars().all()

    # Dimensi 1: work_type per bulan
    months_wt: dict[int, dict[str, float]] = {
        m: {"Project": 0.0, "Non-Project": 0.0} for m in range(1, 13)
    }
    totals_wt: dict[str, float] = {"Project": 0.0, "Non-Project": 0.0}

    # Dimensi 2: project_phase (hanya Project)
    phase_totals: dict[str, float] = {
        "Pre-Implementation": 0.0,
        "Implementation": 0.0,
        "Post-Implementation": 0.0,
    }

    for log in logs:
        hours = float(log.duration_hours)
        wt = log.work_type if log.work_type in ("Project", "Non-Project") else "Project"
        month = log.created_at.month

        months_wt[month][wt] += hours
        totals_wt[wt] += hours

        if wt == "Project" and log.project_phase in phase_totals:
            phase_totals[log.project_phase] += hours

    work_type_data = {
        "months": {str(m): {k: round(v, 2) for k, v in months_wt[m].items()} for m in range(1, 13)},
        "totals": {k: round(v, 2) for k, v in totals_wt.items()},
        "grand_total": round(sum(totals_wt.values()), 2),
    }
    project_phase_data = {
        "totals": {k: round(v, 2) for k, v in phase_totals.items()},
        "total": round(sum(phase_totals.values()), 2),
    }

    return success_response(
        data={
            "year": target_year,
            "work_type": work_type_data,
            "project_phase": project_phase_data,
        },
        message=f"Ringkasan utilisasi tahun {target_year}.",
    )


@router.post(
    "/projects/{project_id}/assign",
    summary="Assign SA ke proyek",
    description=(
        "Menugaskan SA ke proyek yang berstatus 'Pending Assignment'. "
        "Update status menjadi 'Assigned', kirim notifikasi ke SA, "
        "dan trigger folder provisioning. Hanya untuk Lead_SA."
    ),
)
async def assign_sa_to_project(
    project_id: str,
    body: AssignRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Assign SA ke proyek tertentu.

    Flow:
    1. Validasi role Lead_SA
    2. Validasi proyek ada dan berstatus "Pending Assignment"
    3. Validasi SA ada dan role-nya "SA"
    4. Update proyek: status="Assigned", assigned_sa, assigned_at
    5. Insert notifikasi ke SA yang ditugaskan
    6. Trigger Folder_Provisioner async
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada dan berstatus "Pending Assignment" ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    if project.status != "Pending Assignment":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Proyek tidak bisa di-assign karena statusnya '{project.status}'. "
                f"Hanya proyek berstatus 'Pending Assignment' yang bisa di-assign."
            ),
        )

    # === 2. Validasi SA ada dan role-nya SA ===
    sa_result = await db.execute(select(User).where(User.id == body.sa_id))
    sa_user = sa_result.scalar_one_or_none()

    if sa_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SA dengan ID '{body.sa_id}' tidak ditemukan.",
        )

    if sa_user.role not in PERAN_DAPAT_DITUGASKAN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"User '{sa_user.name}' memiliki role '{sa_user.role}', "
                f"bukan 'SA' atau 'Lead_SA'. Hanya user dengan role SA atau Lead_SA "
                f"yang bisa ditugaskan."
            ),
        )

    # === 2a. Tentukan Lead_SA proyek (wajib sejak Assigned; ADR 0014) ===
    lead_sa_id = await tentukan_lead_sa(db, body.lead_sa_id, current_user)

    # === 2b. Lookup email Sales (requester) untuk provisioning folder ===
    sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
    sales_user = sales_result.scalar_one_or_none()
    sales_email = sales_user.email if sales_user else None

    # === 3. Update proyek ===
    now = datetime.now(timezone.utc)
    project.status = "Assigned"
    project.assigned_sa = body.sa_id
    project.lead_sa = lead_sa_id
    project.assigned_at = now
    project.updated_at = now
    # Tandai provisioning akan berjalan (background task men-set 'provisioned'/'failed')
    project.folder_provisioning_status = "pending"

    # === 4. Insert notifikasi ke SA ===
    notification = NotificationLog(
        id=_generate_notification_id(),
        event_type="assignment",
        recipient_user_id=body.sa_id,
        channel="in-app",
        status="sent",
        reference_id=project_id,
        notification_metadata={
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "bant_score": project.bant_score,
            "use_case_tags": project.use_case_tags or [],
            "assigned_by": current_user.name,
        },
        created_at=now,
    )
    db.add(notification)

    # === Auto-seed checklist subtask default (idempoten) ===
    # Subtask default langsung ditugaskan ke SA proyek yang baru di-assign.
    await _seed_default_subtasks(db, project_id, project.assigned_sa)

    # Commit perubahan
    await db.commit()
    await db.refresh(project)

    logger.info(f"Proyek {project_id} di-assign ke SA {sa_user.email} oleh {current_user.email}")

    # === 5. Start SLA timer (Flow 2 DQ Number) ===
    # Buat row SLATracking agar GET /projects/{id}/sla-status aktif sejak H+0.
    # Service start_timer idempoten: skip bila tracker sudah ada (mis. re-assign),
    # jadi tidak akan membuat duplikat atau error pada assignment ulang.
    try:
        await sla_timer.start_timer(
            project_id=project_id,
            assigned_at=project.assigned_at,
            db=db,
        )
    except Exception as e:
        logger.warning(f"Gagal memulai SLA timer untuk proyek {project_id}: {e}")

    # === 6. Trigger Folder_Provisioner async ===
    # Hanya dijadwalkan bila email Sales ditemukan (provisioner butuh email Sales
    # untuk permission Viewer pada Inventory). folder_scheduled mencerminkan apakah
    # task benar-benar dijadwalkan (bukan hardcode True).
    folder_scheduled = False
    if sales_email is not None:
        background_tasks.add_task(
            _trigger_folder_provisioner,
            project_id,
            sa_user.email,
            current_user.email,
            sales_email,
        )
        folder_scheduled = True
    else:
        logger.warning(
            f"Email Sales (sales_pic={project.sales_pic}) tidak ditemukan untuk "
            f"proyek {project_id}; folder provisioning tidak dijadwalkan."
        )

    # === 7. Build response ===
    response_data = AssignmentResponse(
        project=ProjectBrief(
            id_project=project.id_project,
            project_name=project.project_name,
            customer_name=project.customer_name,
            status=project.status,
            bant_score=project.bant_score,
            use_case_tags=project.use_case_tags,
            assigned_sa=project.assigned_sa,
            assigned_at=project.assigned_at,
            target_submit=project.target_submit,
            gdrive_folder_id=project.gdrive_folder_id,
            folder_provisioning_status=project.folder_provisioning_status,
        ),
        assigned_sa_name=sa_user.name,
        notification_sent=True,
        folder_provisioning_triggered=folder_scheduled,
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message=f"Proyek '{project.project_name}' berhasil ditugaskan ke {sa_user.name}.",
    )


@router.post(
    "/projects/{project_id}/reassign",
    summary="Reassign SA ke proyek",
    description=(
        "Mengubah SA yang ditugaskan pada proyek yang sudah berstatus 'Assigned' atau 'Ready'. "
        "Hanya Lead_SA dan Admin yang dapat melakukan reassignment."
    ),
)
async def reassign_sa_to_project(
    project_id: str,
    body: AssignRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reassign SA ke proyek yang sudah memiliki SA sebelumnya.

    Flow:
    1. Validasi role Lead_SA atau Admin
    2. Validasi proyek ada dan berstatus 'Assigned', 'Ready', atau 'Pending Assignment'
    3. Validasi SA baru ada dan role-nya 'SA'
    4. Update proyek: assigned_sa ke SA baru
    5. Insert notifikasi ke SA baru
    6. Drive: SA baru diberi akses Editor, SA lama dicabut (bila folder sudah ada)
    7. Dari 'Pending Assignment': mulai timer SLA + provisioning folder (setara assign)

    Timer SLA yang sudah berjalan TIDAK direset (keputusan 2026-11-10) dan subtask tidak
    dipindahkan dari SA lama.
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    if project.status not in ("Assigned", "Ready", "Pending Assignment"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Proyek tidak bisa di-reassign karena statusnya '{project.status}'. "
                f"Hanya proyek berstatus 'Assigned', 'Ready', atau 'Pending Assignment' "
                f"yang bisa di-reassign."
            ),
        )

    # === 2. Validasi SA baru ada dan role-nya SA ===
    sa_result = await db.execute(select(User).where(User.id == body.sa_id))
    sa_user = sa_result.scalar_one_or_none()

    if sa_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SA dengan ID '{body.sa_id}' tidak ditemukan.",
        )

    if sa_user.role not in PERAN_DAPAT_DITUGASKAN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"User '{sa_user.name}' memiliki role '{sa_user.role}', "
                f"bukan 'SA' atau 'Lead_SA'. Hanya user dengan role SA atau Lead_SA "
                f"yang bisa ditugaskan."
            ),
        )

    # `lead_sa` wajib sejak Assigned (ADR 0014): isi bila kosong; yang sudah ada tidak ditimpa
    # (penggantian lewat PATCH /projects/{id}/people). Admin non-Lead_SA wajib memilih pada alur
    # assign awal (dari Pending Assignment); pada proyek lama yang sudah Assigned/Ready tanpa
    # lead_sa, reassign tetap diizinkan dan admin tidak diam-diam menjadi lead_sa.
    if project.lead_sa is None and (
        body.lead_sa_id is not None
        or project.status == "Pending Assignment"
        or current_user.role == PeranUser.LEAD_SA
    ):
        project.lead_sa = await tentukan_lead_sa(db, body.lead_sa_id, current_user)

    # === 3. Update proyek ===
    now = datetime.now(timezone.utc)
    old_sa_id = project.assigned_sa
    dari_pending = project.status == "Pending Assignment"
    project.assigned_sa = body.sa_id
    project.assigned_at = now
    project.updated_at = now
    # SA utama tidak diulang di SA tambahan (ADR 0014): bila SA baru sebelumnya SA tambahan,
    # ia naik menjadi utama dan keluar dari `project_assignments`.
    await db.execute(
        delete(ProjectAssignment).where(
            ProjectAssignment.id_project == project_id, ProjectAssignment.user_id == body.sa_id
        )
    )

    # Email SA lama (untuk mencabut akses Drive). FK `projects.assigned_sa` menjamin user ada.
    sa_lama_email: Optional[str] = None
    if old_sa_id is not None and old_sa_id != body.sa_id:
        sa_lama_email = (
            await db.execute(select(User.email).where(User.id == old_sa_id))
        ).scalar_one()

    # Jika status masih Pending Assignment, ubah ke Assigned (setara assign: tandai provisioning)
    sales_email: Optional[str] = None
    if dari_pending:
        project.status = "Assigned"
        # `sales_pic` opsional (ADR 0014): tanpa Sales, email kosong (sama seperti assign).
        if project.sales_pic is not None:
            sales_email = (
                await db.execute(select(User.email).where(User.id == project.sales_pic))
            ).scalar_one_or_none()
        project.folder_provisioning_status = "pending"

    # === 4. Insert notifikasi ke SA baru ===
    notification = NotificationLog(
        id=_generate_notification_id(),
        event_type="assignment",
        recipient_user_id=body.sa_id,
        channel="in-app",
        status="sent",
        reference_id=project_id,
        notification_metadata={
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "assigned_by": current_user.name,
            "previous_sa_id": str(old_sa_id) if old_sa_id else None,
        },
        created_at=now,
    )
    db.add(notification)

    # === Auto-seed checklist subtask default (idempoten) ===
    # Subtask default langsung ditugaskan ke SA proyek. Pada re-assign yang sudah
    # punya subtask, seeding di-skip (idempoten) sehingga tidak menduplikasi.
    await _seed_default_subtasks(db, project_id, project.assigned_sa)

    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Proyek {project_id} di-reassign ke SA {sa_user.email} "
        f"oleh {current_user.email} (sebelumnya: {old_sa_id})"
    )

    # === 5. Dari Pending Assignment: timer SLA + provisioning folder (setara assign) ===
    if dari_pending:
        try:
            await sla_timer.start_timer(
                project_id=project_id, assigned_at=project.assigned_at, db=db
            )
        except Exception as e:
            logger.warning(f"Gagal memulai SLA timer untuk proyek {project_id}: {e}")
        if sales_email is not None:
            background_tasks.add_task(
                _trigger_folder_provisioner,
                project_id,
                sa_user.email,
                current_user.email,
                sales_email,
            )
        else:  # tanpa Sales (ADR 0014); penerima akses Drive mengikuti orang di tiket #120
            logger.warning(
                f"Proyek {project_id} tanpa Sales PIC; folder provisioning tidak dijadwalkan."
            )
    elif project.gdrive_folder_id:
        # Folder sudah ada: pindahkan akses Editor dari SA lama ke SA baru.
        background_tasks.add_task(
            _pindahkan_akses_drive_sa, project.gdrive_folder_id, sa_lama_email, sa_user.email
        )

    # === 6. Build response ===
    return success_response(
        data={
            "id_project": project.id_project,
            "project_name": project.project_name,
            "assigned_sa": str(project.assigned_sa),
            "assigned_sa_name": sa_user.name,
            "assigned_sa_email": sa_user.email,
            "status": project.status,
        },
        message=f"SA proyek '{project.project_name}' berhasil diubah ke {sa_user.name}.",
    )


@router.post(
    "/projects/{project_id}/provision-folder",
    summary="Provision ulang folder proyek",
    description=(
        "Men-trigger ulang provisioning folder Google Drive untuk proyek yang "
        "folder-nya belum ter-provision (gdrive_folder_id masih kosong). "
        "Idempoten: menolak (409) bila folder sudah ada. Hanya untuk Lead_SA atau Admin."
    ),
)
async def provision_folder(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-provision folder proyek (ADR 0006: idempotency guard sederhana).

    Flow:
    1. Validasi role Lead_SA/Admin.
    2. Validasi proyek ada (404).
    3. Idempotency: jika gdrive_folder_id sudah terisi -> 409 Conflict.
    4. Jika kosong: set folder_provisioning_status='pending' (commit) lalu
       jadwalkan _trigger_folder_provisioner dengan email SA assigned (lookup
       assigned_sa), Lead_SA (current_user.email), dan Sales (lookup sales_pic).

    Memakai jalur persist yang sama dengan assignment (background task mem-persist
    gdrive_folder_id + gdrive_solutions_folder_id + status).
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # === 2. Idempotency guard: folder sudah ada -> tolak ===
    if project.gdrive_folder_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Folder proyek '{project_id}' sudah ter-provision "
                f"(gdrive_folder_id='{project.gdrive_folder_id}'). "
                f"Re-provision hanya untuk proyek yang folder-nya belum ada."
            ),
        )

    # === 3. Lookup email SA assigned & Sales (requester) ===
    sa_email = None
    if project.assigned_sa is not None:
        sa_result = await db.execute(select(User).where(User.id == project.assigned_sa))
        sa_user = sa_result.scalar_one_or_none()
        sa_email = sa_user.email if sa_user else None

    sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
    sales_user = sales_result.scalar_one_or_none()
    sales_email = sales_user.email if sales_user else None

    if sa_email is None or sales_email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provisioning tidak bisa dijadwalkan: email SA assigned dan/atau "
                "Sales PIC tidak ditemukan. Pastikan proyek sudah di-assign ke SA."
            ),
        )

    # === 4. Tandai pending lalu jadwalkan provisioning ===
    project.folder_provisioning_status = "pending"
    await db.commit()

    background_tasks.add_task(
        _trigger_folder_provisioner,
        project_id,
        sa_email,
        current_user.email,
        sales_email,
    )

    logger.info(
        f"Re-provision folder dijadwalkan untuk proyek {project_id} oleh {current_user.email}."
    )

    return success_response(
        data={
            "id_project": project.id_project,
            "folder_provisioning_status": project.folder_provisioning_status,
            "folder_provisioning_triggered": True,
        },
        message=f"Provisioning folder untuk proyek '{project.project_name}' telah dijadwalkan.",
    )
