"""
Integrasi `GET /api/v1/subtasks/saya` (issue #126, Tracker-4): daftar "Tugas saya" lintas project
terhadap Postgres nyata. Yang diuji: kepemilikan, penyaringan project (Closed/Lost dan soft delete),
filter status, urutan due_date (NULL di akhir, tiebreak stabil), dan bentuk respons.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_subtask
from tests.integration.support_assignment import bangun_dunia

URL = "/api/v1/subtasks/saya"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _tugas(dunia, id_project: str, pemilik, **o):
    st = bangun_subtask(id_project, assigned_sa=pemilik.id, **o)
    dunia.db.add(st)
    await dunia.db.commit()
    return st.id_subtask


async def _ambil(api, dunia, peran="sa", **params):
    resp = await api.client.get(URL, params=params, headers=dunia.h[peran])
    return resp


def _id(resp) -> list[str]:
    return [i["id_subtask"] for i in resp.json()["data"]["items"]]


async def test_tanpa_login_ditolak(api):
    resp = await api.client.get(URL)
    assert resp.status_code in (401, 403)


async def test_hanya_subtask_milik_user_sendiri(dunia, api):
    proyek = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    milik = await _tugas(dunia, proyek.id_project, dunia.sa)
    await _tugas(dunia, proyek.id_project, dunia.sa2)
    tanpa_pemilik = bangun_subtask(proyek.id_project)
    dunia.db.add(tanpa_pemilik)
    await dunia.db.commit()

    resp = await _ambil(api, dunia)

    assert resp.status_code == 200, resp.text
    assert _id(resp) == [milik]
    assert resp.json()["data"]["total"] == 1


async def test_lintas_project_dan_lead_sa_melihat_milik_sendiri_saja(dunia, api):
    p1 = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    p2 = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.lead.id)
    a = await _tugas(dunia, p1.id_project, dunia.lead)
    b = await _tugas(dunia, p2.id_project, dunia.lead)
    await _tugas(dunia, p1.id_project, dunia.sa)

    resp = await _ambil(api, dunia, "lead")

    assert resp.status_code == 200
    assert sorted(_id(resp)) == sorted([a, b])


async def test_respons_memuat_project_status_due_date_dan_estimasi(dunia, api):
    proyek = await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa.id,
        project_name="Proyek Alfa",
        customer_name="PT Alfa",
    )
    st = await _tugas(
        dunia,
        proyek.id_project,
        dunia.sa,
        title="Rancang arsitektur",
        status="in_progress",
        due_date=date(2020, 1, 1),
        estimate_hours=Decimal("6.50"),
    )

    item = (await _ambil(api, dunia)).json()["data"]["items"][0]

    assert item["id_subtask"] == st
    assert item["id_project"] == proyek.id_project
    assert item["project_name"] == "Proyek Alfa"
    assert item["customer_name"] == "PT Alfa"
    assert item["project_status"] == "In Progress"
    assert item["title"] == "Rancang arsitektur"
    assert item["status"] == "in_progress"
    assert item["due_date"] == "2020-01-01"
    assert Decimal(str(item["estimate_hours"])) == Decimal("6.5")
    assert item["terlambat"] is True


async def test_project_closed_dan_lost_tidak_ikut_secara_default(dunia, api):
    aktif = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    closed = await dunia.buat_proyek(status="Closed", assigned_sa=dunia.sa.id)
    lost = await dunia.buat_proyek(status="Lost", assigned_sa=dunia.sa.id, previous_status="In Progress")
    ada = await _tugas(dunia, aktif.id_project, dunia.sa)
    await _tugas(dunia, closed.id_project, dunia.sa)
    await _tugas(dunia, lost.id_project, dunia.sa)

    resp = await _ambil(api, dunia)

    assert _id(resp) == [ada]


async def test_opsi_sertakan_project_selesai_menyertakan_closed_dan_lost(dunia, api):
    aktif = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    closed = await dunia.buat_proyek(status="Closed", assigned_sa=dunia.sa.id)
    lost = await dunia.buat_proyek(status="Lost", assigned_sa=dunia.sa.id, previous_status="In Progress")
    ids = [await _tugas(dunia, p.id_project, dunia.sa) for p in (aktif, closed, lost)]

    resp = await _ambil(api, dunia, sertakan_project_selesai="true")

    assert sorted(_id(resp)) == sorted(ids)


async def test_project_on_hold_won_dan_handed_over_tetap_ikut(dunia, api):
    ids = []
    for status in ("On Hold", "Won", "Handed Over"):
        extra = {"previous_status": "In Progress"} if status == "On Hold" else {}
        p = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id, **extra)
        ids.append(await _tugas(dunia, p.id_project, dunia.sa))

    assert sorted(_id(await _ambil(api, dunia))) == sorted(ids)


async def test_project_soft_deleted_tidak_ikut_bahkan_dengan_opsi_selesai(dunia, api):
    aktif = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    terhapus = await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa.id,
        deleted_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        deleted_by=dunia.lead.id,
    )
    ada = await _tugas(dunia, aktif.id_project, dunia.sa)
    await _tugas(dunia, terhapus.id_project, dunia.sa)

    assert _id(await _ambil(api, dunia)) == [ada]
    assert _id(await _ambil(api, dunia, sertakan_project_selesai="true")) == [ada]


async def test_filter_status_default_semua_termasuk_done(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    ids = [
        await _tugas(dunia, p.id_project, dunia.sa, status=s)
        for s in ("open", "in_progress", "done")
    ]

    assert sorted(_id(await _ambil(api, dunia))) == sorted(ids)


async def test_filter_status_satu_dan_beberapa_nilai(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    buka = await _tugas(dunia, p.id_project, dunia.sa, status="open")
    jalan = await _tugas(dunia, p.id_project, dunia.sa, status="in_progress")
    await _tugas(dunia, p.id_project, dunia.sa, status="done")

    assert _id(await _ambil(api, dunia, status="open")) == [buka]
    resp = await api.client.get(
        URL, params=[("status", "open"), ("status", "in_progress")], headers=dunia.h["sa"]
    )
    assert sorted(_id(resp)) == sorted([buka, jalan])
    assert resp.json()["data"]["total"] == 2


async def test_status_tidak_valid_ditolak_422(dunia, api):
    resp = await _ambil(api, dunia, status="selesai")
    assert resp.status_code == 422


async def test_urut_due_date_naik_kosong_di_akhir_dengan_tiebreak_stabil(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    akhir = await _tugas(dunia, p.id_project, dunia.sa, id_subtask="ST-Z", due_date=date(2031, 5, 1))
    awal = await _tugas(dunia, p.id_project, dunia.sa, id_subtask="ST-Y", due_date=date(2031, 1, 1))
    kosong = await _tugas(dunia, p.id_project, dunia.sa, id_subtask="ST-X")
    sama_b = await _tugas(dunia, p.id_project, dunia.sa, id_subtask="ST-B", due_date=date(2031, 3, 1))
    sama_a = await _tugas(dunia, p.id_project, dunia.sa, id_subtask="ST-A", due_date=date(2031, 3, 1))

    resp = await _ambil(api, dunia)

    # Tiebreak due_date sama: created_at lalu id_subtask (created_at tiap insert berbeda,
    # jadi ST-B yang dibuat lebih dulu mendahului ST-A).
    urutan = _id(resp)
    assert urutan == [awal, sama_b, sama_a, akhir, kosong]
    assert _id(await _ambil(api, dunia)) == urutan


async def test_tanpa_subtask_mengembalikan_daftar_kosong(dunia, api):
    resp = await _ambil(api, dunia)
    assert resp.status_code == 200
    assert resp.json()["data"] == {"items": [], "total": 0}
