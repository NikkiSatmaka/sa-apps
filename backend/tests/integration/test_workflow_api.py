"""
Integrasi `api/workflow` terhadap Postgres nyata (tiket B6, #59, spec #49): transisi status proyek
(rangkaian, Lost, terminal, audit; matriks transisi x peran ada di
`test_workflow_transisi.py`) dan notifikasi wajib HLD saat Won.
Pasangan unit: `tests/test_dokumen_workflow_handover_unit.py`.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, ProjectAssignment
from app.services.notification_service import notification_service
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

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

# `Handed Over` TIDAK dapat dicapai lewat endpoint ini (issue #76): hanya `POST /handover`
# yang memeriksa prasyarat (HLD Final, email PMO/Delivery, folder Drive). Lihat test khusus di bawah.
# `Assigned` hanya lewat penugasan SA; `Submitted` butuh PropTek/BOQ/Mandays minimal Reviewed.
FORWARD = [
    ("Assigned", "Submitted"),
    ("Submitted", "Won"),
]
SEMUA_STATUS = [
    "Intake",
    "Awaiting Assignment",
    "Assigned",
    "In Progress",
    "Submitted",
    "Won",
    "Handed Over",
    "Closed",
    "Lost",
    "On Hold",
]
BISA_LOST = [
    "Intake",
    "Awaiting Assignment",
    "Assigned",
    "In Progress",
    "Submitted",
    "Won",
]


async def _ubah(api, id_project, status_baru, header, **extra):
    return await api.client.patch(
        f"{API}/projects/{id_project}/status",
        json={"new_status": status_baru, **extra},
        headers=header,
    )


async def _status(db, id_project) -> str:
    return (await muat(db, Project, id_project=id_project)).status


async def _audit(db, id_project) -> list[AuditLog]:
    return list(
        (await db.execute(select(AuditLog).where(AuditLog.entity_id == id_project))).scalars().all()
    )


# --------------------------------------------------------------------------- forward per peran


@pytest.mark.parametrize("peran", ["Sales", "SA", "Lead_SA", "Admin"])
async def test_patch_ke_handover_complete_ditolak_dan_diarahkan_ke_endpoint_handover(
    api, db_session, fake_drive, fake_gmail, peran
):
    """#76: PATCH status tidak boleh melewati prasyarat handover. Status tetap, tanpa efek samping."""
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Won")

    resp = await _ubah(api, proyek.id_project, "Handed Over", dunia.header[peran])

    assert resp.status_code == 400, resp.text
    pesan = resp.json()["message"]
    assert "Handed Over" in pesan and "/handover" in pesan
    assert await _status(db_session, proyek.id_project) == "Won"
    assert await _audit(db_session, proyek.id_project) == []
    assert fake_drive.panggilan == [] and fake_gmail.percobaan == []


async def test_transisi_mencatat_audit_log_dengan_nilai_lama_dan_baru(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")
    for tipe in ("PropTek", "BOQ", "Mandays"):
        await buat_dokumen(db_session, proyek, dunia, doc_type=tipe, status="Reviewed")

    resp = await _ubah(api, proyek.id_project, "Submitted", dunia.header["Lead_SA"])

    [audit] = await _audit(db_session, proyek.id_project)
    assert audit.action == "status_change"
    assert audit.entity_type == "project"
    assert audit.performed_by == dunia.user["Lead_SA"].id
    assert audit.old_value == {"status": "Assigned"}
    assert audit.new_value == {"status": "Submitted"}
    respons_audit = resp.json()["data"]["audit_log"]
    assert respons_audit["id"] == audit.id
    assert respons_audit["performed_by"] == str(dunia.user["Lead_SA"].id)
    assert respons_audit["old_value"] == {"status": "Assigned"}
    assert audit.id.startswith("AUDIT-")


async def test_rangkaian_forward_penuh_sampai_won_dengan_satu_audit_per_langkah(
    api, db_session
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")
    for tipe in ("PropTek", "BOQ", "Mandays"):
        await buat_dokumen(db_session, proyek, dunia, doc_type=tipe, status="Reviewed")

    for _, tujuan in FORWARD:
        resp = await _ubah(api, proyek.id_project, tujuan, dunia.header["Lead_SA"])
        assert resp.status_code == 200, (tujuan, resp.text)

    assert await _status(db_session, proyek.id_project) == "Won"
    jejak = sorted(
        (a.old_value["status"], a.new_value["status"])
        for a in await _audit(db_session, proyek.id_project)
    )
    assert jejak == sorted(FORWARD)


# --------------------------------------------------------------------------- transisi tidak valid


@pytest.mark.parametrize(
    ("awal", "tujuan"),
    [
        ("Intake", "Assigned"),  # loncat
        ("Awaiting Assignment", "Won"),  # loncat jauh
        ("Awaiting Assignment", "Submitted"),  # loncat
        ("Assigned", "Awaiting Assignment"),  # mundur
        ("Submitted", "Assigned"),  # mundur
        ("Won", "Submitted"),  # mundur
        ("Assigned", "Assigned"),  # sama
        ("Assigned", "Status-Ngawur"),  # tidak dikenal
        ("Assigned", "Pending DQ"),  # bukan status proyek (ADR 0001, 2026-11-10)
        ("Intake", "Awaiting Assignment"),  # keluar dari Intake hanya oleh sistem (gate BANT)
    ],
)
async def test_transisi_tidak_valid_400_status_tetap_dan_tanpa_audit(api, db_session, awal, tujuan):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=awal)

    resp = await _ubah(api, proyek.id_project, tujuan, dunia.header["Lead_SA"])

    assert resp.status_code == 400
    assert "Transisi status tidak valid" in resp.json()["message"]
    assert await _status(db_session, proyek.id_project) == awal
    assert await _audit(db_session, proyek.id_project) == []


@pytest.mark.parametrize("peran", ["Sales", "SA", "Lead_SA", "Admin"])
@pytest.mark.parametrize("terminal", ["Lost", "Closed"])
async def test_status_terminal_tidak_bisa_diubah_siapa_pun(api, db_session, peran, terminal):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=terminal)

    for tujuan in SEMUA_STATUS:
        resp = await _ubah(api, proyek.id_project, tujuan, dunia.header[peran])
        assert resp.status_code in (400, 403), (peran, terminal, tujuan, resp.text)

    assert await _status(db_session, proyek.id_project) == terminal
    assert await _audit(db_session, proyek.id_project) == []


