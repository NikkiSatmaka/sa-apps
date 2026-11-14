"""
SA tambahan punya hak SETARA SA utama, dan ditolak pada aksi khusus Lead_SA/Admin
(issue #119, ADR 0014, spec §2.5).

Seam: HTTP API di Postgres nyata dengan `skenario_akses` bersama + satu aktor baru `sa_tambahan`
(berrole SA, tercatat di `project_assignments`, BUKAN `assigned_sa`). Matriks rute lama dipakai
ulang: sel `sa_tambahan` harus sama dengan sel `sa` (SA utama) di setiap baris.
"""

import pytest
from sqlalchemy import select

from app.core.dependencies import TingkatAkses, ensure_project_access
from app.models import ActivityLog, Document, Project, ProjectAssignment, SLATracking
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_document, bangun_user, simpan
from tests.integration.support_akses import ID_PROYEK
from tests.integration.test_akses_k5_penyelarasan_akhir import (
    API,
    RUTE_MIGRASI,
    RUTE_ROLE_GATE,
    _keadaan,
    _url,
)

pytestmark = pytest.mark.usefixtures("komit_sesi_request")


@pytest.fixture
async def skenario(db_session, skenario_akses):
    """`skenario_akses` + SA tambahan pada proyek utama."""
    tambahan = bangun_user(role="SA", email="sa-tambahan@akses.test", google_id="g-sa-tambahan")
    await simpan(db_session, tambahan)
    db_session.add(
        ProjectAssignment(
            id_project=ID_PROYEK,
            user_id=tambahan.id,
            added_by=skenario_akses.aktor["lead"].id,
        )
    )
    await db_session.commit()
    skenario_akses.aktor["sa_tambahan"] = tambahan
    return skenario_akses


# --------------------------------------------------------------------------- hak setara (matriks)


@pytest.mark.parametrize(
    "nama,method,path,body,berhak,ok",
    [pytest.param(*r, id=r[0]) for r in RUTE_MIGRASI],
)
async def test_sa_tambahan_mendapat_hasil_sama_dengan_sa_utama_di_matriks_rute(
    api,
    db_session,
    skenario,
    fake_llm,
    fake_drive,
    fake_gmail,
    nama,
    method,
    path,
    body,
    berhak,
    ok,
):
    resp = await api.client.request(
        method, _url(path, skenario), json=body, headers=skenario.header("sa_tambahan")
    )
    hasil = {"sa_tambahan": resp.status_code}
    if "sa" in berhak:
        assert hasil["sa_tambahan"] in ok, hasil
    else:
        assert hasil["sa_tambahan"] == 403, hasil


# --------------------------------------------------------------------------- aksi khusus Lead_SA


@pytest.mark.parametrize(
    "nama,method,path,body,target", [pytest.param(*r, id=r[0]) for r in RUTE_ROLE_GATE]
)
async def test_sa_tambahan_ditolak_pada_semua_aksi_khusus_lead_sa_tanpa_efek_samping(
    api, db_session, skenario, fake_llm, fake_drive, fake_gmail, nama, method, path, body, target
):
    from tests.integration.model_helpers import bangun_subtask

    subtask = bangun_subtask(ID_PROYEK)
    db_session.add(subtask)
    await db_session.commit()
    url = API + path.format(p=ID_PROYEK, s=subtask.id_subtask)
    sebelum = await _keadaan(db_session, skenario.proyek)

    resp = await api.client.request(
        method, url, json=body(skenario), headers=skenario.header("sa_tambahan")
    )

    assert resp.status_code == 403, resp.text
    assert await _keadaan(db_session, skenario.proyek) == sebelum
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/projects/{p}/tim-sa", lambda s: {"user_id": str(s.aktor["sa_luar"].id)}),
        ("PUT", "/projects/{p}/tim-sa/utama", lambda s: {"user_id": str(s.aktor["sa_luar"].id)}),
        ("DELETE", "/projects/{p}/tim-sa/{u}", lambda s: None),
    ],
    ids=["tambah", "ganti-utama", "lepas"],
)
async def test_sa_tambahan_dan_sa_utama_tidak_boleh_mengatur_tim_sa(
    api, db_session, skenario, method, path, body
):
    sebelum = await _keadaan(db_session, skenario.proyek)
    for aktor in ("sa_tambahan", "sa"):
        resp = await api.client.request(
            method,
            API + path.format(p=ID_PROYEK, u=skenario.aktor["sa_tambahan"].id),
            json=body(skenario),
            headers=skenario.header(aktor),
        )
        assert resp.status_code == 403, (aktor, resp.text)
    assert await _keadaan(db_session, skenario.proyek) == sebelum


# --------------------------------------------------------------------------- aksi SA (setara)


