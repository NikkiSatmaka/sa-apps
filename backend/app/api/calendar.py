"""
API endpoints untuk integrasi Google Calendar.
Sync events dan mapping ke activity log proyek.
"""

import logging
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import TingkatAkses, ensure_project_access, get_current_user
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.user import User
from app.schemas.calendar import (
    CalendarMapRequest,
    CalendarMapResponse,
    CalendarSyncRequest,
    CalendarSyncResponse,
)
from app.schemas.response import error_response, success_response
from app.services.calendar_service import (
    CalendarAPIError,
    CalendarTimeoutError,
    calendar_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])


@router.get(
    "/auth-url",
    summary="Generate Google OAuth URL untuk Calendar",
    description=(
        "Endpoint untuk memulai OAuth flow khusus Google Calendar. "
        "User akan di-redirect ke Google consent screen. "
        "Setelah authorize, Google redirect kembali ke frontend dengan token di URL hash."
    ),
)
async def get_calendar_auth_url():
    """
    Generate Google OAuth URL khusus calendar scope.
    User akan di-redirect ke Google untuk authorize akses calendar.
    Setelah callback, token akan tersedia di URL hash frontend.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response(
                message="Google OAuth belum dikonfigurasi. Calendar sync tidak tersedia."
            ),
        )

    # State parameter: "calendar_auth|{return_url}"
    # Callback handler akan detect prefix ini dan handle sebagai calendar auth.
    # return_url diarahkan ke halaman Calendar Sync agar komponen CalendarSync
    # (yang membaca #gcal_token dari URL hash) ter-mount dan menangkap token.
    # Tanpa path ini, user mendarat di root dan token tidak pernah terbaca.
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    return_url = f"{frontend_url}/activity-logs/calendar"
    state = f"calendar_auth|{return_url}"

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.readonly",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"

    return success_response(
        data={"auth_url": auth_url},
        message="URL otorisasi Google Calendar berhasil dibuat.",
    )


def _generate_log_id() -> str:
    """
    Generate ID activity log unik dengan format LOG-{YYYYMMDD}-{random 6 chars}.
    Contoh: LOG-20250101-A3X9K2
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"LOG-{date_part}-{random_part}"


