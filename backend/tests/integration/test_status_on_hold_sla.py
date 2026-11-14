"""
Timer SLA DQ berhenti selama `On Hold` dan lanjut sesudahnya (issue #122, spec §2.0 dan Flow 2).

Waktu dikendalikan lewat `bekukan_waktu` (jam `sla_timer`). Jeda/lanjut lewat
`PATCH /projects/{id}/status` agar jalur produksi yang diuji; cron SLA dipanggil langsung.
"""

from datetime import timedelta

import pytest

from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.support_assignment import (
    SLA_PROCESS,
    SLA_STATUS,
    T0,
    ambil_sla,
    bangun_dunia,
    bekukan_waktu,
    daftar_notif,
    proyek_aktif_sla,
)

STATUS = "/api/v1/projects/{}/status"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


@pytest.fixture
def jam(monkeypatch):
    return bekukan_waktu(monkeypatch, T0)


async def _ubah(api, dunia, id_project, tujuan, peran="lead", **extra):
    return await api.client.patch(
        STATUS.format(id_project),
        json={"new_status": tujuan, **extra},
        headers=dunia.h[peran],
    )


async def _proses(db):
    await db.commit()
    return await sla_timer.process_sla_actions()


async def test_sla_tidak_menembak_reminder_atau_eskalasi_selama_on_hold(
    api, dunia, jam, fake_drive
):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=1))
    assert (await _ubah(api, dunia, proyek.id_project, "On Hold")).status_code == 200

    jam.ke(T0 + timedelta(days=30))
    stats = await _proses(dunia.db)

    assert stats["total_checked"] == 0
    assert stats["reminders_sent"] == stats["escalations_sent"] == stats["locks_performed"] == 0
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_reminder") == []
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_escalation") == []
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.paused_at == T0 + timedelta(days=1)
    assert sla.is_locked is False


async def test_lanjut_menghitung_ulang_batas_waktu_dengan_durasi_jeda(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=2))  # sudah berjalan 2 hari
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    jam.ke(T0 + timedelta(days=12))  # jeda 10 hari
    assert (await _ubah(api, dunia, proyek.id_project, "Assigned")).status_code == 200

    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.paused_at is None
    assert sla.paused_total_seconds == int(timedelta(days=10).total_seconds())

    # 2 hari 23 jam berjalan efektif: belum H+3.
    jam.ke(T0 + timedelta(days=12, hours=23))
    stats = await _proses(dunia.db)
    assert stats["total_checked"] == 1 and stats["reminders_sent"] == 0

    # Tepat 3 hari efektif: reminder H+3 menembak.
    jam.ke(T0 + timedelta(days=13))
    stats = await _proses(dunia.db)
    assert stats["reminders_sent"] == 1 and stats["escalations_sent"] == 0

    # 5 hari efektif = T0 + 15 hari: eskalasi dan lock.
    jam.ke(T0 + timedelta(days=15))
    stats = await _proses(dunia.db)
    assert stats["escalations_sent"] == 1


async def test_dua_jeda_berurutan_mengakumulasi(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    id_project = proyek.id_project
    jam.ke(T0 + timedelta(days=1))
    await _ubah(api, dunia, id_project, "On Hold")
    jam.ke(T0 + timedelta(days=3))  # jeda pertama 2 hari
    await _ubah(api, dunia, id_project, "Assigned")
    jam.ke(T0 + timedelta(days=4))
    await _ubah(api, dunia, id_project, "On Hold")
    jam.ke(T0 + timedelta(days=7))  # jeda kedua 3 hari
    await _ubah(api, dunia, id_project, "Assigned")

    sla = await ambil_sla(dunia.db, id_project)
    assert sla.paused_total_seconds == int(timedelta(days=5).total_seconds())


async def test_sla_status_menunjukkan_jeda_dan_hari_membeku(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=2))
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    jam.ke(T0 + timedelta(days=20))

    resp = await api.client.get(SLA_STATUS.format(proyek.id_project), headers=dunia.h["lead"])

    data = resp.json()["data"]
    assert resp.status_code == 200, resp.text
    assert (data["days_elapsed"], data["status"], data["is_paused"]) == (2, "green", True)
    assert data["is_active"] is True


async def test_sla_status_setelah_lanjut_tidak_lagi_dijeda(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=2))
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    jam.ke(T0 + timedelta(days=20))
    await _ubah(api, dunia, proyek.id_project, "Assigned")

    resp = await api.client.get(SLA_STATUS.format(proyek.id_project), headers=dunia.h["lead"])

    data = resp.json()["data"]
    assert (data["days_elapsed"], data["is_paused"]) == (2, False)


async def test_endpoint_sla_process_juga_melewati_proyek_on_hold(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    jam.ke(T0 + timedelta(days=30))
    await dunia.db.commit()

    resp = await api.client.post(SLA_PROCESS, headers=dunia.h["admin"])

    data = resp.json()["data"]
    assert (data["total_checked"], data["reminders_sent"], data["escalations_sent"]) == (0, 0, 0)


async def test_jeda_tanpa_tracker_sla_tetap_berhasil(api, dunia):
    proyek = await dunia.buat_proyek(status="Awaiting Assignment")

    resp = await _ubah(api, dunia, proyek.id_project, "On Hold")

    assert resp.status_code == 200, resp.text
    assert await ambil_sla(dunia.db, proyek.id_project) is None


async def test_lost_dari_on_hold_menjaga_timer_tetap_berhenti(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    await _ubah(api, dunia, proyek.id_project, "Lost", reason="Batal")
    jam.ke(T0 + timedelta(days=30))

    stats = await _proses(dunia.db)

    assert stats["total_checked"] == 0
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.paused_at is not None


async def test_buka_kembali_dari_lost_menjalankan_timer_lagi(api, dunia, jam, fake_drive):
    proyek = await proyek_aktif_sla(dunia, fake_drive)
    jam.ke(T0 + timedelta(days=1))
    await _ubah(api, dunia, proyek.id_project, "On Hold")
    await _ubah(api, dunia, proyek.id_project, "Lost", reason="Batal")
    jam.ke(T0 + timedelta(days=11))

    resp = await _ubah(api, dunia, proyek.id_project, "Assigned", "admin", reason="Customer kembali")

    assert resp.status_code == 200, resp.text
    sla = await ambil_sla(dunia.db, proyek.id_project)
    assert sla.paused_at is None
    assert sla.paused_total_seconds == int(timedelta(days=10).total_seconds())
