"""
Aturan status proyek yang dipakai lintas endpoint (issue #122, ADR 0013, spec §2.0).

- `majukan_ke_in_progress`: `Assigned` → `In Progress` otomatis dari activity log atau subtask
  `in_progress` pertama. Hanya berlaku dari `Assigned`, jadi terjadi sekali saja per siklus.
- `pastikan_proyek_bisa_ditulis`: guard read-only terpusat. `Closed` dan `Lost` menolak semua
  aksi tulis turunan proyek (subtask, activity log, dokumen, dan komentar saat #125 ada).
  Endpoint baru yang menulis data turunan proyek WAJIB memanggil guard ini.
"""

import random
import string
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status as status_konst
from app.models.audit_log import AuditLog
from app.models.project import Project

# Status read-only: aksi tulis turunan proyek ditolak (409 Conflict: proyek dalam status
# yang tidak menerima penulisan; berbeda dari 403 yang berarti peran tidak berhak).
STATUS_READ_ONLY = (status_konst.CLOSED, status_konst.LOST)


def pastikan_proyek_bisa_ditulis(project: Project) -> None:
    """Tolak (409) bila proyek `Closed` atau `Lost`. Panggil SETELAH cek akses (403)."""
    if project.status in STATUS_READ_ONLY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Proyek berstatus '{project.status}' dan bersifat read-only. "
                f"Buka kembali proyek (hanya Admin) sebelum menambah atau mengubah data."
            ),
        )


def _id_audit() -> str:
    tanggal = datetime.now(timezone.utc).strftime("%Y%m%d")
    acak = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"AUDIT-{tanggal}-{acak}"


def majukan_ke_in_progress(
    db: AsyncSession, project: Project, pelaku: UUID | None, pemicu: str
) -> bool:
    """
    `Assigned` → `In Progress` bila `project` masih `Assigned`; status lain dibiarkan.

    TIDAK commit: pemanggil menyimpan perubahan bersama operasi pemicunya (satu transaksi).
    Mencatat audit log `status_change`. Return True bila status berubah.
    """
    if project.status != status_konst.ASSIGNED:
        return False
    sekarang = datetime.now(timezone.utc)
    project.status = status_konst.IN_PROGRESS
    project.updated_at = sekarang
    db.add(
        AuditLog(
            id=_id_audit(),
            entity_type="project",
            entity_id=project.id_project,
            action="status_change",
            performed_by=pelaku,
            old_value={"status": status_konst.ASSIGNED},
            new_value={"status": status_konst.IN_PROGRESS, "otomatis": True, "pemicu": pemicu},
            created_at=sekarang,
        )
    )
    return True
