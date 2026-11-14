"""
Perbaikan temuan code-review integration branch kebijakan akses (spec #87).

Matriks peran × aksi di Postgres nyata untuk empat temuan perilaku:
- A. `GET /projects/{id}/documents` tidak boleh membocorkan link Solutions ke Sales di luar aturan
  gating `GET /projects/{id}/documents/solutions` (Sales PIC + DQ terisi + Reviewed/Final).
- B. `PATCH /projects/{id}` dengan `dq_number` mengikuti aturan DAN efek samping yang sama dengan
  `PATCH /projects/{id}/dq-number` (status diizinkan, Sales hanya mengisi yang kosong, timer SLA
  berhenti + unlock + status tidak berubah).
- C. `PATCH /projects/subtasks/{id}/status`: pemilik subtask non-privileged harus masih berhak
  TULIS ke proyek subtask itu.
- D. `POST /calendar/map`: pesan 409 tidak membocorkan nama proyek lain.

Sesi request di-commit juga pada jalur 403 (`komit_sesi_request`) agar penulisan-lalu-403
terdeteksi.
"""

import pytest
from sqlalchemy import select

from app.models import Project, SLATracking, Subtask
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_document, bangun_subtask, simpan
from tests.integration.support_akses import ID_PROYEK

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

API = "/api/v1"
URL_PROYEK = f"{API}/projects/{ID_PROYEK}"
URL_DQ = f"{API}/projects/{ID_PROYEK}/dq-number"
LINK_SOLUTIONS = "https://drive.google.com/file/d/rahasia-solutions"
LINK_INVENTORY = "https://drive.google.com/file/d/inventory-biasa"


async def _muat(db, model, **kriteria):
    obj = (await db.execute(select(model).filter_by(**kriteria))).scalar_one()
    await db.refresh(obj)
    return obj


async def _siapkan_proyek(db, skenario, *, dq=None, status="Assigned"):
    proyek = skenario.proyek
    proyek.dq_number = dq
    proyek.status = status
    proyek.gdrive_folder_id = "folder-master"
    proyek.gdrive_solutions_folder_id = "folder-solutions"
    await db.commit()
    return proyek


# =========================================================================== A. daftar dokumen


async def _dokumen(db, skenario, *, status, folder, link, doc_type="BOQ"):
    dok = bangun_document(
        ID_PROYEK,
        skenario.aktor["sa"].id,
        status=status,
        doc_type=doc_type,
        folder_type=folder,
        gdrive_link=link,
    )
    await simpan(db, dok)
    await db.commit()
    return dok


async def _daftar(api, skenario, aktor):
    resp = await api.client.get(
        f"{API}/projects/{ID_PROYEK}/documents", headers=skenario.header(aktor)
    )
    assert resp.status_code == 200, resp.text
    return resp


@pytest.mark.parametrize("aktor", ["lead", "admin", "sa", "kolab_viewer", "kolab_contrib"])
async def test_daftar_dokumen_peran_non_sales_melihat_semua_termasuk_solutions(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq=None)
    await _dokumen(
        db_session, skenario_akses, status="Draft", folder="Solutions", link=LINK_SOLUTIONS
    )
    await _dokumen(
        db_session, skenario_akses, status="Draft", folder="Inventory", link=LINK_INVENTORY
    )

    resp = await _daftar(api, skenario_akses, aktor)

    assert resp.json()["data"]["total"] == 2
    assert LINK_SOLUTIONS in resp.text


@pytest.mark.parametrize("status_dok", ["Draft", "Reviewed", "Final"])
async def test_daftar_dokumen_sales_pic_tanpa_dq_tidak_melihat_solutions_apa_pun_statusnya(
    api, db_session, skenario_akses, status_dok
):
    await _siapkan_proyek(db_session, skenario_akses, dq=None)
    await _dokumen(
        db_session, skenario_akses, status=status_dok, folder="Solutions", link=LINK_SOLUTIONS
    )
    await _dokumen(
        db_session, skenario_akses, status="Draft", folder="Inventory", link=LINK_INVENTORY
    )

    resp = await _daftar(api, skenario_akses, "sales_pic")

    data = resp.json()["data"]
    assert LINK_SOLUTIONS not in resp.text
    # jumlah diturunkan dari daftar yang sudah disaring: tidak membocorkan keberadaan Solutions
    assert (data["total"], [d["folder_type"] for d in data["documents"]]) == (1, ["Inventory"])
    assert "ditemukan 1 dokumen" in resp.json()["message"].lower()


