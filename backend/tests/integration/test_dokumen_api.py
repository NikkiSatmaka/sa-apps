"""
Integrasi `api/documents` terhadap Postgres nyata (tiket B6, #59, spec #49): pembuatan dokumen,
daftar dokumen (matriks akses), state machine status dokumen per peran, serta `doc_ready` dan
pembukaan akses Solutions lewat Drive palsu.
Pasangan unit: `tests/test_dokumen_workflow_handover_unit.py`.
"""

import pytest
from sqlalchemy import select

from app.models import Document
from tests.integration.b6_support import (  # noqa: F401
    API,
    buat_dokumen,
    buat_proyek,
    komit_sesi_request,
    muat,
    notifikasi,
    siapkan_dunia,
    user_baru,
)
from tests.integration.model_helpers import bangun_kolaborator, simpan

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

LINK = "https://drive.google.com/file/d/abc"


def _body(**o):
    d = {"doc_type": "PropTek", "gdrive_link": LINK, "folder_type": "Solutions"}
    d.update(o)
    return d


# --------------------------------------------------------------------------- pembuatan dokumen


async def test_buat_dokumen_tersimpan_draft_dengan_pembuat(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/documents",
        json=_body(notes="catatan awal"),
        headers=dunia.header["SA"],
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "Draft"
    assert data["doc_type"] == "PropTek"
    assert data["created_by"] == str(dunia.user["SA"].id)
    assert data["updated_by"] is None
    baris = await muat(db_session, Document, id_doc=data["id_doc"])
    assert baris.id_project == proyek.id_project
    assert baris.status == "Draft"
    assert baris.gdrive_link == LINK
    assert baris.folder_type == "Solutions"
    assert baris.notes == "catatan awal"
    assert baris.created_by == dunia.user["SA"].id


async def test_buat_dokumen_requirement_ditolak_dan_tidak_tersimpan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/documents",
        json=_body(doc_type="Requirement"),
        headers=dunia.header["Lead_SA"],
    )

    assert resp.status_code == 422
    assert "Requirement" in resp.json()["message"]
    semua = (await db_session.execute(select(Document))).scalars().all()
    assert semua == []


async def test_buat_dokumen_proyek_tidak_ada_404(api, db_session):
    dunia = await siapkan_dunia(api, db_session)

    resp = await api.client.post(
        f"{API}/projects/PRJ-TIDAK-ADA/documents", json=_body(), headers=dunia.header["SA"]
    )

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "ubah",
    [
        {"doc_type": "Lain"},
        {"folder_type": "Rahasia"},
        {"gdrive_link": ""},
    ],
)
async def test_buat_dokumen_input_tidak_valid_422_dan_tidak_tersimpan(api, db_session, ubah):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/documents",
        json=_body(**ubah),
        headers=dunia.header["SA"],
    )

    assert resp.status_code == 422
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_buat_dokumen_tanpa_login_401(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(f"{API}/projects/{proyek.id_project}/documents", json=_body())

    assert resp.status_code in (401, 403)
    assert (await db_session.execute(select(Document))).scalars().all() == []


# --------------------------------------------------------------------------- daftar dokumen & akses


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin", "Sales", "SA"])
async def test_daftar_dokumen_diizinkan_untuk_peran_terkait_proyek(api, db_session, peran):
    """Lead_SA/Admin: semua proyek. Sales: PIC proyek. SA: SA yang ditugaskan.

    DIUBAH (review kebijakan akses): dokumen kini di folder Inventory. Sebelumnya folder default
    Solutions, yang kini disembunyikan dari Sales PIC sebelum DQ terisi (gating sama dengan
    GET .../documents/solutions; dikunci test_akses_perbaikan_review.py). Assertion tidak berubah.
    """
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, folder_type="Inventory")

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents", headers=dunia.header[peran]
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["documents"][0]["id_doc"] == dokumen.id_doc


async def test_daftar_dokumen_collaborator_diizinkan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    await buat_dokumen(db_session, proyek, dunia)
    kolab, header = await user_baru(db_session, "SA")
    await simpan(
        db_session, bangun_kolaborator(proyek.id_project, kolab.id, dunia.user["Lead_SA"].id)
    )

    resp = await api.client.get(f"{API}/projects/{proyek.id_project}/documents", headers=header)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1


