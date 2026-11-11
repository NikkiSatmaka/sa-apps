"""
Akses dokumen, gating Solutions, `doc_ready`, dan DQ Number (tiket #90, spec #87).

Matriks peran × aksi di Postgres nyata. Pihak berhak berhasil; pihak tidak berhak mendapat 403
TANPA efek samping — tidak ada penulisan dokumen/status/DQ, timer SLA tidak berhenti, tidak ada
notifikasi, tidak ada panggilan Drive/LLM/Gmail. Sesi request di-commit juga pada jalur 403
(`komit_sesi_request`) sehingga penulisan-lalu-403 terdeteksi.
"""

import pytest
from sqlalchemy import func, select

from app.models import Document, NotificationLog, Project, SLATracking
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_document, simpan
from tests.integration.support_akses import AKTOR_BACA, AKTOR_TIDAK_BERHAK, ID_PROYEK

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

API = "/api/v1"
LINK = "https://drive.google.com/file/d/abc"
PESAN_403 = "Anda tidak memiliki akses ke proyek ini."
FOLDER_SOLUTIONS = "folder-solutions"

# Penulis berhak (matriks #87): Lead_SA, Admin, SA ditugaskan, collaborator contributor.
AKTOR_TULIS = ["lead", "admin", "sa", "kolab_contrib"]
AKTOR_TULIS_DITOLAK = ["sales_pic", "kolab_viewer", "kolab_lain", "sales_luar", "sa_luar"]
# Memajukan status dokumen: Lead_SA, Admin, SA ditugaskan.
AKTOR_MAJU = ["lead", "admin", "sa"]
AKTOR_MAJU_DITOLAK = [
    "sales_pic",
    "kolab_viewer",
    "kolab_contrib",
    "kolab_lain",
    "sales_luar",
    "sa_luar",
]
# Isi DQ: Sales PIC proyek itu, Lead_SA, Admin.
AKTOR_DQ = ["sales_pic", "lead", "admin"]
AKTOR_DQ_DITOLAK = ["sa", "kolab_viewer", "kolab_contrib", "kolab_lain", "sales_luar", "sa_luar"]


async def _siapkan_proyek(db, skenario, *, dq=None, status="Assigned"):
    p = skenario.proyek
    p.dq_number = dq
    p.status = status
    p.gdrive_folder_id = "folder-master"
    p.gdrive_solutions_folder_id = FOLDER_SOLUTIONS
    await db.commit()
    return p


async def _dokumen(db, skenario, *, status="Draft", doc_type="BOQ", folder="Solutions"):
    dok = bangun_document(
        ID_PROYEK,
        skenario.aktor["sa"].id,
        status=status,
        doc_type=doc_type,
        folder_type=folder,
    )
    await simpan(db, dok)
    await db.commit()
    return dok


async def _jumlah(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _tanpa_efek_samping(db, fake_drive, fake_llm, fake_gmail, *, notif_awal=0):
    assert await _jumlah(db, NotificationLog) == notif_awal
    assert fake_drive.panggilan == []
    assert fake_llm.jumlah() == 0
    assert fake_gmail.percobaan == []


async def _muat(db, model, **kriteria):
    obj = (await db.execute(select(model).filter_by(**kriteria))).scalar_one()
    await db.refresh(obj)
    return obj


# --------------------------------------------------------------------------- POST dokumen (TULIS)


def _url_dok(id_proyek=ID_PROYEK) -> str:
    return f"{API}/projects/{id_proyek}/documents"


def _body_dok():
    return {"doc_type": "PropTek", "gdrive_link": LINK, "folder_type": "Solutions"}


@pytest.mark.parametrize("aktor", AKTOR_TULIS)
async def test_penulis_berhak_membuat_dokumen_201(api, db_session, skenario_akses, aktor):
    resp = await api.client.post(_url_dok(), json=_body_dok(), headers=skenario_akses.header(aktor))

    assert resp.status_code == 201, resp.text
    baris = await _muat(db_session, Document, id_doc=resp.json()["data"]["id_doc"])
    assert baris.id_project == ID_PROYEK
    assert baris.created_by == skenario_akses.aktor[aktor].id


@pytest.mark.parametrize("aktor", AKTOR_TULIS_DITOLAK)
async def test_buat_dokumen_pihak_tak_berhak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_drive, fake_llm, fake_gmail, aktor
):
    resp = await api.client.post(_url_dok(), json=_body_dok(), headers=skenario_akses.header(aktor))

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    assert await _jumlah(db_session, Document) == 0
    await _tanpa_efek_samping(db_session, fake_drive, fake_llm, fake_gmail)


# --------------------------------------------------------------------------- PATCH status dokumen


