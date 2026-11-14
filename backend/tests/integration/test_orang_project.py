# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Orang per project: `created_by`, `product_pic` (wajib), `sales_pic` (opsional) (issue #117,
ADR 0014).

Seam: HTTP API terhadap Postgres nyata (pembuatan, daftar, detail, akses, assign, SLA).
Layanan eksternal (Drive, Gmail) memakai fake bersama.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import NotificationLog, Project
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.kualifikasi_support import (  # noqa: F401
    ambil_proyek,
    api,
    bearer,
    buat_proyek,
    tanpa_tunggu,
    user_baru,
)
from tests.integration.model_helpers import bangun_document, bangun_project, simpan
from tests.integration.support_assignment import (
    ASSIGN,
    T0,
    bangun_dunia,
    bekukan_waktu,
    rekam_background,
)

API = "/api/v1"

pytestmark = pytest.mark.usefixtures("tanpa_tunggu")


async def _jumlah_proyek(db) -> int:
    return (await db.execute(select(func.count()).select_from(Project))).scalar_one()


def _galat_field(resp) -> dict[str, str]:
    assert resp.status_code == 422, resp.text
    return {e["field"]: e["reason"] for e in resp.json()["data"]}


# ------------------------------------------------------------------------------ pembuatan


async def test_sales_pembuat_menjadi_created_by_dan_sales_pic_dengan_product_pilihannya(
    api, db_session
):
    sales = await user_baru(db_session, "Sales")
    produk = await user_baru(db_session, "Product")

    resp = await buat_proyek(api, bearer(sales), product_pic=str(produk.id))

    assert resp.status_code == 201, resp.text
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert (proyek.created_by, proyek.sales_pic, proyek.product_pic) == (
        sales.id,
        sales.id,
        produk.id,
    )
    assert proyek.lead_sa is None


async def test_sales_pembuat_wajib_memilih_product(api, db_session):
    sales = await user_baru(db_session, "Sales")

    resp = await buat_proyek(api, bearer(sales), product_pic=None)

    assert "product_pic" in _galat_field(resp)
    assert await _jumlah_proyek(db_session) == 0


@pytest.mark.parametrize("peran_salah", ["Sales", "SA", "Lead_SA"])
async def test_product_pic_harus_user_berrole_product(api, db_session, peran_salah):
    sales = await user_baru(db_session, "Sales")
    bukan_product = await user_baru(db_session, peran_salah)

    resp = await buat_proyek(api, bearer(sales), product_pic=str(bukan_product.id))

    assert "Product" in _galat_field(resp)["product_pic"]
    assert await _jumlah_proyek(db_session) == 0


@pytest.mark.parametrize(
    "nilai", ["bukan-uuid", "00000000-0000-4000-8000-0000000000aa"], ids=["format", "tidak-ada"]
)
async def test_product_pic_tidak_valid_ditolak(api, db_session, nilai):
    sales = await user_baru(db_session, "Sales")

    resp = await buat_proyek(api, bearer(sales), product_pic=nilai)

    assert "product_pic" in _galat_field(resp)
    assert await _jumlah_proyek(db_session) == 0


async def test_product_pembuat_otomatis_product_pic_dan_sales_pic_kosong(api, db_session):
    produk = await user_baru(db_session, "Product")

    resp = await buat_proyek(api, bearer(produk))

    assert resp.status_code == 201, resp.text
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert (proyek.created_by, proyek.product_pic, proyek.sales_pic) == (
        produk.id,
        produk.id,
        None,
    )


async def test_product_pembuat_boleh_memilih_sales_opsional(api, db_session):
    produk = await user_baru(db_session, "Product")
    sales = await user_baru(db_session, "Sales")

    resp = await buat_proyek(api, bearer(produk), sales_pic=str(sales.id))

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert (proyek.created_by, proyek.product_pic, proyek.sales_pic) == (
        produk.id,
        produk.id,
        sales.id,
    )


@pytest.mark.parametrize("peran_salah", ["Product", "SA", "Lead_SA"])
async def test_sales_pic_pilihan_harus_user_berrole_sales(api, db_session, peran_salah):
    produk = await user_baru(db_session, "Product")
    bukan_sales = await user_baru(db_session, peran_salah)

    resp = await buat_proyek(api, bearer(produk), sales_pic=str(bukan_sales.id))

    assert "Sales" in _galat_field(resp)["sales_pic"]
    assert await _jumlah_proyek(db_session) == 0


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_lead_sa_dan_admin_pembuat_wajib_memilih_product(api, db_session, peran):
    pembuat = await user_baru(db_session, peran)

    resp = await buat_proyek(api, bearer(pembuat), product_pic=None)

    assert "product_pic" in _galat_field(resp)
    assert await _jumlah_proyek(db_session) == 0


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_lead_sa_dan_admin_pembuat_mengisi_product_dan_sales_opsional(
    api, db_session, peran
):
    pembuat = await user_baru(db_session, peran)
    produk = await user_baru(db_session, "Product")
    sales = await user_baru(db_session, "Sales")

    tanpa_sales = await buat_proyek(api, bearer(pembuat), product_pic=str(produk.id))
    dengan_sales = await buat_proyek(
        api, bearer(pembuat), product_pic=str(produk.id), sales_pic=str(sales.id)
    )

    a = await ambil_proyek(db_session, tanpa_sales.json()["data"]["id_project"])
    b = await ambil_proyek(db_session, dengan_sales.json()["data"]["id_project"])
    assert (a.created_by, a.product_pic, a.sales_pic) == (pembuat.id, produk.id, None)
    assert (b.created_by, b.product_pic, b.sales_pic) == (pembuat.id, produk.id, sales.id)


