"""
Service ActivityLogger — Modul untuk mencatat dan memproses aktivitas harian SA.

Fitur utama:
- Membuat log aktivitas dengan validasi project
- AI note polishing via LLM Provider
- Retry polish untuk entry yang gagal
- Project story timeline dengan filter dan pagination
- Google Calendar sync dan event mapping
"""

import logging
import math
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.subtask import Subtask
from app.services.llm_provider import LLMResponse, llm_factory
from app.utils.guardrails import PolishResult, sanitize_text_input, validate_llm_json

logger = logging.getLogger(__name__)


# Schema output untuk AI polishing (dikirim ke LLM)
AI_POLISH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "discussion_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Daftar poin-poin diskusi yang sudah dirapikan",
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Deskripsi item aksi",
                    },
                    "pic": {
                        "type": "string",
                        "nullable": True,
                        "description": "Person in charge (jika disebutkan dalam notes)",
                    },
                },
                "required": ["description"],
            },
            "description": "Daftar item aksi yang harus ditindaklanjuti",
        },
    },
    "required": ["discussion_points", "action_items"],
}


def _generate_log_id() -> str:
    """
    Generate ID log aktivitas unik.
    Format: LOG-{YYYYMMDD}-{random 6 chars}
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"LOG-{date_part}-{random_part}"


class ActivityLogger:
    """
    Service class untuk manajemen activity log SA.

    Menangani:
    - Pembuatan log dengan validasi project
    - AI polishing catatan via LLM
    - Retry polishing untuk entry yang gagal
    - Query project story dengan filter dan pagination
    """

    def __init__(self, db: AsyncSession):
        """Inisialisasi service dengan database session."""
        self.db = db

    async def create_log(
        self,
        sa_id: uuid.UUID,
        subtask_category: str,
        duration_hours: Decimal,
        raw_notes: str,
        work_type: str = "Project",
        id_project: Optional[str] = None,
        project_phase: Optional[str] = None,
        gcal_event_id: Optional[str] = None,
        id_subtask: Optional[str] = None,
    ) -> ActivityLog:
        """
        Buat activity log baru.

        Flow:
        1. Jika Project: validasi project_id ada di database
        2. Generate ID log unik
        3. Coba polish notes via AI
        4. Simpan record ke database (dengan atau tanpa polished notes)

        Args:
            sa_id: UUID user (SA atau Lead_SA) yang membuat log.
            subtask_category: Sub-kategori aktivitas (tergantung work_type).
            duration_hours: Durasi dalam jam.
            raw_notes: Catatan mentah.
            work_type: 'Project' atau 'Non-Project'.
            id_project: ID proyek (wajib untuk Project, None untuk Non-Project).
            project_phase: Fase proyek (wajib untuk Project, None untuk Non-Project).
            gcal_event_id: ID event Google Calendar (opsional).
            id_subtask: ID subtask terkait (opsional). Bila di-set, jalur ini
                memvalidasi bahwa subtask milik id_project yang sama (tolak bila
                beda proyek) dan memajukan subtask ber-status 'open' ke
                'in_progress' (ADR 0008). Idempoten: 'in_progress'/'done' tidak
                diubah; aktivitas tidak pernah ke 'done' maupun memundurkan status.

        Returns:
            Instance ActivityLog yang sudah tersimpan.

        Raises:
            ValueError: Jika Project dan project_id tidak ditemukan, atau bila
                id_subtask menunjuk subtask dari proyek lain.
        """
        # Validasi project hanya untuk aktivitas Project
        if work_type == "Project":
            await self._validate_project(id_project)
        else:
            # Non-Project: pastikan tidak terkait proyek/fase/subtask
            id_project = None
            project_phase = None
            id_subtask = None

        # Subtask: validasi scope proyek + majukan open -> in_progress (ADR 0008).
        # Dilakukan sebelum membuat log agar penolakan cross-project membatalkan
        # seluruh operasi (tidak ada log yang tersimpan).
        if id_subtask is not None:
            await self._advance_subtask_on_activity(id_subtask, id_project)

        # Generate ID unik
        id_log = _generate_log_id()

        # Coba polish notes via AI (requirement 8.3)
        ai_polished_notes = await self.polish_notes(raw_notes)

        # Buat record activity log
        activity_log = ActivityLog(
            id_log=id_log,
            work_type=work_type,
            id_project=id_project,
            project_phase=project_phase,
            sa_id=sa_id,
            subtask_category=subtask_category,
            id_subtask=id_subtask,
            duration_hours=duration_hours,
            raw_notes=raw_notes,
            ai_polished_notes=ai_polished_notes,
            gcal_event_id=gcal_event_id,
            created_at=datetime.now(timezone.utc),
        )

        self.db.add(activity_log)
        await self.db.commit()
        await self.db.refresh(activity_log)

        target = id_project if work_type == "Project" else "Non-Project"
        logger.info(
            f"Activity log dibuat: {id_log} ({target}) "
            f"(polished: {'ya' if ai_polished_notes else 'tidak'})"
        )

        return activity_log

    async def polish_notes(self, raw_notes: str) -> Optional[dict]:
        """
        Polish raw notes menggunakan LLM Provider (requirement 8.3).

        Mengirim raw notes ke LLM untuk diubah menjadi format terstruktur:
        - discussion_points: daftar poin diskusi
        - action_items: daftar item aksi dengan deskripsi dan PIC

        Args:
            raw_notes: Teks catatan mentah dari SA.

        Returns:
            Dict berisi discussion_points dan action_items, atau None jika LLM gagal.
        """
        try:
            provider = llm_factory.get_provider()

            # Guardrail teks: sanitize raw notes sebelum dikirim ke LLM (Req 8.2).
            guard = sanitize_text_input(raw_notes)

            # Kirim ke LLM untuk structuring
            response: LLMResponse = await provider.structure_text(
                text=guard.safe_value,
                output_schema=AI_POLISH_OUTPUT_SCHEMA,
            )

            # Cek apakah response berhasil
            if response.status == "success" and response.content is not None:
                # Validasi output terstruktur terhadap kontrak PolishResult (Req 8.4).
                validation = validate_llm_json(response.content, PolishResult)
                if validation.valid:
                    content = validation.data.model_dump()
                    logger.info(
                        f"AI polishing berhasil. "
                        f"Points: {len(content.get('discussion_points', []))}, "
                        f"Actions: {len(content.get('action_items', []))}"
                    )
                    return content
                else:
                    # Output tidak valid → None agar entry ditandai needs_repolish (Req 8.5).
                    logger.warning("AI polishing: output gagal validasi schema PolishResult.")
                    return None
            else:
                # LLM gagal — log error dan return None (requirement 8.6)
                logger.warning(
                    f"AI polishing gagal: {response.error_type} - {response.error_message}"
                )
                return None

        except Exception as e:
            # Tangkap semua error agar tidak menggagalkan penyimpanan (requirement 8.6)
            logger.error(f"AI polishing exception: {e}")
            return None

    async def retry_polish(self, id_log: str, sa_id: uuid.UUID) -> ActivityLog:
        """
        Re-trigger AI polishing untuk entry yang gagal (requirement 8.6).

        Dipanggil saat SA mengklik tombol "Polish Ulang".

        Args:
            id_log: ID log yang akan di-polish ulang.
            sa_id: UUID SA yang meminta retry (untuk validasi ownership).

        Returns:
            ActivityLog yang sudah di-update.

        Raises:
            ValueError: Jika log tidak ditemukan atau bukan milik SA.
        """
        # Cari activity log berdasarkan ID
        result = await self.db.execute(select(ActivityLog).where(ActivityLog.id_log == id_log))
        activity_log = result.scalar_one_or_none()

        if activity_log is None:
            raise ValueError(f"Activity log '{id_log}' tidak ditemukan.")

        # Validasi ownership — hanya SA yang membuat bisa retry
        if activity_log.sa_id != sa_id:
            raise ValueError("Anda tidak memiliki akses ke activity log ini.")

        # Re-trigger polishing
        ai_polished_notes = await self.polish_notes(activity_log.raw_notes)

        # Update record
        activity_log.ai_polished_notes = ai_polished_notes
        await self.db.commit()
        await self.db.refresh(activity_log)

        logger.info(
            f"Retry polish untuk log {id_log}: {'berhasil' if ai_polished_notes else 'gagal lagi'}"
        )

        return activity_log

    async def get_project_story(
        self,
        id_project: str,
        page: int = 1,
        page_size: int = 20,
        category: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        Ambil project story — timeline aktivitas per proyek (requirement 8.5).

        Mendukung filter berdasarkan subtask category dan rentang tanggal,
        dengan pagination maksimal 20 entry per halaman.

        Args:
            id_project: ID proyek yang ingin dilihat story-nya.
            page: Halaman yang diminta (1-based).
            page_size: Jumlah entry per halaman (max 20).
            category: Filter berdasarkan subtask category (opsional).
            date_from: Filter tanggal mulai (opsional).
            date_to: Filter tanggal akhir (opsional).

        Returns:
            Dict berisi items, total, page, page_size, total_pages.
        """
        # Validasi project exists
        await self._validate_project(id_project)

        # Batasi page_size maksimal 20
        page_size = min(page_size, 20)

        # Bangun query base
        conditions = [ActivityLog.id_project == id_project]

        # Filter category
        if category:
            conditions.append(ActivityLog.subtask_category == category)

        # Filter rentang tanggal
        if date_from:
            conditions.append(ActivityLog.created_at >= date_from)
        if date_to:
            conditions.append(ActivityLog.created_at <= date_to)

        where_clause = and_(*conditions)

        # Hitung total
        count_query = select(func.count()).select_from(ActivityLog).where(where_clause)
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Hitung total pages
        total_pages = math.ceil(total / page_size) if total > 0 else 1

        # Query data dengan pagination
        offset = (page - 1) * page_size
        data_query = (
            select(ActivityLog)
            .where(where_clause)
            .order_by(ActivityLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(data_query)
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def sync_calendar(self, sa_id: uuid.UUID) -> list[dict]:
        """
        Sync events dari Google Calendar (placeholder untuk MVP).

        Di MVP ini hanya menyiapkan interface — implementasi lengkap
        akan dilakukan di task terpisah (Google Calendar integration).

        Args:
            sa_id: UUID SA yang meminta sync.

        Returns:
            List event yang berhasil di-sync (empty list untuk saat ini).
        """
        # TODO: Implementasi Google Calendar sync di iterasi berikutnya
        logger.info(f"Calendar sync diminta oleh SA {sa_id} (placeholder)")
        return []

    async def map_event_to_project(
        self,
        sa_id: uuid.UUID,
        gcal_event_id: str,
        id_project: str,
        duration_hours: Decimal,
        subtask_category: str,
        raw_notes: str = "",
        project_phase: str = "Pre-Implementation",
    ) -> ActivityLog:
        """
        Map event Google Calendar ke proyek sebagai activity log (requirement 9.3).

        Args:
            sa_id: UUID SA yang melakukan mapping.
            gcal_event_id: ID event Google Calendar.
            id_project: ID proyek tujuan.
            duration_hours: Durasi dari event calendar.
            subtask_category: Kategori subtask.
            raw_notes: Catatan (opsional, default kosong).
            project_phase: Fase proyek (wajib untuk aktivitas Project; default
                Pre-Implementation, sama dengan default mayoritas kerja pre-sales).

        Returns:
            ActivityLog yang dibuat dari mapping event.

        Raises:
            ValueError: Jika event sudah dimapping atau project tidak valid.
        """
        # Cek apakah event sudah dimapping (unique constraint)
        existing = await self.db.execute(
            select(ActivityLog).where(ActivityLog.gcal_event_id == gcal_event_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"Event '{gcal_event_id}' sudah dipetakan ke proyek lain.")

        # Buat log dari event calendar
        return await self.create_log(
            sa_id=sa_id,
            id_project=id_project,
            project_phase=project_phase,
            subtask_category=subtask_category,
            duration_hours=duration_hours,
            raw_notes=raw_notes or "[Mapped dari Google Calendar event]",
            gcal_event_id=gcal_event_id,
        )

    async def _advance_subtask_on_activity(
        self, id_subtask: str, id_project: Optional[str]
    ) -> None:
        """
        Validasi scope subtask dan majukan statusnya saat ada aktivitas (ADR 0008).

        Dipanggil dari create_log saat id_subtask di-set. Memastikan subtask
        memang milik id_project yang sama (tolak bila beda proyek), lalu
        memajukan subtask ber-status 'open' ke 'in_progress'. Idempoten:
        'in_progress'/'done' dibiarkan; aktivitas tidak pernah memajukan ke
        'done' maupun memundurkan status.

        Args:
            id_subtask: ID subtask yang ditautkan ke activity log.
            id_project: ID proyek pemilik activity log (untuk cek scope).

        Raises:
            ValueError: Jika subtask tidak ditemukan atau milik proyek lain.
        """
        result = await self.db.execute(
            select(Subtask).where(Subtask.id_subtask == id_subtask)
        )
        subtask = result.scalar_one_or_none()

        if subtask is None:
            raise ValueError(f"Subtask dengan ID '{id_subtask}' tidak ditemukan.")

        if subtask.id_project != id_project:
            raise ValueError(
                f"Subtask '{id_subtask}' bukan milik proyek '{id_project}'."
            )

        # Hanya transisi maju open -> in_progress; status lain dibiarkan.
        if subtask.status == "open":
            subtask.status = "in_progress"
            self.db.add(subtask)

    async def _validate_project(self, id_project: str) -> Project:
        """
        Validasi bahwa project ID ada di database.

        Args:
            id_project: ID proyek yang akan divalidasi.

        Returns:
            Instance Project jika ditemukan.

        Raises:
            ValueError: Jika proyek tidak ditemukan.
        """
        result = await self.db.execute(select(Project).where(Project.id_project == id_project))
        project = result.scalar_one_or_none()

        if project is None:
            raise ValueError(f"Proyek dengan ID '{id_project}' tidak ditemukan.")

        return project