async def _ubah(api, skenario, dokumen, tujuan, aktor):
    return await api.client.patch(
        f"{API}/documents/{dokumen.id_doc}/status",
        json={"new_status": tujuan},
        headers=skenario.header(aktor),
    )


@pytest.mark.parametrize("aktor", AKTOR_MAJU)
@pytest.mark.parametrize(("awal", "akhir"), [("Draft", "Reviewed"), ("Reviewed", "Final")])
async def test_maju_oleh_pihak_berhak_200(api, db_session, skenario_akses, aktor, awal, akhir):
    await _siapkan_proyek(db_session, skenario_akses)
    dok = await _dokumen(db_session, skenario_akses, status=awal)

    resp = await _ubah(api, skenario_akses, dok, akhir, aktor)

    assert resp.status_code == 200, resp.text
    baris = await _muat(db_session, Document, id_doc=dok.id_doc)
    assert (baris.status, baris.updated_by) == (akhir, skenario_akses.aktor[aktor].id)


@pytest.mark.parametrize("aktor", AKTOR_MAJU_DITOLAK)
@pytest.mark.parametrize(("awal", "akhir"), [("Draft", "Reviewed"), ("Reviewed", "Final")])
async def test_maju_pihak_tak_berhak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_drive, fake_llm, fake_gmail, aktor, awal, akhir
):
    # DQ terisi: bila lolos, Draft → Reviewed akan memicu doc_ready dan membuka Drive.
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status=awal)

    resp = await _ubah(api, skenario_akses, dok, akhir, aktor)

    assert resp.status_code == 403
    baris = await _muat(db_session, Document, id_doc=dok.id_doc)
    assert (baris.status, baris.updated_by) == (awal, None)
    await _tanpa_efek_samping(db_session, fake_drive, fake_llm, fake_gmail)


@pytest.mark.parametrize("aktor", ["lead", "admin"])
@pytest.mark.parametrize(("awal", "akhir"), [("Final", "Reviewed"), ("Reviewed", "Draft")])
async def test_mundur_lead_sa_dan_admin_200(api, db_session, skenario_akses, aktor, awal, akhir):
    await _siapkan_proyek(db_session, skenario_akses)
    dok = await _dokumen(db_session, skenario_akses, status=awal)

    resp = await _ubah(api, skenario_akses, dok, akhir, aktor)

    assert resp.status_code == 200, resp.text
    baris = await _muat(db_session, Document, id_doc=dok.id_doc)
    assert (baris.status, baris.updated_by) == (akhir, skenario_akses.aktor[aktor].id)


@pytest.mark.parametrize("aktor", ["sa", "sales_pic", "kolab_contrib", "sa_luar"])
@pytest.mark.parametrize(("awal", "akhir"), [("Final", "Reviewed"), ("Reviewed", "Draft")])
async def test_mundur_selain_lead_sa_dan_admin_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_drive, fake_llm, fake_gmail, aktor, awal, akhir
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status=awal)

    resp = await _ubah(api, skenario_akses, dok, akhir, aktor)

    assert resp.status_code == 403
    assert (await _muat(db_session, Document, id_doc=dok.id_doc)).status == awal
    await _tanpa_efek_samping(db_session, fake_drive, fake_llm, fake_gmail)


async def test_final_ke_draft_admin_400_bukan_403(api, db_session, skenario_akses):
    """Admin = Lead_SA: lolos proteksi Final, lalu Final → Draft ditolak sebagai loncat (400)."""
    await _siapkan_proyek(db_session, skenario_akses)
    dok = await _dokumen(db_session, skenario_akses, status="Final")

    resp = await _ubah(api, skenario_akses, dok, "Draft", "admin")

    assert resp.status_code == 400


# --------------------------------------------------------------------------- doc_ready


async def _doc_ready_terkirim(db) -> bool:
    n = await _jumlah(db, NotificationLog)
    return n > 0


@pytest.mark.parametrize("aktor", AKTOR_MAJU)
async def test_draft_ke_reviewed_dengan_dq_doc_ready_dan_buka_solutions(
    api, db_session, skenario_akses, fake_drive, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status="Draft")

    resp = await _ubah(api, skenario_akses, dok, "Reviewed", aktor)

    assert resp.status_code == 200, resp.text
    assert await _doc_ready_terkirim(db_session)
    sales = skenario_akses.aktor["sales_pic"]
    assert fake_drive.peran(FOLDER_SOLUTIONS, sales.email) == "reader"


