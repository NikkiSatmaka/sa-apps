"""
Integrasi `api/handover` dan `services/handover_service` terhadap Postgres nyata (tiket B6, #59,
spec #49): konfigurasi PMO/Delivery, kesiapan handover (setiap prasyarat), eksekusi handover
(folder Final_Deliverables dan permission lewat Drive palsu, notifikasi, audit, status), kegagalan
Drive, dan hak akses per peran.
Pasangan unit: `tests/test_dokumen_workflow_handover_unit.py`.
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Document, Project
from tests.integration.b6_support import (  # noqa: F401
    API,
    Dunia,
    buat_dokumen,
    buat_proyek,
    komit_sesi_request,
    muat,
    notifikasi,
    siapkan_dunia,
    user_baru,
)
from tests.integration.model_helpers import bangun_user, simpan

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

PMO = "pmo@portal-sa.local"
DELIVERY = "delivery@portal-sa.local"
SOLUTIONS = "folder-solutions"
MASTER = "folder-master"


async def _proyek_siap(db, dunia: Dunia, *, hld: str | None = "Final", **o) -> Project:
    """Proyek yang memenuhi SEMUA prasyarat handover (dapat dirusak per kasus lewat `o`)."""
    kw = {
        "status": "Won",
        "pmo_lead_email": PMO,
        "delivery_lead_email": DELIVERY,
        "gdrive_folder_id": MASTER,
        "gdrive_solutions_folder_id": SOLUTIONS,
    }
    kw.update(o)
    proyek = await buat_proyek(db, dunia, **kw)
    if hld is not None:
        await buat_dokumen(db, proyek, dunia, doc_type="HLD", status=hld)
    return proyek


async def _daftarkan_pmo_dan_delivery(db):
    pmo = bangun_user(role="SA", email=PMO, name="PMO")
    delivery = bangun_user(role="SA", email=DELIVERY, name="Delivery")
    await simpan(db, pmo, delivery)
    return pmo, delivery


async def _trigger(api, id_project, header):
    return await api.client.post(f"{API}/projects/{id_project}/handover", headers=header)


async def _kesiapan(api, id_project, header):
    return await api.client.get(f"{API}/projects/{id_project}/handover-status", headers=header)


async def _tak_berubah(db, proyek, fake_drive):
    """Handover gagal total: status sama, tanpa audit handover, tanpa efek Drive."""
    assert (await muat(db, Project, id_project=proyek.id_project)).status == proyek.status
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "handover"))).scalars().all()
    )
    assert audit == []
    assert fake_drive.panggilan_operasi("provision_handover") == []
    assert await notifikasi(db, event_type="handover") == []


# --------------------------------------------------------------------------- konfigurasi


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_konfigurasi_handover_oleh_lead_sa_dan_admin_tersimpan(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/handover-config",
        json={"pmo_email": PMO, "delivery_email": DELIVERY},
        headers=dunia.header[peran],
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["pmo_lead_email"], data["delivery_lead_email"]) == (PMO, DELIVERY)
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.pmo_lead_email, baris.delivery_lead_email) == (PMO, DELIVERY)


async def test_konfigurasi_handover_ditimpa_oleh_konfigurasi_berikutnya(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, pmo_lead_email="lama@x.id")

    await api.client.post(
        f"{API}/projects/{proyek.id_project}/handover-config",
        json={"pmo_email": PMO, "delivery_email": DELIVERY},
        headers=dunia.header["Admin"],
    )

    assert (await muat(db_session, Project, id_project=proyek.id_project)).pmo_lead_email == PMO


@pytest.mark.parametrize("peran", ["SA", "Sales"])
async def test_konfigurasi_handover_selain_lead_sa_dan_admin_403(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/handover-config",
        json={"pmo_email": PMO, "delivery_email": DELIVERY},
        headers=dunia.header[peran],
    )

    assert resp.status_code == 403
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.pmo_lead_email, baris.delivery_lead_email) == (None, None)


async def test_konfigurasi_handover_proyek_tidak_ada_404_dan_email_tidak_valid_422(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia)

    tak_ada = await api.client.post(
        f"{API}/projects/PRJ-TIDAK-ADA/handover-config",
        json={"pmo_email": PMO, "delivery_email": DELIVERY},
        headers=dunia.header["Lead_SA"],
    )
    tidak_valid = await api.client.post(
        f"{API}/projects/{proyek.id_project}/handover-config",
        json={"pmo_email": "bukan-email", "delivery_email": DELIVERY},
        headers=dunia.header["Lead_SA"],
    )

    assert tak_ada.status_code == 404
    assert tidak_valid.status_code == 422
    assert (await muat(db_session, Project, id_project=proyek.id_project)).pmo_lead_email is None


# --------------------------------------------------------------------------- kesiapan (readiness)


async def test_kesiapan_semua_prasyarat_terpenuhi(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _kesiapan(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {
        "ready": True,
        "missing_items": [],
        "pmo_email": PMO,
        "delivery_email": DELIVERY,
        "project_status": "Won",
        "hld_status": "Final",
    }


@pytest.mark.parametrize(
    ("ubah", "hld", "potongan"),
    [
        ({"status": "Submitted"}, "Final", "Won"),
        ({}, None, "HLD belum dibuat"),
        ({}, "Draft", "Final"),
        ({}, "Reviewed", "Final"),
        ({"pmo_lead_email": None}, "Final", "PMO"),
        ({"delivery_lead_email": None}, "Final", "Delivery"),
        ({"gdrive_folder_id": None}, "Final", "Google Drive"),
    ],
)
async def test_kesiapan_setiap_prasyarat_yang_kurang_dilaporkan(
    api, db_session, ubah, hld, potongan
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia, hld=hld, **ubah)

    resp = await _kesiapan(api, proyek.id_project, dunia.header["Admin"])

    data = resp.json()["data"]
    assert data["ready"] is False
    assert len(data["missing_items"]) == 1
    assert potongan in data["missing_items"][0]
    assert data["hld_status"] == hld


async def test_kesiapan_semua_prasyarat_kurang_melaporkan_semuanya(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")

    resp = await _kesiapan(api, proyek.id_project, dunia.header["Lead_SA"])

    data = resp.json()["data"]
    assert data["ready"] is False
    assert len(data["missing_items"]) == 6
    assert data["project_status"] == "Assigned"
    assert (data["hld_status"], data["pmo_email"], data["delivery_email"]) == (None, None, None)


async def test_kesiapan_hld_final_di_antara_beberapa_dokumen_hld_tetap_siap(api, db_session):
    """Revisi HLD (beberapa dokumen HLD) tidak boleh membuat pengecekan kesiapan error 500."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia, hld="Draft")
    await buat_dokumen(db_session, proyek, dunia, doc_type="HLD", status="Final")

    resp = await _kesiapan(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["ready"] is True
    assert data["hld_status"] == "Final"


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin", "SA"])
async def test_kesiapan_dapat_dilihat_lead_sa_admin_dan_sa_yang_ditugaskan(api, db_session, peran):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _kesiapan(api, proyek.id_project, dunia.header[peran])

    assert resp.status_code == 200, resp.text


async def test_kesiapan_ditolak_untuk_sales_dan_sa_tidak_ditugaskan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)
    _, sa_lain = await user_baru(db_session, "SA")

    sales = await _kesiapan(api, proyek.id_project, dunia.header["Sales"])
    lain = await _kesiapan(api, proyek.id_project, sa_lain)

    assert (sales.status_code, lain.status_code) == (403, 403)
    assert "Sales" in sales.json()["message"]


