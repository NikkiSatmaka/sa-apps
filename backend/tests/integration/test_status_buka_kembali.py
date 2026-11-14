"""
Buka kembali `Closed`/`Lost` (issue #122, ADR 0013, spec §2.0): hanya `is_admin`, alasan wajib
dan tercatat di audit log, status kembali ke `previous_status`.

Keputusan konservatif (spec tidak merinci): tanpa `previous_status` (data hasil migration 020)
pembukaan kembali ditolak 400 daripada menebak status tujuan; `lost_reason` lama dipertahankan.
"""

import pytest

from app.models import Project
from tests.integration.b6_support import API, muat
from tests.integration.test_workflow_transisi import (  # noqa: F401
    PERAN,
    komit_sesi_request,
    skenario,
)

pytestmark = pytest.mark.usefixtures("komit_sesi_request")


async def _muat(s, p) -> Project:
    return await muat(s.db, Project, id_project=p.id_project)


@pytest.mark.parametrize("peran", PERAN)
@pytest.mark.parametrize(
    ("awal", "kolom", "tujuan"),
    [
        ("Closed", {"previous_status": "Handed Over"}, "Handed Over"),
        ("Lost", {"previous_status": "In Progress"}, "In Progress"),
    ],
)
async def test_buka_kembali_hanya_admin(skenario, peran, awal, kolom, tujuan):
    s = skenario
    p = await s.proyek(awal, **kolom)

    resp = await s.ubah(p, tujuan, peran, reason="Customer mengajukan revisi")

    if peran == "Admin":
        assert resp.status_code == 200, resp.text
        proyek = await _muat(s, p)
        assert (proyek.status, proyek.previous_status) == (tujuan, None)
    else:
        assert resp.status_code == 403, resp.text
        assert await s.status(p) == awal


@pytest.mark.parametrize("alasan", [None, "", "   "])
async def test_buka_kembali_tanpa_alasan_ditolak(skenario, alasan):
    s = skenario
    p = await s.proyek("Closed", previous_status="Handed Over")
    extra = {} if alasan is None else {"reason": alasan}

    resp = await s.ubah(p, "Handed Over", "Admin", **extra)

    assert resp.status_code == 400, resp.text
    assert "reason" in resp.json()["message"]
    assert await s.status(p) == "Closed"


async def test_buka_kembali_alasan_tercatat_di_audit_log(skenario):
    s = skenario
    p = await s.proyek("Lost", previous_status="Submitted", lost_reason="Anggaran dipotong")

    resp = await s.ubah(p, "Submitted", "Admin", reason="Anggaran cair kembali")

    assert resp.status_code == 200, resp.text
    audit = [a for a in await s.audit(p) if a.action == "status_change"]
    assert len(audit) == 1
    assert audit[0].old_value == {"status": "Lost"}
    assert audit[0].new_value["status"] == "Submitted"
    assert audit[0].new_value["aksi"] == "buka_kembali"
    assert audit[0].new_value["reason"] == "Anggaran cair kembali"
    assert audit[0].performed_by == s.user["Admin"].id


async def test_buka_kembali_mempertahankan_lost_reason_lama(skenario):
    s = skenario
    p = await s.proyek("Lost", previous_status="Submitted", lost_reason="Anggaran dipotong")

    await s.ubah(p, "Submitted", "Admin", reason="Cair")

    assert (await _muat(s, p)).lost_reason == "Anggaran dipotong"


async def test_buka_kembali_ke_status_selain_previous_status_ditolak(skenario):
    s = skenario
    p = await s.proyek("Closed", previous_status="Handed Over")

    resp = await s.ubah(p, "In Progress", "Admin", reason="x")

    assert resp.status_code == 400, resp.text
    assert "Handed Over" in resp.json()["message"]
    assert await s.status(p) == "Closed"


async def test_buka_kembali_tanpa_previous_status_ditolak(skenario):
    s = skenario
    p = await s.proyek("Lost", previous_status=None)

    resp = await s.ubah(p, "Assigned", "Admin", reason="x")

    assert resp.status_code == 400, resp.text
    assert await s.status(p) == "Lost"


async def test_setelah_dibuka_kembali_aksi_tulis_diizinkan_lagi(skenario):
    s = skenario
    p = await s.proyek("Closed", previous_status="Handed Over")
    url = f"{API}/projects/{p.id_project}/subtasks"
    assert (
        await s.api.client.post(url, json={"title": "T"}, headers=s.header["Lead_SA"])
    ).status_code == 409

    assert (await s.ubah(p, "Handed Over", "Admin", reason="Revisi")).status_code == 200

    resp = await s.api.client.post(url, json={"title": "T"}, headers=s.header["Lead_SA"])
    assert resp.status_code == 201, resp.text


async def test_lost_kembali_ke_lost_dari_closed_atau_lainnya_tetap_ditolak(skenario):
    s = skenario
    p = await s.proyek("Closed", previous_status="Handed Over")

    resp = await s.ubah(p, "Lost", "Admin", reason="x")

    assert resp.status_code == 400, resp.text
