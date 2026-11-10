"""
Unit test `core/database` (tiket #55): `get_db` dan `check_database_health`. Tanpa Postgres:
sesi diganti fake; satu test memakai engine nyata ke target gagal-cepat dari conftest.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import database


class _FabrikSesi:
    """Pengganti `AsyncSessionLocal`: `async with factory() as session`."""

    def __init__(self, session):
        self.session = session
        self.dibuka = 0

    def __call__(self):
        self.dibuka += 1
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _sesi() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.close = AsyncMock()
    return s


class TestGetDb:
    async def test_memberikan_sesi_lalu_menutupnya(self, monkeypatch):
        sesi = _sesi()
        monkeypatch.setattr(database, "AsyncSessionLocal", _FabrikSesi(sesi))

        gen = database.get_db()
        diberikan = await gen.__anext__()
        assert diberikan is sesi
        sesi.close.assert_not_awaited()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        sesi.close.assert_awaited_once()

    async def test_sesi_ditutup_juga_saat_handler_error(self, monkeypatch):
        sesi = _sesi()
        monkeypatch.setattr(database, "AsyncSessionLocal", _FabrikSesi(sesi))

        gen = database.get_db()
        await gen.__anext__()
        with pytest.raises(RuntimeError, match="handler gagal"):
            await gen.athrow(RuntimeError("handler gagal"))

        sesi.close.assert_awaited_once()


class TestCheckDatabaseHealth:
    async def test_sehat_bila_select_1_berhasil(self, monkeypatch):
        sesi = _sesi()
        fabrik = _FabrikSesi(sesi)
        monkeypatch.setattr(database, "AsyncSessionLocal", fabrik)

        assert await database.check_database_health() is True
        assert fabrik.dibuka == 1
        assert str(sesi.execute.await_args.args[0]) == "SELECT 1"

    async def test_tidak_sehat_bila_query_gagal(self, monkeypatch):
        sesi = _sesi()
        sesi.execute.side_effect = ConnectionError("db mati")
        monkeypatch.setattr(database, "AsyncSessionLocal", _FabrikSesi(sesi))

        assert await database.check_database_health() is False

    async def test_tidak_sehat_dan_tidak_melempar_saat_server_tak_terjangkau(self):
        """Engine nyata ke 127.0.0.1:1 (conftest): ditolak seketika → False, bukan exception."""
        assert await database.check_database_health() is False


def test_engine_memakai_database_url_dan_driver_asyncpg():
    assert database.engine.url.drivername == "postgresql+asyncpg"
    assert database.engine.url.database == "test_unit_tanpa_db"  # dipaksa conftest, bukan DB dev


def test_base_mendaftarkan_semua_tabel_model():
    import app.models  # noqa: F401

    assert {"users", "projects", "project_collaborators"} <= set(database.Base.metadata.tables)