@pytest.mark.parametrize("peran", ["SA", "Sales"])
async def test_daftar_dokumen_tanpa_hubungan_ke_proyek_403(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    await buat_dokumen(db_session, proyek, dunia)
    _, header = await user_baru(db_session, peran)

    resp = await api.client.get(f"{API}/projects/{proyek.id_project}/documents", headers=header)

    assert resp.status_code == 403
    assert resp.json()["message"] == "Anda tidak memiliki akses ke proyek ini."


async def test_daftar_dokumen_sa_proyek_lain_dan_sales_proyek_lain_403(api, db_session):
    """SA demo ditugaskan di proyek A, bukan B; Sales demo PIC proyek A, bukan B."""
    dunia = await siapkan_dunia(api, db_session)
    sales_lain, _ = await user_baru(db_session, "Sales")
    from tests.integration.model_helpers import bangun_project

    proyek_b = bangun_project(sales_lain.id, status="Assigned")
    await simpan(db_session, proyek_b)

    for peran in ("SA", "Sales"):
        resp = await api.client.get(
            f"{API}/projects/{proyek_b.id_project}/documents", headers=dunia.header[peran]
        )
        assert resp.status_code == 403, peran


async def test_daftar_dokumen_proyek_tidak_ada_404_dan_urutan_terbaru_di_atas(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    kosong = await api.client.get(
        f"{API}/projects/PRJ-TIDAK-ADA/documents", headers=dunia.header["Lead_SA"]
    )
    assert kosong.status_code == 404

    from datetime import datetime, timedelta, timezone

    sekarang = datetime.now(timezone.utc)
    lama = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", created_at=sekarang)
    baru = await buat_dokumen(
        db_session, proyek, dunia, doc_type="Mandays", created_at=sekarang + timedelta(hours=1)
    )

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents", headers=dunia.header["Lead_SA"]
    )

    ids = [d["id_doc"] for d in resp.json()["data"]["documents"]]
    assert ids == [baru.id_doc, lama.id_doc]
    assert resp.json()["data"]["requirement_generation_status"] is None


async def test_daftar_dokumen_flag_regenerate_requirement_sesuai_peran(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    hasil = {}
    for peran in ("Lead_SA", "Admin", "SA", "Sales"):
        resp = await api.client.get(
            f"{API}/projects/{proyek.id_project}/documents", headers=dunia.header[peran]
        )
        hasil[peran] = resp.json()["data"]["can_regenerate_requirement"]

    assert hasil == {"Lead_SA": True, "Admin": True, "SA": True, "Sales": False}


async def test_daftar_dokumen_requirement_override_menandai_sumber_berubah(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, qualification_answers={"a": "b"})
    requirement = await buat_dokumen(
        db_session,
        proyek,
        dunia,
        doc_type="Requirement",
        gdrive_link=None,
        content=[{"id": "abcd1234", "kategori": "Fungsional", "butir": "Login"}],
        is_overridden=True,
        source_hash="hash-lama-yang-pasti-beda",
    )

    resp = await api.client.get(
        f"{API}/projects/{proyek.id_project}/documents", headers=dunia.header["Lead_SA"]
    )

    doc = resp.json()["data"]["documents"][0]
    assert doc["id_doc"] == requirement.id_doc
    assert doc["source_changed"] is True


# --------------------------------------------------------------------------- state machine status

MAJU = [("Draft", "Reviewed"), ("Reviewed", "Final")]
MUNDUR = [("Final", "Reviewed"), ("Reviewed", "Draft")]


async def _ubah(api, dokumen, status_baru, header):
    return await api.client.patch(
        f"{API}/documents/{dokumen.id_doc}/status",
        json={"new_status": status_baru},
        headers=header,
    )


@pytest.mark.parametrize("peran", ["SA", "Lead_SA"])
@pytest.mark.parametrize(("awal", "akhir"), MAJU)
async def test_transisi_maju_sa_dan_lead_sa_diizinkan_dan_dicatat(
    api, db_session, peran, awal, akhir
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status=awal)

    resp = await _ubah(api, dokumen, akhir, dunia.header[peran])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == akhir
    baris = await muat(db_session, Document, id_doc=dokumen.id_doc)
    assert baris.status == akhir
    assert baris.updated_by == dunia.user[peran].id


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
@pytest.mark.parametrize(("awal", "akhir"), MUNDUR)
async def test_transisi_mundur_lead_sa_dan_admin_diizinkan(api, db_session, peran, awal, akhir):
    # Diubah (#90): Admin = Lead_SA untuk semua aksi matriks; sebelumnya Admin keliru ditolak.
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status=awal)

    resp = await _ubah(api, dokumen, akhir, dunia.header[peran])

    assert resp.status_code == 200, resp.text
    baris = await muat(db_session, Document, id_doc=dokumen.id_doc)
    assert baris.status == akhir
    assert baris.updated_by == dunia.user[peran].id


@pytest.mark.parametrize("peran", ["SA", "Sales"])
@pytest.mark.parametrize(("awal", "akhir"), MUNDUR)
async def test_transisi_mundur_selain_lead_sa_dan_admin_403_status_tidak_berubah(
    api, db_session, peran, awal, akhir
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status=awal)

    resp = await _ubah(api, dokumen, akhir, dunia.header[peran])

    assert resp.status_code == 403
    baris = await muat(db_session, Document, id_doc=dokumen.id_doc)
    assert baris.status == awal
    assert baris.updated_by is None


@pytest.mark.parametrize("peran", ["SA", "Lead_SA", "Admin"])
async def test_loncat_draft_ke_final_ditolak_semua_peran(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status="Draft")

    resp = await _ubah(api, dokumen, "Final", dunia.header[peran])

    assert resp.status_code == 400
    assert "tidak valid" in resp.json()["message"]
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Draft"


@pytest.mark.parametrize(("peran", "kode"), [("Lead_SA", 400), ("Admin", 400), ("SA", 403)])
async def test_final_ke_draft_bukan_transisi_valid_bagi_siapa_pun(api, db_session, peran, kode):
    """
    Final ke Draft melompat dua langkah. Selain Lead_SA/Admin ditolak lebih dulu oleh proteksi
    Final. Diubah (#90): Admin kini lolos proteksi Final (400 sebagai loncat), bukan 403.
    """
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status="Final")

    resp = await _ubah(api, dokumen, "Draft", dunia.header[peran])

    assert resp.status_code == kode
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Final"


