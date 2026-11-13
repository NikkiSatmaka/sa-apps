"""
Integrasi SLA Flow 2 terhadap Postgres nyata dengan Drive palsu dan WAKTU TERKENDALI
(tiket B5 #58, spec #49): timer, reminder H+3, eskalasi H+5, auto-lock, auto-unlock saat DQ
diinput, folder belum ada, kegagalan Drive, dan endpoint `/sla/process` + `/sla-status`.

Waktu dikendalikan lewat `bekukan_waktu` (jam `sla_timer` digeser); tidak ada sleep nyata.
`process_sla_actions` dipanggil langsung (pola `test_fake_boundary_contoh.py`) karena membuka
sesinya sendiri; email dijadwalkan di background sehingga ditahan/dilepas lewat `fake_gmail`.
"""

from datetime import timedelta

import pytest

from app.services.notification_service import notification_service
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.support_assignment import (
    DQ_NUMBER,
    SLA_PROCESS,
    SLA_STATUS,
    T0,
    ambil_proyek,
    ambil_sla,
    bangun_dunia,
    bekukan_waktu,
    daftar_audit,
    daftar_notif,
    proyek_aktif_sla,
)


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    """Service yang membuka sesinya sendiri (cron SLA, notifikasi) memakai koneksi test."""
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


@pytest.fixture
def jam(monkeypatch):
    return bekukan_waktu(monkeypatch, T0)


async def _proses(db):
    """Commit state test lalu jalankan cron SLA (sesi sendiri), dan segarkan cache test."""
    await db.commit()
    stats = await sla_timer.process_sla_actions()
    return stats


# ----------------------------------------------------------------------------- start & hijau


async def test_timer_dimulai_hijau_dan_tidak_ada_aksi_sebelum_h3(dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)

    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.current_status, sla.days_elapsed, sla.is_locked) == ("green", 0, False)
    assert sla.started_at == T0 and sla.stopped_at is None

    jam.ke(T0 + timedelta(days=2, hours=23))
    stats = await _proses(dunia.db)

    assert stats["total_checked"] == 1
    assert stats["reminders_sent"] == stats["escalations_sent"] == stats["locks_performed"] == 0
    assert stats["errors"] == []
    assert (await ambil_sla(dunia.db, proyek.id_project)).current_status == "green"
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_reminder") == []
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []


async def test_start_timer_idempoten_satu_tracker_dan_started_at_tetap(dunia, jam):
    proyek = await proyek_aktif_sla(dunia)

    ulang = await sla_timer.start_timer(proyek.id_project, T0 + timedelta(days=9), dunia.db)

    assert ulang.started_at == T0
    from sqlalchemy import func, select

    from app.models import SLATracking

    jumlah = await dunia.db.scalar(
        select(func.count())
        .select_from(SLATracking)
        .where(SLATracking.project_id == proyek.id_project)
    )
    assert jumlah == 1


# ----------------------------------------------------------------------------- reminder H+3


async def test_reminder_h3_ke_sales_sekali_saja_dan_status_kuning(dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)

    jam.ke(T0 + timedelta(days=3))
    stats = await _proses(dunia.db)

    assert stats["reminders_sent"] == 1 and stats["escalations_sent"] == 0
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.current_status, sla.days_elapsed, sla.is_locked) == ("yellow", 3, False)
    notif = await daftar_notif(dunia.db, proyek.id_project, "sla_reminder")
    assert [n.recipient_user_id for n in notif] == [dunia.sales.id]
    assert notif[0].notification_metadata["days_elapsed"] == 3
    assert "DQ Number" in notif[0].notification_metadata["message"]

    # H+4 masih kuning: tidak ada reminder kedua dan folder belum dikunci.
    jam.ke(T0 + timedelta(days=4, hours=23))
    stats = await _proses(dunia.db)
    assert stats["reminders_sent"] == 0 and stats["escalations_sent"] == 0
    assert len(await daftar_notif(dunia.db, proyek.id_project, "sla_reminder")) == 1
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []


async def test_reminder_memicu_email_ke_sales_lewat_gmail_palsu(dunia, jam, fake_drive, fake_gmail):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=3))
    fake_gmail.tahan_email()

    await _proses(dunia.db)
    fake_gmail.lepaskan_email()

    await fake_gmail.tunggu_percobaan(1)
    surat = fake_gmail.terkirim[0]
    assert surat.to == dunia.sales.email
    assert surat.context["event_type"] == "sla_reminder"
    assert surat.context["reference_id"] == proyek.id_project


