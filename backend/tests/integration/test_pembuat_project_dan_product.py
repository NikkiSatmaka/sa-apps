# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Pembuat project dan Product setara Sales (issue #115, ADR 0012).

Seam: HTTP API terhadap Postgres nyata. `POST /projects` hanya untuk Sales, Product, Lead_SA,
dan `is_admin` (SA ditolak). Sementara `product_pic` belum ada (tiket Orang-1), pembuat dicatat
di `sales_pic`, sehingga aturan akses berbasis PIC harus mengenali Product.
"""

import pytest
from sqlalchemy import func, select

from app.models import Project
from tests.integration.b6_support import API
from tests.integration.b6_support import user_baru as user_baru_b6
from tests.integration.kualifikasi_support import (  # noqa: F401
    ambil_proyek,
    api,
    buat_proyek,
    id_product_demo,
    tanpa_tunggu,
)
from tests.integration.model_helpers import bangun_document, bangun_project, simpan

pytestmark = pytest.mark.usefixtures("tanpa_tunggu")


async def _jumlah_proyek(db) -> int:
    return (await db.execute(select(func.count()).select_from(Project))).scalar_one()


@pytest.mark.parametrize("peran", ["Sales", "Product", "Lead_SA", "Admin"])
async def test_pembuat_yang_diizinkan_membuat_proyek_dan_tercatat_sebagai_pic(
    api, db_session, peran
):
    headers = await api.login_demo(peran)

    resp = await buat_proyek(api, headers)

    assert resp.status_code == 201, resp.text
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    pembuat = (await api.client.get(f"{API}/auth/me", headers=headers)).json()["id"]
    product = await id_product_demo(api)
    assert str(proyek.created_by) == pembuat
    assert str(proyek.product_pic) == (pembuat if peran == "Product" else product)
    # Sales selalu dirinya sendiri; pembuat lain tanpa Sales (opsional, ADR 0014).
    assert (str(proyek.sales_pic) if proyek.sales_pic else None) == (
        pembuat if peran == "Sales" else None
    )


async def test_sa_tidak_boleh_membuat_proyek_dan_tidak_ada_baris_tersimpan(api, db_session):
    headers = await api.login_demo("SA")

    resp = await buat_proyek(api, headers)

    assert resp.status_code == 403
    assert await _jumlah_proyek(db_session) == 0


async def test_tanpa_login_tidak_bisa_membuat_proyek(api, db_session):
    resp = await buat_proyek(api, {})

    assert resp.status_code == 401
    assert await _jumlah_proyek(db_session) == 0


# --------------------------------------------------------------------------- Product = Sales


async def _proyek_milik(db, pic, **o) -> Project:
    proyek = bangun_project(pic.id, status="Assigned", **o)
    await simpan(db, proyek)
    return proyek


async def test_product_pic_boleh_ubah_status_proyek_miliknya_tapi_bukan_milik_lain(api, db_session):
    produk, h_produk = await user_baru_b6(db_session, "Product")
    lain, _ = await user_baru_b6(db_session, "Product")
    miliknya = await _proyek_milik(db_session, produk)
    milik_lain = await _proyek_milik(db_session, lain)

    ok = await api.client.patch(
        f"{API}/projects/{miliknya.id_project}/status",
        json={"new_status": "Submitted"},
        headers=h_produk,
    )
    ditolak = await api.client.patch(
        f"{API}/projects/{milik_lain.id_project}/status",
        json={"new_status": "Submitted"},
        headers=h_produk,
    )

    assert ok.status_code == 200, ok.text
    assert ditolak.status_code == 403


async def test_product_pic_boleh_mengisi_dq_pertama_proyeknya(api, db_session):
    produk, h_produk = await user_baru_b6(db_session, "Product")
    proyek = await _proyek_milik(db_session, produk)

    resp = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/dq-number",
        json={"dq_number": "DQ-2025-001"},
        headers=h_produk,
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(db_session, proyek.id_project)).dq_number == "DQ-2025-001"


async def test_product_tidak_bisa_mengubah_dq_yang_sudah_terisi_seperti_sales(api, db_session):
    produk, h_produk = await user_baru_b6(db_session, "Product")
    proyek = await _proyek_milik(db_session, produk, dq_number="DQ-2025-001")

    resp = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/dq-number",
        json={"dq_number": "DQ-2025-002"},
        headers=h_produk,
    )

    assert resp.status_code == 403
    assert (await ambil_proyek(db_session, proyek.id_project)).dq_number == "DQ-2025-001"


async def test_product_tanpa_dq_tidak_melihat_dokumen_solutions_seperti_sales(api, db_session):
    produk, h_produk = await user_baru_b6(db_session, "Product")
    proyek = await _proyek_milik(db_session, produk)
    sa, _ = await user_baru_b6(db_session, "SA")
    await simpan(
        db_session, bangun_document(proyek.id_project, sa.id, doc_type="PropTek", status="Final")
    )

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents/solutions", headers=h_produk
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == {"documents": [], "total": 0, "dq_required": True}


async def test_product_hanya_boleh_menambah_sesama_sales_atau_product_sebagai_kolaborator(
    api, db_session
):
    produk, h_produk = await user_baru_b6(db_session, "Product")
    proyek = await _proyek_milik(db_session, produk)
    sales, _ = await user_baru_b6(db_session, "Sales")
    sa, _ = await user_baru_b6(db_session, "SA")
    url = f"{API}/projects/{proyek.id_project}/collaborators"

    boleh = await api.client.post(url, json={"user_id": str(sales.id)}, headers=h_produk)
    ditolak = await api.client.post(url, json={"user_id": str(sa.id)}, headers=h_produk)

    assert boleh.status_code == 200, boleh.text
    assert ditolak.status_code == 403