async def test_sa_tambahan_menulis_activity_log_dan_dokumen_dan_memajukan_status_dokumen(
    api, db_session, skenario, fake_llm
):
    h = skenario.header("sa_tambahan")
    log = await api.client.post(
        f"{API}/activity-logs",
        json={
            "id_project": ID_PROYEK,
            "project_phase": "Pre-Implementation",
            "subtask_category": "Assessment",
            "duration_hours": "1.5",
            "raw_notes": "diskusi arsitektur",
        },
        headers=h,
    )
    dokumen = await api.client.post(
        f"{API}/projects/{ID_PROYEK}/documents",
        json={
            "doc_type": "PropTek",
            "gdrive_link": "https://drive.google.com/file/d/abc",
            "folder_type": "Solutions",
        },
        headers=h,
    )
    ada = bangun_document(ID_PROYEK, skenario.aktor["sa"].id, status="Draft")
    await simpan(db_session, ada)
    await db_session.commit()
    maju = await api.client.patch(
        f"{API}/documents/{ada.id_doc}/status", json={"new_status": "Reviewed"}, headers=h
    )

    assert (log.status_code, dokumen.status_code, maju.status_code) == (201, 201, 200), (
        log.text,
        dokumen.text,
        maju.text,
    )
    pelaku = skenario.aktor["sa_tambahan"].id
    assert (
        await db_session.execute(
            select(ActivityLog.sa_id).where(ActivityLog.id_project == ID_PROYEK)
        )
    ).scalar_one() == pelaku
    assert (
        await db_session.execute(
            select(Document.created_by).where(Document.id_doc == dokumen.json()["data"]["id_doc"])
        )
    ).scalar_one() == pelaku


async def test_sa_tambahan_ubah_status_proyek_dan_cek_handover_diizinkan(
    api, db_session, skenario, fake_gmail, fake_drive
):
    h = skenario.header("sa_tambahan")

    status = await api.client.patch(
        f"{API}/projects/{ID_PROYEK}/status", json={"new_status": "Submitted"}, headers=h
    )
    cek = await api.client.get(f"{API}/projects/{ID_PROYEK}/handover-status", headers=h)

    assert status.status_code == 200, status.text
    assert cek.status_code == 200, cek.text


async def test_sa_tambahan_tidak_boleh_mengisi_dq_number(api, db_session, skenario):
    resp = await api.client.patch(
        f"{API}/projects/{ID_PROYEK}/dq-number",
        json={"dq_number": "DQ-12345"},
        headers=skenario.header("sa_tambahan"),
    )

    assert resp.status_code == 403, resp.text
    proyek = (
        await db_session.execute(
            select(Project)
            .where(Project.id_project == ID_PROYEK)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert proyek.dq_number is None
    sla = (await db_session.execute(select(SLATracking))).scalar_one()
    assert sla.stopped_at is None


async def test_sa_tambahan_menandai_dapat_regenerate_requirement_di_daftar_dokumen(api, skenario):
    sa = await api.client.get(
        f"{API}/projects/{ID_PROYEK}/documents", headers=skenario.header("sa")
    )
    tambahan = await api.client.get(
        f"{API}/projects/{ID_PROYEK}/documents", headers=skenario.header("sa_tambahan")
    )
    luar = await api.client.get(
        f"{API}/projects/{ID_PROYEK}/documents", headers=skenario.header("sa_luar")
    )

    assert sa.json()["data"]["can_regenerate_requirement"] is True
    assert tambahan.json()["data"]["can_regenerate_requirement"] is True
    assert luar.json()["data"]["can_regenerate_requirement"] is False


async def test_sa_tambahan_yang_dilepas_kehilangan_hak_tulis(api, db_session, skenario):
    h = skenario.header("sa_tambahan")
    url = f"{API}/projects/{ID_PROYEK}/documents"
    body = {
        "doc_type": "PropTek",
        "gdrive_link": "https://drive.google.com/file/d/abc",
        "folder_type": "Solutions",
    }
    sebelum = await api.client.post(url, json=body, headers=h)
    lepas = await api.client.delete(
        f"{API}/projects/{ID_PROYEK}/tim-sa/{skenario.aktor['sa_tambahan'].id}",
        headers=skenario.header("lead"),
    )
    sesudah = await api.client.post(url, json=body, headers=h)

    assert (sebelum.status_code, lepas.status_code, sesudah.status_code) == (201, 200, 403)


async def test_hubungan_sa_tambahan_tidak_privileged_dan_bukan_sales_pic(db_session, skenario):
    from fastapi import HTTPException

    proyek = skenario.proyek
    tambahan = skenario.aktor["sa_tambahan"]
    # ISI_DQ khusus Sales PIC: SA tambahan ditolak; TULIS dan KELOLA setara SA utama.
    with pytest.raises(HTTPException) as galat:
        await ensure_project_access(db_session, proyek, tambahan, TingkatAkses.ISI_DQ)
    assert galat.value.status_code == 403
    await ensure_project_access(db_session, proyek, tambahan, TingkatAkses.TULIS)
    await ensure_project_access(db_session, proyek, tambahan, TingkatAkses.KELOLA)