@pytest.mark.parametrize("aktor", ["lead", "admin"])
async def test_final_ke_reviewed_tidak_memicu_doc_ready_atau_membuka_solutions(
    api, db_session, skenario_akses, fake_drive, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status="Final")

    resp = await _ubah(api, skenario_akses, dok, "Reviewed", aktor)

    assert resp.status_code == 200, resp.text
    assert (await _muat(db_session, Document, id_doc=dok.id_doc)).status == "Reviewed"
    assert not await _doc_ready_terkirim(db_session)
    assert fake_drive.panggilan == []


async def test_requirement_tidak_memicu_doc_ready(api, db_session, skenario_akses, fake_drive):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status="Draft", doc_type="Requirement")

    resp = await _ubah(api, skenario_akses, dok, "Reviewed", "lead")

    assert resp.status_code == 200, resp.text
    assert not await _doc_ready_terkirim(db_session)
    assert fake_drive.panggilan == []


# --------------------------------------------------------------------------- GET link Solutions


def _url_solutions(id_proyek=ID_PROYEK) -> str:
    return f"{API}/projects/{id_proyek}/documents/solutions"


@pytest.mark.parametrize("aktor", ["lead", "admin", "sa", "kolab_viewer", "kolab_contrib"])
async def test_solutions_akses_proyek_biasa_200_semua_dokumen(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses)
    await _dokumen(db_session, skenario_akses, status="Draft")

    resp = await api.client.get(_url_solutions(), headers=skenario_akses.header(aktor))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1


async def test_solutions_sales_pic_tanpa_dq_200_daftar_kosong(api, db_session, skenario_akses):
    await _siapkan_proyek(db_session, skenario_akses, dq=None)
    await _dokumen(db_session, skenario_akses, status="Reviewed")

    resp = await api.client.get(_url_solutions(), headers=skenario_akses.header("sales_pic"))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["documents"], data["total"], data["dq_required"]) == ([], 0, True)


async def test_solutions_sales_pic_dengan_dq_hanya_reviewed_dan_final(
    api, db_session, skenario_akses
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    await _dokumen(db_session, skenario_akses, status="Draft")
    await _dokumen(db_session, skenario_akses, status="Reviewed")

    resp = await api.client.get(_url_solutions(), headers=skenario_akses.header("sales_pic"))

    assert resp.status_code == 200, resp.text
    assert [d["status"] for d in resp.json()["data"]["documents"]] == ["Reviewed"]


@pytest.mark.parametrize("dq", [None, "DQ-10001"])
@pytest.mark.parametrize("aktor", ["sales_luar", "kolab_lain", "sa_luar"])
async def test_solutions_pihak_tak_berhak_403(api, db_session, skenario_akses, aktor, dq):
    await _siapkan_proyek(db_session, skenario_akses, dq=dq)
    await _dokumen(db_session, skenario_akses, status="Final")

    resp = await api.client.get(_url_solutions(), headers=skenario_akses.header(aktor))

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403


async def test_solutions_sales_collaborator_bukan_pic_403(api, db_session, skenario_akses):
    """Sales yang hanya collaborator (bukan PIC) tidak boleh melihat link Solutions."""
    from app.models.project_collaborator import ProjectCollaborator

    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    db_session.add(
        ProjectCollaborator(
            id_project=ID_PROYEK,
            user_id=skenario_akses.aktor["sales_luar"].id,
            role="viewer",
            added_by=skenario_akses.aktor["lead"].id,
        )
    )
    await db_session.commit()

    resp = await api.client.get(_url_solutions(), headers=skenario_akses.header("sales_luar"))

    assert resp.status_code == 403


# --------------------------------------------------------------------------- PATCH dq-number


def _url_dq(id_proyek=ID_PROYEK) -> str:
    return f"{API}/projects/{id_proyek}/dq-number"


async def _isi_dq(api, skenario, aktor, nilai="DQ-12345"):
    return await api.client.patch(
        _url_dq(), json={"dq_number": nilai}, headers=skenario.header(aktor)
    )


async def _sla(db) -> SLATracking:
    return await _muat(db, SLATracking, project_id=ID_PROYEK)


@pytest.mark.parametrize("aktor", AKTOR_DQ)
async def test_dq_pengisi_berhak_menyimpan_dan_menghentikan_timer(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses)

    resp = await _isi_dq(api, skenario_akses, aktor)

    assert resp.status_code == 200, resp.text
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.status) == ("DQ-12345", "Ready")
    assert (await _sla(db_session)).stopped_at is not None


@pytest.mark.parametrize("aktor", AKTOR_DQ_DITOLAK)
async def test_dq_pihak_tak_berhak_403_timer_tidak_berhenti(
    api, db_session, skenario_akses, fake_drive, fake_llm, fake_gmail, aktor
):
    await _siapkan_proyek(db_session, skenario_akses)

    resp = await _isi_dq(api, skenario_akses, aktor)

    assert resp.status_code == 403
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.status) == (None, "Assigned")
    assert (await _sla(db_session)).stopped_at is None
    await _tanpa_efek_samping(db_session, fake_drive, fake_llm, fake_gmail)


