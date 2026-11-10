"""
Integrasi `api/dq_number` terhadap Postgres nyata (tiket B6, #59, spec #49): input DQ Number
(status proyek, peran, format), efeknya pada SLA timer dan akses Solutions (Drive palsu), serta
read-gating dokumen Solutions.
Pasangan unit: `tests/test_dokumen_workflow_handover_unit.py`.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, SLATracking
from app.services.sla_timer import sla_timer
from tests.integration.b6_support import (  # noqa: F401
    API,
    buat_dokumen,
    buat_proyek,
    komit_sesi_request,
    muat,
    siapkan_dunia,
)
from tests.integration.model_helpers import bangun_sla, bangun_user, simpan

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

DQ = "DQ-2025-001"
STATUS_BOLEH = ["Assigned", "Ready", "Closed-Win", "Handover Complete"]
STATUS_DITOLAK = [
    "New",
    "Pending Assignment",
    "Need Clarification",
    "Scoring Pending",
    "Manual Review Required",
    "Lost",
]


async def _input_dq(api, id_project, dq, header):
    return await api.client.patch(
        f"{API}/projects/{id_project}/dq-number", json={"dq_number": dq}, headers=header
    )


async def _dq_tersimpan(db, id_project):
    return (await muat(db, Project, id_project=id_project)).dq_number


# --------------------------------------------------------------------------- input DQ: happy path


async def test_dq_pertama_oleh_sales_tersimpan_dan_status_assigned_menjadi_ready(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["dq_number"] == DQ
    assert data["status"] == "Ready"
    assert "Ready" in resp.json()["message"]
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (DQ, "Ready")


@pytest.mark.parametrize("status_", STATUS_BOLEH)
async def test_dq_diterima_pada_status_assigned_atau_lebih_tinggi(api, db_session, status_):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=status_)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert baris.dq_number == DQ
    # Hanya Assigned yang naik ke Ready; status lain tidak berubah.
    assert baris.status == ("Ready" if status_ == "Assigned" else status_)


@pytest.mark.parametrize("status_", STATUS_DITOLAK)
async def test_dq_ditolak_pada_status_di_bawah_assigned(api, db_session, status_):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=status_, sa=False)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 400
    assert status_ in resp.json()["message"]
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (None, status_)


async def test_dq_proyek_tidak_ada_404_dan_tanpa_login_ditolak(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    tak_ada = await _input_dq(api, "PRJ-TIDAK-ADA", DQ, dunia.header["Sales"])
    anonim = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/dq-number", json={"dq_number": DQ}
    )

    assert tak_ada.status_code == 404
    assert anonim.status_code in (401, 403)
    assert await _dq_tersimpan(db_session, proyek.id_project) is None


@pytest.mark.parametrize(
    "dq",
    ["AB-1", "ABC 12345", "ABC_12345", "ABC-1234\n", "A" * 21, "", "DQ/2025/01"],
)
async def test_dq_format_tidak_valid_422_tidak_tersimpan(api, db_session, dq):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, dq, dunia.header["Sales"])

    assert resp.status_code == 422
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (None, "Assigned")


@pytest.mark.parametrize("dq", ["ABCDE", "A" * 20, "12-34-56", "dq-abc12"])
async def test_dq_format_batas_valid_tersimpan(api, db_session, dq):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, dq, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    assert await _dq_tersimpan(db_session, proyek.id_project) == dq


# --------------------------------------------------------------------------- peran & proteksi edit


async def test_sa_tidak_boleh_input_dq(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["SA"])

    assert resp.status_code == 403
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (None, "Assigned")


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_lead_sa_dan_admin_boleh_input_dq_pertama(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header[peran])

    assert resp.status_code == 200, resp.text
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (DQ, "Ready")


async def test_sales_tidak_bisa_mengubah_dq_yang_sudah_tersimpan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Ready", dq_number="DQ-LAMA-1")

    resp = await _input_dq(api, proyek.id_project, "DQ-BARU-2", dunia.header["Sales"])

    assert resp.status_code == 403
    assert "Lead SA" in resp.json()["message"]
    assert await _dq_tersimpan(db_session, proyek.id_project) == "DQ-LAMA-1"


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_lead_sa_dan_admin_boleh_mengedit_dq_tersimpan_tanpa_mengubah_status(
    api, db_session, peran
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Ready", dq_number="DQ-LAMA-1")

    resp = await _input_dq(api, proyek.id_project, "DQ-BARU-2", dunia.header[peran])

    assert resp.status_code == 200, resp.text
    assert "diperbarui" in resp.json()["message"]
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == ("DQ-BARU-2", "Ready")


async def test_sa_tidak_bisa_mengedit_dq_tersimpan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Ready", dq_number="DQ-LAMA-1")

    resp = await _input_dq(api, proyek.id_project, "DQ-BARU-2", dunia.header["SA"])

    assert resp.status_code == 403
    assert await _dq_tersimpan(db_session, proyek.id_project) == "DQ-LAMA-1"


# --------------------------------------------------------------------------- DQ → SLA & unlock


async def test_dq_pertama_menghentikan_timer_sla_dan_membuka_kunci_solutions(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(
        db_session, dunia, gdrive_folder_id="master", gdrive_solutions_folder_id="solutions"
    )
    sla = bangun_sla(
        proyek.id_project, is_locked=True, locked_at=datetime(2025, 1, 6, tzinfo=timezone.utc)
    )
    # Audit unlock SLA memakai "system user" UUID nol sebagai `performed_by` (FK ke users), tetapi
    # tidak ada migration/seed yang membuat baris itu: tanpa baris ini unlock gagal dengan
    # FK violation (temuan dilaporkan di tiket #59; perbaikannya milik modul SLA).
    sistem = bangun_user(id=uuid.UUID(int=0), role="Admin", email="sistem@portal-sa.local")
    await simpan(db_session, sistem, sla)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    sla = await muat(db_session, SLATracking, project_id=proyek.id_project)
    assert sla.stopped_at is not None
    assert sla.is_locked is False
    assert sla.unlocked_at is not None
    assert fake_drive.peran("solutions", dunia.user["Sales"].email) == "reader"
    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == proyek.id_project)))
        .scalars()
        .all()
    )
    assert [(a.entity_type, a.action) for a in audit] == [("folder", "unlock")]


async def test_dq_pertama_tanpa_kunci_hanya_menghentikan_timer_tanpa_menyentuh_drive(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, gdrive_solutions_folder_id="solutions")
    await simpan(db_session, bangun_sla(proyek.id_project))

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200
    sla = await muat(db_session, SLATracking, project_id=proyek.id_project)
    assert sla.stopped_at is not None
    assert sla.is_locked is False
    assert fake_drive.panggilan == []


async def test_dq_tanpa_tracker_sla_tetap_tersimpan(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200
    assert await _dq_tersimpan(db_session, proyek.id_project) == DQ
    assert (await db_session.execute(select(SLATracking))).scalars().all() == []


async def test_edit_dq_oleh_lead_sa_tidak_menghentikan_ulang_timer(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(
        db_session,
        dunia,
        status="Ready",
        dq_number="DQ-LAMA-1",
        gdrive_solutions_folder_id="solutions",
    )
    await simpan(db_session, bangun_sla(proyek.id_project, is_locked=True))

    resp = await _input_dq(api, proyek.id_project, "DQ-BARU-2", dunia.header["Lead_SA"])

    assert resp.status_code == 200
    sla = await muat(db_session, SLATracking, project_id=proyek.id_project)
    assert sla.stopped_at is None
    assert sla.is_locked is True
    assert fake_drive.panggilan == []


async def test_unlock_drive_gagal_dq_tetap_tersimpan_kunci_tetap(api, db_session, fake_drive):
    fake_drive.fail_always("unlock_solutions_folder")
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, gdrive_solutions_folder_id="solutions")
    await simpan(db_session, bangun_sla(proyek.id_project, is_locked=True))

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    assert await _dq_tersimpan(db_session, proyek.id_project) == DQ
    sla = await muat(db_session, SLATracking, project_id=proyek.id_project)
    assert sla.stopped_at is not None
    assert sla.is_locked is True  # belum terbuka karena Drive gagal
    assert fake_drive.peran("solutions", dunia.user["Sales"].email) is None


async def test_kegagalan_stop_timer_tidak_menggagalkan_input_dq(api, db_session, monkeypatch):
    monkeypatch.setattr(sla_timer, "stop_timer", AsyncMock(side_effect=RuntimeError("boom")))
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])

    assert resp.status_code == 200, resp.text
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.dq_number, baris.status) == (DQ, "Ready")


# --------------------------------------------------------------------------- read-gating Solutions


async def _solutions(api, id_project, header):
    return await api.client.get(f"{API}/projects/{id_project}/documents/solutions", headers=header)


async def test_sales_tanpa_dq_tidak_melihat_dokumen_solutions(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    await buat_dokumen(db_session, proyek, dunia, status="Final")

    resp = await _solutions(api, proyek.id_project, dunia.header["Sales"])

    assert resp.status_code == 200
    assert resp.json()["data"] == {"documents": [], "total": 0, "dq_required": True}


async def test_sales_dengan_dq_hanya_melihat_solutions_reviewed_atau_final(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, dq_number=DQ)
    draft = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", status="Draft")
    reviewed = await buat_dokumen(db_session, proyek, dunia, doc_type="Mandays", status="Reviewed")
    final = await buat_dokumen(db_session, proyek, dunia, doc_type="HLD", status="Final")
    lain_folder = await buat_dokumen(
        db_session, proyek, dunia, doc_type="MoM", status="Final", folder_type="Inventory"
    )

    resp = await _solutions(api, proyek.id_project, dunia.header["Sales"])

    assert resp.status_code == 200
    data = resp.json()["data"]
    ids = {d["id_doc"] for d in data["documents"]}
    assert ids == {reviewed.id_doc, final.id_doc}
    assert draft.id_doc not in ids and lain_folder.id_doc not in ids
    assert data["total"] == 2
    assert data["dq_number"] == DQ
    assert {d["doc_type"] for d in data["documents"]} == {"Mandays", "HLD"}


@pytest.mark.parametrize("peran", ["SA", "Lead_SA", "Admin"])
async def test_peran_internal_melihat_semua_solutions_tanpa_dq(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    solusi = [
        await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", status="Draft"),
        await buat_dokumen(db_session, proyek, dunia, doc_type="Mandays", status="Reviewed"),
    ]
    await buat_dokumen(db_session, proyek, dunia, doc_type="MoM", folder_type="Diagram")

    resp = await _solutions(api, proyek.id_project, dunia.header[peran])

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {d["id_doc"] for d in data["documents"]} == {d.id_doc for d in solusi}
    assert data["dq_number"] is None
    assert "dq_required" not in data


async def test_solutions_proyek_tidak_ada_404(api, db_session):
    dunia = await siapkan_dunia(api, db_session)

    resp = await _solutions(api, "PRJ-TIDAK-ADA", dunia.header["Lead_SA"])

    assert resp.status_code == 404


async def test_input_dq_membuka_gating_solutions_untuk_sales_secara_menyeluruh(
    api, db_session, fake_drive
):
    """Alur utuh: sebelum DQ tersembunyi, DQ diinput, dokumen Reviewed lalu terlihat."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, gdrive_solutions_folder_id="solutions")
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", status="Reviewed")

    sebelum = await _solutions(api, proyek.id_project, dunia.header["Sales"])
    await _input_dq(api, proyek.id_project, DQ, dunia.header["Sales"])
    sesudah = await _solutions(api, proyek.id_project, dunia.header["Sales"])

    assert sebelum.json()["data"]["documents"] == []
    assert [d["id_doc"] for d in sesudah.json()["data"]["documents"]] == [dokumen.id_doc]
