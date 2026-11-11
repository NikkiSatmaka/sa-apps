"""
Aturan akses pengisian DQ Number (spec #87, tiket #90).

Dipakai oleh `PATCH /projects/{id}` agar perubahan NILAI `dq_number` lewat form edit proyek
mengikuti aturan yang sama dengan `PATCH /projects/{id}/dq-number`: hanya Sales PIC proyek itu,
Lead_SA, dan Admin (`TingkatAkses.ISI_DQ`).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TingkatAkses, ensure_project_access
from app.models.project import Project
from app.models.user import User


def normalisasi_dq(nilai: object) -> str | None:
    """Nilai kosong ("", None) = DQ tidak terisi, sama seperti perilaku PATCH sebelumnya."""
    return nilai if nilai else None


async def periksa_perubahan_dq(
    db: AsyncSession, project: Project, user: User, nilai_dikirim: object
) -> bool:
    """
    Putuskan apakah `dq_number` pada body PATCH proyek perlu diterapkan.

    - Nilai sama dengan yang tersimpan → `False` (diabaikan; form edit mengirim semua field,
      jadi peran lain yang tidak mengubah DQ tidak boleh mendapat 403).
    - Nilai berubah dan `user` berhak mengisi DQ → `True`.
    - Nilai berubah dan `user` tidak berhak → raise 403 (via `ensure_project_access`).

    Panggil SEBELUM mutasi field apa pun.
    """
    baru = normalisasi_dq(nilai_dikirim)
    if baru == project.dq_number:
        return False
    await ensure_project_access(db, project, user, TingkatAkses.ISI_DQ)
    return True
