"""
`On Hold` dan lanjut (issue #122, ADR 0013, spec §2.0) lewat `PATCH /projects/{id}/status`,
per peran, terhadap Postgres nyata.

- Jeda: dari `Awaiting Assignment` sampai `Submitted` oleh Lead_SA, Admin, Sales PIC, Product PIC.
  `previous_status` menyimpan status sebelum jeda.
- Lanjut: hanya kembali ke `previous_status`, oleh peran yang sama; `previous_status` dikosongkan.
- Efek ke timer SLA diuji di `test_status_on_hold_sla.py`.
"""

import pytest

from app.models import Project
from tests.integration.b6_support import muat
from tests.integration.test_workflow_transisi import (  # noqa: F401
    HAK_PIC,
    PERAN,
    Skenario,
    komit_sesi_request,
    skenario,
)

pytestmark = pytest.mark.usefixtures("komit_sesi_request")



async def _muat(s, p) -> Project:
    return await muat(s.db, Project, id_project=p.id_project)


STATUS_BOLEH_JEDA = ["Awaiting Assignment", "Assigned", "In Progress", "Submitted"]
STATUS_TIDAK_BOLEH_JEDA = ["Intake", "Won", "Handed Over", "Closed", "Lost", "On Hold"]


def _kasus_jeda():
    return [
        pytest.param(awal, peran, peran in HAK_PIC, id=f"{awal}-{peran}")
        for awal in STATUS_BOLEH_JEDA
        for peran in PERAN
    ]


@pytest.mark.parametrize(("awal", "peran", "boleh"), _kasus_jeda())
async def test_jeda_per_peran(skenario, awal, peran, boleh):
    s = skenario
    p = await s.proyek(awal)

    resp = await s.ubah(p, "On Hold", peran)

    if boleh:
        assert resp.status_code == 200, resp.text
        proyek = await _muat(s, p)
        assert (proyek.status, proyek.previous_status) == ("On Hold", awal)
    else:
        assert resp.status_code == 403, resp.text
        assert await s.status(p) == awal


@pytest.mark.parametrize("awal", STATUS_TIDAK_BOLEH_JEDA)
async def test_jeda_ditolak_dari_status_di_luar_rentang(skenario, awal):
    s = skenario
    p = await s.proyek(awal)

    resp = await s.ubah(p, "On Hold", "Admin")

    assert resp.status_code == 400, resp.text
    assert await s.status(p) == awal


async def test_jeda_tercatat_di_audit_log_dengan_alasan(skenario):
    s = skenario
    p = await s.proyek("In Progress")

    resp = await s.ubah(p, "On Hold", "Sales_PIC", reason="Customer menunda anggaran")

    assert resp.status_code == 200, resp.text
    audit = [a for a in await s.audit(p) if a.action == "status_change"]
    assert len(audit) == 1
    assert audit[0].old_value == {"status": "In Progress"}
    assert audit[0].new_value["status"] == "On Hold"
    assert audit[0].new_value["reason"] == "Customer menunda anggaran"
    assert audit[0].new_value["aksi"] == "jeda"
    assert audit[0].performed_by == s.user["Sales"].id


def _kasus_lanjut():
    return [
        pytest.param(peran, peran in HAK_PIC, id=peran)
        for peran in PERAN
    ]


@pytest.mark.parametrize(("peran", "boleh"), _kasus_lanjut())
@pytest.mark.parametrize("sebelum", STATUS_BOLEH_JEDA)
async def test_lanjut_kembali_ke_previous_status_per_peran(skenario, sebelum, peran, boleh):
    s = skenario
    p = await s.proyek("On Hold", previous_status=sebelum)

    resp = await s.ubah(p, sebelum, peran)

    if boleh:
        assert resp.status_code == 200, resp.text
        proyek = await _muat(s, p)
        assert (proyek.status, proyek.previous_status) == (sebelum, None)
    else:
        assert resp.status_code == 403, resp.text
        assert await s.status(p) == "On Hold"


async def test_lanjut_ke_status_selain_previous_status_ditolak(skenario):
    s = skenario
    p = await s.proyek("On Hold", previous_status="Assigned")

    resp = await s.ubah(p, "Submitted", "Admin")

    assert resp.status_code == 400, resp.text
    assert "Assigned" in resp.json()["message"]
    assert await s.status(p) == "On Hold"


async def test_lanjut_tanpa_previous_status_ditolak(skenario):
    s = skenario
    p = await s.proyek("On Hold", previous_status=None)
    p.previous_status = None
    await s.db.commit()

    resp = await s.ubah(p, "Assigned", "Admin")

    assert resp.status_code == 400, resp.text
    assert await s.status(p) == "On Hold"


async def test_lanjut_tercatat_di_audit_log(skenario):
    s = skenario
    p = await s.proyek("On Hold", previous_status="Submitted")

    resp = await s.ubah(p, "Submitted", "Lead_SA", reason="Anggaran cair")

    assert resp.status_code == 200, resp.text
    audit = [a for a in await s.audit(p) if a.action == "status_change"]
    assert audit[-1].old_value == {"status": "On Hold"}
    assert audit[-1].new_value["status"] == "Submitted"
    assert audit[-1].new_value["aksi"] == "lanjut"
    assert audit[-1].new_value["reason"] == "Anggaran cair"


async def test_jeda_lalu_lanjut_penuh_lewat_api(skenario):
    s = skenario
    p = await s.proyek("In Progress")

    assert (await s.ubah(p, "On Hold", "Lead_SA")).status_code == 200
    assert (await s.ubah(p, "In Progress", "Lead_SA")).status_code == 200

    proyek = await _muat(s, p)
    assert (proyek.status, proyek.previous_status) == ("In Progress", None)


async def test_lost_dari_on_hold_mempertahankan_previous_status_sebelum_jeda(skenario):
    s = skenario
    p = await s.proyek("In Progress")
    assert (await s.ubah(p, "On Hold", "Lead_SA")).status_code == 200

    resp = await s.ubah(p, "Lost", "Lead_SA", reason="Customer batal")

    assert resp.status_code == 200, resp.text
    proyek = await _muat(s, p)
    assert (proyek.status, proyek.previous_status) == ("Lost", "In Progress")


async def test_closed_menyimpan_previous_status_handed_over(skenario):
    s = skenario
    p = await s.proyek("Handed Over")

    resp = await s.ubah(p, "Closed", "Lead_SA")

    assert resp.status_code == 200, resp.text
    proyek = await _muat(s, p)
    assert (proyek.status, proyek.previous_status) == ("Closed", "Handed Over")
