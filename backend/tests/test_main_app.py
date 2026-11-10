"""
`app.main`: guard produksi saat startup, ketahanan registrasi adapter, registrasi router
(setiap prefix API terpasang) dan /health. Startup dipanggil langsung sebagai fungsi agar
tidak menjalankan scheduler/sweep sungguhan.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app


@pytest.fixture
def startup_terisolasi():
    """Patch semua efek samping startup; kembalikan mock yang bisa diperiksa."""
    with (
        patch.object(main, "sweep_stale_pending_requirements", new=AsyncMock()) as sweep,
        patch.object(main, "sla_scheduler") as scheduler,
        patch.object(main, "llm_factory") as factory,
    ):
        yield MagicMock(sweep=sweep, scheduler=scheduler, factory=factory)


class TestStartup:
    async def test_produksi_dengan_demo_mode_menolak_start(self, monkeypatch, startup_terisolasi):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(main.settings, "DEMO_MODE", True)
        with pytest.raises(RuntimeError, match="DEMO_MODE tidak boleh aktif"):
            await main.startup_register_adapters()
        # Gagal sebelum efek samping apa pun.
        startup_terisolasi.scheduler.start.assert_not_called()
        startup_terisolasi.sweep.assert_not_awaited()

    @pytest.mark.parametrize(
        "env,demo", [("production", False), ("development", True), ("development", False)]
    )
    async def test_kombinasi_lain_boleh_start(self, monkeypatch, startup_terisolasi, env, demo):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", env)
        monkeypatch.setattr(main.settings, "DEMO_MODE", demo)
        monkeypatch.setattr(main.settings, "SLA_SCHEDULER_ENABLED", True)
        await main.startup_register_adapters()
        startup_terisolasi.scheduler.start.assert_called_once_with()

    async def test_adapter_gemini_didaftarkan_dan_sweep_dijalankan(
        self, monkeypatch, startup_terisolasi
    ):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", "development")
        await main.startup_register_adapters()
        startup_terisolasi.factory.register_adapter.assert_called_once_with(
            "gemini", main.GeminiAdapter
        )
        startup_terisolasi.sweep.assert_awaited_once()

    async def test_gagal_daftar_adapter_tidak_menggagalkan_startup(
        self, monkeypatch, startup_terisolasi
    ):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(main.settings, "SLA_SCHEDULER_ENABLED", True)
        startup_terisolasi.factory.register_adapter.side_effect = RuntimeError("rusak")
        await main.startup_register_adapters()
        # Bagian berikutnya tetap jalan.
        startup_terisolasi.sweep.assert_awaited_once()
        startup_terisolasi.scheduler.start.assert_called_once_with()

    async def test_gagal_sweep_tidak_menggagalkan_startup(self, monkeypatch, startup_terisolasi):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(main.settings, "SLA_SCHEDULER_ENABLED", True)
        startup_terisolasi.sweep.side_effect = RuntimeError("db mati")
        await main.startup_register_adapters()
        startup_terisolasi.scheduler.start.assert_called_once_with()

    async def test_scheduler_tidak_dijalankan_bila_dinonaktifkan(
        self, monkeypatch, startup_terisolasi
    ):
        monkeypatch.setattr(main.settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(main.settings, "SLA_SCHEDULER_ENABLED", False)
        await main.startup_register_adapters()
        startup_terisolasi.scheduler.start.assert_not_called()

    async def test_shutdown_menghentikan_scheduler(self, startup_terisolasi):
        startup_terisolasi.scheduler.stop = AsyncMock()
        await main.shutdown_stop_scheduler()
        startup_terisolasi.scheduler.stop.assert_awaited_once()


class TestRegistrasiRouter:
    def test_setiap_domain_punya_route_terdaftar(self):
        """Lewat skema OpenAPI (route router yang di-include tidak tampil di `app.routes`)."""
        paths = app.openapi()["paths"]
        domain = {p.split("/")[3] for p in paths if p.startswith("/api/v1/")}
        assert {
            "auth",
            "projects",
            "notifications",
            "sla",
            "calendar",
            "qualification",
            "admin",
            "activity-logs",
            "documents",
        } <= domain, sorted(domain)
        # Router handover/scoring/dq berada di bawah /projects/{id}/...
        assert any(p.endswith("/handover") for p in paths)
        assert any("/scoring" in p or "/score" in p for p in paths)
        assert "/health" in paths

    def test_literal_pending_assignment_tidak_tertangkap_route_dinamis(self):
        paths = list(app.openapi()["paths"])
        assert paths.index("/api/v1/projects/pending-assignment") < paths.index(
            "/api/v1/projects/{project_id}"
        )

    def test_endpoint_dilindungi_menolak_tanpa_token(self):
        """Semua router bisa dijangkau (tidak 404) dan auth aktif (401/403), bukan terbuka."""
        client = TestClient(app)
        for url in (
            "/api/v1/projects",
            "/api/v1/notifications",
            "/api/v1/notifications/unread-count",
            "/api/v1/qualification/schema",
        ):
            resp = client.get(url)
            assert resp.status_code in (401, 403), (url, resp.status_code)

    def test_route_tak_dikenal_404_berformat_standar(self):
        resp = TestClient(app).get("/api/v1/tidak-ada")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    def test_openapi_dan_docs_tersedia(self):
        client = TestClient(app)
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200

    def test_health_tidak_butuh_auth(self):
        with patch("app.main.check_database_health", new=AsyncMock(return_value=True)):
            assert TestClient(app).get("/health").status_code == 200