async def test_dokumen_final_sa_ditugaskan_ditolak_dengan_pesan_proteksi_final(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status="Final")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 403
    assert "yang sudah 'Final'" in resp.json()["message"]
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Final"


async def test_dokumen_final_sales_ditolak_oleh_cek_akses_proyek(api, db_session):
    """Sales (PIC sekalipun) tidak berhak mengelola status dokumen: 403 generik dari cek akses."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status="Final")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["Sales"])

    assert resp.status_code == 403
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Final"


async def test_dokumen_final_admin_boleh_mundur_ke_reviewed(api, db_session):
    # Diubah (#90): sebelumnya Admin ditolak oleh proteksi Final yang hanya mengizinkan Lead_SA.
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status="Final")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["Admin"])

    assert resp.status_code == 200, resp.text
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Reviewed"


@pytest.mark.parametrize("status_", ["Draft", "Reviewed", "Final"])
async def test_status_sama_ditolak_400(api, db_session, status_):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, status=status_)

    resp = await _ubah(api, dokumen, status_, dunia.header["Lead_SA"])

    assert resp.status_code == 400
    assert "Tidak ada perubahan" in resp.json()["message"]


async def test_status_tidak_dikenal_422_dokumen_tidak_ada_404(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia)

    tak_dikenal = await _ubah(api, dokumen, "Archived", dunia.header["Lead_SA"])
    tak_ada = await api.client.patch(
        f"{API}/documents/DOC-TIDAK-ADA/status",
        json={"new_status": "Reviewed"},
        headers=dunia.header["Lead_SA"],
    )

    assert tak_dikenal.status_code == 422
    assert tak_ada.status_code == 404
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Draft"


async def test_siklus_penuh_draft_ke_final_lalu_mundur_oleh_lead_sa(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia)

    langkah = [
        ("Reviewed", "SA", 200),
        ("Final", "SA", 200),
        ("Reviewed", "SA", 403),  # SA tidak boleh mengubah dokumen Final
        ("Reviewed", "Lead_SA", 200),
        ("Draft", "Lead_SA", 200),
    ]
    for tujuan, peran, kode in langkah:
        resp = await _ubah(api, dokumen, tujuan, dunia.header[peran])
        assert resp.status_code == kode, (tujuan, peran, resp.text)

    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Draft"


# --------------------------------------------------------------------------- doc_ready & Solutions


async def _proyek_dengan_solutions(db, dunia, *, dq="DQ-12345", **o):
    return await buat_proyek(
        db,
        dunia,
        dq_number=dq,
        gdrive_folder_id="folder-master",
        gdrive_solutions_folder_id="folder-solutions",
        **o,
    )


async def test_reviewed_dengan_dq_kirim_doc_ready_dan_buka_akses_solutions_sales(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")
    sales = dunia.user["Sales"]
    assert fake_drive.peran("folder-solutions", sales.email) is None

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200, resp.text
    notif = await notifikasi(db_session, event_type="doc_ready", recipient_user_id=sales.id)
    assert len(notif) == 1
    assert notif[0].reference_id == proyek.id_project
    assert notif[0].notification_metadata["doc_id"] == dokumen.id_doc
    assert notif[0].notification_metadata["doc_type"] == "BOQ"
    assert fake_drive.peran("folder-solutions", sales.email) == "reader"
    [panggilan] = fake_drive.panggilan_operasi("unlock_solutions_folder")
    assert panggilan.argumen == {
        "solutions_folder_id": "folder-solutions",
        "sales_email": sales.email,
    }


async def test_reviewed_tanpa_dq_tidak_kirim_doc_ready_dan_akses_tetap_tertutup(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia, dq=None)
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Reviewed"
    assert await notifikasi(db_session, event_type="doc_ready") == []
    assert fake_drive.panggilan == []
    assert fake_drive.peran("folder-solutions", dunia.user["Sales"].email) is None


async def test_requirement_reviewed_tidak_memicu_doc_ready_maupun_akses_solutions(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    requirement = await buat_dokumen(
        db_session,
        proyek,
        dunia,
        doc_type="Requirement",
        gdrive_link=None,
        content=[],
        created_by=None,
    )

    resp = await _ubah(api, requirement, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200, resp.text
    assert (await muat(db_session, Document, id_doc=requirement.id_doc)).status == "Reviewed"
    assert await notifikasi(db_session, event_type="doc_ready") == []
    assert fake_drive.panggilan == []


async def test_reviewed_ke_final_dan_reviewed_ke_draft_tidak_memicu_doc_ready(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    a = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", status="Reviewed")
    b = await buat_dokumen(db_session, proyek, dunia, doc_type="Mandays", status="Reviewed")

    ke_final = await _ubah(api, a, "Final", dunia.header["SA"])
    ke_draft = await _ubah(api, b, "Draft", dunia.header["Lead_SA"])

    assert (ke_final.status_code, ke_draft.status_code) == (200, 200)
    assert await notifikasi(db_session, event_type="doc_ready") == []
    assert fake_drive.panggilan == []


async def test_proyek_tanpa_folder_solutions_notifikasi_tetap_terkirim_akses_dilewati(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, dq_number="DQ-12345")
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200
    assert len(await notifikasi(db_session, event_type="doc_ready")) == 1
    assert fake_drive.panggilan == []


async def test_kegagalan_drive_tidak_menggagalkan_transisi_dokumen(api, db_session, fake_drive):
    fake_drive.fail_always("unlock_solutions_folder")
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200, resp.text
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Reviewed"
    assert [p.berhasil for p in fake_drive.panggilan_operasi("unlock_solutions_folder")] == [False]
    assert fake_drive.peran("folder-solutions", dunia.user["Sales"].email) is None
    assert len(await notifikasi(db_session, event_type="doc_ready")) == 1


async def test_kegagalan_notifikasi_tidak_menggagalkan_transisi_akses_solutions_tetap_dibuka(
    api, db_session, fake_drive, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.services.notification_service import notification_service

    monkeypatch.setattr(
        notification_service, "send_notification", AsyncMock(side_effect=RuntimeError("boom"))
    )
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["SA"])

    assert resp.status_code == 200, resp.text
    assert (await muat(db_session, Document, id_doc=dokumen.id_doc)).status == "Reviewed"
    assert fake_drive.peran("folder-solutions", dunia.user["Sales"].email) == "reader"


async def test_dokumen_proyek_terhapus_soft_delete_tetap_bisa_diubah_tanpa_doc_ready(
    api, db_session, fake_drive
):
    """Proyek soft-deleted tersembunyi dari ORM: doc_ready dilewati, transisi tetap sukses."""
    from datetime import datetime, timezone

    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_dengan_solutions(db_session, dunia)
    dokumen = await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ")
    proyek.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    resp = await _ubah(api, dokumen, "Reviewed", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert await notifikasi(db_session, event_type="doc_ready") == []
    assert fake_drive.panggilan == []


async def test_edit_butir_requirement_proyek_tidak_ada_404(api, db_session):
    dunia = await siapkan_dunia(api, db_session)

    resp = await api.client.post(
        f"{API}/projects/PRJ-TIDAK-ADA/requirement/items",
        json={"kategori": "Fungsional", "butir": "Login"},
        headers=dunia.header["Lead_SA"],
    )

    assert resp.status_code == 404
