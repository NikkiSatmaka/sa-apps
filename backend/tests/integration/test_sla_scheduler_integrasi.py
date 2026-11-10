"""
Integrasi SLA scheduler (ADR 0003) terhadap Postgres nyata dengan waktu terkendali
(tiket B5 #58, spec #49): scheduler benar-benar memproses tracker di database tiap siklus,
tahan error, dan berhenti rapi. `asyncio.sleep` scheduler diganti gerbang berbasis Event;
tidak ada interval nyata yang ditunggu.
"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.services import sla_scheduler as modul_scheduler
from app.services.sla_scheduler import SLAScheduler
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.support_assignment import (
    T0,
    ambil_sla,
    bangun_dunia,
    bekukan_waktu,
    daftar_notif,
    proyek_aktif_sla,
)


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


class GerbangTidur:
    """Pengganti `asyncio.sleep` scheduler: catat interval dan beri sinyal tiap siklus selesai."""

    def __init__(self, monkeypatch):
        self.interval: list[float] = []
        self.siklus_selesai = asyncio.Event()
        gerbang = self

        async def _tidur(detik):
            gerbang.interval.append(detik)
            gerbang.siklus_selesai.set()
            await asyncio.Event().wait()  # menggantung sampai scheduler dihentikan test

        # Proxy khusus modul scheduler agar `asyncio.sleep` global tidak ikut berubah.
        proxy = SimpleNamespace(
            sleep=_tidur,
            create_task=asyncio.create_task,
            CancelledError=asyncio.CancelledError,
            Task=asyncio.Task,
        )
        monkeypatch.setattr(modul_scheduler, "asyncio", proxy)

    async def tunggu_siklus(self):
        await asyncio.wait_for(self.siklus_selesai.wait(), timeout=5)
        self.siklus_selesai.clear()


async def test_scheduler_memproses_tracker_di_database_lalu_berhenti_rapi(dunia, monkeypatch):
    proyek = await proyek_aktif_sla(dunia)
    jam = bekukan_waktu(monkeypatch, T0 + timedelta(days=3))
    await dunia.db.commit()
    gerbang = GerbangTidur(monkeypatch)
    scheduler = SLAScheduler(interval_seconds=3600)

    scheduler.start()
    await gerbang.tunggu_siklus()

    assert scheduler.is_running
    assert gerbang.interval == [3600]
    notif = await daftar_notif(dunia.db, proyek.id_project, "sla_reminder")
    assert [n.recipient_user_id for n in notif] == [dunia.sales.id]
    assert (await ambil_sla(dunia.db, proyek.id_project)).current_status == "yellow"
    await scheduler.stop()
    assert not scheduler.is_running
    assert jam.sekarang == T0 + timedelta(days=3)


async def test_scheduler_tahan_error_database_dan_lanjut_siklus_berikutnya(dunia, monkeypatch):
    proyek = await proyek_aktif_sla(dunia)
    bekukan_waktu(monkeypatch, T0 + timedelta(days=3))
    await dunia.db.commit()
    asli = sla_timer.process_sla_actions
    percobaan = []

    async def _kadang_gagal():
        percobaan.append(1)
        if len(percobaan) == 1:
            raise ConnectionError("database sedang tidak tersedia")
        return await asli()

    monkeypatch.setattr(sla_timer, "process_sla_actions", _kadang_gagal)
    gerbang = GerbangTidur(monkeypatch)
    scheduler = SLAScheduler(interval_seconds=60)

    scheduler.start()
    await gerbang.tunggu_siklus()  # siklus 1: gagal, tetap tidur
    assert scheduler.is_running
    assert await daftar_notif(dunia.db, proyek.id_project, "sla_reminder") == []
    await scheduler.stop()

    scheduler.start()  # mulai ulang → siklus berikutnya berhasil memproses
    await gerbang.tunggu_siklus()
    assert len(await daftar_notif(dunia.db, proyek.id_project, "sla_reminder")) == 1
    await scheduler.stop()
    assert len(percobaan) == 2
