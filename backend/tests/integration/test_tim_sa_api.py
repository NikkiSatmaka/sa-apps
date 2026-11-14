"""
Tim SA per project: SA utama + SA tambahan (`ProjectAssignments`) (issue #119, ADR 0014, spec §2.5).

Seam: HTTP API terhadap Postgres nyata. Mencakup tambah/lepas SA tambahan, ganti SA utama, aturan
"minimal satu SA", validasi role, audit log, hak akses (hanya Lead_SA/Admin), invarian SA utama
tidak diulang di tabel, dan validasi assignee subtask terhadap tim SA project.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import ProjectAssignment, Subtask
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_subtask, bangun_user, simpan
from tests.integration.support_assignment import (
    REASSIGN,
    SUBTASK,
    bangun_dunia,
    daftar_audit,
    header,
    rekam_background,
)

TIM = "/api/v1/projects/{}/tim-sa"
TIM_ORANG = "/api/v1/projects/{}/tim-sa/{}"
TIM_UTAMA = "/api/v1/projects/{}/tim-sa/utama"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    d = await bangun_dunia(db_session)
    # SA ketiga dan Lead_SA kedua (di luar `Dunia` bersama).
    sa3 = bangun_user(role="SA", name="Sa3", email="sa3-119@portal-sa.local")
    lead2 = bangun_user(role="Lead_SA", name="Lead2", email="lead2-119@portal-sa.local")
    await simpan(db_session, sa3)
    await simpan(db_session, lead2)
    d.sa3 = sa3
    d.lead2 = lead2
    d.h["sa3"] = header(sa3)
    d.h["lead2"] = header(lead2)
    return d


async def _proyek(dunia, **o):
    return await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id, **o)


async def _anggota(db, id_project) -> set[uuid.UUID]:
    q = select(ProjectAssignment.user_id).where(ProjectAssignment.id_project == id_project)
    return set((await db.execute(q.execution_options(populate_existing=True))).scalars())


async def _tambah_langsung(db, id_project, user_id, added_by):
    db.add(ProjectAssignment(id_project=id_project, user_id=user_id, added_by=added_by))
    await db.commit()


def _ids(daftar) -> set[str]:
    return {x["id"] for x in daftar}


# ----------------------------------------------------------------------------- baca tim


async def test_baca_tim_menampilkan_sa_utama_dan_sa_tambahan_untuk_semua_pengguna(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    for peran in ("sales", "produk", "sa3", "sa", "lead"):
        resp = await api.client.get(TIM.format(proyek.id_project), headers=dunia.h[peran])
        assert resp.status_code == 200, (peran, resp.text)
        data = resp.json()["data"]
        assert data["sa_utama"]["id"] == str(dunia.sa.id)
        assert data["sa_utama"]["name"] == dunia.sa.name
        assert _ids(data["sa_tambahan"]) == {str(dunia.sa2.id)}
        assert data["sa_tambahan"][0]["email"] == dunia.sa2.email


async def test_baca_tim_proyek_tanpa_sa_utama(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.get(TIM.format(proyek.id_project), headers=dunia.h["sales"])

    assert resp.status_code == 200
    assert resp.json()["data"] == {"sa_utama": None, "sa_tambahan": []}


async def test_baca_tim_proyek_tak_ada_404_dan_tanpa_login_401(dunia, api):
    assert (
        await api.client.get(TIM.format("PRJ-NONE"), headers=dunia.h["lead"])
    ).status_code == 404
    assert (await api.client.get(TIM.format("PRJ-NONE"))).status_code == 401


# ----------------------------------------------------------------------------- tambah


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_lead_atau_admin_menambah_sa_tambahan_dan_tercatat_di_audit(dunia, api, peran):
    proyek = await _proyek(dunia)
    pelaku = getattr(dunia, peran)

    resp = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(dunia.sa2.id)}, headers=dunia.h[peran]
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["sa_utama"]["id"] == str(dunia.sa.id)
    assert _ids(data["sa_tambahan"]) == {str(dunia.sa2.id)}
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa2.id}
    baris = (
        await dunia.db.execute(select(ProjectAssignment).execution_options(populate_existing=True))
    ).scalar_one()
    assert baris.added_by == pelaku.id
    audit = await daftar_audit(dunia.db, proyek.id_project, "sa_tambahan_ditambah")
    assert len(audit) == 1
    assert audit[0].performed_by == pelaku.id
    assert audit[0].old_value == {"sa_utama": str(dunia.sa.id), "sa_tambahan": []}
    assert audit[0].new_value == {
        "sa_utama": str(dunia.sa.id),
        "sa_tambahan": [str(dunia.sa2.id)],
    }


async def test_lead_sa_boleh_menjadi_sa_tambahan(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        TIM.format(proyek.id_project),
        json={"user_id": str(dunia.lead2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 201, resp.text
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.lead2.id}


@pytest.mark.parametrize("peran", ["sa", "sa2", "sales", "produk"])
async def test_menambah_sa_tambahan_ditolak_untuk_selain_lead_atau_admin(dunia, api, peran):
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(dunia.sa3.id)}, headers=dunia.h[peran]
    )

    assert resp.status_code == 403, resp.text
    assert await _anggota(dunia.db, proyek.id_project) == set()
    assert await daftar_audit(dunia.db, proyek.id_project, "sa_tambahan_ditambah") == []


@pytest.mark.parametrize("peran_target", ["sales", "produk"])
async def test_menambah_user_berrole_bukan_sa_atau_lead_sa_ditolak_400(dunia, api, peran_target):
    proyek = await _proyek(dunia)
    target = getattr(dunia, peran_target)

    resp = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(target.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 400, resp.text
    assert await _anggota(dunia.db, proyek.id_project) == set()


async def test_menambah_user_tak_ada_404(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(uuid.uuid4())}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 404, resp.text


async def test_menambah_sa_utama_atau_anggota_yang_sudah_ada_409(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    utama = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    ganda = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert (utama.status_code, ganda.status_code) == (409, 409)
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa2.id}


async def test_menambah_ke_proyek_tanpa_sa_utama_409(dunia, api):
    proyek = await dunia.buat_proyek()  # Awaiting Assignment, belum ada SA utama

    resp = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 409, resp.text
    assert await _anggota(dunia.db, proyek.id_project) == set()


async def test_menambah_ke_proyek_tak_ada_404_dan_body_tidak_valid_422(dunia, api):
    proyek = await _proyek(dunia)

    tak_ada = await api.client.post(
        TIM.format("PRJ-NONE"), json={"user_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )
    rusak = await api.client.post(
        TIM.format(proyek.id_project), json={"user_id": "bukan-uuid"}, headers=dunia.h["lead"]
    )

    assert (tak_ada.status_code, rusak.status_code) == (404, 422)


# ----------------------------------------------------------------------------- lepas


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_melepas_sa_tambahan_dan_tercatat_di_audit(dunia, api, peran):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa2.id), headers=dunia.h[peran]
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sa_tambahan"] == []
    assert await _anggota(dunia.db, proyek.id_project) == set()
    audit = await daftar_audit(dunia.db, proyek.id_project, "sa_tambahan_dilepas")
    assert len(audit) == 1
    assert audit[0].old_value["sa_tambahan"] == [str(dunia.sa2.id)]
    assert audit[0].new_value["sa_tambahan"] == []


async def test_melepas_sa_tambahan_ditolak_untuk_selain_lead_atau_admin(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    for peran in ("sa", "sa2", "sales"):  # termasuk SA tambahan itu sendiri
        resp = await api.client.delete(
            TIM_ORANG.format(proyek.id_project, dunia.sa2.id), headers=dunia.h[peran]
        )
        assert resp.status_code == 403, (peran, resp.text)

    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa2.id}


async def test_melepas_user_yang_bukan_anggota_tim_404(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa3.id), headers=dunia.h["lead"]
    )

    assert resp.status_code == 404, resp.text


async def test_melepas_sa_utama_tanpa_sa_tambahan_ditolak_minimal_satu_sa(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa.id), headers=dunia.h["lead"]
    )

    assert resp.status_code == 409, resp.text
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa.id


async def test_melepas_sa_utama_saat_ada_sa_tambahan_wajib_menunjuk_sa_utama_baru(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa.id), headers=dunia.h["lead"]
    )

    assert resp.status_code == 409, resp.text
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa.id
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa2.id}


async def test_melepas_sa_utama_dengan_pengganti_dari_sa_tambahan_berhasil(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa3.id, dunia.lead.id)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa.id),
        params={"sa_utama_baru": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["sa_utama"]["id"] == str(dunia.sa2.id)
    assert _ids(data["sa_tambahan"]) == {str(dunia.sa3.id)}
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa2.id
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa3.id}  # utama tak diulang
    audit = await daftar_audit(dunia.db, proyek.id_project, "sa_utama_diganti")
    assert len(audit) == 1
    assert audit[0].old_value["sa_utama"] == str(dunia.sa.id)
    assert audit[0].new_value["sa_utama"] == str(dunia.sa2.id)


async def test_pengganti_sa_utama_harus_anggota_sa_tambahan_400(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    resp = await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa.id),
        params={"sa_utama_baru": str(dunia.sa3.id)},  # bukan anggota
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400, resp.text
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa.id


# ----------------------------------------------------------------------------- ganti utama


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_ganti_sa_utama_ke_user_baru_melepas_sa_lama_secara_default(dunia, api, peran):
    proyek = await _proyek(dunia)

    resp = await api.client.put(
        TIM_UTAMA.format(proyek.id_project),
        json={"user_id": str(dunia.sa3.id)},
        headers=dunia.h[peran],
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["sa_utama"]["id"] == str(dunia.sa3.id)
    assert data["sa_tambahan"] == []
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa3.id
    assert await _anggota(dunia.db, proyek.id_project) == set()
    audit = await daftar_audit(dunia.db, proyek.id_project, "sa_utama_diganti")
    assert [(a.old_value["sa_utama"], a.new_value["sa_utama"]) for a in audit] == [
        (str(dunia.sa.id), str(dunia.sa3.id))
    ]


async def test_ganti_sa_utama_dengan_mempertahankan_sa_lama_sebagai_tambahan(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.put(
        TIM_UTAMA.format(proyek.id_project),
        json={"user_id": str(dunia.sa3.id), "pertahankan_sebagai_tambahan": True},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()["data"]["sa_tambahan"]) == {str(dunia.sa.id)}
    assert await _anggota(dunia.db, proyek.id_project) == {dunia.sa.id}


async def test_ganti_sa_utama_ke_sa_tambahan_memindahkannya_keluar_dari_tabel(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    resp = await api.client.put(
        TIM_UTAMA.format(proyek.id_project),
        json={"user_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa2.id
    assert await _anggota(dunia.db, proyek.id_project) == set()


async def test_ganti_sa_utama_ke_diri_sendiri_409_role_salah_400_user_tak_ada_404(dunia, api):
    proyek = await _proyek(dunia)
    url = TIM_UTAMA.format(proyek.id_project)

    sama = await api.client.put(url, json={"user_id": str(dunia.sa.id)}, headers=dunia.h["lead"])
    role = await api.client.put(url, json={"user_id": str(dunia.sales.id)}, headers=dunia.h["lead"])
    hilang = await api.client.put(url, json={"user_id": str(uuid.uuid4())}, headers=dunia.h["lead"])

    assert (sama.status_code, role.status_code, hilang.status_code) == (409, 400, 404)
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa.id


async def test_ganti_sa_utama_ditolak_untuk_selain_lead_atau_admin_dan_tanpa_sa_utama_409(
    dunia, api
):
    proyek = await _proyek(dunia)
    kosong = await dunia.buat_proyek()

    for peran in ("sa", "sa2", "sales"):
        resp = await api.client.put(
            TIM_UTAMA.format(proyek.id_project),
            json={"user_id": str(dunia.sa3.id)},
            headers=dunia.h[peran],
        )
        assert resp.status_code == 403, (peran, resp.text)
    tanpa_utama = await api.client.put(
        TIM_UTAMA.format(kosong.id_project),
        json={"user_id": str(dunia.sa3.id)},
        headers=dunia.h["lead"],
    )

    assert tanpa_utama.status_code == 409
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa.id


# ----------------------------------------------------------------------------- reassign lama


async def test_reassign_ke_sa_tambahan_menjaga_invarian_utama_tidak_diulang(
    dunia, api, monkeypatch
):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    await dunia.db.refresh(proyek)
    assert proyek.assigned_sa == dunia.sa2.id
    assert await _anggota(dunia.db, proyek.id_project) == set()


# ----------------------------------------------------------------------------- subtask


async def _subtask(dunia, proyek, **o):
    st = bangun_subtask(proyek.id_project, **o)
    dunia.db.add(st)
    await dunia.db.commit()
    return st


async def _assign(api, dunia, st, user_id, peran="lead"):
    return await api.client.patch(
        SUBTASK.format(st.id_subtask) + "/assign",
        json={"assigned_sa": None if user_id is None else str(user_id)},
        headers=dunia.h[peran],
    )


async def _penugasan(db, id_subtask):
    q = select(Subtask).where(Subtask.id_subtask == id_subtask)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one().assigned_sa


async def test_subtask_boleh_ke_sa_utama_sa_tambahan_dan_lead_sa(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)
    st = await _subtask(dunia, proyek)

    for target in (dunia.sa, dunia.sa2, dunia.lead2, dunia.lead):
        resp = await _assign(api, dunia, st, target.id)
        assert resp.status_code == 200, (target.name, resp.text)
        assert await _penugasan(dunia.db, st.id_subtask) == target.id


async def test_subtask_ditolak_untuk_sa_di_luar_tim_project(dunia, api):
    proyek = await _proyek(dunia)
    st = await _subtask(dunia, proyek, assigned_sa=dunia.sa.id)

    resp = await _assign(api, dunia, st, dunia.sa3.id)

    assert resp.status_code == 400, resp.text
    assert "tim SA" in resp.json()["message"]
    assert await _penugasan(dunia.db, st.id_subtask) == dunia.sa.id


async def test_subtask_ditolak_untuk_sa_yang_sudah_dilepas_dari_tim(dunia, api):
    proyek = await _proyek(dunia)
    await _tambah_langsung(dunia.db, proyek.id_project, dunia.sa2.id, dunia.lead.id)
    st = await _subtask(dunia, proyek)
    await api.client.delete(
        TIM_ORANG.format(proyek.id_project, dunia.sa2.id), headers=dunia.h["lead"]
    )

    resp = await _assign(api, dunia, st, dunia.sa2.id)

    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize("peran_target", ["sales", "produk"])
async def test_subtask_ditolak_untuk_user_bukan_sa_atau_lead_sa(dunia, api, peran_target):
    proyek = await _proyek(dunia)
    st = await _subtask(dunia, proyek)

    resp = await _assign(api, dunia, st, getattr(dunia, peran_target).id)

    assert resp.status_code == 400, resp.text
    assert await _penugasan(dunia.db, st.id_subtask) is None


async def test_subtask_melepas_penugasan_tetap_boleh(dunia, api):
    proyek = await _proyek(dunia)
    st = await _subtask(dunia, proyek, assigned_sa=dunia.sa.id)

    resp = await _assign(api, dunia, st, None)

    assert resp.status_code == 200, resp.text
    assert await _penugasan(dunia.db, st.id_subtask) is None
