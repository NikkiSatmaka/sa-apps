"""
Integrasi API komentar project (issue #125, spec §2.0, §2.5, A5) terhadap Postgres nyata.

Menulis: orang yang ditugaskan (Sales/Product PIC, SA utama/tambahan, collaborator contributor),
Lead_SA, Admin. Membaca: semua pengguna terautentikasi. Ditolak 409 pada proyek Closed/Lost,
404 pada proyek soft-deleted atau tidak ada. Notifikasi: lihat `test_komentar_notifikasi.py`.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import Project, ProjectAssignment, ProjectComment
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_kolaborator, bangun_user
from tests.integration.support_assignment import bangun_dunia, header

KOMENTAR = "/api/v1/projects/{}/comments"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _proyek_lengkap(dunia, **o):
    """Proyek 'In Progress': sales PIC, produk PIC, SA utama `sa`, SA tambahan `sa2`, serta
    dua collaborator (contributor dan viewer) dan satu SA yang tidak terkait."""
    db = dunia.db
    kontributor = bangun_user(role="SA", name="Kontributor", email="kontrib@portal-sa.local")
    viewer = bangun_user(role="Sales", name="Viewer", email="viewer@portal-sa.local")
    sa_luar = bangun_user(role="SA", name="SA Luar", email="sa-luar@portal-sa.local")
    db.add_all([kontributor, viewer, sa_luar])
    await db.commit()
    o.setdefault("status", "In Progress")
    proyek = await dunia.buat_proyek(
        product_pic=dunia.produk.id, assigned_sa=dunia.sa.id, lead_sa=dunia.lead.id, **o
    )
    db.add(ProjectAssignment(id_project=proyek.id_project, user_id=dunia.sa2.id, added_by=dunia.lead.id))
    db.add(
        bangun_kolaborator(
            proyek.id_project, kontributor.id, dunia.lead.id, role="contributor"
        )
    )
    db.add(bangun_kolaborator(proyek.id_project, viewer.id, dunia.lead.id, role="viewer"))
    await db.commit()
    dunia.h["kontributor"] = header(kontributor)
    dunia.h["viewer"] = header(viewer)
    dunia.h["sa_luar"] = header(sa_luar)
    return proyek.id_project


async def _komentar_tersimpan(db, id_project):
    q = select(ProjectComment).where(ProjectComment.id_project == id_project)
    return (await db.execute(q.order_by(ProjectComment.created_at))).scalars().all()


# ------------------------------------------------------------------------------ tulis


@pytest.mark.parametrize(
    "peran", ["sales", "produk", "sa", "sa2", "kontributor", "lead", "admin"]
)
async def test_tulis_komentar_oleh_yang_ditugaskan_lead_dan_admin(dunia, api, peran):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Mohon cek BOQ"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["id_comment"].startswith("CMT-")
    assert (data["id_project"], data["body"]) == (id_project, "Mohon cek BOQ")
    tersimpan = await _komentar_tersimpan(dunia.db, id_project)
    assert [(k.body, str(k.author_id)) for k in tersimpan] == [
        ("Mohon cek BOQ", data["author_id"])
    ]


@pytest.mark.parametrize("peran", ["sales_lain", "sa_luar", "viewer"])
async def test_tulis_komentar_ditolak_untuk_yang_tidak_ditugaskan_dan_viewer(dunia, api, peran):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 403
    assert await _komentar_tersimpan(dunia.db, id_project) == []


async def test_tulis_komentar_tanpa_login_401(dunia, api):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(KOMENTAR.format(id_project), json={"body": "Halo"})

    assert resp.status_code in (401, 403)
    assert await _komentar_tersimpan(dunia.db, id_project) == []


@pytest.mark.parametrize("status_proyek", ["Closed", "Lost"])
@pytest.mark.parametrize("peran", ["sa", "admin"])
async def test_tulis_komentar_pada_proyek_read_only_409(dunia, api, status_proyek, peran):
    id_project = await _proyek_lengkap(dunia, status=status_proyek)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 409
    assert await _komentar_tersimpan(dunia.db, id_project) == []


async def test_proyek_read_only_tetap_403_bagi_yang_tidak_berhak(dunia, api):
    id_project = await _proyek_lengkap(dunia, status="Closed")

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa_luar"]
    )

    assert resp.status_code == 403


async def test_tulis_komentar_proyek_tidak_ada_404(dunia, api):
    resp = await api.client.post(
        KOMENTAR.format("PRJ-GAIB"), json={"body": "Halo"}, headers=dunia.h["admin"]
    )

    assert resp.status_code == 404


async def test_tulis_komentar_proyek_soft_deleted_404(dunia, api):
    id_project = await _proyek_lengkap(
        dunia, deleted_at=datetime(2030, 1, 1, tzinfo=timezone.utc), deleted_by=dunia.admin.id
    )

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["admin"]
    )

    assert resp.status_code == 404
    assert await _komentar_tersimpan(dunia.db, id_project) == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"body": ""}, {"body": "   "}, {"body": "\n\t"}, {"body": "x" * 4001}, {"body": 5}],
)
async def test_tulis_komentar_body_tidak_valid_422(dunia, api, payload):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json=payload, headers=dunia.h["sa"]
    )

    assert resp.status_code == 422
    assert await _komentar_tersimpan(dunia.db, id_project) == []


async def test_tulis_komentar_body_maksimum_diterima_dan_spasi_tepi_dirapikan(dunia, api):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "  " + "x" * 4000 + "\n"}, headers=dunia.h["sa"]
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["body"] == "x" * 4000


async def test_komentar_tidak_dapat_diedit_atau_dihapus(dunia, api):
    id_project = await _proyek_lengkap(dunia)
    buat = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa"]
    )
    url = f"{KOMENTAR.format(id_project)}/{buat.json()['data']['id_comment']}"

    assert (await api.client.patch(url, json={"body": "Ubah"}, headers=dunia.h["admin"])).status_code in (404, 405)
    assert (await api.client.delete(url, headers=dunia.h["admin"])).status_code in (404, 405)
    assert [k.body for k in await _komentar_tersimpan(dunia.db, id_project)] == ["Halo"]


async def test_komentar_tidak_mengubah_project_story(dunia, api):
    from app.models import ActivityLog

    id_project = await _proyek_lengkap(dunia)

    await api.client.post(KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa"])

    logs = (await dunia.db.execute(select(ActivityLog).where(ActivityLog.id_project == id_project))).all()
    assert logs == []


async def test_kegagalan_notifikasi_tidak_menggagalkan_komentar(dunia, api, monkeypatch):
    from app.services.notification_service import notification_service

    monkeypatch.setattr(
        notification_service, "send_notification", AsyncMock(side_effect=RuntimeError("boom"))
    )
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa"]
    )

    assert resp.status_code == 201
    assert len(await _komentar_tersimpan(dunia.db, id_project)) == 1


# ------------------------------------------------------------------------------- baca


@pytest.mark.parametrize(
    "peran", ["sales", "sales_lain", "produk", "sa", "sa_luar", "viewer", "kontributor", "lead", "admin"]
)
async def test_baca_komentar_terbuka_untuk_semua_pengguna_terautentikasi(dunia, api, peran):
    id_project = await _proyek_lengkap(dunia)
    await api.client.post(KOMENTAR.format(id_project), json={"body": "Satu"}, headers=dunia.h["sa"])

    resp = await api.client.get(KOMENTAR.format(id_project), headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    assert [k["body"] for k in resp.json()["data"]["items"]] == ["Satu"]


async def test_baca_komentar_tanpa_login_ditolak(dunia, api):
    id_project = await _proyek_lengkap(dunia)

    resp = await api.client.get(KOMENTAR.format(id_project))

    assert resp.status_code in (401, 403)


async def test_baca_komentar_urut_kronologis_naik_dengan_nama_dan_peran_penulis(dunia, api):
    id_project = await _proyek_lengkap(dunia)
    for peran, teks in [("sales", "Pertama"), ("sa", "Kedua"), ("admin", "Ketiga")]:
        r = await api.client.post(
            KOMENTAR.format(id_project), json={"body": teks}, headers=dunia.h[peran]
        )
        assert r.status_code == 201, r.text

    resp = await api.client.get(KOMENTAR.format(id_project), headers=dunia.h["produk"])

    data = resp.json()["data"]
    assert data["total"] == 3
    assert [(k["body"], k["author_name"], k["author_role"]) for k in data["items"]] == [
        ("Pertama", dunia.sales.name, "Sales"),
        ("Kedua", dunia.sa.name, "SA"),
        ("Ketiga", dunia.admin.name, "Admin"),
    ]


async def test_baca_komentar_hanya_milik_proyek_itu(dunia, api):
    a = await _proyek_lengkap(dunia)
    b = (await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)).id_project
    await api.client.post(KOMENTAR.format(a), json={"body": "Di A"}, headers=dunia.h["sa"])

    resp = await api.client.get(KOMENTAR.format(b), headers=dunia.h["sa"])

    assert resp.json()["data"] == {"items": [], "total": 0}


async def test_baca_komentar_proyek_read_only_tetap_diizinkan(dunia, api):
    id_project = await _proyek_lengkap(dunia)
    await api.client.post(KOMENTAR.format(id_project), json={"body": "Lama"}, headers=dunia.h["sa"])
    proyek = await dunia.db.get(Project, id_project)
    proyek.status = "Closed"
    await dunia.db.commit()

    resp = await api.client.get(KOMENTAR.format(id_project), headers=dunia.h["sales_lain"])

    assert resp.status_code == 200
    assert [k["body"] for k in resp.json()["data"]["items"]] == ["Lama"]


async def test_baca_komentar_proyek_tidak_ada_atau_soft_deleted_404(dunia, api):
    terhapus = await _proyek_lengkap(
        dunia, deleted_at=datetime(2030, 1, 1, tzinfo=timezone.utc), deleted_by=dunia.admin.id
    )

    for id_project in ("PRJ-GAIB", terhapus):
        resp = await api.client.get(KOMENTAR.format(id_project), headers=dunia.h["admin"])
        assert resp.status_code == 404

