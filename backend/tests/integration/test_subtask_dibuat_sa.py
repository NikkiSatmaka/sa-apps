"""
Integrasi #147: SA yang ditugaskan boleh membuat subtask (spec §2.0 / §2.5).

`POST /projects/{id}/subtasks`: SA utama, SA tambahan, Lead_SA, Admin boleh (201); Sales/Product
PIC, SA yang tidak ditugaskan, collaborator (viewer maupun contributor) ditolak 403; proyek
`Closed`/`Lost` 409 (cek 403 lebih dulu). Subtask buatan SA berassignee kosong (keputusan
konservatif: Lead_SA yang menugaskan). Ubah field/status tetap pemilik atau Lead_SA/Admin;
`assign` dan hapus tetap Lead_SA/Admin.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.project_assignment import ProjectAssignment
from app.models.subtask import Subtask
from tests.integration.model_helpers import bangun_user, simpan
from tests.integration.support_akses import ID_PROYEK

API = "/api/v1"
URL = f"{API}/projects/{ID_PROYEK}/subtasks"
BODY = {"title": "Subtask dari SA"}


async def _jumlah_subtask(db) -> int:
    return (await db.execute(select(func.count()).select_from(Subtask))).scalar_one()


async def _tambah_aktor(db, skenario, kunci: str, role: str) -> None:
    user = bangun_user(role=role, email=f"{kunci}@akses.test", google_id=f"g-{kunci}")
    await simpan(db, user)
    skenario.aktor[kunci] = user


async def _akhiri_proyek(db, skenario, status_proyek: str) -> None:
    skenario.proyek.status = status_proyek
    if status_proyek == "Lost":
        skenario.proyek.lost_reason = "Anggaran dipotong"  # wajib oleh chk_projects_lost_reason
    await db.commit()


async def _jadikan_sa_tambahan(db, skenario) -> None:
    await _tambah_aktor(db, skenario, "sa_tambahan", "SA")
    db.add(
        ProjectAssignment(
            id_project=ID_PROYEK,
            user_id=skenario.aktor["sa_tambahan"].id,
            added_by=skenario.aktor["lead"].id,
        )
    )
    await db.commit()


@pytest.mark.parametrize("aktor", ["sa", "sa_tambahan", "lead", "admin"])
async def test_buat_subtask_berhak_201_dengan_assignee_kosong(
    api, db_session, skenario_akses, aktor
):
    await _jadikan_sa_tambahan(db_session, skenario_akses)

    resp = await api.client.post(URL, json=BODY, headers=skenario_akses.header(aktor))

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Subtask dari SA"
    assert data["status"] == "open"
    assert data["assigned_sa"] is None


@pytest.mark.parametrize(
    "aktor",
    ["sales_pic", "product_pic", "sa_luar", "sales_luar", "kolab_viewer", "kolab_contrib"],
)
async def test_buat_subtask_tidak_berhak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, aktor
):
    # Product PIC: user berperan Product yang menjadi product_pic proyek.
    await _tambah_aktor(db_session, skenario_akses, "product_pic", "Product")
    skenario_akses.proyek.product_pic = skenario_akses.aktor["product_pic"].id
    await db_session.commit()
    sebelum = await _jumlah_subtask(db_session)

    resp = await api.client.post(URL, json=BODY, headers=skenario_akses.header(aktor))

    assert resp.status_code == 403, resp.text
    assert await _jumlah_subtask(db_session) == sebelum


@pytest.mark.parametrize("status_proyek", ["Closed", "Lost"])
@pytest.mark.parametrize("aktor", ["sa", "lead", "admin"])
async def test_buat_subtask_proyek_selesai_409(
    api, db_session, skenario_akses, aktor, status_proyek
):
    await _akhiri_proyek(db_session, skenario_akses, status_proyek)

    resp = await api.client.post(URL, json=BODY, headers=skenario_akses.header(aktor))

    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize("status_proyek", ["Closed", "Lost"])
async def test_buat_subtask_proyek_selesai_cek_403_lebih_dulu(
    api, db_session, skenario_akses, status_proyek
):
    await _akhiri_proyek(db_session, skenario_akses, status_proyek)

    resp = await api.client.post(URL, json=BODY, headers=skenario_akses.header("sa_luar"))

    assert resp.status_code == 403, resp.text


async def test_buat_subtask_proyek_tak_ada_404(api, skenario_akses):
    resp = await api.client.post(
        f"{API}/projects/PRJ-TIDAK-ADA/subtasks", json=BODY, headers=skenario_akses.header("sa")
    )
    assert resp.status_code == 404, resp.text


async def test_sa_pembuat_bukan_pemilik_tidak_boleh_ubah_status_assign_hapus(
    api, db_session, skenario_akses
):
    """Subtask buatan SA berassignee kosong: SA pembuat bukan pemilik, jadi tetap 403."""
    buat = await api.client.post(URL, json=BODY, headers=skenario_akses.header("sa"))
    assert buat.status_code == 201, buat.text
    id_subtask = buat.json()["data"]["id_subtask"]
    header = skenario_akses.header("sa")

    status_resp = await api.client.patch(
        f"{API}/projects/subtasks/{id_subtask}/status", json={"status": "done"}, headers=header
    )
    field_resp = await api.client.patch(
        f"{API}/projects/subtasks/{id_subtask}", json={"description": "x"}, headers=header
    )
    assign_resp = await api.client.patch(
        f"{API}/projects/subtasks/{id_subtask}/assign",
        json={"assigned_sa": str(skenario_akses.aktor["sa"].id)},
        headers=header,
    )
    hapus_resp = await api.client.delete(f"{API}/projects/subtasks/{id_subtask}", headers=header)

    assert [r.status_code for r in (status_resp, field_resp, assign_resp, hapus_resp)] == [403] * 4


async def test_lead_sa_bisa_menugaskan_subtask_buatan_sa(
    api, db_session, skenario_akses
):
    buat = await api.client.post(URL, json=BODY, headers=skenario_akses.header("sa"))
    id_subtask = buat.json()["data"]["id_subtask"]

    resp = await api.client.patch(
        f"{API}/projects/subtasks/{id_subtask}/assign",
        json={"assigned_sa": str(skenario_akses.aktor["sa"].id)},
        headers=skenario_akses.header("lead"),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["assigned_sa"] == str(skenario_akses.aktor["sa"].id)
