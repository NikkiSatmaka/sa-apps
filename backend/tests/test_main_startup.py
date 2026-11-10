"""
Unit test lifecycle `app.main` (tiket #55): hard guard DEMO_MODE di produksi, registrasi adapter,
toleransi gagal sweep, dan toggle scheduler SLA. Dependency berat di-patch di boundary.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main
from app.core.config import settings


@pytest.fixture
def luar(monkeypatch):
    """Patch boundary startup: sweep DB, scheduler SLA, dan factory LLM."""
    sweep = AsyncMock()
    scheduler = MagicMock()
    scheduler.stop = AsyncMock()
    factory = MagicMock()
    monkeypatch.setattr(main, "sweep_stale_pending_requirements", sweep)
    monkeypatch.setattr(main, "sla_scheduler", scheduler)
    monkeypatch.setattr(main, "llm_factory", factory)
    monkeypatch.setattr(settings, "SLA_SCHEDULER_ENABLED", True)
    return MagicMock(sweep=sweep, scheduler=scheduler, factory=factory)


class TestStartupGuard:
    async def test_produksi_dengan_demo_mode_menolak_start(self, luar, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DEMO_MODE", True)

        with pytest.raises(RuntimeError, match="DEMO_MODE"):
            await main.startup_register_adapters()

        # Refuse-to-start: tidak ada efek samping startup yang sempat berjalan.
        luar.sweep.assert_not_awaited()
        luar.scheduler.start.assert_not_called()
        luar.factory.register_adapter.assert_not_called()

    @pytest.mark.parametrize(
        ("env", "demo"),
        [("production", False), ("development", True), ("staging", True), ("development", False)],
    )
    async def test_kombinasi_lain_boleh_start(self, luar, monkeypatch, env, demo):
        monkeypatch.setattr(settings, "ENVIRONMENT", env)
        monkeypatch.setattr(settings, "DEMO_MODE", demo)

        await main.startup_register_adapters()

        luar.factory.register_adapter.assert_called_once_with("gemini", main.GeminiAdapter)
        luar.sweep.assert_awaited_once()


class TestStartupLainnya:
    async def test_scheduler_dijalankan_bila_aktif(self, luar, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        await main.startup_register_adapters()
        luar.scheduler.start.assert_called_once()

    async def test_scheduler_tidak_dijalankan_bila_dinonaktifkan(self, luar, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "SLA_SCHEDULER_ENABLED", False)
        await main.startup_register_adapters()
        luar.scheduler.start.assert_not_called()

    async def test_sweep_gagal_tidak_menggagalkan_startup(self, luar, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        luar.sweep.side_effect = ConnectionError("db belum siap")
        await main.startup_register_adapters()
        luar.scheduler.start.assert_called_once()

    async def test_registrasi_adapter_gagal_tidak_menggagalkan_startup(self, luar, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        luar.factory.register_adapter.side_effect = ValueError("duplikat")
        await main.startup_register_adapters()
        luar.sweep.assert_awaited_once()

    async def test_shutdown_menghentikan_scheduler(self, luar):
        await main.shutdown_stop_scheduler()
        luar.scheduler.stop.assert_awaited_once()


def test_cors_memakai_allow_list_konkret_bukan_wildcard():
    cors = next(m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert "*" not in cors.kwargs["allow_origins"]
    assert cors.kwargs["allow_credentials"] is True


def test_rate_limiter_terpasang_di_app():
    assert any(m.cls.__name__ == "RateLimiterMiddleware" for m in main.app.user_middleware)


def test_router_auth_terdaftar_di_prefix_v1():
    rute = set(main.app.openapi()["paths"])
    assert {
        "/api/v1/auth/config",
        "/api/v1/auth/demo-login",
        "/api/v1/auth/login",
        "/api/v1/auth/callback",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    } <= rute
