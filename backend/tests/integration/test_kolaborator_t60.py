"""
Integrasi kolaborator proyek terhadap Postgres nyata (tiket #60, spec #49; ADR 0002).

Mencakup daftar/tambah/hapus/cari user, validasi, duplikasi (unique constraint DB), dan hak akses
per peran: Admin, Lead_SA, Sales PIC, SA ditugaskan, kolaborator viewer/contributor, dan user tak
terkait. Pasangan unit: tidak ada (seluruh perilaku bergantung pada constraint/relasi Postgres).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import ProjectCollaborator
from tests.integration.helpers_t60 import (
    API,
    bearer,
    buat_kolaborator,
    buat_proyek,
    buat_user,
)

PROYEK = f"{API}/projects"


def _url(id_project: str, user_id=None) -> str:
    dasar = f"{PROYEK}/{id_project}/collaborators"
    return f"{dasar}/{user_id}" if user_id else dasar


async def _skenario(db):
    """Sales PIC + SA ditugaskan + proyek, plus satu user tiap peran yang tak terkait."""
    sales = await buat_user(db, "Sales", name="Sales Pic")
    sa = await buat_user(db, "SA", name="SA Utama")
    proyek = await buat_proyek(db, sales, assigned_sa=sa)
    return sales, sa, proyek


async def _jumlah(db, id_project: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ProjectCollaborator)
            .where(ProjectCollaborator.id_project == id_project)
        )
    ).scalar_one()


# ---  daftar


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_daftar_privileged_boleh_dan_berisi_info_user_terbaru_dulu(api, db_session, peran):
    sales, sa, proyek = await _skenario(db_session)
    v = await buat_user(db_session, "SA", name="Viewer Satu", email="v1@portal-sa.local")
    c = await buat_user(db_session, "SA", name="Kontributor Dua", email="c2@portal-sa.local")
    await buat_kolaborator(db_session, proyek, v, sa, "viewer")
    await buat_kolaborator(db_session, proyek, c, sa, "contributor")
    pengakses = await buat_user(db_session, peran)

    resp = await api.client.get(_url(proyek.id_project), headers=bearer(pengakses))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 2
    # Terbaru ditambahkan tampil lebih dulu.
    assert [i["user_name"] for i in data["items"]] == ["Kontributor Dua", "Viewer Satu"]
    item = data["items"][0]
    assert item["user_email"] == "c2@portal-sa.local"
    assert item["user_role"] == "SA"
    assert item["role"] == "contributor"
    assert item["added_by_name"] == "SA Utama"
    assert item["user_id"] == str(c.id)


async def test_daftar_kosong_untuk_proyek_tanpa_kolaborator(api, db_session):
    sales, sa, proyek = await _skenario(db_session)

    resp = await api.client.get(_url(proyek.id_project), headers=bearer(sales))

    assert resp.json()["data"] == {"items": [], "total": 0}


@pytest.mark.parametrize("peran_akses", ["sales_pic", "assigned_sa", "viewer", "contributor"])
async def test_daftar_boleh_untuk_pihak_terkait_proyek(api, db_session, peran_akses):
    sales, sa, proyek = await _skenario(db_session)
    kolab = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, kolab, sa, "contributor")
    viewer = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, viewer, sa, "viewer")
    pengakses = {"sales_pic": sales, "assigned_sa": sa, "viewer": viewer, "contributor": kolab}[
        peran_akses
    ]

    resp = await api.client.get(_url(proyek.id_project), headers=bearer(pengakses))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 2


@pytest.mark.parametrize("peran", ["SA", "Sales"])
async def test_daftar_user_tak_terkait_tetap_boleh_membaca(api, db_session, peran):
    """Keputusan 2026-11-10: semua proyek dapat dibaca siapa pun (menambah/menghapus tetap dibatasi)."""
    _, _, proyek = await _skenario(db_session)
    orang_luar = await buat_user(db_session, peran)

    resp = await api.client.get(_url(proyek.id_project), headers=bearer(orang_luar))

    assert resp.status_code == 200, resp.text


async def test_daftar_proyek_tidak_ada_404_dan_tanpa_token_401(api, db_session):
    admin = await buat_user(db_session, "Admin")

    assert (await api.client.get(_url("PRJ-TIDAK-ADA"), headers=bearer(admin))).status_code == 404
    assert (await api.client.get(_url("PRJ-APA-SAJA"))).status_code == 401


async def test_user_dihapus_kolaborator_ikut_hilang_karena_cascade(api, db_session):
    """FK `user_id` ON DELETE CASCADE: user dihapus → baris kolaborator ikut hilang."""
    sales, sa, proyek = await _skenario(db_session)
    v = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, v, sa)
    await db_session.delete(v)
    await db_session.commit()

    resp = await api.client.get(_url(proyek.id_project), headers=bearer(sales))

    assert resp.json()["data"]["total"] == 0


# ---  tambah


async def test_tambah_default_viewer_tersimpan_dengan_added_by(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    peer = await buat_user(db_session, "SA", name="Peer SA")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(peer.id)}, headers=bearer(sa)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["role"] == "viewer"
    assert data["user_id"] == str(peer.id)
    assert data["user_name"] == "Peer SA"
    baris = (
        await db_session.execute(
            select(ProjectCollaborator).where(ProjectCollaborator.id_project == proyek.id_project)
        )
    ).scalar_one()
    assert str(baris.id) == data["id"]
    assert (baris.user_id, baris.role, baris.added_by) == (peer.id, "viewer", sa.id)


async def test_tambah_contributor_sa_oleh_sa_sukses(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    peer = await buat_user(db_session, "SA")

    resp = await api.client.post(
        _url(proyek.id_project),
        json={"user_id": str(peer.id), "role": "contributor"},
        headers=bearer(sa),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "contributor"


async def test_tambah_sales_sesama_sales_viewer_sukses(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    rekan = await buat_user(db_session, "Sales")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(rekan.id)}, headers=bearer(sales)
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("peran_target", ["SA", "Lead_SA", "Admin", "Sales"])
async def test_tambah_lead_sa_boleh_semua_peran_target_sebagai_viewer(
    api, db_session, peran_target
):
    sales, sa, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")
    target = await buat_user(db_session, peran_target)

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(target.id)}, headers=bearer(lead)
    )

    assert resp.status_code == 200, resp.text


async def test_tambah_admin_boleh_dan_contributor_untuk_lead_sa_dan_admin(api, db_session):
    _, _, proyek = await _skenario(db_session)
    admin = await buat_user(db_session, "Admin")
    lead = await buat_user(db_session, "Lead_SA")
    admin2 = await buat_user(db_session, "Admin")

    for target in (lead, admin2):
        resp = await api.client.post(
            _url(proyek.id_project),
            json={"user_id": str(target.id), "role": "contributor"},
            headers=bearer(admin),
        )
        assert resp.status_code == 200, resp.text


async def test_tambah_sales_ke_sa_ditolak_403_tanpa_baris(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    peer_sa = await buat_user(db_session, "SA")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(peer_sa.id)}, headers=bearer(sales)
    )

    assert resp.status_code == 403
    assert "Sales" in resp.json()["message"]
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_tambah_sa_ke_non_sa_ditolak_403(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    rekan_sales = await buat_user(db_session, "Sales")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(rekan_sales.id)}, headers=bearer(sa)
    )

    assert resp.status_code == 403
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_tambah_role_invalid_400(api, db_session):
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")
    target = await buat_user(db_session, "SA")

    resp = await api.client.post(
        _url(proyek.id_project),
        json={"user_id": str(target.id), "role": "owner"},
        headers=bearer(lead),
    )

    assert resp.status_code == 400
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_tambah_contributor_bukan_sa_ditolak_400(api, db_session):
    """Contributor hanya untuk peran yang dapat membuat activity log (SA/Lead_SA/Admin)."""
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")
    target_sales = await buat_user(db_session, "Sales")

    resp = await api.client.post(
        _url(proyek.id_project),
        json={"user_id": str(target_sales.id), "role": "contributor"},
        headers=bearer(lead),
    )

    assert resp.status_code == 400
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_tambah_user_target_tidak_ada_404(api, db_session):
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(uuid.uuid4())}, headers=bearer(lead)
    )

    assert resp.status_code == 404


async def test_tambah_proyek_tidak_ada_404(api, db_session):
    lead = await buat_user(db_session, "Lead_SA")
    target = await buat_user(db_session, "SA")

    resp = await api.client.post(
        _url("PRJ-TIDAK-ADA"), json={"user_id": str(target.id)}, headers=bearer(lead)
    )

    assert resp.status_code == 404


async def test_tambah_user_id_bukan_uuid_422(api, db_session):
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": "bukan-uuid"}, headers=bearer(lead)
    )

    assert resp.status_code == 422


async def test_tambah_duplikat_409_dan_tetap_satu_baris(api, db_session):
    _, sa, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")
    target = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, target, sa, "viewer")

    resp = await api.client.post(
        _url(proyek.id_project),
        json={"user_id": str(target.id), "role": "contributor"},
        headers=bearer(lead),
    )

    assert resp.status_code == 409
    assert await _jumlah(db_session, proyek.id_project) == 1
    # Role lama tidak tertimpa oleh upaya duplikat.
    assert (
        await db_session.execute(
            select(ProjectCollaborator.role).where(ProjectCollaborator.user_id == target.id)
        )
    ).scalar_one() == "viewer"


async def test_tambah_diri_sendiri_ditolak_400(api, db_session):
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")

    resp = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(lead.id)}, headers=bearer(lead)
    )

    assert resp.status_code == 400
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_user_yang_sama_boleh_jadi_kolaborator_di_proyek_berbeda(api, db_session):
    sales, sa, proyek1 = await _skenario(db_session)
    proyek2 = await buat_proyek(db_session, sales, assigned_sa=sa)
    lead = await buat_user(db_session, "Lead_SA")
    target = await buat_user(db_session, "SA")

    for p in (proyek1, proyek2):
        resp = await api.client.post(
            _url(p.id_project), json={"user_id": str(target.id)}, headers=bearer(lead)
        )
        assert resp.status_code == 200, resp.text


async def test_tambah_kolaborator_lalu_dapat_akses_baca_story_backup_sa(api, db_session):
    """ADR 0002: kolaborator = Backup SA, mendapat akses baca Project Story setelah ditambahkan."""
    sales, sa, proyek = await _skenario(db_session)
    backup = await buat_user(db_session, "SA", name="Backup SA")

    tambah = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(backup.id)}, headers=bearer(sa)
    )
    story = await api.client.get(
        f"{API}/projects/{proyek.id_project}/story", headers=bearer(backup)
    )
    daftar = await api.client.get(_url(proyek.id_project), headers=bearer(backup))

    assert tambah.status_code == 200
    assert story.status_code == 200, story.text
    assert daftar.status_code == 200


async def test_kontributor_dapat_menambah_activity_log_ke_proyek(api, db_session, fake_llm):
    sales, sa, proyek = await _skenario(db_session)
    kontributor = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, kontributor, sa, "contributor")
    fake_llm.error("structure_text", "timeout")

    resp = await api.client.post(
        f"{API}/activity-logs",
        json={
            "id_project": proyek.id_project,
            "project_phase": "Pre-Implementation",
            "subtask_category": "Assessment",
            "duration_hours": "1",
            "raw_notes": "catatan kontributor",
        },
        headers=bearer(kontributor),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["sa_id"] == str(kontributor.id)


# ---  hapus


@pytest.mark.parametrize("pelaku", ["Lead_SA", "Admin", "sales_pic", "assigned_sa"])
async def test_hapus_oleh_pihak_berwenang_menghapus_baris(api, db_session, pelaku):
    sales, sa, proyek = await _skenario(db_session)
    target = await buat_user(db_session, "SA", name="Dihapus")
    await buat_kolaborator(db_session, proyek, target, sa)
    pengakses = {
        "sales_pic": sales,
        "assigned_sa": sa,
        "Lead_SA": await buat_user(db_session, "Lead_SA"),
        "Admin": await buat_user(db_session, "Admin"),
    }[pelaku]

    resp = await api.client.delete(_url(proyek.id_project, target.id), headers=bearer(pengakses))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] is None
    assert "Dihapus" in resp.json()["message"]
    assert await _jumlah(db_session, proyek.id_project) == 0


async def test_hapus_kolaborator_kehilangan_akses_tulis_dan_boleh_ditambah_lagi(api, db_session):
    sales, sa, proyek = await _skenario(db_session)
    target = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, target, sa, "contributor")
    ubah = {"project_name": "Diubah kolaborator"}
    url_proyek = f"{PROYEK}/{proyek.id_project}"
    assert (
        await api.client.patch(url_proyek, json=ubah, headers=bearer(target))
    ).status_code == 200

    await api.client.delete(_url(proyek.id_project, target.id), headers=bearer(sa))

    # Membaca tetap terbuka, tetapi hak tulis (contributor) hilang bersama baris kolaboratornya.
    assert (
        await api.client.get(_url(proyek.id_project), headers=bearer(target))
    ).status_code == 200
    assert (
        await api.client.patch(url_proyek, json=ubah, headers=bearer(target))
    ).status_code == 403
    ulang = await api.client.post(
        _url(proyek.id_project), json={"user_id": str(target.id)}, headers=bearer(sa)
    )
    assert ulang.status_code == 200, ulang.text


@pytest.mark.parametrize("pelaku", ["viewer", "contributor", "luar_sa", "luar_sales"])
async def test_hapus_oleh_non_berwenang_403_baris_tetap(api, db_session, pelaku):
    sales, sa, proyek = await _skenario(db_session)
    target = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, target, sa)
    kolab = await buat_user(db_session, "SA")
    await buat_kolaborator(
        db_session, proyek, kolab, sa, pelaku if pelaku in ("viewer", "contributor") else "viewer"
    )
    pengakses = {
        "viewer": kolab,
        "contributor": kolab,
        "luar_sa": await buat_user(db_session, "SA"),
        "luar_sales": await buat_user(db_session, "Sales"),
    }[pelaku]

    resp = await api.client.delete(_url(proyek.id_project, target.id), headers=bearer(pengakses))

    assert resp.status_code == 403
    assert await _jumlah(db_session, proyek.id_project) == 2


async def test_hapus_kolaborator_tidak_ada_404(api, db_session):
    _, _, proyek = await _skenario(db_session)
    lead = await buat_user(db_session, "Lead_SA")

    resp = await api.client.delete(_url(proyek.id_project, uuid.uuid4()), headers=bearer(lead))

    assert resp.status_code == 404


async def test_hapus_proyek_tidak_ada_404_dan_user_id_bukan_uuid_422(api, db_session):
    lead = await buat_user(db_session, "Lead_SA")

    gone = await api.client.delete(_url("PRJ-TIDAK-ADA", uuid.uuid4()), headers=bearer(lead))
    bad = await api.client.delete(_url("PRJ-X", "bukan-uuid"), headers=bearer(lead))

    assert gone.status_code == 404
    assert bad.status_code == 422


async def test_hapus_hanya_proyek_yang_dimaksud(api, db_session):
    sales, sa, proyek1 = await _skenario(db_session)
    proyek2 = await buat_proyek(db_session, sales, assigned_sa=sa)
    target = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek1, target, sa)
    await buat_kolaborator(db_session, proyek2, target, sa)

    await api.client.delete(_url(proyek1.id_project, target.id), headers=bearer(sa))

    assert await _jumlah(db_session, proyek1.id_project) == 0
    assert await _jumlah(db_session, proyek2.id_project) == 1


# ---  cari user


async def test_cari_user_cocok_nama_atau_email_tanpa_diri_sendiri_urut_nama(api, db_session):
    saya = await buat_user(db_session, "SA", name="Budi Saya", email="budi.saya@portal-sa.local")
    await buat_user(db_session, "SA", name="Budi Zulkarnain", email="zul@portal-sa.local")
    await buat_user(db_session, "Sales", name="Andi", email="andi.budi@portal-sa.local")
    await buat_user(db_session, "SA", name="Citra", email="citra@portal-sa.local")

    resp = await api.client.get(
        f"{PROYEK}/users/search", params={"q": "BUDI"}, headers=bearer(saya)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [u["name"] for u in data] == ["Andi", "Budi Zulkarnain"]
    assert set(data[0]) == {"id", "name", "email", "role"}
    assert data[0]["role"] == "Sales"


async def test_cari_user_limit_dan_validasi_parameter(api, db_session):
    saya = await buat_user(db_session, "SA")
    for i in range(5):
        await buat_user(db_session, "SA", name=f"Kandidat {i}")
    h = bearer(saya)

    dua = await api.client.get(
        f"{PROYEK}/users/search", params={"q": "kandidat", "limit": 2}, headers=h
    )
    pendek = await api.client.get(f"{PROYEK}/users/search", params={"q": "k"}, headers=h)
    tanpa_q = await api.client.get(f"{PROYEK}/users/search", headers=h)
    limit_besar = await api.client.get(
        f"{PROYEK}/users/search", params={"q": "kandidat", "limit": 51}, headers=h
    )
    kosong = await api.client.get(f"{PROYEK}/users/search", params={"q": "tidakadasama"}, headers=h)

    assert [u["name"] for u in dua.json()["data"]] == ["Kandidat 0", "Kandidat 1"]
    assert pendek.status_code == tanpa_q.status_code == limit_besar.status_code == 422
    assert kosong.json()["data"] == []


@pytest.mark.parametrize(
    ("q", "cocok", "tidak_cocok"),
    [
        ("i%t", "Andi%Tes", "AndiXTes"),
        ("a_x", "Rina_xyz", "RinaZxyz"),
        ("a\\b", "Sa\\bro", "Saxbro"),
    ],
    ids=["persen", "garis-bawah", "backslash"],
)
async def test_cari_user_karakter_wildcard_diperlakukan_harfiah(
    api, db_session, q, cocok, tidak_cocok
):
    """#78: `%`, `_`, dan `\\` di kata kunci bukan wildcard `ilike`."""
    saya = await buat_user(db_session, "SA", name="Penanya")
    await buat_user(db_session, "SA", name=cocok, email=f"{uuid.uuid4().hex[:8]}@portal-sa.local")
    await buat_user(
        db_session, "SA", name=tidak_cocok, email=f"{uuid.uuid4().hex[:8]}@portal-sa.local"
    )

    resp = await api.client.get(f"{PROYEK}/users/search", params={"q": q}, headers=bearer(saya))

    assert resp.status_code == 200, resp.text
    assert [u["name"] for u in resp.json()["data"]] == [cocok]


async def test_cari_user_karakter_nul_422_bukan_500(api, db_session):
    saya = await buat_user(db_session, "SA")

    resp = await api.client.get(
        f"{PROYEK}/users/search", params={"q": "bu\x00di"}, headers=bearer(saya)
    )

    assert resp.status_code == 422, resp.text