async def test_respons_pembuatan_memuat_tiga_orang_dengan_id_nama_email(api, db_session):
    produk = await user_baru(db_session, "Product", name="Pia Produk")

    resp = await buat_proyek(api, bearer(produk))

    data = resp.json()["data"]
    esensi = {"id": str(produk.id), "name": "Pia Produk", "email": produk.email}
    assert data["created_by"] == data["product_pic"] == esensi
    assert data["sales_pic"] is None


# ------------------------------------------------------------------- daftar, detail, filter


async def _proyek_dengan_orang(db, *, sales, produk, pembuat, **o) -> Project:
    o.setdefault("status", "Assigned")
    proyek = bangun_project(
        sales.id if sales else None,
        product_pic=produk.id,
        created_by=pembuat.id,
        **o,
    )
    await simpan(db, proyek)
    return proyek


async def test_detail_menampilkan_created_by_product_dan_sales_kosong_sebagai_null(
    api, db_session
):
    produk = await user_baru(db_session, "Product", name="Pia Produk")
    sales = await user_baru(db_session, "Sales", name="Sari Sales")
    lead = await user_baru(db_session, "Lead_SA", name="Lena Lead")
    lengkap = await _proyek_dengan_orang(db_session, sales=sales, produk=produk, pembuat=lead)
    tanpa_sales = await _proyek_dengan_orang(db_session, sales=None, produk=produk, pembuat=lead)

    d1 = (
        await api.client.get(f"{API}/projects/{lengkap.id_project}", headers=bearer(lead))
    ).json()["data"]
    d2 = (
        await api.client.get(f"{API}/projects/{tanpa_sales.id_project}", headers=bearer(lead))
    ).json()["data"]

    assert d1["created_by"]["name"] == "Lena Lead"
    assert d1["product_pic"] == {"id": str(produk.id), "name": "Pia Produk", "email": produk.email}
    assert d1["sales_pic"]["name"] == "Sari Sales"
    assert d2["sales_pic"] is None
    assert d2["product_pic"]["name"] == "Pia Produk"


async def test_daftar_menampilkan_orang_per_proyek(api, db_session):
    produk = await user_baru(db_session, "Product", name="Pia Produk")
    sales = await user_baru(db_session, "Sales", name="Sari Sales")
    lead = await user_baru(db_session, "Lead_SA", name="Lena Lead")
    await _proyek_dengan_orang(db_session, sales=sales, produk=produk, pembuat=lead)
    await _proyek_dengan_orang(db_session, sales=None, produk=produk, pembuat=lead)

    data = (await api.client.get(f"{API}/projects", headers=bearer(lead))).json()["data"]

    assert len(data) == 2
    assert {d["product_pic"]["name"] for d in data} == {"Pia Produk"}
    assert {d["created_by"]["name"] for d in data} == {"Lena Lead"}
    assert sorted(d["sales_pic"]["name"] if d["sales_pic"] else "-" for d in data) == [
        "-",
        "Sari Sales",
    ]


# ------------------------------------------------------------------------------------ akses


async def test_product_pic_setara_sales_pic_walau_sales_pic_orang_lain(api, db_session):
    produk = await user_baru(db_session, "Product")
    sales = await user_baru(db_session, "Sales")
    proyek = await _proyek_dengan_orang(
        db_session, sales=sales, produk=produk, pembuat=sales, status="Submitted"
    )

    ubah_status = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/status",
        json={"new_status": "Won"},
        headers=bearer(produk),
    )
    isi_dq = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/dq-number",
        json={"dq_number": "DQ-2025-001"},
        headers=bearer(produk),
    )

    assert ubah_status.status_code == 200, ubah_status.text
    assert isi_dq.status_code == 200, isi_dq.text


