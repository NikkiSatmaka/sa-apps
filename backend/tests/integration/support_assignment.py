"""
Helper bersama test integrasi assignment/SLA/subtask/provisioning (tiket B5 #58, spec #49).

Isi:
- `Dunia`: sekumpulan user (semua peran) + token JWT asli, dibuat langsung di Postgres uji.
- `buat_proyek`/`tugaskan`: proyek pada status tertentu tanpa melewati alur kuesioner.
- `bekukan_waktu`: mengendalikan "sekarang" milik `sla_timer` (tanpa sleep nyata).
- `rekam_background`: menangkap background task provisioning agar dijalankan setelah request
  selesai (harness satu koneksi: sesi request yang masih terbuka dapat me-rollback hasil task).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Disimpan saat impor: `rekam_background` mengganti nama ini di modul assignment per test.
from app.api.assignment import _trigger_folder_provisioner as _TRIGGER_ASLI
from app.models import (
    AuditLog,
    NotificationLog,
    Project,
    SLATracking,
    Subtask,
    User,
)
from app.services.auth_service import auth_service
from tests.integration.model_helpers import bangun_project, bangun_user

ASSIGN = "/api/v1/projects/{}/assign"
REASSIGN = "/api/v1/projects/{}/reassign"
REPROVISION = "/api/v1/projects/{}/provision-folder"
SLA_STATUS = "/api/v1/projects/{}/sla-status"
SLA_PROCESS = "/api/v1/sla/process"
DQ_NUMBER = "/api/v1/projects/{}/dq-number"
SUBTASK_PROYEK = "/api/v1/projects/{}/subtasks"
SUBTASK = "/api/v1/projects/subtasks/{}"

T0 = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)  # titik awal deterministik (Senin)


def header(user: User) -> dict[str, str]:
    """Header Authorization berisi JWT asli untuk `user` (tanpa demo login)."""
    return {"Authorization": f"Bearer {auth_service._create_token_pair(user).access_token}"}


@dataclass(frozen=True)
class Pengguna:
    """Salinan nilai user (aman diakses walau objek ORM-nya kedaluwarsa)."""

    id: Any
    email: str
    name: str
    role: str


@dataclass
class Dunia:
    """User semua peran + header-nya. Dibuat per test; di-rollback otomatis."""

    db: AsyncSession
    lead: Pengguna
    admin: Pengguna
    sales: Pengguna
    sales_lain: Pengguna
    sa: Pengguna
    sa2: Pengguna
    h: dict[str, dict[str, str]] = field(default_factory=dict)

    async def buat_proyek(self, **o: Any) -> Project:
        o.setdefault("status", "Pending Assignment")
        proyek = bangun_project(self.sales.id, **o)
        self.db.add(proyek)
        await self.db.commit()
        return proyek


async def bangun_dunia(db: AsyncSession) -> Dunia:
    user = {
        nama: bangun_user(role=role, name=nama.title(), email=f"{nama}-t58@portal-sa.local")
        for nama, role in {
            "lead": "Lead_SA",
            "admin": "Admin",
            "sales": "Sales",
            "sales_lain": "Sales",
            "sa": "SA",
            "sa2": "SA",
        }.items()
    }
    db.add_all(user.values())
    await db.commit()
    dunia = Dunia(
        db=db,
        **{n: Pengguna(u.id, u.email, u.name, u.role) for n, u in user.items()},
    )
    dunia.h = {nama: header(u) for nama, u in user.items()}
    return dunia


class WaktuBeku:
    """Kendali jam `sla_timer`: `sekarang` bisa digeser tanpa menunggu."""

    def __init__(self, sekarang: datetime) -> None:
        self.sekarang = sekarang

    def maju(self, **delta: float) -> None:
        self.sekarang += timedelta(**delta)

    def ke(self, sekarang: datetime) -> None:
        self.sekarang = sekarang


def bekukan_waktu(monkeypatch: pytest.MonkeyPatch, sekarang: datetime = T0) -> WaktuBeku:
    """Ganti `datetime` di `app.services.sla_timer` agar `now()` mengikuti `WaktuBeku`."""
    from app.services import sla_timer as modul

    jam = WaktuBeku(sekarang)
    asli = modul.datetime

    class _Beku(asli):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return jam.sekarang if tz is None else jam.sekarang.astimezone(tz)

    monkeypatch.setattr(modul, "datetime", _Beku)
    return jam


def rekam_background(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """
    Tangkap argumen background task provisioning dari endpoint assign/provision-folder.

    Mengembalikan daftar argumen; test menjalankan `_trigger_folder_provisioner` ASLI sendiri
    setelah request selesai (pola `test_fake_boundary_contoh.py`).
    """
    from app.api import assignment

    terekam: list[tuple] = []

    async def _tangkap(*args: Any) -> None:
        terekam.append(args)

    monkeypatch.setattr(assignment, "_trigger_folder_provisioner", _tangkap)
    return terekam


async def jalankan_provisioning(db: AsyncSession, args: tuple) -> None:
    """Jalankan `_trigger_folder_provisioner` asli (sesi sendiri) lalu segarkan state test."""
    await db.commit()
    await _TRIGGER_ASLI(*args)


# --------------------------------------------------------------------------- pembacaan state


async def ambil_proyek(db: AsyncSession, id_project: str) -> Project:
    q = select(Project).where(Project.id_project == id_project)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one()


async def ambil_sla(db: AsyncSession, id_project: str) -> SLATracking | None:
    q = select(SLATracking).where(SLATracking.project_id == id_project)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def daftar_subtask(db: AsyncSession, id_project: str) -> list[Subtask]:
    q = select(Subtask).where(Subtask.id_project == id_project)
    return list((await db.execute(q.execution_options(populate_existing=True))).scalars())


async def daftar_notif(
    db: AsyncSession, id_project: str, event_type: str | None = None, *, channel: str = "in-app"
) -> list[NotificationLog]:
    q = select(NotificationLog).where(
        NotificationLog.reference_id == id_project, NotificationLog.channel == channel
    )
    if event_type:
        q = q.where(NotificationLog.event_type == event_type)
    return list((await db.execute(q.execution_options(populate_existing=True))).scalars())


async def daftar_audit(db: AsyncSession, id_project: str, action: str) -> list[AuditLog]:
    q = select(AuditLog).where(AuditLog.entity_id == id_project, AuditLog.action == action)
    return list((await db.execute(q.execution_options(populate_existing=True))).scalars())


@dataclass(frozen=True)
class InfoProyek:
    id_project: str
    gdrive_folder_id: str | None
    gdrive_solutions_folder_id: str | None


async def proyek_aktif_sla(
    dunia: Dunia, fake_drive: Any | None = None, *, mulai: datetime = T0, **o: Any
) -> InfoProyek:
    """
    Proyek 'Assigned' pada `mulai` dengan SLA timer berjalan.

    Bila `fake_drive` diberikan, folder diprovision lewat fake itu (id master + Solutions
    tersimpan) dan Sales diberi akses reader pada Solutions agar efek lock/unlock terlihat.
    """
    from app.services.sla_timer import sla_timer

    proyek = await dunia.buat_proyek(
        status="Assigned", assigned_sa=dunia.sa.id, assigned_at=mulai, **o
    )
    if fake_drive is not None:
        hasil = await fake_drive.provision_project_folder(
            proyek, dunia.sa.email, dunia.lead.email, dunia.sales.email
        )
        proyek.gdrive_folder_id = hasil.master
        proyek.gdrive_solutions_folder_id = hasil.solutions
        proyek.folder_provisioning_status = "provisioned"
        fake_drive.izin[hasil.solutions][dunia.sales.email] = "reader"
        await dunia.db.commit()
    await sla_timer.start_timer(proyek.id_project, mulai, dunia.db)
    return InfoProyek(proyek.id_project, proyek.gdrive_folder_id, proyek.gdrive_solutions_folder_id)