async def test_daftar_dokumen_sales_pic_dengan_dq_hanya_solutions_reviewed_dan_final(
    api, db_session, skenario_akses
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    await _dokumen(db_session, skenario_akses, status="Draft", folder="Solutions", link="draft-x")
    await _dokumen(db_session, skenario_akses, status="Reviewed", folder="Solutions", link="rev-x")
    await _dokumen(db_session, skenario_akses, status="Final", folder="Solutions", link="fin-x")
    await _dokumen(db_session, skenario_akses, status="Draft", folder="Inventory", link="inv-x")

    resp = await _daftar(api, skenario_akses, "sales_pic")

    tampil = sorted(d["gdrive_link"] for d in resp.json()["data"]["documents"])
    assert tampil == ["fin-x", "inv-x", "rev-x"]
    assert resp.json()["data"]["total"] == 3
    assert "draft-x" not in resp.text


async def test_daftar_dokumen_sales_bukan_pic_tidak_melihat_solutions_sama_sekali(
    api, db_session, skenario_akses
):
    """Sales yang hanya collaborator (bukan PIC) lolos akses baca, tetapi Solutions tertutup."""
    from app.models.project_collaborator import ProjectCollaborator

    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10001")
    await _dokumen(
        db_session, skenario_akses, status="Final", folder="Solutions", link=LINK_SOLUTIONS
    )
    await _dokumen(
        db_session, skenario_akses, status="Final", folder="Inventory", link=LINK_INVENTORY
    )
    db_session.add(
        ProjectCollaborator(
            id_project=ID_PROYEK,
            user_id=skenario_akses.aktor["sales_luar"].id,
            role="viewer",
            added_by=skenario_akses.aktor["lead"].id,
        )
    )
    await db_session.commit()

    resp = await _daftar(api, skenario_akses, "sales_luar")

    assert LINK_SOLUTIONS not in resp.text
    assert resp.json()["data"]["total"] == 1


async def test_daftar_dokumen_sales_pic_dokumen_non_solutions_tidak_berubah(
    api, db_session, skenario_akses
):
    await _siapkan_proyek(db_session, skenario_akses, dq=None)
    for folder in ("Inventory", "Diagram"):
        await _dokumen(
            db_session, skenario_akses, status="Draft", folder=folder, link=f"l-{folder}"
        )

    resp = await _daftar(api, skenario_akses, "sales_pic")

    assert resp.json()["data"]["total"] == 2


# =========================================================================== B. DQ via PATCH proyek


async def _patch_proyek(api, skenario, aktor, **badan):
    return await api.client.patch(URL_PROYEK, json=badan, headers=skenario.header(aktor))


async def _patch_dq(api, skenario, aktor, nilai):
    return await api.client.patch(URL_DQ, json={"dq_number": nilai}, headers=skenario.header(aktor))


async def _kunci_sla(db, *, terkunci=True):
    sla = await _muat(db, SLATracking, project_id=ID_PROYEK)
    sla.is_locked = terkunci
    await db.commit()


async def _keadaan(db):
    proyek = await _muat(db, Project, id_project=ID_PROYEK)
    sla = await _muat(db, SLATracking, project_id=ID_PROYEK)
    return {
        "dq": proyek.dq_number,
        "status": proyek.status,
        "timer_berhenti": sla.stopped_at is not None,
        "terkunci": sla.is_locked,
        "dibuka": sla.unlocked_at is not None,
    }


@pytest.mark.parametrize("aktor", ["sales_pic", "lead", "admin"])
async def test_patch_proyek_isi_dq_pertama_kali_efek_samping_sama_dengan_jalur_dq_number(
    api, db_session, skenario_akses, fake_drive, aktor
):
    """Isi pertama lewat PATCH proyek == lewat /dq-number: status tetap, timer berhenti, unlock Drive."""
    await _siapkan_proyek(db_session, skenario_akses)
    await _kunci_sla(db_session)
    resp = await _patch_dq(api, skenario_akses, aktor, "DQ-12345")
    assert resp.status_code == 200, resp.text
    lewat_dq = (await _keadaan(db_session), list(fake_drive.panggilan))

    # reset lalu ulangi lewat PATCH proyek
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    proyek.dq_number, proyek.status = None, "Assigned"
    sla = await _muat(db_session, SLATracking, project_id=ID_PROYEK)
    sla.stopped_at, sla.is_locked, sla.unlocked_at = None, True, None
    await db_session.commit()
    fake_drive.panggilan.clear()

    resp = await _patch_proyek(api, skenario_akses, aktor, dq_number="DQ-12345")
    assert resp.status_code == 200, resp.text
    lewat_patch = (await _keadaan(db_session), list(fake_drive.panggilan))

    assert lewat_patch == lewat_dq
    assert lewat_patch[0] == {
        "dq": "DQ-12345",
        "status": "Assigned",
        "timer_berhenti": True,
        "terkunci": False,
        "dibuka": True,
    }
    assert lewat_patch[1] != []  # unlock Drive benar-benar terjadi


@pytest.mark.parametrize("status_proyek", ["Intake", "Awaiting Assignment", "On Hold"])
@pytest.mark.parametrize("aktor", ["sales_pic", "lead", "admin"])
async def test_patch_proyek_dq_pada_status_tak_diizinkan_400_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_drive, aktor, status_proyek
):
    await _siapkan_proyek(db_session, skenario_akses, status=status_proyek)

    resp = await _patch_proyek(
        api, skenario_akses, aktor, project_name="Nama Baru", dq_number="DQ-12345"
    )

    assert resp.status_code == 400, resp.text
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.status, proyek.project_name) == (
        None,
        status_proyek,
        "Proyek Akses",
    )
    assert (await _keadaan(db_session))["timer_berhenti"] is False
    assert fake_drive.panggilan == []


