"""
API endpoints untuk Activity Log — pencatatan aktivitas harian SA.

Endpoints:
- POST /activity-logs — Buat activity log baru
- POST /activity-logs/{id}/polish — Re-trigger AI polishing
- GET /projects/{id}/story — Ambil project story timeline

Sesuai requirement 8.1–8.7.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import TingkatAkses, ensure_project_access, get_current_user
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.user import User
from app.schemas.activity_log import (
    ActivityLogCreate,
    ActivityLogResponse,
    ProjectStoryResponse,
)
from app.services.status_proyek import pastikan_proyek_bisa_ditulis
from app.schemas.response import error_response, success_response
from app.services.activity_logger import ActivityLogger
from app.services.llm_provider import llm_factory
from app.utils.guardrails import is_nonempty_summary, sanitize_text_input

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Activity Logs"])


async def _periksa_akses_proyek(
    db: AsyncSession, id_project: str | None, user: User, tingkat: TingkatAkses
) -> None:
    """Cek akses `user` ke proyek `id_project` pada `tingkat` (403 bila tidak berhak).

    WAJIB dipanggil di LUAR blok `try/except Exception` handler: `HTTPException` 403 yang
    di-raise di dalam `try` akan tertelan jadi 500. Proyek yang tidak ada (atau `id_project`
    kosong, mis. Non-Project) tidak ditolak di sini; validasi 404/422 tetap milik
    `ActivityLogger` sehingga kontrak lama tidak berubah.
    """
    if id_project is None:
        return
    project = (
        await db.execute(select(Project).where(Project.id_project == id_project))
    ).scalar_one_or_none()
    if project is not None:
        await ensure_project_access(db, project, user, tingkat)
        if tingkat == TingkatAkses.TULIS:
            pastikan_proyek_bisa_ditulis(project)  # Closed/Lost read-only (409)


def _build_log_response(log) -> dict:
    """Helper untuk membangun response dict dari ActivityLog model."""
    return {
        "id_log": log.id_log,
        "work_type": log.work_type,
        "id_project": log.id_project,
        "project_phase": log.project_phase,
        "sa_id": str(log.sa_id),
        "subtask_category": log.subtask_category,
        "id_subtask": log.id_subtask,
        "duration_hours": float(log.duration_hours),
        "raw_notes": log.raw_notes,
        "ai_polished_notes": log.ai_polished_notes,
        "gcal_event_id": log.gcal_event_id,
        "created_at": log.created_at.isoformat(),
        "needs_repolish": log.ai_polished_notes is None,
    }


def _teks_catatan(log) -> str:
    """
    Teks catatan untuk ringkasan proyek: hasil polish AI (`discussion_points` + `action_items`)
    bila ada isinya, selain itu `raw_notes`. Dijadikan satu baris agar format daftar aktivitas
    di prompt tetap satu entri per baris.
    """
    polished = log.ai_polished_notes or {}
    bagian = [str(p).strip() for p in polished.get("discussion_points", []) if str(p).strip()]
    for item in polished.get("action_items", []):
        deskripsi = str(item.get("description", "")).strip()
        if not deskripsi:
            continue
        pic = item.get("pic")
        bagian.append(f"Aksi: {deskripsi} (PIC: {pic})" if pic else f"Aksi: {deskripsi}")
    if not bagian:
        return log.raw_notes
    return " ".join(" ".join(bagian).split())


@router.post(
    "/activity-logs",
    status_code=status.HTTP_201_CREATED,
    summary="Buat activity log baru",
    description=(
        "Endpoint untuk SA mencatat aktivitas harian pada proyek tertentu. "
        "Menerima project ID, subtask category, durasi, dan raw notes. "
        "AI akan otomatis memproses raw notes menjadi structured format."
    ),
)
async def create_activity_log(
    payload: ActivityLogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Buat activity log baru.

    Flow:
    1. Validasi input (schema Pydantic)
    2. Validasi project_id ada di database
    3. Proses AI polishing untuk raw_notes
    4. Simpan record (dengan atau tanpa polished notes)
    5. Return 201 dengan data log

    Requirement: 8.1, 8.2, 8.3, 8.4, 8.6
    """
    # Akses TULIS dicek sebelum polish LLM, insert, dan kemajuan subtask. Non-Project tidak
    # terkait proyek sehingga tidak dicek. Di luar try agar 403 tidak tertelan jadi 500.
    if payload.work_type == "Project":
        await _periksa_akses_proyek(
            db, payload.id_project, current_user, TingkatAkses.TULIS
        )

    try:
        activity_logger = ActivityLogger(db)

        # Buat log baru — service menangani validasi project dan AI polishing
        activity_log = await activity_logger.create_log(
            sa_id=current_user.id,
            work_type=payload.work_type,
            id_project=payload.id_project,
            project_phase=payload.project_phase,
            subtask_category=payload.subtask_category,
            duration_hours=payload.duration_hours,
            raw_notes=payload.raw_notes,
            gcal_event_id=payload.gcal_event_id,
            id_subtask=payload.id_subtask,
        )

        # Build response
        response_data = _build_log_response(activity_log)

        # Tentukan pesan berdasarkan status polishing
        if activity_log.ai_polished_notes:
            message = "Activity log berhasil dibuat dan notes di-polish oleh AI."
        else:
            message = (
                "Activity log berhasil dibuat. AI polishing gagal — "
                "gunakan tombol 'Polish Ulang' untuk mencoba kembali."
            )

        return success_response(data=response_data, message=message)

    except ValueError as e:
        # Project tidak ditemukan atau validasi gagal
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_response(message=str(e)),
        )
    except Exception as e:
        logger.error(f"Gagal membuat activity log: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(message="Gagal membuat activity log. Silakan coba lagi."),
        )