# ----------------------------------------------------------------------------- eskalasi H+5 & lock


async def test_h5_eskalasi_ke_manager_dan_sales_serta_lock_solutions(dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    solutions = proyek.gdrive_solutions_folder_id
    assert fake_drive.peran(solutions, dunia.sales.email) == "reader"

    jam.ke(T0 + timedelta(days=5))
    stats = await _proses(dunia.db)

    assert (stats["escalations_sent"], stats["locks_performed"], stats["errors"]) == (1, 1, [])
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.current_status, sla.is_locked, sla.days_elapsed) == ("red", True, 5)
    assert sla.locked_at == T0 + timedelta(days=5)
    # Akses Sales pada Solutions (bukan folder master) benar-benar dicabut di Drive.
    assert fake_drive.peran(solutions, dunia.sales.email) is None
    panggilan = fake_drive.panggilan_operasi("lock_solutions_folder")
    assert len(panggilan) == 1
    assert panggilan[0].argumen == {
        "solutions_folder_id": solutions,
        "sales_email": dunia.sales.email,
    }
    # Eskalasi: setiap Lead_SA/Admin + satu pemberitahuan lock ke Sales.
    penerima = {
        n.recipient_user_id
        for n in await daftar_notif(dunia.db, proyek.id_project, "sla_escalation")
    }
    assert penerima == {dunia.lead.id, dunia.admin.id, dunia.sales.id}
    # Loncat langsung hijau→H+5: reminder H+3 tetap terkirim (belum pernah kuning).
    assert stats["reminders_sent"] == 1
    # Jejak audit lock tercatat.
    audit = await daftar_audit(dunia.db, proyek.id_project, "lock")
    assert len(audit) == 1 and audit[0].new_value["is_locked"] is True
    # Aksi otomatis: pelaku NULL (tidak ada user sistem; #77).
    assert audit[0].performed_by is None


async def test_audit_lock_tertulis_tanpa_user_sistem_dengan_pelaku_null(dunia, jam, fake_drive):
    """#77: tidak ada user sistem; audit aksi otomatis tertulis dengan `performed_by` NULL."""
    proyek = await proyek_aktif_sla(dunia, fake_drive)

    jam.ke(T0 + timedelta(days=5))
    stats = await _proses(dunia.db)

    assert (stats["locks_performed"], stats["errors"]) == (1, [])
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.is_locked, sla.current_status) == (True, "red")
    assert fake_drive.peran(proyek.gdrive_solutions_folder_id, dunia.sales.email) is None
    [audit] = await daftar_audit(dunia.db, proyek.id_project, "lock")
    assert audit.performed_by is None and audit.entity_type == "folder"


async def test_eskalasi_dan_lock_hanya_sekali_walau_diproses_berulang(dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=5))
    await _proses(dunia.db)

    jam.ke(T0 + timedelta(days=8))
    stats = await _proses(dunia.db)

    assert stats["escalations_sent"] == stats["locks_performed"] == stats["reminders_sent"] == 0
    assert len(fake_drive.panggilan_operasi("lock_solutions_folder")) == 1
    assert len(await daftar_notif(dunia.db, proyek.id_project, "sla_escalation")) == 3
    assert (await ambil_sla(dunia.db, proyek.id_project)).days_elapsed == 8


async def test_folder_solutions_belum_ada_lock_dilewati_graceful(dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia)  # tanpa provisioning → tidak ada folder Solutions
    assert proyek.gdrive_solutions_folder_id is None

    jam.ke(T0 + timedelta(days=5))
    stats = await _proses(dunia.db)

    assert stats["escalations_sent"] == 1 and stats["locks_performed"] == 0
    assert stats["errors"] == []
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.current_status, sla.is_locked, sla.locked_at) == ("red", False, None)
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []
    assert await daftar_audit(dunia.db, proyek.id_project, "lock") == []


