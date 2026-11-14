"""
Notifikasi komentar baru (issue #125, spec §2.5): semua orang yang ditugaskan di project
diberi notifikasi in-app `komentar`, kecuali penulisnya. Gmail tidak dikonfigurasi di test, jadi
hanya kanal in-app yang terekam.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import NotificationLog, ProjectAssignment
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


async def _proyek(dunia, **o):
    """Proyek dengan: sales PIC `sales`, produk PIC `produk`, SA utama `sa`, SA tambahan `sa2`,
    lead_sa `lead`, contributor, viewer; `sales_lain` dan `sa_luar` tidak terkait."""
    db = dunia.db
    kontributor = bangun_user(role="SA", name="Kontributor", email="kontrib@portal-sa.local")
    viewer = bangun_user(role="Sales", name="Viewer", email="viewer@portal-sa.local")
    sa_luar = bangun_user(role="SA", name="SA Luar", email="sa-luar@portal-sa.local")
    db.add_all([kontributor, viewer, sa_luar])
    await db.commit()
    proyek = await dunia.buat_proyek(
        status="In Progress",
        product_pic=dunia.produk.id,
        assigned_sa=dunia.sa.id,
        lead_sa=dunia.lead.id,
        project_name="Migrasi DB",
        **o,
    )
    db.add(ProjectAssignment(id_project=proyek.id_project, user_id=dunia.sa2.id, added_by=dunia.lead.id))
    db.add(bangun_kolaborator(proyek.id_project, kontributor.id, dunia.lead.id, role="contributor"))
    db.add(bangun_kolaborator(proyek.id_project, viewer.id, dunia.lead.id, role="viewer"))
    await db.commit()
    dunia.h["kontributor"] = header(kontributor)
    dunia.h["sa_luar"] = header(sa_luar)
    dunia.orang = {
        "sales": dunia.sales.id,
        "produk": dunia.produk.id,
        "sa": dunia.sa.id,
        "sa2": dunia.sa2.id,
        "lead": dunia.lead.id,
        "kontributor": kontributor.id,
        "viewer": viewer.id,
        "sa_luar": sa_luar.id,
        "sales_lain": dunia.sales_lain.id,
        "admin": dunia.admin.id,
    }
    return proyek.id_project


async def _penerima(db, id_project) -> list:
    q = select(NotificationLog).where(
        NotificationLog.event_type == "komentar", NotificationLog.reference_id == id_project
    )
    return list((await db.execute(q.execution_options(populate_existing=True))).scalars().all())


def _nama(dunia, ids) -> set[str]:
    balik = {v: k for k, v in dunia.orang.items()}
    return {balik[i] for i in ids}


SEMUA_TERKAIT = {"sales", "produk", "sa", "sa2", "lead", "kontributor", "viewer"}


@pytest.mark.parametrize("penulis", ["sales", "produk", "sa", "sa2", "lead", "kontributor"])
async def test_semua_orang_ditugaskan_diberi_notifikasi_kecuali_penulis(dunia, api, penulis):
    id_project = await _proyek(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Cek ya"}, headers=dunia.h[penulis]
    )

    assert resp.status_code == 201, resp.text
    notif = await _penerima(dunia.db, id_project)
    assert _nama(dunia, [n.recipient_user_id for n in notif]) == SEMUA_TERKAIT - {penulis}
    assert {n.channel for n in notif} == {"in-app"}


async def test_penulis_admin_tidak_terkait_tidak_menerima_tetapi_semua_orang_terkait_ya(dunia, api):
    id_project = await _proyek(dunia)

    await api.client.post(KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["admin"])

    notif = await _penerima(dunia.db, id_project)
    assert _nama(dunia, [n.recipient_user_id for n in notif]) == SEMUA_TERKAIT


async def test_pihak_luar_tidak_diberi_notifikasi(dunia, api):
    id_project = await _proyek(dunia)

    await api.client.post(KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa"])

    penerima = _nama(dunia, [n.recipient_user_id for n in await _penerima(dunia.db, id_project)])
    assert not penerima & {"sa_luar", "sales_lain", "admin"}


async def test_satu_notifikasi_per_penerima_walau_punya_beberapa_hubungan(dunia, api):
    """`lead` sekaligus lead_sa dan SA tambahan; `sa` sekaligus SA utama dan collaborator."""
    id_project = await _proyek(dunia)
    dunia.db.add(ProjectAssignment(id_project=id_project, user_id=dunia.lead.id, added_by=dunia.admin.id))
    dunia.db.add(bangun_kolaborator(id_project, dunia.sa.id, dunia.lead.id, role="contributor"))
    await dunia.db.commit()

    await api.client.post(KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sales"])

    ids = [n.recipient_user_id for n in await _penerima(dunia.db, id_project)]
    assert len(ids) == len(set(ids)) == len(SEMUA_TERKAIT - {"sales"})


async def test_metadata_notifikasi_memuat_proyek_penulis_dan_cuplikan(dunia, api):
    id_project = await _proyek(dunia)

    await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Mohon cek BOQ " + "x" * 400}, headers=dunia.h["sa"]
    )

    notif = (await _penerima(dunia.db, id_project))[0]
    meta = notif.notification_metadata
    assert meta["project_name"] == "Migrasi DB"
    assert meta["author_name"] == dunia.sa.name
    assert meta["message"].startswith(f"{dunia.sa.name} berkomentar di 'Migrasi DB'")
    assert "Mohon cek BOQ" in meta["message"]
    assert len(meta["message"]) < 400


async def test_komentar_ditolak_tidak_mengirim_notifikasi(dunia, api):
    id_project = await _proyek(dunia)

    ditolak = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sa_luar"]
    )
    kosong = await api.client.post(
        KOMENTAR.format(id_project), json={"body": " "}, headers=dunia.h["sa"]
    )

    assert (ditolak.status_code, kosong.status_code) == (403, 422)
    assert await _penerima(dunia.db, id_project) == []


async def test_kegagalan_satu_penerima_tidak_menghalangi_penerima_lain(dunia, api, monkeypatch):
    from app.services.notification_service import notification_service

    asli = notification_service.send_notification
    panggilan: list = []

    async def _kadang_gagal(event):
        panggilan.append(event.recipient_user_id)
        if len(panggilan) == 1:
            raise RuntimeError("boom")
        await asli(event)

    monkeypatch.setattr(notification_service, "send_notification", AsyncMock(side_effect=_kadang_gagal))
    id_project = await _proyek(dunia)

    resp = await api.client.post(
        KOMENTAR.format(id_project), json={"body": "Halo"}, headers=dunia.h["sales"]
    )

    assert resp.status_code == 201
    assert len(panggilan) == len(SEMUA_TERKAIT - {"sales"})
    assert len(await _penerima(dunia.db, id_project)) == len(panggilan) - 1
