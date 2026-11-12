"""
Verifikasi tingkat API terhadap Google Drive NYATA (#27, skenario e): assign → provisioning →
SLA lock/unlock → `doc_ready`, dengan `folder_provisioner` ASLI (TANPA fixture `fake_drive`).

Butuh `TEST_DATABASE_URL` (Postgres sementara; lihat backend/README.md) selain kredensial Drive.
User Lead_SA/SA/Sales dibuat di Postgres sementara dengan email NYATA dari env, lalu endpoint
produksi dipakai apa adanya. Email dibelokkan ke `fake_gmail` agar tidak ada surat nyata terkirim
ke akun uji. Hasil di Drive selalu dibaca ulang lewat `Verifikator` (klien terpisah).

BELUM PERNAH DIJALANKAN terhadap Drive sungguhan oleh penulisnya. Ekspektasi mengikuti spec/
glossary (Solutions tertutup bagi Sales sampai DQ terisi; doc Reviewed + DQ membukanya); jangan
dilonggarkan bila hasil live berbeda — laporkan sebagai gap.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.drive_live.konfigurasi import KonfigurasiLive
from tests.integration.drive_live.verifikator import Verifikator
from tests.integration.model_helpers import bangun_document, bangun_project, bangun_user, simpan
from tests.integration.support_assignment import (
    ASSIGN,
    DQ_NUMBER,
    ambil_proyek,
    ambil_sla,
    bekukan_waktu,
    header,
    jalankan_provisioning,
    rekam_background,
)

pytestmark = pytest.mark.drive_live

SISTEM_ID = uuid.UUID(int=0)


@pytest.fixture(autouse=True)
def _prasyarat_api_live(monkeypatch, session_factory, fake_gmail):
    """
    - Service yang membuka sesinya sendiri memakai koneksi test.
    - `fake_gmail` dipasang dan DITAHAN selamanya: tidak ada email nyata ke akun uji, dan task
      email tidak bertabrakan dengan sesi test (harness satu koneksi).
    """
    if not os.environ.get("TEST_DATABASE_URL", "").strip():
        pytest.fail(
            "Skenario API live butuh TEST_DATABASE_URL (Postgres sementara; lihat "
            "backend/README.md, bagian Verifikasi Drive live).",
            pytrace=False,
        )
    patch_session_factory(monkeypatch, session_factory)
    fake_gmail.tahan_email()


@pytest.fixture
async def user_sistem(db_session: AsyncSession) -> None:
    """User sistem (UUID nol) sebagai pelaku audit aksi otomatis SLA (FK `audit_logs`)."""
    db_session.add(
        User(
            id=SISTEM_ID,
            email="sistem-drive-live@portal-sa.local",
            name="Sistem",
            role="SA",
            google_id="g-sistem-drive-live",
        )
    )
    await db_session.commit()


@dataclass
class DuniaLive:
    db: AsyncSession
    cfg: KonfigurasiLive
    lead: User
    sa: User
    sales: User

    def h(self, nama: str) -> dict[str, str]:
        return header(getattr(self, nama))


@pytest.fixture
async def dunia(db_session: AsyncSession, konfigurasi_live: KonfigurasiLive) -> DuniaLive:
    cfg = konfigurasi_live
    lead = bangun_user(role="Lead_SA", name="Lead Live", email=cfg.email_lead)
    sa = bangun_user(role="SA", name="SA Live", email=cfg.email_sa)
    sales = bangun_user(role="Sales", name="Sales Live", email=cfg.email_sales)
    db_session.add_all([lead, sa, sales])
    await db_session.commit()
    return DuniaLive(db=db_session, cfg=cfg, lead=lead, sa=sa, sales=sales)


async def _assign_dan_provision(
    dunia: DuniaLive, api, monkeypatch, provisioner, pembersih, awalan
) -> str:
    """Proyek Pending Assignment → assign (endpoint nyata) → provisioning ASLI. Return id proyek."""
    proyek = bangun_project(
        dunia.sales.id,
        status="Pending Assignment",
        customer_name=f"{awalan}PT Uji",
        project_name="Proyek Live",
    )
    dunia.db.add(proyek)
    await dunia.db.commit()
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)

    resp = await asyncio.wait_for(
        api.client.post(
            ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h("lead")
        ),
        dunia.cfg.timeout,
    )

    assert resp.status_code == 200, resp.text
    assert tugas == [(pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)]
    await asyncio.wait_for(jalankan_provisioning(dunia.db, tugas[0]), dunia.cfg.timeout)
    p = await ambil_proyek(dunia.db, pid)
    if p.gdrive_folder_id:
        pembersih.append(p.gdrive_folder_id)
    assert p.folder_provisioning_status == "provisioned", p.folder_provisioning_status
    return pid


def _subfolder(verifikator: Verifikator, master: str) -> dict[str, str]:
    return {f["name"]: f["id"] for f in verifikator.anak(master)}


async def test_assign_membuat_tree_asli_dan_menyimpan_id(
    dunia, api, monkeypatch, provisioner, verifikator, pembersih, awalan
):
    cfg = dunia.cfg

    pid = await _assign_dan_provision(dunia, api, monkeypatch, provisioner, pembersih, awalan)

    p = await ambil_proyek(dunia.db, pid)
    assert p.status == "Assigned" and p.assigned_sa == dunia.sa.id
    assert p.gdrive_folder_id and p.gdrive_solutions_folder_id
    # Dibaca ulang dari Drive, bukan dari nilai kembalian provisioner.
    assert verifikator.ambil(p.gdrive_folder_id)["name"] == f"{awalan}PT Uji - Proyek Live"
    anak = _subfolder(verifikator, p.gdrive_folder_id)
    assert set(anak) == {"Inventory", "Diagram", "Solutions"}
    assert anak["Solutions"] == p.gdrive_solutions_folder_id
    for folder in anak.values():
        assert verifikator.peran_efektif(folder, cfg.email_sa) == "writer"
        assert verifikator.peran_efektif(folder, cfg.email_lead) == "writer"
    assert verifikator.peran_efektif(anak["Inventory"], cfg.email_sales) == "reader"
    assert verifikator.peran_efektif(anak["Diagram"], cfg.email_sales) is None
    assert verifikator.peran_efektif(anak["Solutions"], cfg.email_sales) is None
    assert verifikator.peran_efektif(p.gdrive_folder_id, cfg.email_sales) is None


async def test_sla_lock_lalu_dq_membuka_solutions(
    dunia, api, monkeypatch, provisioner, verifikator, pembersih, awalan, user_sistem
):
    cfg = dunia.cfg
    pid = await _assign_dan_provision(dunia, api, monkeypatch, provisioner, pembersih, awalan)
    p = await ambil_proyek(dunia.db, pid)
    solutions, inventory = (
        p.gdrive_solutions_folder_id,
        _subfolder(verifikator, p.gdrive_folder_id)["Inventory"],
    )

    # H+5 tanpa DQ → cron SLA mengunci Solutions (Drive asli).
    sla = await ambil_sla(dunia.db, pid)
    bekukan_waktu(monkeypatch, sla.started_at + timedelta(days=5, hours=1))
    await dunia.db.commit()
    stats = await asyncio.wait_for(sla_timer.process_sla_actions(), cfg.timeout)

    assert stats["errors"] == []
    assert stats["locks_performed"] == 1
    assert (await ambil_sla(dunia.db, pid)).is_locked is True
    assert verifikator.peran_efektif(solutions, cfg.email_sales) is None
    assert verifikator.peran_efektif(inventory, cfg.email_sales) == "reader"

    # Sales mengisi DQ → timer berhenti dan Solutions dibuka untuk Sales (reader).
    resp = await asyncio.wait_for(
        api.client.patch(
            DQ_NUMBER.format(pid), json={"dq_number": "DQ-LIVE-1"}, headers=dunia.h("sales")
        ),
        cfg.timeout,
    )

    assert resp.status_code == 200, resp.text
    sla = await ambil_sla(dunia.db, pid)
    assert sla.is_locked is False and sla.stopped_at is not None
    assert verifikator.peran_efektif(solutions, cfg.email_sales) == "reader"
    # Hanya Solutions yang dibuka: master & Diagram tetap tertutup bagi Sales.
    anak = _subfolder(verifikator, p.gdrive_folder_id)
    assert verifikator.peran_efektif(anak["Diagram"], cfg.email_sales) is None
    assert verifikator.peran_efektif(p.gdrive_folder_id, cfg.email_sales) is None


async def _dokumen_draft(dunia: DuniaLive, pid: str):
    dokumen = bangun_document(pid, dunia.sa.id, doc_type="BOQ", status="Draft")
    await simpan(dunia.db, dokumen)
    await dunia.db.commit()
    return dokumen


async def _jadikan_reviewed(dunia: DuniaLive, api, dokumen):
    return await asyncio.wait_for(
        api.client.patch(
            f"/api/v1/documents/{dokumen.id_doc}/status",
            json={"new_status": "Reviewed"},
            headers=dunia.h("sa"),
        ),
        dunia.cfg.timeout,
    )


async def test_doc_reviewed_dengan_dq_membuka_solutions_untuk_sales(
    dunia, api, monkeypatch, provisioner, verifikator, pembersih, awalan
):
    cfg = dunia.cfg
    pid = await _assign_dan_provision(dunia, api, monkeypatch, provisioner, pembersih, awalan)
    p = await ambil_proyek(dunia.db, pid)
    p.dq_number = "DQ-LIVE-2"
    await dunia.db.commit()
    dokumen = await _dokumen_draft(dunia, pid)
    assert verifikator.peran_efektif(p.gdrive_solutions_folder_id, cfg.email_sales) is None

    resp = await _jadikan_reviewed(dunia, api, dokumen)

    assert resp.status_code == 200, resp.text
    assert verifikator.peran_efektif(p.gdrive_solutions_folder_id, cfg.email_sales) == "reader"
    anak = _subfolder(verifikator, p.gdrive_folder_id)
    assert verifikator.peran_efektif(anak["Diagram"], cfg.email_sales) is None
    assert verifikator.peran_efektif(p.gdrive_folder_id, cfg.email_sales) is None


async def test_doc_reviewed_tanpa_dq_solutions_tetap_tertutup(
    dunia, api, monkeypatch, provisioner, verifikator, pembersih, awalan
):
    cfg = dunia.cfg
    pid = await _assign_dan_provision(dunia, api, monkeypatch, provisioner, pembersih, awalan)
    p = await ambil_proyek(dunia.db, pid)
    assert p.dq_number is None
    dokumen = await _dokumen_draft(dunia, pid)

    resp = await _jadikan_reviewed(dunia, api, dokumen)

    assert resp.status_code == 200, resp.text
    assert verifikator.peran_efektif(p.gdrive_solutions_folder_id, cfg.email_sales) is None