async def test_lock_gagal_di_drive_tidak_mengunci_dan_dicoba_lagi_pada_siklus_berikutnya(
    dunia, jam, fake_drive
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    solutions = proyek.gdrive_solutions_folder_id
    fake_drive.fail_next("lock_solutions_folder")

    jam.ke(T0 + timedelta(days=5))
    stats = await _proses(dunia.db)

    assert stats["locks_performed"] == 0 and stats["errors"] == []
    assert (await ambil_sla(dunia.db, proyek.id_project)).is_locked is False
    assert fake_drive.peran(solutions, dunia.sales.email) == "reader"

    jam.ke(T0 + timedelta(days=5, hours=1))
    stats = await _proses(dunia.db)

    assert stats["locks_performed"] == 1
    assert (await ambil_sla(dunia.db, proyek.id_project)).is_locked is True
    assert fake_drive.peran(solutions, dunia.sales.email) is None


async def test_eskalasi_hanya_sekali_walau_lock_gagal_terus_dan_lock_tetap_dicoba_tiap_siklus(
    dunia, jam, fake_drive
):
    """#77: lock gagal tidak boleh membuat eskalasi dikirim ulang tiap siklus (3 siklus = 9 notif)."""
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    solutions = proyek.gdrive_solutions_folder_id
    fake_drive.fail_next("lock_solutions_folder", times=2)

    jam.ke(T0 + timedelta(days=5))
    pertama = await _proses(dunia.db)
    jam.ke(T0 + timedelta(days=5, hours=1))
    kedua = await _proses(dunia.db)
    jam.ke(T0 + timedelta(days=5, hours=2))
    ketiga = await _proses(dunia.db)

    assert [s["escalations_sent"] for s in (pertama, kedua, ketiga)] == [1, 0, 0]
    assert [s["locks_performed"] for s in (pertama, kedua, ketiga)] == [0, 0, 1]
    # Tiga penerima (Lead_SA, Admin, Sales) sekali saja, bukan sembilan.
    assert len(await daftar_notif(dunia.db, proyek.id_project, "sla_escalation")) == 3
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.escalated_at == T0 + timedelta(days=5)
    assert len(fake_drive.panggilan_operasi("lock_solutions_folder")) == 3
    assert sla.is_locked is True and fake_drive.peran(solutions, dunia.sales.email) is None
    assert len(await daftar_audit(dunia.db, proyek.id_project, "lock")) == 1


async def test_error_satu_proyek_tidak_menghentikan_proyek_lain(
    dunia, jam, fake_drive, monkeypatch
):
    p_rusak = await proyek_aktif_sla(dunia, fake_drive, project_name="Rusak")
    p_sehat = await proyek_aktif_sla(dunia, fake_drive, project_name="Sehat")
    asli = notification_service.dispatch_email_for_user

    async def _dispatch(event_type, penerima, reference_id=None, metadata=None):
        if reference_id == p_rusak.id_project:
            raise RuntimeError("dispatch rusak")
        await asli(event_type, penerima, reference_id, metadata)

    monkeypatch.setattr(notification_service, "dispatch_email_for_user", _dispatch)
    jam.ke(T0 + timedelta(days=3))

    stats = await _proses(dunia.db)

    assert stats["total_checked"] == 2 and stats["reminders_sent"] == 1
    assert len(stats["errors"]) == 1 and p_rusak.id_project in stats["errors"][0]
    assert len(await daftar_notif(dunia.db, p_sehat.id_project, "sla_reminder")) == 1


# ----------------------------------------------------------------------------- stop & unlock (DQ)


async def test_dq_diinput_sebelum_lock_menghentikan_timer_dan_tidak_ada_aksi_lanjutan(
    dunia, jam, fake_drive, api
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=2))

    resp = await api.client.patch(
        DQ_NUMBER.format(proyek.id_project), json={"dq_number": "DQ-001"}, headers=dunia.h["sales"]
    )

    assert resp.status_code == 200, resp.text
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.stopped_at == T0 + timedelta(days=2) and sla.is_locked is False
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Ready"
    jam.ke(T0 + timedelta(days=9))
    stats = await _proses(dunia.db)
    assert stats["total_checked"] == 0
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []
    assert fake_drive.panggilan_operasi("unlock_solutions_folder") == []


async def test_dq_diinput_setelah_lock_membuka_kembali_solutions_untuk_sales(
    dunia, jam, fake_drive, api
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    solutions = proyek.gdrive_solutions_folder_id
    jam.ke(T0 + timedelta(days=6))
    await _proses(dunia.db)
    assert fake_drive.peran(solutions, dunia.sales.email) is None

    jam.ke(T0 + timedelta(days=7))
    resp = await api.client.patch(
        DQ_NUMBER.format(proyek.id_project), json={"dq_number": "DQ-002"}, headers=dunia.h["sales"]
    )

    assert resp.status_code == 200, resp.text
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.is_locked, sla.stopped_at, sla.unlocked_at) == (
        False,
        T0 + timedelta(days=7),
        T0 + timedelta(days=7),
    )
    assert fake_drive.peran(solutions, dunia.sales.email) == "reader"
    audit = await daftar_audit(dunia.db, proyek.id_project, "unlock")
    assert len(audit) == 1
    assert audit[0].new_value["delay_days"] == 6 and audit[0].old_value["is_locked"] is True
    assert audit[0].performed_by is None


