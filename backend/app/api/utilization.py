"""API endpoints for SA utilization reporting."""

import logging
import uuid
from datetime import date as date_type
from datetime import datetime as dt_type
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import adalah_privileged, get_current_user
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.user import User
from app.schemas.response import success_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Utilization"])


def _require_lead_sa(current_user: User) -> None:
    """Keep the utilization endpoints' Lead_SA/Admin authorization contract."""
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat melakukan operasi ini.",
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

    try:
        target_year = year or date_type.today().year

        sa_query = select(User).where(User.role.in_(["SA", "Lead_SA"])).order_by(User.name)
        if sa_id:
            try:
                sa_uuid = uuid.UUID(sa_id)
                sa_query = sa_query.where(User.id == sa_uuid)
            except ValueError:
                pass

        sa_result = await db.execute(sa_query)
        sa_users = sa_result.scalars().all()

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

        sa_monthly: dict[uuid.UUID, dict[int, float]] = {}
        for log in logs:
            sid = log.sa_id
            month = log.created_at.month
            hours = float(log.duration_hours)
            if sid not in sa_monthly:
                sa_monthly[sid] = {}
            sa_monthly[sid][month] = sa_monthly[sid].get(month, 0.0) + hours

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

    sa_hours_query = select(
        ActivityLog.id_project,
        ActivityLog.sa_id,
        func.sum(ActivityLog.duration_hours).label("hours"),
    ).group_by(ActivityLog.id_project, ActivityLog.sa_id)
    sa_hours_result = await db.execute(sa_hours_query)
    sa_hours_rows = sa_hours_result.all()

    project_sa_map: dict[str, list[dict]] = {}
    for row in sa_hours_rows:
        pid = row[0]
        if pid not in project_sa_map:
            project_sa_map[pid] = []
        project_sa_map[pid].append({"sa_id": row[1], "hours": float(row[2])})

    project_ids = list(project_sa_map.keys())
    if not project_ids:
        return success_response(data=[], message="Belum ada data activity log.")

    projects_result = await db.execute(select(Project).where(Project.id_project.in_(project_ids)))
    projects = {p.id_project: p for p in projects_result.scalars().all()}

    all_sa_ids = set()
    for entries in project_sa_map.values():
        for entry in entries:
            all_sa_ids.add(entry["sa_id"])

    sa_users_result = await db.execute(select(User).where(User.id.in_(list(all_sa_ids))))
    sa_name_map = {u.id: u.name for u in sa_users_result.scalars().all()}

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
    """Ringkasan utilisasi dua dimensi untuk dashboard Lead SA."""
    _require_lead_sa(current_user)

    target_year = year or date_type.today().year
    year_start = dt_type(target_year, 1, 1, tzinfo=timezone.utc)
    year_end = dt_type(target_year + 1, 1, 1, tzinfo=timezone.utc)

    log_result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.created_at >= year_start)
        .where(ActivityLog.created_at < year_end)
    )
    logs = log_result.scalars().all()

    months_wt: dict[int, dict[str, float]] = {
        m: {"Project": 0.0, "Non-Project": 0.0} for m in range(1, 13)
    }
    totals_wt: dict[str, float] = {"Project": 0.0, "Non-Project": 0.0}

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