async def test_created_by_saja_tidak_memberi_hak_requester(api, db_session):
    """Lead_SA pembuat tetap berhak sebagai Lead_SA; Sales yang hanya `created_by` tidak."""
    produk = await user_baru(db_session, "Product")
    sales_pic = await user_baru(db_session, "Sales")
    pembuat_sales_lain = await user_baru(db_session, "Sales")
    proyek = await _proyek_dengan_orang(
        db_session, sales=sales_pic, produk=produk, pembuat=pembuat_sales_lain
    )

    resp = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/dq-number",
        json={"dq_number": "DQ-2025-002"},
        headers=bearer(pembuat_sales_lain),
    )

    assert resp.status_code == 403


async def test_product_pic_tanpa_sales_melihat_solutions_setelah_dq_terisi(api, db_session):
    produk = await user_baru(db_session, "Product")
    sa = await user_baru(db_session, "SA")
    proyek = await _proyek_dengan_orang(
        db_session, sales=None, produk=produk, pembuat=produk, dq_number="DQ-2025-003"
    )
    await simpan(
        db_session, bangun_document(proyek.id_project, sa.id, doc_type="PropTek", status="Final")
    )

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents/solutions", headers=bearer(produk)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1


async def test_product_lain_bukan_pic_tidak_melihat_solutions(api, db_session):
    produk = await user_baru(db_session, "Product")
    bukan_pic = await user_baru(db_session, "Product")
    sa = await user_baru(db_session, "SA")
    proyek = await _proyek_dengan_orang(
        db_session, sales=None, produk=produk, pembuat=produk, dq_number="DQ-2025-004"
    )
    await simpan(
        db_session, bangun_document(proyek.id_project, sa.id, doc_type="PropTek", status="Final")
    )

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents/solutions", headers=bearer(bukan_pic)
    )

    assert resp.status_code == 403


# ---------------------------------------------------- proyek tanpa Sales berjalan sampai Assigned


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


async def test_proyek_tanpa_sales_dibuat_lalu_ditugaskan_sampai_assigned(
    api, db_session, fake_drive, monkeypatch
):
    dunia = await bangun_dunia(db_session)
    dibuat = await buat_proyek(api, dunia.h["produk"])
    assert dibuat.status_code == 201, dibuat.text
    pid = dibuat.json()["data"]["id_project"]
    proyek = await ambil_proyek(db_session, pid)
    proyek.status = "Awaiting Assignment"  # lolos gate kualifikasi
    await db_session.commit()
    rekam_background(monkeypatch)

    resp = await api.client.post(
        ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["project"]["status"] == "Assigned"
    assert (await ambil_proyek(db_session, pid)).sales_pic is None


async def test_eskalasi_sla_proyek_tanpa_sales_tidak_crash_dan_manager_tetap_diberi_tahu(
    api, db_session, monkeypatch
):
    dunia = await bangun_dunia(db_session)
    bekukan_waktu(monkeypatch, T0)
    proyek = bangun_project(
        None,
        product_pic=dunia.produk.id,
        created_by=dunia.produk.id,
        status="Assigned",
        assigned_sa=dunia.sa.id,
        assigned_at=T0,
    )
    await simpan(db_session, proyek)
    await sla_timer.start_timer(proyek.id_project, T0, db_session)
    await db_session.commit()
    bekukan_waktu(monkeypatch, T0 + timedelta(days=5))

    stats = await sla_timer.process_sla_actions()

    assert stats["errors"] == []
    assert stats["escalations_sent"] == 1
    penerima = (
        await db_session.execute(
            select(NotificationLog.recipient_user_id).where(
                NotificationLog.reference_id == proyek.id_project
            )
        )
    ).scalars().all()
    assert dunia.lead.id in penerima  # manager tetap menerima eskalasi


# --------------------------------------------------------------- pencarian user per role


async def test_pencarian_user_dapat_disaring_per_role_tanpa_kata_kunci(api, db_session):
    sales = await user_baru(db_session, "Sales")
    await user_baru(db_session, "Product", name="Produk Satu")
    await user_baru(db_session, "Product", name="Produk Dua")
    await user_baru(db_session, "SA", name="Produk Palsu SA")

    tanpa_q = await api.client.get(f"{API}/projects/users/search?role=Product", headers=bearer(sales))
    dengan_q = await api.client.get(
        f"{API}/projects/users/search?role=Product&q=satu", headers=bearer(sales)
    )
    tanpa_keduanya = await api.client.get(f"{API}/projects/users/search", headers=bearer(sales))
    role_salah = await api.client.get(
        f"{API}/projects/users/search?role=Dewa", headers=bearer(sales)
    )

    assert {u["name"] for u in tanpa_q.json()["data"]} == {"Produk Satu", "Produk Dua"}
    assert {u["role"] for u in tanpa_q.json()["data"]} == {"Product"}
    assert [u["name"] for u in dengan_q.json()["data"]] == ["Produk Satu"]
    assert tanpa_keduanya.status_code == 422
    assert role_salah.status_code == 422