async def test_pesan_transisi_tidak_valid_menyebut_status_terminal(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Closed")

    resp = await _ubah(api, proyek.id_project, "Submitted", dunia.header["Lead_SA"])

    assert resp.status_code == 400
    assert "status terminal" in resp.json()["message"]


# --------------------------------------------------------------------------- Lost


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
@pytest.mark.parametrize("awal", BISA_LOST)
async def test_lost_oleh_lead_sa_dan_admin_dari_status_non_terminal(api, db_session, peran, awal):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=awal)

    resp = await _ubah(api, proyek.id_project, "Lost", dunia.header[peran], reason="Kalah tender")

    assert resp.status_code == 200, resp.text
    assert await _status(db_session, proyek.id_project) == "Lost"
    [audit] = await _audit(db_session, proyek.id_project)
    assert audit.old_value == {"status": awal}
    assert audit.new_value == {"status": "Lost", "lost_reason": "Kalah tender"}
    baris = await muat(db_session, Project, id_project=proyek.id_project)
    assert (baris.lost_reason, baris.previous_status) == ("Kalah tender", awal)


@pytest.mark.parametrize("peran", ["Sales", "SA"])
@pytest.mark.parametrize("awal", ["Assigned", "Submitted", "Won"])
async def test_lost_oleh_sales_atau_sa_ditolak_403_meski_pemilik_proyek(
    api, db_session, peran, awal
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=awal)

    resp = await _ubah(api, proyek.id_project, "Lost", dunia.header[peran])

    assert resp.status_code == 403
    assert "Lost" in resp.json()["message"]
    assert await _status(db_session, proyek.id_project) == awal
    assert await _audit(db_session, proyek.id_project) == []