async def test_dq_sales_bukan_pic_pada_proyek_lain_tidak_menghentikan_timer_dan_unlock(
    api, db_session, skenario_akses, fake_drive
):
    """Sales lain tidak bisa membuka kunci Solutions lewat pengisian DQ proyek yang terkunci."""
    await _siapkan_proyek(db_session, skenario_akses)
    sla = await _sla(db_session)
    sla.is_locked = True
    await db_session.commit()

    resp = await _isi_dq(api, skenario_akses, "sales_luar")

    assert resp.status_code == 403
    sla = await _sla(db_session)
    assert (sla.stopped_at, sla.is_locked) == (None, True)
    assert fake_drive.panggilan == []


# --------------------------------------------------------------------------- PATCH proyek: dq_number


def _url_proyek() -> str:
    return f"{API}/projects/{ID_PROYEK}"


@pytest.mark.parametrize("aktor", AKTOR_DQ)
async def test_patch_proyek_ubah_nilai_dq_pengisi_berhak_200(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002")

    resp = await api.client.patch(
        _url_proyek(), json={"dq_number": "DQ-10003"}, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 200, resp.text
    assert (await _muat(db_session, Project, id_project=ID_PROYEK)).dq_number == "DQ-10003"


@pytest.mark.parametrize("aktor", ["sa", "kolab_contrib"])
@pytest.mark.parametrize("nilai", ["DQ-10003", "", None])
async def test_patch_proyek_ubah_nilai_dq_peran_lain_403_tanpa_efek_samping(
    api, db_session, skenario_akses, aktor, nilai
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002")

    resp = await api.client.patch(
        _url_proyek(),
        json={"project_name": "Nama Baru", "dq_number": nilai},
        headers=skenario_akses.header(aktor),
    )

    assert resp.status_code == 403
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.project_name) == ("DQ-10002", "Proyek Akses")


@pytest.mark.parametrize("aktor", ["sa", "kolab_contrib"])
async def test_patch_proyek_peran_lain_isi_dq_pertama_kali_403(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq=None)

    resp = await api.client.patch(
        _url_proyek(), json={"dq_number": "DQ-10001"}, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert (await _muat(db_session, Project, id_project=ID_PROYEK)).dq_number is None


@pytest.mark.parametrize("aktor", ["sa", "kolab_contrib"])
@pytest.mark.parametrize("dq", ["DQ-10002", None])
async def test_patch_proyek_dq_sama_diabaikan_field_lain_tetap_berlaku(
    api, db_session, skenario_akses, aktor, dq
):
    """Form edit mengirim semua field: nilai dq yang tidak berubah tidak boleh memicu 403."""
    await _siapkan_proyek(db_session, skenario_akses, dq=dq)
    kirim = dq if dq is not None else ""

    resp = await api.client.patch(
        _url_proyek(),
        json={"project_name": "Nama Baru", "dq_number": kirim},
        headers=skenario_akses.header(aktor),
    )

    assert resp.status_code == 200, resp.text
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.project_name) == (dq, "Nama Baru")


# --------------------------------------------------------------------------- konsistensi fixture


def test_himpunan_aktor_menutupi_seluruh_skenario():
    """Penjaga agar tabel peran × aksi di berkas ini tidak diam-diam melewatkan aktor."""
    semua = set(AKTOR_BACA) | set(AKTOR_TIDAK_BERHAK)
    assert set(AKTOR_TULIS) | set(AKTOR_TULIS_DITOLAK) == semua
    assert set(AKTOR_MAJU) | set(AKTOR_MAJU_DITOLAK) == semua
    assert set(AKTOR_DQ) | set(AKTOR_DQ_DITOLAK) == semua


@pytest.mark.parametrize(("aktor", "kode"), [("lead", 200), ("admin", 200), ("sa", 403)])
async def test_ubah_status_dokumen_proyek_terhapus_hanya_lead_sa_dan_admin(
    api, db_session, skenario_akses, fake_drive, aktor, kode
):
    """Proyek soft-deleted: relasi tak bisa dibuktikan, jadi SA ditugaskan pun ditolak."""
    from datetime import datetime, timezone

    proyek = await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    dok = await _dokumen(db_session, skenario_akses, status="Draft")
    proyek.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await _ubah(api, skenario_akses, dok, "Reviewed", aktor)

    assert resp.status_code == kode, resp.text
    assert fake_drive.panggilan == []