async def test_kesiapan_proyek_tidak_ada_404(api, db_session):
    dunia = await siapkan_dunia(api, db_session)

    resp = await _kesiapan(api, "PRJ-TIDAK-ADA", dunia.header["Lead_SA"])

    assert resp.status_code == 404


# --------------------------------------------------------------------------- trigger: sukses


async def test_handover_sukses_membuat_final_deliverables_dengan_permission_pmo_dan_delivery(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["old_status"], data["new_status"]) == ("Won", "Handed Over")
    assert (data["pmo_email"], data["delivery_email"]) == (PMO, DELIVERY)
    folder_id = data["final_deliverables_folder_id"]
    assert fake_drive.folder[folder_id] == {"name": "Final_Deliverables", "parent": SOLUTIONS}
    assert fake_drive.peran(folder_id, PMO) == "reader"
    assert fake_drive.peran(folder_id, DELIVERY) == "reader"
    assert fake_drive.peran(folder_id, dunia.user["Sales"].email) is None
    assert data["documents_handed_over"] == ["HLD"]
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert baris.status == "Handed Over"


async def test_handover_sukses_mencatat_audit_log_lengkap(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Admin"])

    [audit] = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "handover")))
        .scalars()
        .all()
    )
    assert audit.entity_id == proyek.id_project
    assert audit.performed_by == dunia.user["Admin"].id
    assert audit.old_value == {"status": "Won"}
    assert audit.new_value["status"] == "Handed Over"
    assert audit.new_value["pmo_lead_email"] == PMO
    assert audit.new_value["delivery_lead_email"] == DELIVERY
    assert (
        audit.new_value["final_deliverables_folder_id"]
        == resp.json()["data"]["final_deliverables_folder_id"]
    )


