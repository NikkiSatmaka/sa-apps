"""
Integrasi API subtask terhadap Postgres nyata (tiket B5 #58, spec #49): buat, daftar, ubah
status, assign/reassign/lepas penugasan, dan hapus, dengan hak akses per peran
(Lead_SA/Admin, SA pemilik, SA lain, Sales PIC, collaborator, tanpa login).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Project, ProjectAssignment, Subtask
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
    id_project, sid = await _siapkan(dunia)
    # Assignee harus anggota tim SA project (ADR 0014): sa2 dijadikan SA tambahan.
    dunia.db.add(ProjectAssignment(id_project=id_project, user_id=dunia.sa2.id, added_by=dunia.lead.id))
    await dunia.db.commit()
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


# Lead_SA kini assignee sah (ADR 0014; dilindungi test_tim_sa_api.py), jadi tidak lagi di sini.
@pytest.mark.parametrize("target", ["sales_lain"])
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


# ----------------------------------------------------------------------------- subtask kaya (#124)

LALU = "2000-01-01"  # selalu sudah lewat
DEPAN = "2999-12-31"  # selalu belum tiba


async def _kolom_kaya(db, id_subtask):
    st = await _status_tersimpan(db, id_subtask)
    return st.description, st.due_date, st.estimate_hours


async def test_buat_subtask_dengan_description_due_date_dan_estimate_hours(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project),
        json={
            "title": "Susun HLD",
            "description": "Draf HLD v1",
            "due_date": DEPAN,
            "estimate_hours": "12.5",
        },
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["description"] == "Draf HLD v1"
    assert data["due_date"] == DEPAN
    assert Decimal(data["estimate_hours"]) == Decimal("12.5")
    assert data["terlambat"] is False
    [tersimpan] = await daftar_subtask(dunia.db, proyek.id_project)
    assert (tersimpan.description, tersimpan.due_date) == ("Draf HLD v1", date(2999, 12, 31))
    assert tersimpan.estimate_hours == Decimal("12.50")


async def test_buat_subtask_tanpa_field_baru_menghasilkan_null_dan_tidak_terlambat(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project), json={"title": "Polos"}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert (data["description"], data["due_date"], data["estimate_hours"]) == (None, None, None)
    assert data["terlambat"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"estimate_hours": "-1"},
        {"estimate_hours": "-0.01"},
        {"estimate_hours": "abc"},
        {"estimate_hours": "1.234"},
        {"estimate_hours": "100000"},
        {"due_date": "bukan-tanggal"},
        {"description": "x" * 2001},
    ],
)
async def test_buat_subtask_field_baru_tidak_valid_422_dan_tidak_tersimpan(dunia, api, body):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project),
        json={"title": "Salah", **body},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 422, resp.text
    assert await daftar_subtask(dunia.db, proyek.id_project) == []


@pytest.mark.parametrize("jam", ["0", "0.00", "99999.99"])
async def test_buat_subtask_estimate_hours_batas_valid_diterima(dunia, api, jam):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        SUBTASK_PROYEK.format(proyek.id_project),
        json={"title": "Batas", "estimate_hours": jam},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("peran", ["sa", "lead", "admin"])
async def test_ubah_field_subtask_oleh_pemilik_atau_privileged(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid),
        json={"description": "Uraian", "due_date": DEPAN, "estimate_hours": "4"},
        headers=dunia.h[peran],
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["description"], data["due_date"]) == ("Uraian", DEPAN)
    assert Decimal(data["estimate_hours"]) == Decimal("4")
    assert await _kolom_kaya(dunia.db, sid) == ("Uraian", date(2999, 12, 31), Decimal("4.00"))


@pytest.mark.parametrize("peran", ["sa2", "sales"])
async def test_non_pemilik_tidak_boleh_mengubah_field_subtask(dunia, api, peran):
    _, sid = await _siapkan(dunia)

    resp = await api.client.patch(
        SUBTASK.format(sid), json={"description": "Retas"}, headers=dunia.h[peran]
    )

    assert resp.status_code == 403
    assert await _kolom_kaya(dunia.db, sid) == (None, None, None)


async def test_sa_pemilik_yang_sudah_dilepas_dari_proyek_tidak_boleh_mengubah_field(dunia, api):
    id_project, sid = await _siapkan(dunia)
    await dunia.db.execute(
        ProjectAssignment.__table__.delete().where(ProjectAssignment.id_project == id_project)
    )
    proyek = await dunia.db.get(Project, id_project)
    proyek.assigned_sa = None
    await dunia.db.commit()

    resp = await api.client.patch(
        SUBTASK.format(sid), json={"description": "Retas"}, headers=dunia.h["sa"]
    )

    assert resp.status_code == 403
    assert await _kolom_kaya(dunia.db, sid) == (None, None, None)


async def test_ubah_sebagian_field_tidak_menyentuh_field_lain(dunia, api):
    _, sid = await _siapkan(
        dunia, description="Lama", due_date=date(2999, 1, 1), estimate_hours=Decimal("8")
    )

    resp = await api.client.patch(
        SUBTASK.format(sid), json={"estimate_hours": "9.5"}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert await _kolom_kaya(dunia.db, sid) == ("Lama", date(2999, 1, 1), Decimal("9.50"))


async def test_ubah_field_dengan_null_mengosongkan_field_due_date_boleh_kosong(dunia, api):
    _, sid = await _siapkan(
        dunia, description="Lama", due_date=date(2999, 1, 1), estimate_hours=Decimal("8")
    )

    resp = await api.client.patch(
        SUBTASK.format(sid),
        json={"description": None, "due_date": None, "estimate_hours": None},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert await _kolom_kaya(dunia.db, sid) == (None, None, None)


async def test_description_kosong_atau_spasi_disimpan_sebagai_null(dunia, api):
    _, sid = await _siapkan(dunia, description="Lama")

    resp = await api.client.patch(
        SUBTASK.format(sid), json={"description": "   "}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert (await _kolom_kaya(dunia.db, sid))[0] is None


@pytest.mark.parametrize(
    "body",
    [
        {"estimate_hours": "-1"},
        {"estimate_hours": "-0.5"},
        {"due_date": "31-12-2030"},
        {"description": "x" * 2001},
        {},
    ],
)
async def test_ubah_field_tidak_valid_422_dan_tidak_mengubah_data(dunia, api, body):
    _, sid = await _siapkan(dunia, estimate_hours=Decimal("8"))

    resp = await api.client.patch(SUBTASK.format(sid), json=body, headers=dunia.h["lead"])

    assert resp.status_code == 422, resp.text
    assert await _kolom_kaya(dunia.db, sid) == (None, None, Decimal("8.00"))


async def test_ubah_field_tidak_ada_404_dan_tanpa_login(dunia, api):
    _, sid = await _siapkan(dunia)

    tidak_ada = await api.client.patch(
        SUBTASK.format("SUB-TIDAK-ADA"), json={"description": "X"}, headers=dunia.h["lead"]
    )
    tanpa_login = await api.client.patch(SUBTASK.format(sid), json={"description": "X"})

    assert tidak_ada.status_code == 404
    assert tanpa_login.status_code in (401, 403)


async def test_ubah_field_tidak_mengubah_status_maupun_penugasan(dunia, api):
    _, sid = await _siapkan(dunia, status="in_progress")

    await api.client.patch(SUBTASK.format(sid), json={"description": "X"}, headers=dunia.h["lead"])

    st = await _status_tersimpan(dunia.db, sid)
    assert (st.status, st.assigned_sa) == ("in_progress", dunia.sa.id)


@pytest.mark.parametrize(
    ("due", "status", "terlambat"),
    [
        (LALU, "open", True),
        (LALU, "in_progress", True),
        (LALU, "done", False),
        (DEPAN, "open", False),
        (None, "open", False),
    ],
)
async def test_daftar_subtask_menandai_terlambat_hanya_bila_lewat_due_date_dan_belum_done(
    dunia, api, due, status, terlambat
):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    st = bangun_subtask(
        proyek.id_project,
        status=status,
        due_date=date.fromisoformat(due) if due else None,
        description="Uraian",
        estimate_hours=Decimal("3"),
    )
    dunia.db.add(st)
    await dunia.db.commit()

    resp = await api.client.get(SUBTASK_PROYEK.format(proyek.id_project), headers=dunia.h["lead"])

    [item] = resp.json()["data"]["items"]
    assert item["terlambat"] is terlambat
    assert item["due_date"] == due
    assert (item["description"], Decimal(item["estimate_hours"])) == ("Uraian", Decimal("3"))


async def test_ubah_status_dan_assign_juga_mengembalikan_field_baru(dunia, api):
    _, sid = await _siapkan(dunia, description="U", due_date=date(2000, 1, 1))

    status_resp = await api.client.patch(
        SUBTASK.format(sid) + "/status", json={"status": "done"}, headers=dunia.h["lead"]
    )
    assign_resp = await api.client.patch(
        SUBTASK.format(sid) + "/assign",
        json={"assigned_sa": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert status_resp.json()["data"]["terlambat"] is False  # sudah done
    assert assign_resp.json()["data"]["description"] == "U"
