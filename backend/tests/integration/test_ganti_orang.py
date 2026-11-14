"""
Mengganti `product_pic`/`sales_pic`/`lead_sa` dan mengisi `lead_sa` saat assign (issue #118,
ADR 0014).

Seam: HTTP API terhadap Postgres nyata (authz per peran, constraint, audit log).
Layanan eksternal (Drive) di-fake/dilewati lewat fixture bersama.
"""

import pytest

from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_user
from tests.integration.support_assignment import (
    ASSIGN,
    REASSIGN,
    ambil_proyek,
    bangun_dunia,
    daftar_audit,
    rekam_background,
)

ORANG = "/api/v1/projects/{}/people"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _user(dunia, role, nama):
    u = bangun_user(role=role, name=nama, email=f"{nama.lower()}-118@portal-sa.local")
    dunia.db.add(u)
    await dunia.db.commit()
    return u


async def _proyek(dunia, **o):
    o.setdefault("product_pic", dunia.produk.id)
    sales_pic = o.pop("sales_pic", None)
    proyek = await dunia.buat_proyek(**o)  # `dunia.sales` jadi sales_pic bawaan
    proyek.sales_pic = sales_pic
    await dunia.db.commit()
    return proyek


# ------------------------------------------------------------------------------ authz


@pytest.mark.parametrize("peran", ["sales", "produk", "sa"])
async def test_peran_selain_lead_sa_dan_admin_ditolak_403(dunia, api, peran):
    proyek = await _proyek(dunia)
    produk_baru = await _user(dunia, "Product", "ProdukBaru")

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={"product_pic": str(produk_baru.id)},
        headers=dunia.h[peran],
    )

    assert resp.status_code == 403, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).product_pic == dunia.produk.id
    assert await daftar_audit(dunia.db, proyek.id_project, "people_change") == []


async def test_tanpa_token_ditolak(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.patch(ORANG.format(proyek.id_project), json={"sales_pic": None})

    assert resp.status_code in (401, 403)


@pytest.mark.parametrize("pelaku", ["lead", "admin"])
async def test_lead_sa_dan_admin_berhasil_mengganti_product_pic(dunia, api, pelaku):
    proyek = await _proyek(dunia)
    produk_baru = await _user(dunia, "Product", "ProdukBaru")

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={"product_pic": str(produk_baru.id)},
        headers=dunia.h[pelaku],
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["product_pic"]["id"] == str(produk_baru.id)
    assert (await ambil_proyek(dunia.db, proyek.id_project)).product_pic == produk_baru.id


# ---------------------------------------------------------------------------- aturan field


async def test_product_pic_tidak_boleh_dikosongkan(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project), json={"product_pic": None}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 422, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).product_pic == dunia.produk.id
    assert await daftar_audit(dunia.db, proyek.id_project, "people_change") == []


async def test_sales_pic_boleh_dikosongkan(dunia, api):
    proyek = await _proyek(dunia, sales_pic=dunia.sales.id)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project), json={"sales_pic": None}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sales_pic"] is None
    assert (await ambil_proyek(dunia.db, proyek.id_project)).sales_pic is None


async def test_sales_pic_diganti_ke_sales_lain(dunia, api):
    proyek = await _proyek(dunia, sales_pic=dunia.sales.id)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={"sales_pic": str(dunia.sales_lain.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).sales_pic == dunia.sales_lain.id


async def test_lead_sa_diganti_ke_lead_sa_lain(dunia, api):
    lead2 = await _user(dunia, "Lead_SA", "LeadDua")
    proyek = await _proyek(dunia, lead_sa=dunia.lead.id)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project), json={"lead_sa": str(lead2.id)}, headers=dunia.h["admin"]
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == lead2.id


async def test_lead_sa_tidak_boleh_dikosongkan(dunia, api):
    proyek = await _proyek(dunia, lead_sa=dunia.lead.id)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project), json={"lead_sa": None}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 422, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == dunia.lead.id