@router.post(
    "/activity-logs/{id_log}/polish",
    summary="Re-trigger AI polishing",
    description=(
        "Endpoint untuk SA memicu ulang proses AI polishing pada entry "
        "yang sebelumnya gagal. Menghasilkan structured notes dari raw_notes."
    ),
)
async def retry_polish_notes(
    id_log: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-trigger AI polishing untuk activity log tertentu.

    Digunakan saat polishing awal gagal dan SA ingin mencoba kembali.

    Requirement: 8.6
    """
    # Kepemilikan log tetap ditegakkan service (orang lain → 404). Di atasnya (spec #87, #92)
    # penulis harus MASIH punya akses TULIS ke proyek log: penulis yang kini viewer / kehilangan
    # akses ditolak 403 sebelum panggilan LLM. Log Non-Project tidak terkait proyek → dilewati.
    # Dilakukan di LUAR try agar 403 tidak tertelan jadi 500.
    log = (
        await db.execute(select(ActivityLog).where(ActivityLog.id_log == id_log))
    ).scalar_one_or_none()
    if log is not None and log.sa_id == current_user.id:
        # Proyek soft-deleted tersaring filter global (select(Project) → None), padahal log
        # masih menunjuknya (FK): tolak 404 seperti endpoint proyek lain, sebelum LLM dipanggil.
        if log.id_project is not None:
            proyek = (
                await db.execute(select(Project).where(Project.id_project == log.id_project))
            ).scalar_one_or_none()
            if proyek is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content=error_response(message="Proyek untuk log ini tidak ditemukan."),
                )
        await _periksa_akses_proyek(db, log.id_project, current_user, TingkatAkses.TULIS)

    try:
        activity_logger = ActivityLogger(db)

        # Retry polish — service menangani validasi ownership
        activity_log, berhasil = await activity_logger.retry_polish(
            id_log=id_log,
            sa_id=current_user.id,
        )

        response_data = _build_log_response(activity_log)

        if berhasil:
            message = "AI polishing berhasil. Notes sudah diperbarui."
        else:
            message = "AI polishing masih gagal. Silakan coba lagi nanti."

        return success_response(data=response_data, message=message)

    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_response(message=str(e)),
        )
    except Exception as e:
        logger.error(f"Gagal retry polish log {id_log}: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(message="Gagal memproses ulang notes. Silakan coba lagi."),
        )


@router.get(
    "/projects/{id_project}/story",
    summary="Ambil project story timeline",
    description=(
        "Endpoint untuk menampilkan timeline aktivitas proyek. "
        "Mendukung filter berdasarkan subtask category dan rentang tanggal, "
        "dengan pagination maksimal 20 entry per halaman."
    ),
)
async def get_project_story(
    id_project: str,
    page: int = Query(default=1, ge=1, description="Halaman (1-based)"),
    page_size: int = Query(default=20, ge=1, le=20, description="Entry per halaman (max 20)"),
    category: Optional[str] = Query(
        default=None,
        description="Filter subtask category",
    ),
    date_from: Optional[datetime] = Query(
        default=None,
        description="Filter tanggal mulai (ISO 8601)",
    ),
    date_to: Optional[datetime] = Query(
        default=None,
        description="Filter tanggal akhir (ISO 8601)",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil project story sebagai timeline aktivitas.

    Menampilkan daftar activity log per proyek, diurutkan terbaru terlebih dahulu.
    Mendukung filter category dan rentang tanggal.

    Requirement: 8.5
    """
    # Akses STORY (termasuk Sales PIC proyek itu) di luar try agar 403 tidak tertelan jadi 500.
    await _periksa_akses_proyek(db, id_project, current_user, TingkatAkses.STORY)

    try:
        activity_logger = ActivityLogger(db)

        # Ambil project story — service menangani validasi project
        result = await activity_logger.get_project_story(
            id_project=id_project,
            page=page,
            page_size=page_size,
            category=category,
            date_from=date_from,
            date_to=date_to,
        )

        # Build response items
        items = [_build_log_response(log) for log in result["items"]]

        response_data = {
            "items": items,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "total_pages": result["total_pages"],
        }

        return success_response(
            data=response_data,
            message=f"Project story untuk {id_project} (halaman {page}/{result['total_pages']}).",
        )

    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_response(message=str(e)),
        )
    except Exception as e:
        logger.error(f"Gagal mengambil project story {id_project}: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(message="Gagal mengambil project story."),
        )