@pytest.mark.parametrize("nilai", ["DQ-10003", "", None])
async def test_patch_proyek_sales_pic_tidak_boleh_menimpa_atau_mengosongkan_dq(
    api, db_session, skenario_akses, fake_drive, nilai
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002", status="Submitted")

    resp = await _patch_proyek(
        api, skenario_akses, "sales_pic", project_name="Nama Baru", dq_number=nilai
    )

    assert resp.status_code == 403, resp.text
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.project_name) == ("DQ-10002", "Proyek Akses")
    assert fake_drive.panggilan == []


async def test_patch_proyek_sales_pic_dq_sama_diabaikan_field_lain_berlaku(
    api, db_session, skenario_akses
):
    """Form edit mengirim semua field: DQ tak berubah tidak memicu 403 meski Sales PIC."""
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002", status="Submitted")

    resp = await _patch_proyek(
        api, skenario_akses, "sales_pic", project_name="Nama Baru", dq_number="DQ-10002"
    )

    assert resp.status_code == 200, resp.text
    proyek = await _muat(db_session, Project, id_project=ID_PROYEK)
    assert (proyek.dq_number, proyek.project_name) == ("DQ-10002", "Nama Baru")


@pytest.mark.parametrize("aktor", ["lead", "admin"])
async def test_patch_proyek_lead_dan_admin_boleh_mengubah_dq_yang_sudah_ada(
    api, db_session, skenario_akses, aktor
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002", status="Submitted")

    resp = await _patch_proyek(api, skenario_akses, aktor, dq_number="DQ-10003")

    assert resp.status_code == 200, resp.text
    assert (await _muat(db_session, Project, id_project=ID_PROYEK)).dq_number == "DQ-10003"


async def test_patch_proyek_ubah_dq_tidak_menghentikan_timer_ulang_bila_bukan_pertama_kali(
    api, db_session, skenario_akses
):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002", status="Submitted")

    resp = await _patch_proyek(api, skenario_akses, "lead", dq_number="DQ-10003")

    assert resp.status_code == 200
    assert (await _keadaan(db_session))["timer_berhenti"] is False


@pytest.mark.parametrize("aktor", ["sa", "kolab_contrib"])
async def test_patch_proyek_peran_lain_ubah_dq_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_drive, aktor
):
    await _siapkan_proyek(db_session, skenario_akses)

    resp = await _patch_proyek(api, skenario_akses, aktor, dq_number="DQ-12345")

    assert resp.status_code == 403
    assert (await _keadaan(db_session))["dq"] is None
    assert (await _keadaan(db_session))["timer_berhenti"] is False
    assert fake_drive.panggilan == []


async def test_jalur_dq_number_tetap_sales_pic_tidak_menimpa(api, db_session, skenario_akses):
    await _siapkan_proyek(db_session, skenario_akses, dq="DQ-10002", status="Submitted")

    resp = await _patch_dq(api, skenario_akses, "sales_pic", "DQ-10003")

    assert resp.status_code == 403
    assert (await _keadaan(db_session))["dq"] == "DQ-10002"


# =========================================================================== C. status subtask


async def _ubah_status_subtask(api, skenario, subtask, aktor):
    return await api.client.patch(
        f"{API}/projects/subtasks/{subtask.id_subtask}/status",
        json={"status": "done"},
        headers=skenario.header(aktor),
    )