async def test_handover_sukses_mengirim_notifikasi_ke_pmo_dan_delivery_terdaftar(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    pmo, delivery = await _daftarkan_pmo_dan_delivery(db_session)
    proyek = await _proyek_siap(db_session, dunia)
    await buat_dokumen(db_session, proyek, dunia, doc_type="BOQ", status="Final")
    await buat_dokumen(db_session, proyek, dunia, doc_type="Mandays", status="Draft")

    resp = await _trigger(api, proyek.id_project, dunia.header["SA"])

    assert resp.status_code == 200, resp.text
    notif = await notifikasi(db_session, event_type="handover")
    assert {n.recipient_user_id for n in notif} == {pmo.id, delivery.id}
    assert len(notif) == 2
    for n in notif:
        meta = n.notification_metadata
        assert n.reference_id == proyek.id_project
        assert meta["project_id"] == proyek.id_project
        assert meta["customer_name"] == proyek.customer_name
        assert meta["gdrive_folder_id"] == MASTER
        assert (
            meta["final_deliverables_folder_id"]
            == resp.json()["data"]["final_deliverables_folder_id"]
        )
        assert sorted(meta["final_documents"]) == ["BOQ", "HLD"]  # Draft tidak ikut
    assert sorted(resp.json()["data"]["documents_handed_over"]) == ["BOQ", "HLD"]


async def test_handover_sukses_mengirim_email_ke_penerima_terdaftar(
    api, db_session, fake_drive, fake_gmail
):
    """
    Hanya PMO yang didaftarkan: email dikirim di background task bersesi sendiri, dan dua task
    paralel akan berebut satu koneksi pada harness B2 (lihat `tahan_email` di fakes/gmail.py).
    Delivery tidak punya akun: ia menerima email langsung (tanpa sesi DB, jadi tidak berebut).
    """
    dunia = await siapkan_dunia(api, db_session)
    pmo = bangun_user(role="SA", email=PMO, name="PMO")
    await simpan(db_session, pmo)
    proyek = await _proyek_siap(db_session, dunia)
    fake_gmail.tahan_email()

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])
    fake_gmail.lepaskan_email()

    assert resp.status_code == 200, resp.text
    await fake_gmail.tunggu_percobaan(2)
    surat = next(s for s in fake_gmail.terkirim if s.to == PMO)
    assert "Handover" in surat.subject
    assert surat.context["reference_id"] == proyek.id_project


async def test_handover_pmo_delivery_belum_terdaftar_di_portal_tetap_selesai(
    api, db_session, fake_drive
):
    """PMO/Delivery tidak wajib punya akun portal: folder tetap dibuat dan status tetap selesai."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    folder_id = resp.json()["data"]["final_deliverables_folder_id"]
    assert fake_drive.peran(folder_id, PMO) == "reader"
    assert (await muat(db_session, Project, id_project=proyek.id_project)).status == (
        "Handed Over"
    )


async def test_handover_penerima_tanpa_akun_diemail_langsung_dan_tercatat_di_audit(
    api, db_session, fake_drive, fake_gmail
):
    """#76: PMO/Delivery tanpa akun portal tidak lagi dilewati; mereka menerima email langsung."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    await fake_gmail.tunggu_percobaan(2)
    assert sorted(s.to for s in fake_gmail.terkirim) == [DELIVERY, PMO]
    for surat in fake_gmail.terkirim:
        assert "Handover" in surat.subject
        assert surat.context["reference_id"] == proyek.id_project
        assert surat.context["metadata"]["project_id"] == proyek.id_project
    # Tanpa akun = tanpa baris notifikasi (penerima notifikasi wajib user portal).
    assert await notifikasi(db_session, event_type="handover") == []
    [audit] = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "handover")))
        .scalars()
        .all()
    )
    assert audit.new_value["penerima_email_langsung"] == [PMO, DELIVERY]


