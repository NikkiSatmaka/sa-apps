"""
Integrasi API subtask terhadap Postgres nyata (tiket B5 #58, spec #49): buat, daftar, ubah
status, assign/reassign/lepas penugasan, dan hapus, dengan hak akses per peran
(Lead_SA/Admin, SA pemilik, SA lain, Sales PIC, collaborator, tanpa login).
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import Subtask
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_kolaborator, bangun_subtask, bangun_user
from tests.integration.support_assignment import (
    SUBTASK,
    SUBTASK_PROYEK,
    bangun_dunia,
    daftar_subtask,
    header,
)


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _siapkan(dunia, **o):
    """Proyek 'Assigned' ke SA + satu subtask milik SA itu."""
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    st = bangun_subtask(proyek.id_project, assigned_sa=dunia.sa.id, **o)
    dunia.db.add(st)
    await dunia.db.commit()
    return proyek.id_project, st.id_subtask


async def _status_tersimpan(db, id_subtask):
    q = select(Subtask).where(Subtask.id_subtask == id_subtask)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


# ----------------------------------------------------------------------------- buat


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_buat_subtask_oleh_lead_sa_atau_admin(dunia, api, peran):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project),
        json={"title": "Peer Review"},
        headers=dunia.h[peran],
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert (data["title"], data["status"], data["assigned_sa"]) == ("Peer Review", "open", None)
    assert data["id_subtask"].startswith("SUB-")
    tersimpan = await daftar_subtask(dunia.db, proyek.id_project)
    assert [(s.title, s.status) for s in tersimpan] == [("Peer Review", "open")]


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_buat_subtask_ditolak_untuk_sa_dan_sales(dunia, api, peran):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project), json={"title": "X"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 403
    assert await daftar_subtask(dunia.db, proyek.id_project) == []


async def test_buat_subtask_proyek_tidak_ada_judul_tidak_valid_dan_tanpa_login(dunia, api):
    proyek = await dunia.buat_proyek()
    url = SUBTASK_PROYEK.format(proyek.id_project)

    tanpa_proyek = await api.client.post(
        SUBTASK_PROYEK.format("PRJ-TIDAK-ADA"), json={"title": "X"}, headers=dunia.h["lead"]
    )
    kosong = await api.client.post(url, json={"title": ""}, headers=dunia.h["lead"])
    kepanjangan = await api.client.post(url, json={"title": "x" * 151}, headers=dunia.h["lead"])
    tanpa_login = await api.client.post(url, json={"title": "X"})

    assert tanpa_proyek.status_code == 404
    assert (kosong.status_code, kepanjangan.status_code) == (422, 422)
    assert tanpa_login.status_code in (401, 403)
    assert await daftar_subtask(dunia.db, proyek.id_project) == []


# ----------------------------------------------------------------------------- daftar


@pytest.mark.parametrize("peran", ["lead", "admin", "sa", "sales"])
async def test_daftar_subtask_boleh_untuk_pihak_terkait_proyek(dunia, api, peran):
    # `sa` = SA assigned, `sales` = Sales PIC; Lead/Admin bersifat privileged.
    pid, _ = await _siapkan(dunia)

    resp = await api.client.get(SUBTASK_PROYEK.format(pid), headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    isi = resp.json()["data"]
    assert isi["total"] == 1 and isi["items"][0]["assigned_sa_name"] == dunia.sa.name


async def test_daftar_subtask_semua_pengguna_boleh_membaca_termasuk_pihak_tak_terkait(dunia, api):
    pid, _ = await _siapkan(dunia)
    kolaborator = bangun_user(role="SA", email="kolab-t58@portal-sa.local")
    dunia.db.add(kolaborator)
    await dunia.db.commit()
    dunia.db.add(bangun_kolaborator(pid, kolaborator.id, dunia.lead.id))
    await dunia.db.commit()

    kolab = await api.client.get(SUBTASK_PROYEK.format(pid), headers=header(kolaborator))
    sa_lain = await api.client.get(SUBTASK_PROYEK.format(pid), headers=dunia.h["sa2"])
    sales_lain = await api.client.get(SUBTASK_PROYEK.format(pid), headers=dunia.h["sales_lain"])

    assert kolab.status_code == 200
    # Keputusan 2026-11-10: membaca terbuka untuk semua pengguna terautentikasi.
    assert (sa_lain.status_code, sales_lain.status_code) == (200, 200)


async def test_daftar_subtask_urut_pembuatan_nama_sa_dan_null_bila_belum_ditugaskan(dunia, api):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    pertama = bangun_subtask(proyek.id_project, title="Pertama", assigned_sa=dunia.sa.id)
    dunia.db.add(pertama)
    await dunia.db.commit()
    kedua = bangun_subtask(proyek.id_project, title="Kedua")
    dunia.db.add(kedua)
    await dunia.db.commit()

    resp = await api.client.get(SUBTASK_PROYEK.format(proyek.id_project), headers=dunia.h["lead"])

    items = resp.json()["data"]["items"]
    assert [(i["title"], i["assigned_sa_name"]) for i in items] == [
        ("Pertama", dunia.sa.name),
        ("Kedua", None),
    ]


async def test_daftar_subtask_proyek_tidak_ada_404_dan_proyek_tanpa_subtask_kosong(dunia, api):
    kosong = await dunia.buat_proyek()

    tidak_ada = await api.client.get(
        SUBTASK_PROYEK.format("PRJ-TIDAK-ADA"), headers=dunia.h["lead"]
    )
    resp = await api.client.get(SUBTASK_PROYEK.format(kosong.id_project), headers=dunia.h["lead"])

    assert tidak_ada.status_code == 404
    assert resp.json()["data"] == {"items": [], "total": 0}


# ----------------------------------------------------------------------------- ubah status


@pytest.mark.parametrize("status", ["in_progress", "done", "open"])
async def test_sa_pemilik_mengubah_status_subtask(dunia, api, status):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid) + "/status", json={"status": status}, headers=dunia.h["sa"]
    )

    assert resp.status_code == 200, resp.text
    assert (await _status_tersimpan(dunia.db, sid)).status == status


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_lead_sa_dan_admin_mengubah_status_subtask_siapa_pun(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid) + "/status", json={"status": "done"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 200
    assert (await _status_tersimpan(dunia.db, sid)).status == "done"


@pytest.mark.parametrize("peran", ["sa2", "sales"])
async def test_non_pemilik_tidak_boleh_mengubah_status_subtask(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid) + "/status", json={"status": "done"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 403
    assert (await _status_tersimpan(dunia.db, sid)).status == "open"


async def test_ubah_status_tidak_valid_404_dan_tanpa_login(dunia, api):
    _, sid = await _siapkan(dunia)

    invalid = await api.client.patch(
        SUBTASK.format(sid) + "/status", json={"status": "selesai"}, headers=dunia.h["lead"]
    )
    tidak_ada = await api.client.patch(
        SUBTASK.format("SUB-TIDAK-ADA") + "/status",
        json={"status": "done"},
        headers=dunia.h["lead"],
    )
    tanpa_login = await api.client.patch(SUBTASK.format(sid) + "/status", json={"status": "done"})

    assert invalid.status_code == 400 and "open" in invalid.json()["message"]
    assert tidak_ada.status_code == 404
    assert tanpa_login.status_code in (401, 403)
    assert (await _status_tersimpan(dunia.db, sid)).status == "open"


# ----------------------------------------------------------------------------- assign


async def test_assign_dan_reassign_subtask_lalu_lepas_penugasan(dunia, api):
    _, sid = await _siapkan(dunia)
    url = SUBTASK.format(sid) + "/assign"

    ke_sa2 = await api.client.patch(
        url, json={"assigned_sa": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )
    assert ke_sa2.status_code == 200, ke_sa2.text
    assert ke_sa2.json()["data"]["assigned_sa_name"] == dunia.sa2.name
    assert (await _status_tersimpan(dunia.db, sid)).assigned_sa == dunia.sa2.id

    lepas = await api.client.patch(url, json={"assigned_sa": None}, headers=dunia.h["admin"])
    assert lepas.status_code == 200
    assert lepas.json()["data"]["assigned_sa"] is None
    assert (await _status_tersimpan(dunia.db, sid)).assigned_sa is None


@pytest.mark.parametrize("target", ["sales_lain", "lead"])
async def test_assign_subtask_ke_bukan_sa_dan_user_tak_dikenal_ditolak(dunia, api, target):
    _, sid = await _siapkan(dunia)
    url = SUBTASK.format(sid) + "/assign"

    bukan_sa = await api.client.patch(
        url, json={"assigned_sa": str(getattr(dunia, target).id)}, headers=dunia.h["lead"]
    )
    tak_dikenal = await api.client.patch(
        url, json={"assigned_sa": str(uuid.uuid4())}, headers=dunia.h["lead"]
    )

    assert (bukan_sa.status_code, tak_dikenal.status_code) == (400, 400)
    assert (await _status_tersimpan(dunia.db, sid)).assigned_sa == dunia.sa.id


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_assign_subtask_ditolak_untuk_sa_dan_sales(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid) + "/assign",
        json={"assigned_sa": str(dunia.sa2.id)},
        headers=dunia.h[peran],
    )

    assert resp.status_code == 403
    assert (await _status_tersimpan(dunia.db, sid)).assigned_sa == dunia.sa.id


async def test_assign_subtask_tidak_ada_404(dunia, api):
    resp = await api.client.patch(
        SUBTASK.format("SUB-TIDAK-ADA") + "/assign",
        json={"assigned_sa": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 404


# ----------------------------------------------------------------------------- hapus


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_hapus_subtask_oleh_lead_sa_atau_admin(dunia, api, peran):
    pid, sid = await _siapkan(dunia)

    resp = await api.client.delete(SUBTASK.format(sid), headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    assert await _status_tersimpan(dunia.db, sid) is None
    assert await daftar_subtask(dunia.db, pid) == []


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_hapus_subtask_ditolak_untuk_sa_dan_sales(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.delete(SUBTASK.format(sid), headers=dunia.h[peran])

    assert resp.status_code == 403
    assert await _status_tersimpan(dunia.db, sid) is not None


async def test_hapus_subtask_tidak_ada_404(dunia, api):
    resp = await api.client.delete(SUBTASK.format("SUB-TIDAK-ADA"), headers=dunia.h["lead"])

    assert resp.status_code == 404
