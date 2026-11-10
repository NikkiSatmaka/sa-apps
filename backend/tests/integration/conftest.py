"""
Fondasi test integrasi terhadap Postgres nyata (tiket B2, spec #49).

Alur:
- `TEST_DATABASE_URL` (asyncpg) menunjuk SERVER Postgres uji. Fixture tingkat sesi membuat
  database sementara bernama acak `sa_test_<hex>` DI SERVER ITU, menjalankan
  `alembic upgrade head` (subprocess), dan menghapusnya di akhir. Database lain di server
  itu tidak pernah disentuh, dan `DATABASE_URL` (yang dipaksa ke target gagal-cepat oleh
  `tests/conftest.py`) tidak pernah dipakai.
- Isolasi per test: satu koneksi dengan transaksi luar yang di-rollback di akhir test;
  `commit()` pada kode produksi menjadi RELEASE SAVEPOINT (`create_savepoint`).
- Klien API ASGI memakai override `get_db` ke sesi test DAN mem-patch `AsyncSessionLocal`
  di semua modul yang membuka sesinya sendiri (background task, notifikasi, SLA, dst.).

Seluruh test di folder ini otomatis diberi marker `integration` dan dilewati dengan pesan
jelas bila `TEST_DATABASE_URL` tidak di-set. Test unit tidak terpengaruh: berkas ini hanya
berlaku untuk `tests/integration/` dan tidak mengubah environment `tests/conftest.py`.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Pakai skrip `alembic` di venv, BUKAN `python -m alembic`: folder `backend/alembic/` (migration)
# menimpa package alembic bila cwd/rootdir ada di sys.path.
ALEMBIC_BIN = Path(sys.executable).parent / "alembic"
ENV_URL = "TEST_DATABASE_URL"
ENV_ALLOW_REMOTE = "TEST_DATABASE_ALLOW_REMOTE"
PREFIX_DB = "sa_test_"
HOST_LOKAL = {"127.0.0.1", "localhost", "::1"}
PESAN_SKIP = (
    f"{ENV_URL} tidak di-set: test integrasi dilewati. Jalankan Postgres 18 sementara "
    f"lalu set {ENV_URL}=postgresql+asyncpg://user:pass@127.0.0.1:<port>/postgres "
    "(lihat backend/README.md, bagian Test integrasi)."
)


# --------------------------------------------------------------------------- marker & skip


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Beri marker `integration` ke semua test di folder ini (tanpa perlu dekorator manual)."""
    for item in items:
        if Path(str(item.path)).is_relative_to(Path(__file__).parent):
            item.add_marker(pytest.mark.integration)


def _url_server_uji() -> str:
    url = os.environ.get(ENV_URL, "").strip()
    if not url:
        pytest.skip(PESAN_SKIP)
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg":
        raise pytest.UsageError(f"{ENV_URL} wajib memakai driver 'postgresql+asyncpg'.")
    if parsed.host not in HOST_LOKAL and os.environ.get(ENV_ALLOW_REMOTE) != "1":
        raise pytest.UsageError(
            f"{ENV_URL} menunjuk host non-lokal ({parsed.host}). Test integrasi membuat dan "
            f"menghapus database; set {ENV_ALLOW_REMOTE}=1 hanya untuk server uji khusus (mis. CI)."
        )
    return url


# --------------------------------------------------------------------------- server & DB sementara


def _jalankan(coro_fn: Callable[[], object]) -> None:
    """Jalankan koroutin dari fixture sinkron (tidak ada event loop aktif di sini)."""
    asyncio.run(coro_fn())  # type: ignore[arg-type]