async def test_unlock_gagal_di_drive_timer_berhenti_tapi_folder_tetap_terkunci(
    dunia, jam, fake_drive
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=6))
    await _proses(dunia.db)
    fake_drive.fail_next("unlock_solutions_folder")

    sla = await sla_timer.stop_timer(proyek.id_project, dunia.db)

    assert sla.stopped_at is not None
    assert sla.is_locked is True and sla.unlocked_at is None
    assert await daftar_audit(dunia.db, proyek.id_project, "unlock") == []


async def test_unlock_yang_gagal_saat_stop_timer_dicoba_ulang_oleh_cron(dunia, jam, fake_drive):
    """#77: timer berhenti tetapi folder masih terkunci -> siklus cron berikutnya membukanya."""
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    solutions = proyek.gdrive_solutions_folder_id
    jam.ke(T0 + timedelta(days=6))
    await _proses(dunia.db)
    fake_drive.fail_next("unlock_solutions_folder")
    await sla_timer.stop_timer(proyek.id_project, dunia.db)
    assert (await ambil_sla(dunia.db, proyek.id_project)).is_locked is True

    jam.ke(T0 + timedelta(days=6, hours=1))
    stats = await _proses(dunia.db)

    assert stats["unlocks_retried"] == 1 and stats["errors"] == []
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert (sla.is_locked, sla.unlocked_at) == (False, T0 + timedelta(days=6, hours=1))
    assert fake_drive.peran(solutions, dunia.sales.email) == "reader"
    [audit] = await daftar_audit(dunia.db, proyek.id_project, "unlock")
    assert audit.performed_by is None and audit.new_value["is_locked"] is False

    jam.ke(T0 + timedelta(days=6, hours=2))
    stats = await _proses(dunia.db)
    assert stats["unlocks_retried"] == 0
    assert len(fake_drive.panggilan_operasi("unlock_solutions_folder")) == 2


async def test_unlock_yang_terus_gagal_dicoba_tiap_siklus_tanpa_error_dan_tanpa_audit_ganda(
    dunia, jam, fake_drive
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=6))
    await _proses(dunia.db)
    fake_drive.fail_next("unlock_solutions_folder", times=3)
    await sla_timer.stop_timer(proyek.id_project, dunia.db)

    for jam_ke in (1, 2):
        jam.ke(T0 + timedelta(days=6, hours=jam_ke))
        stats = await _proses(dunia.db)
        assert stats["unlocks_retried"] == 0 and stats["errors"] == []
    assert (await ambil_sla(dunia.db, proyek.id_project)).is_locked is True
    assert await daftar_audit(dunia.db, proyek.id_project, "unlock") == []

    jam.ke(T0 + timedelta(days=6, hours=3))
    stats = await _proses(dunia.db)
    assert stats["unlocks_retried"] == 1
    assert len(await daftar_audit(dunia.db, proyek.id_project, "unlock")) == 1


async def test_stop_timer_idempoten_dan_tanpa_tracker_mengembalikan_none(dunia, jam):
    proyek = await proyek_aktif_sla(dunia)
    jam.ke(T0 + timedelta(days=1))
    pertama = await sla_timer.stop_timer(proyek.id_project, dunia.db)
    jam.ke(T0 + timedelta(days=4))

    kedua = await sla_timer.stop_timer(proyek.id_project, dunia.db)

    assert kedua.stopped_at == pertama.stopped_at == T0 + timedelta(days=1)
    assert await sla_timer.stop_timer("PRJ-TIDAK-ADA", dunia.db) is None


async def test_unlock_dilewati_bila_folder_solutions_tidak_ada_atau_sales_hilang(
    dunia, jam, fake_drive
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=5))
    await _proses(dunia.db)
    sla = await ambil_sla(dunia.db, proyek.id_project)
    proyek = await ambil_proyek(dunia.db, proyek.id_project)

    proyek.gdrive_solutions_folder_id = None
    await dunia.db.commit()
    assert await sla_timer._unlock_solutions_with_retry(proyek.id_project, sla, dunia.db) is False
    assert await sla_timer._unlock_solutions_with_retry("PRJ-TIDAK-ADA", sla, dunia.db) is False
    assert fake_drive.panggilan_operasi("unlock_solutions_folder") == []


