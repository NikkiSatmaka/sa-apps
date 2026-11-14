"""
Layanan komentar project (issue #125, spec §2.5): penerima dan pengiriman notifikasi.

"Orang yang ditugaskan" = Sales PIC, Product PIC, Lead_SA project, SA utama, SA tambahan
(`ProjectAssignments`), dan semua collaborator (viewer ikut diberi tahu walau tidak boleh menulis).
Penulis tidak pernah menjadi penerima.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.project_collaborator import ProjectCollaborator
from app.models.user import User
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)

CUPLIKAN_MAKS = 140


async def penerima_komentar(db: AsyncSession, project: Project, penulis_id: UUID) -> list[User]:
    """User yang ditugaskan di `project`, tanpa duplikat dan tanpa penulis (urut stabil)."""
    ids: set[UUID] = {
        i
        for i in (project.sales_pic, project.product_pic, project.lead_sa, project.assigned_sa)
        if i is not None
    }
    for model in (ProjectAssignment, ProjectCollaborator):
        hasil = await db.execute(select(model.user_id).where(model.id_project == project.id_project))
        ids.update(hasil.scalars().all())
    ids.discard(penulis_id)
    if not ids:
        return []
    users = await db.execute(select(User).where(User.id.in_(ids)).order_by(User.email))
    return list(users.scalars().all())


def _cuplikan(isi: str) -> str:
    satu_baris = " ".join(isi.split())
    return satu_baris if len(satu_baris) <= CUPLIKAN_MAKS else satu_baris[: CUPLIKAN_MAKS - 1] + "…"


async def kirim_notifikasi_komentar(
    db: AsyncSession, project: Project, penulis: User, isi: str
) -> None:
    """Kirim notifikasi komentar baru. Tidak pernah melempar: kegagalan hanya dicatat, dan
    kegagalan satu penerima tidak menghalangi penerima lain."""
    try:
        penerima = await penerima_komentar(db, project, penulis.id)
    except Exception as e:  # noqa: BLE001 - side-effect tidak boleh menggagalkan komentar
        logger.error(f"Gagal menentukan penerima notifikasi komentar {project.id_project}: {e}")
        return
    # Salin nilai yang dipakai sebelum transaksi baca ditutup, agar sesi request tidak menahan
    # transaksi terbuka selagi notifikasi menulis lewat sesinya sendiri.
    id_project, nama_project, nama_penulis = project.id_project, project.project_name, penulis.name
    penerima = [(u.id, u.email) for u in penerima]
    await db.commit()
    pesan = f"{nama_penulis} berkomentar di '{nama_project}': {_cuplikan(isi)}"
    for user_id, email in penerima:
        try:
            await notification_service.send_notification(
                NotificationEvent(
                    event_type=NotificationEventType.KOMENTAR,
                    recipient_user_id=user_id,
                    recipient_email=email,
                    reference_id=id_project,
                    subject=f"[Portal SA] Komentar baru di proyek {nama_project}",
                    metadata={
                        "project_name": nama_project,
                        "author_name": nama_penulis,
                        "message": pesan,
                    },
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"Gagal mengirim notifikasi komentar {id_project} ke {user_id}: {e}"
            )