async def _perintah_admin(url: str, sql: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def jalankan_alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """
    Jalankan `alembic <args>` sebagai subprocess terhadap `url`.

    Subprocess dipakai karena `alembic/env.py` menimpa URL dari `settings.DATABASE_URL` dan
    memanggil `asyncio.run`, yang tidak bisa berjalan di dalam event loop test. `DATABASE_URL`
    di environment subprocess diarahkan ke database sementara.
    """
    env = {**os.environ, "DATABASE_URL": url}
    hasil = subprocess.run(
        [str(ALEMBIC_BIN), "-c", str(BACKEND_DIR / "alembic.ini"), *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if hasil.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} gagal (exit {hasil.returncode}):\n"
            f"{hasil.stdout}\n{hasil.stderr}"
        )
    return hasil


@dataclass
class ServerUji:
    """Pembuat/penghapus database sementara di server `TEST_DATABASE_URL`."""

    url_admin: str
    dibuat: list[str] = field(default_factory=list)

    def buat_database(self, *, migrasi: bool = False) -> str:
        """Buat database acak `sa_test_<hex>`; kembalikan URL asyncpg-nya."""
        nama = f"{PREFIX_DB}{secrets.token_hex(6)}"
        _jalankan(lambda: _perintah_admin(self.url_admin, f'CREATE DATABASE "{nama}"'))
        self.dibuat.append(nama)
        url = make_url(self.url_admin).set(database=nama).render_as_string(hide_password=False)
        if migrasi:
            jalankan_alembic(url, "upgrade", "head")
        return url

    def hapus_database(self, nama: str) -> None:
        # Jaga-jaga: hanya database buatan fixture ini yang boleh dihapus.
        assert nama.startswith(PREFIX_DB) and nama in self.dibuat, nama
        _jalankan(
            lambda: _perintah_admin(
                self.url_admin, f'DROP DATABASE IF EXISTS "{nama}" WITH (FORCE)'
            )
        )
        self.dibuat.remove(nama)

    def hapus_semua(self) -> None:
        for nama in list(self.dibuat):
            self.hapus_database(nama)


@pytest.fixture(scope="session")
def server_uji() -> Iterator[ServerUji]:
    server = ServerUji(url_admin=_url_server_uji())
    try:
        yield server
    finally:
        server.hapus_semua()


@pytest.fixture(scope="session")
def database_uji_url(server_uji: ServerUji) -> str:
    """URL database sementara bersama (sudah `alembic upgrade head`); dihapus di akhir sesi."""
    return server_uji.buat_database(migrasi=True)


@pytest.fixture
def database_kosong_url(server_uji: ServerUji) -> Iterator[str]:
    """Database sementara KOSONG (tanpa migration) khusus satu test; dihapus setelahnya."""
    url = server_uji.buat_database()
    try:
        yield url
    finally:
        server_uji.hapus_database(make_url(url).database)


# --------------------------------------------------------------------------- isolasi per test


@pytest_asyncio.fixture
async def db_connection(database_uji_url: str) -> AsyncIterator[AsyncConnection]:
    """Koneksi dengan transaksi luar yang SELALU di-rollback di akhir test."""
    engine = create_async_engine(database_uji_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            transaksi = await conn.begin()
            try:
                yield conn
            finally:
                await transaksi.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """
    Factory sesi yang terikat ke koneksi test. `commit()` di kode produksi hanya melepas
    savepoint; transaksi luar tetap di-rollback fixture `db_connection`.
    """
    return async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


def patch_session_factory(
    monkeypatch: pytest.MonkeyPatch, factory: async_sessionmaker[AsyncSession]
) -> list[str]:
    """
    Ganti `AsyncSessionLocal` dengan `factory` di SETIAP modul `app.*` yang memilikinya.

    Service/background task membuka sesi sendiri (`async with AsyncSessionLocal()`), jadi
    `dependency_overrides[get_db]` tidak menjangkaunya. Modul yang mengimpor di level modul
    (mis. `notification_service`, `sla_timer`) menyimpan referensi sendiri, sedangkan yang
    mengimpor lokal membaca `app.core.database.AsyncSessionLocal` saat dipanggil; memindai
    `sys.modules` menutup keduanya dan modul baru di masa depan. Mengembalikan nama modul
    yang dipatch.
    """
    import app.core.database  # noqa: F401  - pastikan modul sudah dimuat

    dipatch: list[str] = []
    for nama, modul in list(sys.modules.items()):
        if (nama == "app" or nama.startswith("app.")) and hasattr(modul, "AsyncSessionLocal"):
            monkeypatch.setattr(modul, "AsyncSessionLocal", factory)
            dipatch.append(nama)
    return dipatch


# --------------------------------------------------------------------------- klien API ASGI


@dataclass
class KlienApi:
    client: httpx.AsyncClient
    generate_requirement: AsyncMock

    async def login_demo(self, role: str) -> dict[str, str]:
        """Demo login → header Authorization (JWT asli lewat alur produksi)."""
        resp = await self.client.post("/api/v1/auth/demo-login", json={"role": role})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


@pytest_asyncio.fixture
async def api(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[KlienApi]:
    """
    Klien ASGI (httpx + ASGITransport) terhadap `app` nyata dengan Postgres uji.

    - `get_db` di-override ke sesi dari `session_factory` (satu koneksi, rollback per test).
    - `AsyncSessionLocal` di-patch di modul yang membuka sesi sendiri.
    - Event startup TIDAK jalan: `ASGITransport` tidak mengirim lifespan, jadi scheduler SLA
      dan sweep Requirement tidak aktif. `SLA_SCHEDULER_ENABLED` juga dimatikan sebagai
      pengaman bila ada yang memakai lifespan.
    - Background task Requirement (`generate_pending_requirement`) diganti AsyncMock agar
      Gemini nyata tidak pernah dipanggil; yang terlihat hanya penanda `pending` di DB dan
      pemanggilan mock. Fake LLM sebenarnya adalah lingkup tiket #54.
    - Demo mode dinyalakan (`DEMO_MODE`) untuk login tanpa OAuth.
    """
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "SLA_SCHEDULER_ENABLED", False)
    patch_session_factory(monkeypatch, session_factory)

    gen_requirement = AsyncMock()
    monkeypatch.setattr("app.api.projects.generate_pending_requirement", gen_requirement)

    async def _get_db_uji() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_uji
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield KlienApi(client=client, generate_requirement=gen_requirement)
    finally:
        app.dependency_overrides.pop(get_db, None)


# Fixture fake boundary (tiket B3): fake_llm, fake_drive, fake_gmail, fake_calendar.
from tests.integration.fakes.fixtures import (  # noqa: E402,F401
    fake_calendar,
    fake_drive,
    fake_gmail,
    fake_llm,
)