# ----------------------------------------------------------------------------- endpoint


async def test_sla_status_endpoint_hijau_kuning_merah_dan_berhenti(dunia, jam, fake_drive, api):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    url = SLA_STATUS.format(proyek.id_project)

    async def _baca():
        resp = await api.client.get(url, headers=dunia.h["sa"])
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    assert (await _baca())["status"] == "green"
    jam.ke(T0 + timedelta(days=4))
    data = await _baca()
    assert (data["status"], data["days_elapsed"], data["is_active"]) == ("yellow", 4, True)
    assert (await ambil_sla(dunia.db, proyek.id_project)).current_status == "yellow"
    jam.ke(T0 + timedelta(days=5))
    assert (await _baca())["status"] == "red"

    await sla_timer.stop_timer(proyek.id_project, dunia.db)
    jam.ke(T0 + timedelta(days=30))
    data = await _baca()
    assert data["is_active"] is False and data["days_elapsed"] == 5
    assert data["stopped_at"] is not None


async def test_sla_status_404_tanpa_tracker_dan_401_tanpa_login(dunia, api):
    proyek = await dunia.buat_proyek()

    sebelum_assign = await api.client.get(
        SLA_STATUS.format(proyek.id_project), headers=dunia.h["lead"]
    )
    tanpa_login = await api.client.get(SLA_STATUS.format(proyek.id_project))

    assert sebelum_assign.status_code == 404
    assert tanpa_login.status_code in (401, 403)


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_endpoint_sla_process_untuk_lead_dan_admin(dunia, jam, fake_drive, api, peran):
    await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=3))
    await dunia.db.commit()

    resp = await api.client.post(SLA_PROCESS, headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["total_checked"], data["reminders_sent"]) == (1, 1)
    assert "1 reminder" in resp.json()["message"]
    # Catatan harness: cron membuka sesi sendiri pada koneksi yang sama dengan sesi request
    # (belum ditutup), jadi efek DB-nya tidak bisa dibaca di sini; efek DB cron sudah dicakup
    # test `process_sla_actions` langsung di atas. Yang ditegaskan: respons dan hak akses.


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_endpoint_sla_process_ditolak_untuk_sa_dan_sales(dunia, jam, fake_drive, api, peran):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=3))
    await dunia.db.commit()

    resp = await api.client.post(SLA_PROCESS, headers=dunia.h[peran])

    assert resp.status_code == 403
    assert (await ambil_sla(dunia.db, proyek.id_project)).current_status == "green"
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_reminder") == []


async def test_sla_process_tanpa_login_ditolak(api):
    resp = await api.client.post(SLA_PROCESS)

    assert resp.status_code in (401, 403)


# ------------------------------------------------------------------ proyek dihapus (ADR 0009)


async def test_hapus_proyek_menghentikan_timer_sehingga_cron_tidak_memprosesnya(
    dunia, jam, fake_drive, api
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)

    resp = await api.client.delete(f"/api/v1/projects/{proyek.id_project}", headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    assert (await ambil_sla(dunia.db, proyek.id_project)).stopped_at is not None
    jam.ke(T0 + timedelta(days=6))
    stats = await _proses(dunia.db)
    assert stats["total_checked"] == 0
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_reminder") == []


async def test_tracker_aktif_milik_proyek_terhapus_dilewati_tanpa_error_dan_tanpa_aksi(
    dunia, jam, fake_drive
):
    """Pengaman: bila tracker lupa dihentikan, proyek terhapus tidak memicu reminder/lock."""
    from sqlalchemy import update

    from app.models import Project

    proyek = await proyek_aktif_sla(dunia, fake_drive)
    await dunia.db.execute(
        update(Project).where(Project.id_project == proyek.id_project).values(deleted_at=T0),
        execution_options={"include_deleted": True},
    )
    jam.ke(T0 + timedelta(days=6))

    stats = await _proses(dunia.db)

    assert stats["total_checked"] == 1 and stats["errors"] == []
    assert stats["reminders_sent"] == stats["escalations_sent"] == stats["locks_performed"] == 0
    assert fake_drive.panggilan_operasi("lock_solutions_folder") == []
    assert await daftar_notif(dunia.db, proyek.id_project) == []
