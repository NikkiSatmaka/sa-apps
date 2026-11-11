"""
Aturan akses DQ Number dan gating link Solutions (spec #87, tiket #90).

Satu sumber kebenaran untuk dua jalur pengisian DQ — `PATCH /projects/{id}/dq-number` dan
`PATCH /projects/{id}` (form edit) — serta untuk dua jalur baca link Solutions —
`GET /projects/{id}/documents/solutions` dan `GET /projects/{id}/documents`.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    PERAN_PRIVILEGED,
    PeranUser,
    TingkatAkses,
    ensure_project_access,
)
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.services.sla_timer import sla_timer

logger = logging.getLogger(__name__)

# Status proyek yang diizinkan untuk input DQ Number ("Assigned" atau lebih tinggi)
ALLOWED_STATUSES_FOR_DQ = (
    "Assigned",
    "Ready",
    "Closed-Win",
    "Handover Complete",
)

FOLDER_SOLUTIONS = "Solutions"
# Sales hanya melihat dokumen Solutions yang sudah melewati review.
STATUS_DOKUMEN_TERLIHAT_SALES = ("Reviewed", "Final")


@dataclass(frozen=True)
class PerubahanDQ:
    """Hasil penerapan DQ; `pertama_kali` = DQ yang sebelumnya kosong kini terisi."""

    pertama_kali: bool


async def terapkan_dq(
    db: AsyncSession, project: Project, user: User, nilai_baru: str | None
) -> PerubahanDQ:
    """
    Aturan + mutasi DQ Number yang dipakai KEDUA jalur pengisian (tanpa commit).

    Urutan keputusan (403/400 sebelum mutasi apa pun):
    1. Akses `ISI_DQ` (Sales PIC proyek itu, Lead_SA, Admin) — 403 generik.
    2. Status proyek harus salah satu `ALLOWED_STATUSES_FOR_DQ` — 400.
    3. Sales tidak boleh menimpa atau mengosongkan DQ yang sudah ada — 403.
    4. Peran harus Sales/Lead_SA/Admin — 403.
    Lalu set `dq_number`, `updated_at`, dan status Assigned → Ready saat DQ pertama kali terisi.

    Pemanggil WAJIB commit lalu memanggil `hentikan_timer_bila_pertama` agar timer SLA berhenti
    (+ auto-unlock Drive) hanya untuk perubahan yang benar-benar tersimpan.
    """
    await ensure_project_access(db, project, user, TingkatAkses.ISI_DQ)

    if project.status not in ALLOWED_STATUSES_FOR_DQ:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"DQ Number hanya bisa diinput pada proyek berstatus "
                f"'Assigned' atau lebih tinggi. Status saat ini: '{project.status}'."
            ),
        )

    if project.dq_number is not None and user.role == PeranUser.SALES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "DQ Number sudah tersimpan dan tidak bisa diubah oleh Sales. "
                "Hubungi Lead SA untuk perubahan."
            ),
        )

    if user.role not in (PeranUser.SALES, *PERAN_PRIVILEGED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Sales atau Lead_SA yang dapat menginput DQ Number.",
        )

    pertama_kali = project.dq_number is None and nilai_baru is not None
    project.dq_number = nilai_baru
    project.updated_at = datetime.now(timezone.utc)
    # Status ke "Ready" hanya saat DQ pertama kali diinput dan status masih "Assigned".
    if pertama_kali and project.status == "Assigned":
        project.status = "Ready"
    return PerubahanDQ(pertama_kali=pertama_kali)


async def hentikan_timer_bila_pertama(
    db: AsyncSession, project_id: str, perubahan: PerubahanDQ
) -> None:
    """Hentikan timer SLA (+ auto-unlock folder Solutions) saat DQ pertama kali terisi.

    Dipanggil SETELAH commit. Kegagalan timer tidak membatalkan penyimpanan DQ.
    """
    if not perubahan.pertama_kali:
        return
    try:
        await sla_timer.stop_timer(project_id=project_id, db=db)
    except Exception as e:
        logger.warning(f"Gagal menghentikan SLA timer untuk proyek {project_id}: {e}")


def dokumen_terlihat(user: User, project: Project, dokumen: Document) -> bool:
    """Gating link dokumen: apakah `user` boleh melihat `dokumen` proyek `project`?

    Hanya dokumen folder Solutions yang digating, hanya untuk peran Sales: ia harus Sales PIC
    proyek itu, DQ sudah terisi, dan dokumen berstatus Reviewed/Final. Dokumen non-Solutions
    dan peran lain tidak berubah.
    """
    if dokumen.folder_type != FOLDER_SOLUTIONS or user.role != PeranUser.SALES:
        return True
    return (
        project.sales_pic == user.id
        and project.dq_number is not None
        and dokumen.status in STATUS_DOKUMEN_TERLIHAT_SALES
    )


def saring_dokumen_terlihat(
    user: User, project: Project, dokumen: Iterable[Document]
) -> Sequence[Document]:
    """Dokumen yang boleh dilihat `user` (lihat `dokumen_terlihat`). Hitung/flag turunan
    harus dibuat dari hasil ini, bukan dari daftar mentah."""
    return [d for d in dokumen if dokumen_terlihat(user, project, d)]
