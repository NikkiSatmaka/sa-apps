"""
Unit tests untuk SLA Scheduler (background scheduler internal, ADR 0003).

Menguji:
- Loop scheduler memanggil `process_sla_actions()` secara periodik.
- Loop tahan error: satu kegagalan tidak mematikan scheduler.
- start() idempoten dan stop() menghentikan loop dengan rapi.
- Wiring startup FastAPI memasang scheduler saat SLA_SCHEDULER_ENABLED=True.
- Endpoint manual POST /sla/process tetap berfungsi berdampingan.

Semua test deterministik: `asyncio.sleep` di dalam scheduler di-patch agar loop
tidak benar-benar menunggu interval, dan loop dihentikan secara eksplisit.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.services.sla_scheduler import SLAScheduler

# =============================================================================
# Test: loop scheduler memanggil process_sla_actions()
# =============================================================================


class TestSchedulerLoop:
    """Test perilaku loop background scheduler."""

    @pytest.mark.asyncio
    async def test_loop_memanggil_process_sla_actions(self):
        """Loop harus memanggil sla_timer.process_sla_actions() secara periodik."""
        call_count = 0

        async def fake_process():
            nonlocal call_count
            call_count += 1

        # sleep di-patch: lewati dua iterasi lalu cancel loop agar deterministik.
        async def fake_sleep(_seconds):
            if call_count >= 2:
                raise asyncio.CancelledError
            return None

        scheduler = SLAScheduler(interval_seconds=3600)

        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions",
            new=AsyncMock(side_effect=fake_process),
        ), patch(
            "app.services.sla_scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=fake_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._run_loop()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_loop_tahan_error(self):
        """Error pada satu iterasi tidak boleh mematikan loop."""
        call_count = 0

        async def flaky_process():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")

        async def fake_sleep(_seconds):
            # Hentikan setelah iterasi kedua (yang sukses) terpanggil.
            if call_count >= 2:
                raise asyncio.CancelledError
            return None

        scheduler = SLAScheduler(interval_seconds=3600)

        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions",
            new=AsyncMock(side_effect=flaky_process),
        ), patch(
            "app.services.sla_scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=fake_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._run_loop()

        # Loop tetap lanjut setelah error pertama → process dipanggil >= 2x.
        assert call_count >= 2


# =============================================================================
# Test: start() / stop() lifecycle
# =============================================================================


class TestSchedulerLifecycle:
    """Test start/stop background task scheduler."""

    @pytest.mark.asyncio
    async def test_start_membuat_task_dan_memanggil_process(self):
        """start() memasang task yang memanggil process_sla_actions()."""
        started = asyncio.Event()

        async def fake_process():
            started.set()

        async def fake_sleep(_seconds):
            # Tidur "selamanya" hingga task di-cancel oleh stop().
            await asyncio.Event().wait()

        scheduler = SLAScheduler(interval_seconds=3600)

        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions",
            new=AsyncMock(side_effect=fake_process),
        ), patch(
            "app.services.sla_scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=fake_sleep),
        ):
            scheduler.start()
            assert scheduler.is_running is True

            # Tunggu iterasi pertama benar-benar memanggil process.
            await asyncio.wait_for(started.wait(), timeout=1)

            await scheduler.stop()

        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_idempoten(self):
        """start() dua kali tidak membuat task baru / kedua."""
        async def fake_sleep(_seconds):
            await asyncio.Event().wait()

        scheduler = SLAScheduler(interval_seconds=3600)

        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions",
            new=AsyncMock(),
        ), patch(
            "app.services.sla_scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=fake_sleep),
        ):
            scheduler.start()
            first_task = scheduler._task
            scheduler.start()
            second_task = scheduler._task

            assert first_task is second_task

            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_tanpa_start_aman(self):
        """stop() saat belum pernah start() tidak error."""
        scheduler = SLAScheduler(interval_seconds=3600)
        await scheduler.stop()  # tidak boleh raise
        assert scheduler.is_running is False


# =============================================================================
# Test: wiring startup FastAPI + endpoint manual tetap jalan
# =============================================================================


class TestSchedulerWiring:
    """Test scheduler terpasang di startup dan endpoint manual tetap berfungsi."""

    def test_startup_memasang_scheduler(self):
        """Startup event memanggil sla_scheduler.start() saat enabled."""
        import app.main as main_module

        with patch.object(
            main_module.settings, "SLA_SCHEDULER_ENABLED", True
        ), patch.object(
            main_module.sla_scheduler, "start"
        ) as mock_start, patch.object(
            main_module.sla_scheduler, "stop", new=AsyncMock()
        ):
            # Context manager TestClient memicu startup & shutdown event.
            with TestClient(main_module.app):
                pass

            mock_start.assert_called_once()

    def test_startup_skip_saat_disabled(self):
        """Startup tidak memanggil start() saat SLA_SCHEDULER_ENABLED=False."""
        import app.main as main_module

        with patch.object(
            main_module.settings, "SLA_SCHEDULER_ENABLED", False
        ), patch.object(
            main_module.sla_scheduler, "start"
        ) as mock_start, patch.object(
            main_module.sla_scheduler, "stop", new=AsyncMock()
        ):
            with TestClient(main_module.app):
                pass

            mock_start.assert_not_called()

    def test_endpoint_manual_sla_process_tetap_jalan(self):
        """POST /sla/process tetap berfungsi berdampingan dengan scheduler."""
        import app.main as main_module
        from app.core.dependencies import get_current_user

        app = main_module.app

        lead_user = MagicMock()
        lead_user.role = "Lead_SA"
        lead_user.email = "lead@company.com"

        fake_stats = {
            "total_checked": 2,
            "reminders_sent": 1,
            "escalations_sent": 1,
            "locks_performed": 0,
            "errors": [],
        }

        app.dependency_overrides[get_current_user] = lambda: lead_user

        try:
            with patch(
                "app.api.sla.sla_timer.process_sla_actions",
                new=AsyncMock(return_value=fake_stats),
            ) as mock_process, patch.object(
                main_module.sla_scheduler, "start"
            ), patch.object(
                main_module.sla_scheduler, "stop", new=AsyncMock()
            ):
                with TestClient(app) as client:
                    response = client.post("/api/v1/sla/process")

            assert response.status_code == status.HTTP_200_OK
            body = response.json()
            assert body["data"]["total_checked"] == 2
            mock_process.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestSchedulerPembatalan:
    """Pembatalan (shutdown) di tengah pemrosesan harus diteruskan, bukan ditelan."""

    @pytest.mark.asyncio
    async def test_cancelled_error_dari_proses_menghentikan_loop(self):
        scheduler = SLAScheduler(interval_seconds=3600)

        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ), patch("app.services.sla_scheduler.asyncio.sleep", new=AsyncMock()) as tidur:
            with pytest.raises(asyncio.CancelledError):
                await scheduler._run_loop()

        tidur.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_stop_start_ulang_berjalan_kembali(self):
        scheduler = SLAScheduler(interval_seconds=3600)
        proses = AsyncMock()

        async def tidur_selamanya(_detik):
            await asyncio.Event().wait()

        # Proxy khusus modul scheduler: `asyncio.sleep` global (dipakai test ini) tidak berubah.
        proxy = SimpleNamespace(
            sleep=tidur_selamanya,
            create_task=asyncio.create_task,
            CancelledError=asyncio.CancelledError,
            Task=asyncio.Task,
        )
        with patch(
            "app.services.sla_scheduler.sla_timer.process_sla_actions", new=proses
        ), patch("app.services.sla_scheduler.asyncio", new=proxy):
            scheduler.start()
            await asyncio.sleep(0)
            assert scheduler.is_running
            await scheduler.stop()
            assert not scheduler.is_running

            scheduler.start()
            await asyncio.sleep(0)
            assert scheduler.is_running
            await scheduler.stop()

        assert proses.await_count == 2