# Prompt untuk summarize activity logs
SUMMARIZE_PROMPT = """Anda adalah asisten yang merangkum aktivitas proyek pre-sales.
Berikut adalah daftar aktivitas log dari sebuah proyek. Buatlah ringkasan dalam bahasa Indonesia.

Ringkasan harus mencakup:
1. Progress utama yang telah dicapai pada proyek
2. Area atau tugas yang memerlukan perhatian lebih / tindak lanjut

Data aktivitas:
{activity_data}

Berikan ringkasan dalam 1 paragraf yang padat dan mudah dibaca."""


@router.post(
    "/projects/{id_project}/summarize",
    summary="Generate LLM summary untuk proyek",
    description=(
        "Endpoint untuk menghasilkan ringkasan proyek menggunakan LLM "
        "berdasarkan semua activity log yang tercatat. "
        "Memerlukan minimal 1 activity log."
    ),
)
async def summarize_project(
    id_project: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate ringkasan proyek menggunakan LLM dari activity logs.

    Flow:
    1. Validasi project ada
    2. Ambil semua activity log proyek
    3. Bangun teks data aktivitas
    4. Kirim ke LLM untuk dirangkum
    5. Return hasil ringkasan

    Akses STORY dicek lebih dulu: penolakan terjadi sebelum query log dan panggilan LLM.
    """
    # Di luar try agar 403 tidak tertelan jadi 500.
    await _periksa_akses_proyek(db, id_project, current_user, TingkatAkses.STORY)

    try:
        activity_logger = ActivityLogger(db)

        # Ambil SEMUA activity log proyek (tanpa pagination) untuk summary
        result = await activity_logger.get_project_story(
            id_project=id_project,
            page=1,
            page_size=200,  # Ambil sebanyak mungkin
        )

        items = result["items"]
        if not items:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=error_response(
                    message="Belum ada activity log untuk proyek ini. "
                    "Tambahkan minimal 1 aktivitas sebelum meminta ringkasan."
                ),
            )

        # Bangun teks data aktivitas
        total_hours = sum(float(log.duration_hours) for log in items)
        lines = []
        for log in items:
            notes_text = _teks_catatan(log)
            lines.append(f"- [{log.subtask_category}] {float(log.duration_hours)}h | {notes_text}")
        activity_data = "\n".join(lines)

        # Guardrail teks: sanitize data aktivitas sebelum dikirim ke LLM (Req 8.3).
        guard = sanitize_text_input(activity_data)

        # Kirim ke LLM
        prompt = SUMMARIZE_PROMPT.format(activity_data=guard.safe_value)
        provider = llm_factory.get_provider()
        llm_response = await provider.complete_text(prompt, temperature=0.3, max_output_tokens=1024)

        if (
            llm_response.status == "success"
            and llm_response.content
            and is_nonempty_summary(llm_response.content)
        ):
            summary_text = llm_response.content
        else:
            # Fallback_Non_LLM jika LLM gagal ATAU summary tidak valid (Req 7.1-7.3).
            reason = (
                llm_response.error_message
                if llm_response.status != "success"
                else "summary LLM kosong atau tidak valid"
            )
            logger.warning(
                f"LLM summarize gagal untuk {id_project}: {reason}. "
                "Menggunakan fallback ringkasan sederhana."
            )
            categories: dict[str, float] = {}
            for log in items:
                cat = log.subtask_category
                categories[cat] = categories.get(cat, 0.0) + float(log.duration_hours)
            cat_summary = ", ".join(
                f"{cat}: {hours:.1f} jam"
                for cat, hours in sorted(categories.items(), key=lambda x: -x[1])
            )
            latest_date = items[0].created_at.strftime("%d %B %Y")
            summary_text = (
                f"Total {len(items)} aktivitas dengan {total_hours:.1f} jam kerja. "
                f"Breakdown: {cat_summary}. "
                f"Aktivitas terakhir: {latest_date}."
            )

        return success_response(
            data={
                "summary": summary_text,
                "total_activities": len(items),
                "total_hours": total_hours,
            },
            message="Ringkasan proyek berhasil dihasilkan.",
        )

    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_response(message=str(e)),
        )
    except Exception as e:
        logger.error(f"Gagal generate summary untuk proyek {id_project}: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(message="Gagal menghasilkan ringkasan. Silakan coba lagi."),
        )