@pytest.mark.parametrize(
    ("pemilik", "boleh"),
    [
        ("sa", True),  # SA ditugaskan di proyek
        ("kolab_contrib", True),  # collaborator contributor masih berhak tulis
        ("kolab_viewer", False),  # viewer: hanya baca
        ("sa_luar", False),  # sudah tidak punya hubungan ke proyek
        ("kolab_lain", False),  # collaborator proyek lain
    ],
)
async def test_status_subtask_pemilik_harus_masih_berhak_tulis_ke_proyek(
    api, db_session, skenario_akses, pemilik, boleh
):
    subtask = bangun_subtask(ID_PROYEK, assigned_sa=skenario_akses.aktor[pemilik].id)
    db_session.add(subtask)
    await db_session.commit()

    resp = await _ubah_status_subtask(api, skenario_akses, subtask, pemilik)

    sesudah = await _muat(db_session, Subtask, id_subtask=subtask.id_subtask)
    if boleh:
        assert resp.status_code == 200, resp.text
        assert sesudah.status == "done"
    else:
        assert resp.status_code == 403, resp.text
        assert sesudah.status == "open"


@pytest.mark.parametrize("aktor", ["lead", "admin"])
async def test_status_subtask_lead_sa_dan_admin_tidak_berubah(
    api, db_session, skenario_akses, aktor
):
    subtask = bangun_subtask(ID_PROYEK, assigned_sa=skenario_akses.aktor["sa_luar"].id)
    db_session.add(subtask)
    await db_session.commit()

    resp = await _ubah_status_subtask(api, skenario_akses, subtask, aktor)

    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("aktor", ["sales_pic", "kolab_contrib", "sa_luar"])
async def test_status_subtask_bukan_pemilik_tetap_403(api, db_session, skenario_akses, aktor):
    subtask = bangun_subtask(ID_PROYEK, assigned_sa=skenario_akses.aktor["sa"].id)
    db_session.add(subtask)
    await db_session.commit()

    resp = await _ubah_status_subtask(api, skenario_akses, subtask, aktor)

    assert resp.status_code == 403
    assert (await _muat(db_session, Subtask, id_subtask=subtask.id_subtask)).status == "open"


# =========================================================================== D. 409 kalender


def _badan_kalender(**o):
    dasar = {
        "gcal_event_id": "evt-bocor",
        "work_type": "Project",
        "project_id": ID_PROYEK,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Diskusi",
        "is_all_day": True,
    }
    dasar.update(o)
    return dasar


async def test_map_kalender_duplikat_409_tidak_membocorkan_nama_proyek(
    api, db_session, skenario_akses
):
    pertama = await api.client.post(
        f"{API}/calendar/map", json=_badan_kalender(), headers=skenario_akses.header("sa")
    )
    kedua = await api.client.post(
        f"{API}/calendar/map",
        json=_badan_kalender(),
        headers=skenario_akses.header("lead"),
    )

    assert (pertama.status_code, kedua.status_code) == (201, 409)
    assert "Proyek Akses" not in kedua.text
    assert ID_PROYEK not in kedua.text
    assert "sudah dipetakan" in kedua.json()["message"]


async def test_map_kalender_duplikat_non_project_409_pesan_sama(api, skenario_akses):
    badan = _badan_kalender(
        work_type="Non-Project", project_id=None, project_phase=None, subtask_category="Training"
    )
    await api.client.post(f"{API}/calendar/map", json=badan, headers=skenario_akses.header("sa"))
    kedua = await api.client.post(
        f"{API}/calendar/map", json=badan, headers=skenario_akses.header("sa")
    )

    assert kedua.status_code == 409
    assert "None" not in kedua.json()["message"]


@pytest.mark.parametrize("jalur", ["dq-number", "patch-proyek"])
async def test_user_berperan_sa_yang_tercatat_sales_pic_tetap_ditolak_isi_dq(
    api, db_session, skenario_akses, fake_drive, jalur
):
    """Hubungan dicocokkan lewat id, tetapi aturan peran DQ (Sales/Lead_SA/Admin) tetap berlaku
    di kedua jalur: SA yang kebetulan tercatat sebagai `sales_pic` tidak boleh mengisi DQ."""
    proyek = await _siapkan_proyek(db_session, skenario_akses)
    proyek.sales_pic = skenario_akses.aktor["sa"].id
    await db_session.commit()

    if jalur == "dq-number":
        resp = await _patch_dq(api, skenario_akses, "sa", "DQ-12345")
    else:
        resp = await _patch_proyek(api, skenario_akses, "sa", dq_number="DQ-12345")

    assert resp.status_code == 403
    assert (await _keadaan(db_session))["dq"] is None
    assert (await _keadaan(db_session))["timer_berhenti"] is False
    assert fake_drive.panggilan == []