async def test_lost_dari_handover_complete_dan_lost_ke_lost_ditolak(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    selesai = await buat_proyek(db_session, dunia, status="Handed Over")
    kalah = await buat_proyek(db_session, dunia, status="Lost")

    r1 = await _ubah(api, selesai.id_project, "Lost", dunia.header["Admin"])
    r2 = await _ubah(api, kalah.id_project, "Lost", dunia.header["Admin"])

    assert (r1.status_code, r2.status_code) == (400, 400)
    assert await _status(db_session, selesai.id_project) == "Handed Over"
    assert await _status(db_session, kalah.id_project) == "Lost"


# --------------------------------------------------------------------------- akses per peran


async def test_sales_dan_sa_bukan_pemilik_proyek_ditolak_403(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")
    _, sales_lain = await user_baru(db_session, "Sales")
    _, sa_lain = await user_baru(db_session, "SA")

    r_sales = await _ubah(api, proyek.id_project, "Submitted", sales_lain)
    r_sa = await _ubah(api, proyek.id_project, "Submitted", sa_lain)

    assert (r_sales.status_code, r_sa.status_code) == (403, 403)
    assert "milik Anda" in r_sales.json()["message"]
    assert "ditugaskan kepada Anda" in r_sa.json()["message"]
    assert await _status(db_session, proyek.id_project) == "Assigned"
    assert await _audit(db_session, proyek.id_project) == []


async def test_sa_tidak_ditugaskan_pada_proyek_tanpa_sa_ditolak(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Awaiting Assignment", sa=False)

    resp = await _ubah(api, proyek.id_project, "Assigned", dunia.header["SA"])

    assert resp.status_code == 403
    assert await _status(db_session, proyek.id_project) == "Awaiting Assignment"


async def test_proyek_tidak_ada_404_tanpa_login_ditolak_dan_body_tidak_valid_422(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Assigned")

    tak_ada = await _ubah(api, "PRJ-TIDAK-ADA", "Submitted", dunia.header["Lead_SA"])
    anonim = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/status", json={"new_status": "Submitted"}
    )
    tanpa_status = await api.client.patch(
        f"{API}/projects/{proyek.id_project}/status", json={}, headers=dunia.header["Lead_SA"]
    )
    alasan_panjang = await _ubah(
        api, proyek.id_project, "Submitted", dunia.header["Lead_SA"], reason="x" * 501
    )

    assert tak_ada.status_code == 404
    assert anonim.status_code in (401, 403)
    assert tanpa_status.status_code == 422
    assert alasan_panjang.status_code == 422
    assert await _status(db_session, proyek.id_project) == "Assigned"


# --------------------------------------------------------------------------- notifikasi wajib HLD


async def test_won_mengirim_satu_notifikasi_wajib_hld_ke_sa(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted")

    resp = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    notif = await notifikasi(db_session, reference_id=proyek.id_project)
    assert len(notif) == 1
    assert notif[0].event_type == "status_change"
    assert notif[0].recipient_user_id == dunia.user["SA"].id
    meta = notif[0].notification_metadata
    assert meta["mandatory_hld"] is True
    assert meta["new_status"] == "Won"
    assert "HLD" in meta["message"]
    assert meta["project_name"] == proyek.project_name


async def test_won_mengirim_notifikasi_hld_ke_sa_utama_dan_semua_sa_tambahan(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted")
    tambahan_1, _ = await user_baru(db_session, "SA")
    tambahan_2, _ = await user_baru(db_session, "Lead_SA")
    for orang in (tambahan_1, tambahan_2):
        db_session.add(
            ProjectAssignment(
                id_project=proyek.id_project,
                user_id=orang.id,
                added_by=dunia.user["Lead_SA"].id,
            )
        )
    await db_session.commit()

    resp = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    notif = await notifikasi(db_session, reference_id=proyek.id_project)
    assert {n.recipient_user_id for n in notif} == {
        dunia.user["SA"].id,
        tambahan_1.id,
        tambahan_2.id,
    }
    assert len(notif) == 3
    assert all(n.notification_metadata["mandatory_hld"] is True for n in notif)
    assert all(n.notification_metadata["new_status"] == "Won" for n in notif)


async def test_won_tidak_mengirim_notifikasi_hld_ke_sales_product_atau_lead_sa_lain(
    api, db_session
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted")

    await _ubah(api, proyek.id_project, "Won", dunia.header["Sales"])

    notif = await notifikasi(db_session, reference_id=proyek.id_project)
    assert [n.recipient_user_id for n in notif] == [dunia.user["SA"].id]


async def test_won_hanya_sa_tambahan_tanpa_sa_utama_tetap_mendapat_notifikasi(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted", sa=False)
    tambahan, _ = await user_baru(db_session, "SA")
    db_session.add(
        ProjectAssignment(
            id_project=proyek.id_project, user_id=tambahan.id, added_by=dunia.user["Lead_SA"].id
        )
    )
    await db_session.commit()

    resp = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    notif = await notifikasi(db_session, reference_id=proyek.id_project)
    assert [n.recipient_user_id for n in notif] == [tambahan.id]


async def test_notifikasi_hld_tidak_terkirim_lagi_pada_transisi_berikutnya_yang_ditolak(
    api, db_session
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted")
    await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    ulang = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert ulang.status_code == 400
    assert len(await notifikasi(db_session, reference_id=proyek.id_project)) == 1


@pytest.mark.parametrize(
    ("awal", "akhir"), [("Submitted", "In Progress"), ("Handed Over", "Closed")]
)
async def test_transisi_selain_won_tidak_mengirim_notifikasi_hld(
    api, db_session, awal, akhir
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status=awal)

    await _ubah(api, proyek.id_project, akhir, dunia.header["Lead_SA"])

    assert await notifikasi(db_session, reference_id=proyek.id_project) == []


async def test_won_tanpa_sa_ditugaskan_melewati_notifikasi_transisi_tetap_berhasil(
    api, db_session
):
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted", sa=False)

    resp = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert await _status(db_session, proyek.id_project) == "Won"
    assert await notifikasi(db_session, reference_id=proyek.id_project) == []


async def test_kegagalan_notifikasi_hld_tidak_menggagalkan_transisi(api, db_session, monkeypatch):
    monkeypatch.setattr(
        notification_service, "send_notification", AsyncMock(side_effect=RuntimeError("boom"))
    )
    dunia = await siapkan_dunia(api, db_session)
    proyek = await buat_proyek(db_session, dunia, status="Submitted")

    resp = await _ubah(api, proyek.id_project, "Won", dunia.header["Lead_SA"])

    assert resp.status_code == 200, resp.text
    assert await _status(db_session, proyek.id_project) == "Won"
    assert len(await _audit(db_session, proyek.id_project)) == 1