@pytest.mark.parametrize(
    ("field", "salah"),
    [
        ("product_pic", "sales"),  # bukan Product
        ("sales_pic", "produk"),  # bukan Sales
        ("lead_sa", "sa"),  # bukan Lead_SA
    ],
)
async def test_user_berrole_salah_ditolak_422(dunia, api, field, salah):
    proyek = await _proyek(dunia)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={field: str(getattr(dunia, salah).id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 422, resp.text
    assert await daftar_audit(dunia.db, proyek.id_project, "people_change") == []


async def test_id_tidak_valid_atau_tidak_ada_ditolak_422(dunia, api):
    proyek = await _proyek(dunia)
    for nilai in ("bukan-uuid", "00000000-0000-0000-0000-000000000000"):
        resp = await api.client.patch(
            ORANG.format(proyek.id_project), json={"product_pic": nilai}, headers=dunia.h["lead"]
        )
        assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("isi", [b"bukan json", b"[1, 2]"])
async def test_body_bukan_objek_json_ditolak_422(dunia, api, isi):
    proyek = await _proyek(dunia)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        content=isi,
        headers={**dunia.h["lead"], "Content-Type": "application/json"},
    )

    assert resp.status_code == 422, resp.text


async def test_proyek_tidak_ada_404(dunia, api):
    resp = await api.client.patch(
        ORANG.format("PRJ-TIDAK-ADA"), json={"sales_pic": None}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 404


async def test_body_kosong_tidak_mengubah_apa_pun(dunia, api):
    proyek = await _proyek(dunia, sales_pic=dunia.sales.id)

    resp = await api.client.patch(ORANG.format(proyek.id_project), json={}, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.product_pic, p.sales_pic) == (dunia.produk.id, dunia.sales.id)
    assert await daftar_audit(dunia.db, proyek.id_project, "people_change") == []


# ------------------------------------------------------------------------------ audit log


async def test_audit_log_mencatat_nilai_lama_baru_dan_pelaku(dunia, api):
    proyek = await _proyek(dunia, sales_pic=dunia.sales.id)
    produk_baru = await _user(dunia, "Product", "ProdukBaru")

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={"product_pic": str(produk_baru.id), "sales_pic": None},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    (audit,) = await daftar_audit(dunia.db, proyek.id_project, "people_change")
    assert audit.entity_type == "project"
    assert audit.performed_by == dunia.lead.id
    assert audit.old_value == {
        "product_pic": str(dunia.produk.id),
        "sales_pic": str(dunia.sales.id),
    }
    assert audit.new_value == {"product_pic": str(produk_baru.id), "sales_pic": None}


async def test_audit_hanya_memuat_field_yang_berubah(dunia, api):
    proyek = await _proyek(dunia, sales_pic=dunia.sales.id)

    resp = await api.client.patch(
        ORANG.format(proyek.id_project),
        json={"product_pic": str(dunia.produk.id), "sales_pic": str(dunia.sales_lain.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    (audit,) = await daftar_audit(dunia.db, proyek.id_project, "people_change")
    assert audit.old_value == {"sales_pic": str(dunia.sales.id)}
    assert audit.new_value == {"sales_pic": str(dunia.sales_lain.id)}
    assert audit.performed_by == dunia.admin.id


# ------------------------------------------------------------------------ detail & assign


async def test_detail_project_menampilkan_lead_sa(dunia, api):
    proyek = await _proyek(dunia, lead_sa=dunia.lead.id)

    resp = await api.client.get(f"/api/v1/projects/{proyek.id_project}", headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["lead_sa"]["id"] == str(dunia.lead.id)


async def test_detail_project_tanpa_lead_sa_bernilai_null(dunia, api):
    proyek = await _proyek(dunia)

    resp = await api.client.get(f"/api/v1/projects/{proyek.id_project}", headers=dunia.h["lead"])

    assert resp.json()["data"]["lead_sa"] is None


async def test_assign_oleh_lead_sa_mengisi_lead_sa_dengan_pengassign(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == dunia.lead.id


async def test_assign_dengan_lead_sa_dipilih(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    lead2 = await _user(dunia, "Lead_SA", "LeadDua")
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id), "lead_sa_id": str(lead2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == lead2.id


async def test_assign_admin_non_lead_sa_tanpa_lead_sa_id_ditolak_400(dunia, api, monkeypatch):
    # Admin = SA dengan flag `is_admin` (ADR 0012): tidak boleh diam-diam menjadi `lead_sa`.
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 400, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.lead_sa, p.assigned_sa) == ("Pending Assignment", None, None)


async def test_assign_admin_non_lead_sa_dengan_lead_sa_id_diterima(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id), "lead_sa_id": str(dunia.lead.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.lead_sa) == ("Assigned", dunia.lead.id)


async def test_assign_lead_sa_pilihan_bukan_lead_sa_ditolak_dan_tidak_mengubah(
    dunia, api, monkeypatch
):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id), "lead_sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.lead_sa) == ("Pending Assignment", None)


async def test_reassign_dari_pending_mengisi_lead_sa(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == dunia.lead.id


async def test_reassign_tidak_menimpa_lead_sa_yang_sudah_ada(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    lead2 = await _user(dunia, "Lead_SA", "LeadDua")
    proyek = await _proyek(
        dunia, status="Assigned", assigned_sa=dunia.sa.id, lead_sa=lead2.id, assigned_at=None
    )

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == lead2.id


async def test_reassign_dari_pending_oleh_admin_non_lead_sa_tanpa_lead_sa_id_ditolak_400(
    dunia, api, monkeypatch
):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 400, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.lead_sa, p.assigned_sa) == ("Pending Assignment", None, None)


async def test_reassign_dari_pending_oleh_admin_dengan_lead_sa_id_diterima(dunia, api, monkeypatch):
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id), "lead_sa_id": str(dunia.lead.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == dunia.lead.id


async def test_reassign_admin_tanpa_lead_sa_id_boleh_bila_lead_sa_sudah_ada(
    dunia, api, monkeypatch
):
    rekam_background(monkeypatch)
    proyek = await _proyek(
        dunia, status="Assigned", assigned_sa=dunia.sa.id, lead_sa=dunia.lead.id, assigned_at=None
    )

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).lead_sa == dunia.lead.id


async def test_reassign_admin_non_lead_sa_pada_assigned_tanpa_lead_sa_tidak_diam_diam_jadi_lead(
    dunia, api, monkeypatch
):
    # Data lama: Assigned tanpa lead_sa. Reassign oleh admin tetap diizinkan (bukan alur assign
    # awal), tetapi admin tidak boleh diam-diam menjadi lead_sa.
    rekam_background(monkeypatch)
    proyek = await _proyek(dunia, status="Assigned", assigned_sa=dunia.sa.id, assigned_at=None)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.assigned_sa, p.lead_sa) == (dunia.sa2.id, None)