@router.post(
    "/sync",
    summary="Sync events dari Google Calendar",
    description=(
        "Fetch events 7 hari lalu + 7 hari depan (max 200 events) dari "
        "Google Calendar primary user. Memerlukan access_token Google OAuth."
    ),
)
async def sync_calendar(
    request: CalendarSyncRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Sync events dari Google Calendar.

    Flow:
    1. Panggil Google Calendar API dengan access_token user
    2. Parse events (termasuk all-day events dengan durasi 8 jam)
    3. Return daftar events yang bisa di-map ke proyek

    Error handling:
    - Timeout 15s → return error "Google Calendar API timeout"
    - API error → return error dengan detail spesifik
    """
    try:
        events = await calendar_service.fetch_events(request.access_token)
    except CalendarTimeoutError:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=error_response(message="Google Calendar API timeout"),
        )
    except CalendarAPIError as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=error_response(message=e.message),
        )

    # Buat response
    sync_response = CalendarSyncResponse(
        events=events,
        total_events=len(events),
    )

    logger.info(
        f"User {current_user.email} sync calendar: {len(events)} events ditemukan"
    )

    return success_response(
        data=sync_response.model_dump(mode="json"),
        message=f"Berhasil sync {len(events)} events dari Google Calendar.",
    )


@router.post(
    "/map",
    status_code=status.HTTP_201_CREATED,
    summary="Map event Google Calendar ke proyek",
    description=(
        "Petakan satu event Google Calendar ke proyek tertentu. "
        "Membuat record ActivityLog dengan gcal_event_id. "
        "Satu event hanya bisa di-map ke satu proyek (unique constraint)."
    ),
)
async def map_event_to_project(
    request: CalendarMapRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Map event Google Calendar ke proyek sebagai activity log.

    Flow:
    1. Validasi project_id ada di database
    2. Hitung durasi (dari event atau override)
    3. Generate raw_notes jika tidak disediakan
    4. Buat record ActivityLog
    5. Handle unique constraint violation (event sudah di-map)

    Error handling:
    - Project tidak ditemukan → 404
    - Event sudah di-map → 409 conflict
    """
    # Validasi project hanya untuk aktivitas Project
    project = None
    if request.work_type == "Project":
        project_result = await db.execute(
            select(Project).where(Project.id_project == request.project_id)
        )
        project = project_result.scalar_one_or_none()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Proyek dengan ID '{request.project_id}' tidak ditemukan.",
            )

        # Akses TULIS sebelum penulisan activity log apa pun (viewer/Sales/pihak luar ditolak).
        await ensure_project_access(db, project, current_user, TingkatAkses.TULIS)

    # Hitung durasi
    if request.duration_hours:
        # User override durasi
        duration = request.duration_hours
    elif request.is_all_day:
        # All-day event: default 8 jam
        duration = Decimal("8.00")
    elif request.event_start and request.event_end:
        # Hitung dari start/end
        delta = request.event_end - request.event_start
        hours = delta.total_seconds() / 3600
        duration = Decimal(str(round(hours, 2)))
        duration = max(Decimal("0.25"), min(duration, Decimal("24.00")))
    else:
        # Fallback 1 jam
        duration = Decimal("1.00")

    # Generate raw_notes
    raw_notes = request.raw_notes
    if not raw_notes:
        raw_notes = calendar_service.generate_notes(
            title=request.event_title,
            description=request.event_description,
        )

    # Buat record ActivityLog
    log_id = _generate_log_id()
    now = datetime.now(timezone.utc)

    # Mapping sesuai work_type: Project (dengan proyek + fase) atau Non-Project.
    # Konsistensi antar-field sudah divalidasi di CalendarMapRequest.
    is_project = request.work_type == "Project"
    activity_log = ActivityLog(
        id_log=log_id,
        work_type=request.work_type,
        id_project=request.project_id if is_project else None,
        project_phase=request.project_phase if is_project else None,
        sa_id=current_user.id,
        subtask_category=request.subtask_category,
        gcal_event_id=request.gcal_event_id,
        duration_hours=duration,
        raw_notes=raw_notes,
        created_at=now,
    )

    db.add(activity_log)

    try:
        await db.commit()
        await db.refresh(activity_log)
    except IntegrityError as e:
        await db.rollback()

        # Cek apakah karena unique constraint gcal_event_id
        error_str = str(e.orig) if e.orig else str(e)
        if "idx_unique_gcal_mapping" in error_str or "gcal_event_id" in error_str:
            # Cari proyek mana yang sudah di-map
            existing = await db.execute(
                select(ActivityLog).where(
                    ActivityLog.gcal_event_id == request.gcal_event_id
                )
            )
            existing_log = existing.scalar_one_or_none()

            if existing_log:
                # Cari nama proyek yang sudah di-map. Event Non-Project tidak punya
                # proyek (id_project None), jadi pakai label "Non-Project".
                if existing_log.id_project is None:
                    project_name = "Non-Project"
                else:
                    proj_result = await db.execute(
                        select(Project).where(
                            Project.id_project == existing_log.id_project
                        )
                    )
                    existing_project = proj_result.scalar_one_or_none()
                    project_name = (
                        existing_project.project_name
                        if existing_project
                        else existing_log.id_project
                    )

                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content=error_response(
                        message=f"Event sudah dipetakan ke proyek {project_name}"
                    ),
                )

            # Fallback jika tidak bisa temukan detail
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content=error_response(
                    message="Event sudah dipetakan ke proyek lain"
                ),
            )

        # IntegrityError lain (bukan unique constraint gcal)
        logger.error(f"IntegrityError saat map event: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_response(
                message="Gagal memetakan event. Periksa data yang dikirim."
            ),
        )

    logger.info(
        f"User {current_user.email} mapped event {request.gcal_event_id} "
        f"ke proyek {request.project_id} (log: {log_id})"
    )

    # Response
    map_response = CalendarMapResponse(
        id_log=log_id,
        work_type=request.work_type,
        id_project=request.project_id if is_project else None,
        project_phase=request.project_phase if is_project else None,
        gcal_event_id=request.gcal_event_id,
        subtask_category=request.subtask_category,
        duration_hours=duration,
        raw_notes=raw_notes,
        created_at=now,
    )

    return success_response(
        data=map_response.model_dump(mode="json"),
        message="Event berhasil dipetakan ke proyek.",
    )