async def test_handover_campuran_akun_dan_tanpa_akun(api, db_session, fake_drive, fake_gmail):
    """PMO punya akun (in-app + email biasa); Delivery tidak (email langsung, dicatat di audit)."""
    dunia = await siapkan_dunia(api, db_session)
    pmo = bangun_user(role="SA", email=PMO, name="PMO")
    await simpan(db_session, pmo)
    proyek = await _proyek_siap(db_session, dunia)
    fake_gmail.tahan_email()

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])
    fake_gmail.lepaskan_email()

    assert resp.status_code == 200, resp.text
    await fake_gmail.tunggu_percobaan(2)
    assert sorted(s.to for s in fake_gmail.terkirim) == [DELIVERY, PMO]
    assert {n.recipient_user_id for n in await notifikasi(db_session, event_type="handover")} == {
        pmo.id
    }
    [audit] = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "handover")))
        .scalars()
        .all()
    )
    assert audit.new_value["penerima_email_langsung"] == [DELIVERY]


async def test_handover_semua_penerima_terdaftar_tidak_mencatat_email_langsung(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    await _daftarkan_pmo_dan_delivery(db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    [audit] = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "handover")))
        .scalars()
        .all()
    )
    assert audit.new_value["penerima_email_langsung"] == []


async def test_handover_tanpa_gmail_penerima_tanpa_akun_tetap_selesai_dan_tercatat(
    api, db_session, fake_drive, fake_gmail
):
    fake_gmail.terkonfigurasi = False
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert fake_gmail.percobaan == []
    [audit] = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "handover")))
        .scalars()
        .all()
    )
    assert audit.new_value["penerima_email_langsung"] == [PMO, DELIVERY]


async def test_handover_kedua_kali_ditolak_karena_status_sudah_selesai(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)
    await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    ulang = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert ulang.status_code == 400
    assert "Won" in ulang.json()["message"]
    assert len(fake_drive.panggilan_operasi("provision_handover")) == 1


async def test_handover_hld_final_di_antara_beberapa_dokumen_hld_berhasil(
    api, db_session, fake_drive
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia, hld="Draft")
    await buat_dokumen(db_session, proyek, dunia, doc_type="HLD", status="Final")

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["new_status"] == "Handed Over"


# --------------------------------------------------------------------------- trigger: prasyarat


@pytest.mark.parametrize(
    ("ubah", "hld", "potongan"),
    [
        ({"status": "Submitted"}, "Final", "Won"),
        ({"status": "Lost"}, "Final", "Won"),
        ({}, None, "HLD"),
        ({}, "Draft", "HLD"),
        ({}, "Reviewed", "HLD"),
        ({"pmo_lead_email": None}, "Final", "PMO"),
        ({"delivery_lead_email": None}, "Final", "PMO"),
        ({"pmo_lead_email": "", "delivery_lead_email": ""}, "Final", "PMO"),
        ({"gdrive_folder_id": None}, "Final", "Google Drive"),
        ({"gdrive_solutions_folder_id": None}, "Final", "Solutions"),
    ],
)
async def test_handover_prasyarat_tidak_terpenuhi_400_tanpa_efek_samping(
    api, db_session, fake_drive, ubah, hld, potongan
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia, hld=hld, **ubah)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 400
    assert potongan in resp.json()["message"]
    await _tak_berubah(db_session, proyek, fake_drive)


