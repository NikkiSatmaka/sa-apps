"""
Fondasi integrasi: isolasi per test dan penggantian session factory.

`test_isolasi_a` dan `test_isolasi_b` menulis data yang SAMA (email unik + commit). Bila
rollback per test tidak bekerja, yang kedua gagal karena unique violation atau melihat
baris sisa. Keduanya juga memastikan tabel kosong saat mulai.
"""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import User

EMAIL = "isolasi@portal-sa.local"


async def _tulis_user(db) -> None:
    jumlah_awal = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    assert jumlah_awal == 0, "tabel users harus kosong di awal setiap test (tanpa sisa)"
    db.add(User(id=uuid.uuid4(), email=EMAIL, name="Isolasi", role="SA", google_id="g-isolasi"))
    await db.commit()  # commit kode produksi = release savepoint, bukan commit nyata
    emails = (await db.execute(select(User.email))).scalars().all()
    assert emails == [EMAIL]


async def test_isolasi_a(db_session):
    await _tulis_user(db_session)


async def test_isolasi_b(db_session):
    await _tulis_user(db_session)


async def test_data_test_tidak_terlihat_koneksi_lain(db_session, database_uji_url):
    """Data yang di-commit via sesi test tidak pernah sampai ke koneksi independen."""
    db_session.add(
        User(id=uuid.uuid4(), email="tak-terlihat@portal-sa.local", name="X", role="SA", google_id="g-x")
    )
    await db_session.commit()

    engine = create_async_engine(database_uji_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            jumlah = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()
    finally:
        await engine.dispose()
    assert jumlah == 0


async def test_patch_session_factory_menjangkau_modul_yang_membuka_sesi_sendiri(
    api, db_session, session_factory
):
    """AsyncSessionLocal di modul-modul pemakai diarahkan ke sesi test (bukan DB gagal-cepat)."""
    import app.core.database as database
    import app.services.notification_service as notification_service
    import app.services.sla_timer as sla_timer

    for modul in (database, notification_service, sla_timer):
        assert modul.AsyncSessionLocal is session_factory

    # Sesi dari AsyncSessionLocal melihat data uncommitted-ke-luar dari sesi test lain.
    db_session.add(
        User(id=uuid.uuid4(), email="bersama@portal-sa.local", name="B", role="SA", google_id="g-b")
    )
    await db_session.commit()
    async with database.AsyncSessionLocal() as lain:
        email = (await lain.execute(select(User.email))).scalar_one()
    assert email == "bersama@portal-sa.local"


def test_marker_integration_otomatis_dipasang(request):
    assert request.node.get_closest_marker("integration") is not None


async def test_startup_app_tidak_dijalankan_di_klien_asgi(api):
    """ASGITransport tidak mengirim lifespan: scheduler SLA tidak aktif."""
    from app.main import sla_scheduler

    resp = await api.client.get("/health")
    assert resp.status_code in (200, 503)
    assert sla_scheduler.is_running is False