async def test_handover_proyek_tidak_ada_404(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)

    resp = await _trigger(api, "PRJ-TIDAK-ADA", dunia.header["Lead_SA"])

    assert resp.status_code == 404
    assert fake_drive.panggilan == []


# --------------------------------------------------------------------------- trigger: akses


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin", "SA"])
async def test_handover_dapat_dipicu_lead_sa_admin_dan_sa_yang_ditugaskan(
    api, db_session, fake_drive, peran
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header[peran])

    assert resp.status_code == 200, resp.text
    assert (await muat(db_session, Project, id_project=proyek.id_project)).status == (
        "Handed Over"
    )


async def test_handover_ditolak_untuk_sales_dan_sa_tidak_ditugaskan(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)
    _, sa_lain = await user_baru(db_session, "SA")

    sales = await _trigger(api, proyek.id_project, dunia.header["Sales"])
    lain = await _trigger(api, proyek.id_project, sa_lain)
    anonim = await api.client.post(f"{API}/projects/{proyek.id_project}/handover")

    assert (sales.status_code, lain.status_code) == (403, 403)
    assert anonim.status_code in (401, 403)
    await _tak_berubah(db_session, proyek, fake_drive)


# --------------------------------------------------------------------------- trigger: Drive gagal


async def test_handover_drive_gagal_status_tetap_dan_sa_serta_lead_sa_diberitahu(
    api, db_session, fake_drive
):
    fake_drive.fail_always("provision_handover", pesan="kuota Drive habis")
    dunia = await siapkan_dunia(api, db_session)
    lead_lain = bangun_user(role="Lead_SA")
    await simpan(db_session, lead_lain)
    pmo, _ = await _daftarkan_pmo_dan_delivery(db_session)
    proyek = await _proyek_siap(db_session, dunia)

    resp = await _trigger(api, proyek.id_project, dunia.header["SA"])

    assert resp.status_code == 400
    assert "kuota Drive habis" in resp.json()["message"]
    # #76: tidak ada status "Handover Failed" yang disimpan; pesan menyatakan status tidak berubah.
    assert "Status proyek tidak berubah" in resp.json()["message"]
    assert "Handover Failed" not in resp.json()["message"]
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert baris.status == "Won"
    assert (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "handover"))
    ).scalars().all() == []
    notif = await notifikasi(db_session, event_type="status_change", reference_id=proyek.id_project)
    penerima = {n.recipient_user_id for n in notif}
    assert penerima == {dunia.user["SA"].id, dunia.user["Lead_SA"].id, lead_lain.id}
    for n in notif:
        assert n.notification_metadata["status"] == "Handover Failed"
        assert n.notification_metadata["error"] == "kuota Drive habis"
    # PMO/Delivery tidak menerima notifikasi handover karena handover tidak selesai.
    assert await notifikasi(db_session, event_type="handover") == []
    assert pmo.id not in penerima


async def test_handover_drive_gagal_tanpa_sa_ditugaskan_hanya_lead_sa_diberitahu(
    api, db_session, fake_drive
):
    fake_drive.fail_always("provision_handover")
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia, sa=False)

    resp = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert resp.status_code == 400
    notif = await notifikasi(db_session, event_type="status_change", reference_id=proyek.id_project)
    assert [n.recipient_user_id for n in notif] == [dunia.user["Lead_SA"].id]


async def test_handover_drive_pulih_setelah_gagal_sekali_dapat_dicoba_ulang(
    api, db_session, fake_drive
):
    fake_drive.fail_next("provision_handover")
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    gagal = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])
    berhasil = await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    assert (gagal.status_code, berhasil.status_code) == (400, 200)
    assert (await muat(db_session, Project, id_project=proyek.id_project)).status == (
        "Handed Over"
    )
    assert [p.berhasil for p in fake_drive.panggilan_operasi("provision_handover")] == [
        False,
        True,
    ]


async def test_dokumen_handover_tidak_berubah_oleh_handover(api, db_session, fake_drive):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await _proyek_siap(db_session, dunia)

    await _trigger(api, proyek.id_project, dunia.header["Lead_SA"])

    dokumen = (await db_session.execute(select(Document))).scalars().all()
    assert [(d.doc_type, d.status) for d in dokumen] == [("HLD", "Final")]
