"""
Unit test jalur galat API notifikasi, activity log, kalender, dan kolaborator (tiket #60, spec #49).

Jalur normal diuji di `tests/integration/*_t60.py` terhadap Postgres. Di sini hanya kegagalan
infrastruktur yang sulit dipancing dari DB nyata (service melempar, IntegrityError non-gcal,
peran tak dikenal). Sesi DB dan user adalah test double sederhana; asersi pada respons HTTP.
"""

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app

PREFIX = "/api/v1"


def _user(role="SA"):
    return SimpleNamespace(id=uuid.uuid4(), email=f"{role}@x.id", name=role, role=role)


@contextmanager
def _klien(user, db=None):
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield db if db is not None else MagicMock()

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _hasil(nilai):
    r = MagicMock()
    r.scalar_one_or_none.return_value = nilai
    return r


# ---  notifikasi


@pytest.mark.parametrize(
    ("metode", "url", "method_service", "pesan"),
    [
        ("get", f"{PREFIX}/notifications", "get_user_notifications", "Gagal mengambil notifikasi."),
        (
            "get",
            f"{PREFIX}/notifications/unread-count",
            "get_unread_count",
            "Gagal mengambil jumlah notifikasi.",
        ),
        (
            "patch",
            f"{PREFIX}/notifications/N-1/read",
            "mark_as_read",
            "Gagal memperbarui notifikasi.",
        ),
    ],
)
def test_notifikasi_error_tak_terduga_500_tanpa_membocorkan_detail(
    monkeypatch, metode, url, method_service, pesan
):
    from app.api import notifications as modul

    monkeypatch.setattr(
        modul.notification_service,
        method_service,
        AsyncMock(side_effect=RuntimeError("rahasia-db")),
    )

    with _klien(_user()) as c:
        resp = getattr(c, metode)(url)

    assert resp.status_code == 500
    assert resp.json()["message"] == pesan
    assert "rahasia-db" not in resp.text


def test_notifikasi_item_dengan_timestamp_null_diserialisasi_none(monkeypatch):
    from app.api import notifications as modul

    item = SimpleNamespace(
        id="N-1",
        event_type="assignment",
        channel="in-app",
        status="sent",
        reference_id=None,
        notification_metadata=None,
        created_at=None,
        read_at=None,
    )
    monkeypatch.setattr(
        modul.notification_service,
        "get_user_notifications",
        AsyncMock(return_value={"items": [item], "total": 1, "page": 1, "per_page": 20}),
    )

    with _klien(_user()) as c:
        resp = c.get(f"{PREFIX}/notifications")

    assert resp.json()["data"]["items"][0]["created_at"] is None
    assert resp.json()["data"]["items"][0]["read_at"] is None


# ---  activity log


class _LoggerMeledak:
    def __init__(self, db):
        pass

    async def create_log(self, **kw):
        raise RuntimeError("rahasia-internal")

    async def retry_polish(self, **kw):
        raise RuntimeError("rahasia-internal")

    async def get_project_story(self, **kw):
        raise RuntimeError("rahasia-internal")


LOG_OK = {
    "id_project": "PRJ-1",
    "project_phase": "Pre-Implementation",
    "subtask_category": "Assessment",
    "duration_hours": "1",
    "raw_notes": "catatan",
}


@pytest.mark.parametrize(
    ("metode", "url", "badan", "pesan"),
    [
        ("post", f"{PREFIX}/activity-logs", LOG_OK, "Gagal membuat activity log"),
        ("post", f"{PREFIX}/activity-logs/LOG-1/polish", None, "Gagal memproses ulang notes"),
        ("get", f"{PREFIX}/projects/PRJ-1/story", None, "Gagal mengambil project story"),
        ("post", f"{PREFIX}/projects/PRJ-1/summarize", None, "Gagal menghasilkan ringkasan"),
    ],
)
def test_activity_log_error_tak_terduga_500_tanpa_membocorkan_detail(
    monkeypatch, metode, url, badan, pesan
):
    from app.api import activity_logs as modul

    monkeypatch.setattr(modul, "ActivityLogger", _LoggerMeledak)
    # Tiket #89: rute story/summarize/activity-logs kini memuat proyek lalu memeriksa akses
    # SEBELUM service. Cek akses di-stub lolos agar yang diuji tetap jalur galat service.
    monkeypatch.setattr(modul, "ensure_project_access", AsyncMock())
    db = MagicMock()
    # #92: polish ulang kini memuat log lebih dulu (cek akses TULIS penulis); `sa_id` ada tapi
    # bukan milik pemanggil agar jalur yang diuji tetap galat service (500), bukan cek akses.
    db.execute = AsyncMock(
        return_value=_hasil(SimpleNamespace(id_project="PRJ-1", sa_id=uuid.uuid4()))
    )

    with _klien(_user(), db) as c:
        resp = c.post(url, json=badan) if metode == "post" and badan else getattr(c, metode)(url)

    assert resp.status_code == 500
    assert pesan in resp.json()["message"]
    assert "rahasia-internal" not in resp.text


# ---  kalender


def test_map_integrity_error_non_gcal_400_dan_rollback(monkeypatch):
    from app.api import calendar as modul

    # Tiket #89: cek akses TULIS di-stub lolos; yang diuji adalah galat commit.
    monkeypatch.setattr(modul, "ensure_project_access", AsyncMock())
    db = MagicMock()
    db.execute = AsyncMock(return_value=_hasil(SimpleNamespace(id_project="PRJ-1")))
    db.add = MagicMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError(
            "INSERT", {}, Exception('violates foreign key constraint "fk_sa"')
        )
    )
    db.rollback = AsyncMock()
    badan = {
        "gcal_event_id": "evt-1",
        "project_id": "PRJ-1",
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "event_title": "Rapat",
        "is_all_day": True,
    }

    with _klien(_user(), db) as c:
        resp = c.post(f"{PREFIX}/calendar/map", json=badan)

    assert resp.status_code == 400
    assert "Gagal memetakan event" in resp.json()["message"]
    db.rollback.assert_awaited_once()


def test_map_konflik_gcal_409_pesan_generik_tanpa_mencari_proyek_lain(monkeypatch):
    """Unique violation gcal -> 409 generik. DIUBAH: dulu menguji fallback "log lama hilang"
    ("...ke proyek lain"); pesan kini selalu generik dan tidak lagi mencari log/proyek lain."""
    from app.api import calendar as modul

    monkeypatch.setattr(modul, "ensure_project_access", AsyncMock())  # tiket #89: cek akses lolos
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_hasil(SimpleNamespace(id_project="PRJ-1")), _hasil(None)])
    db.add = MagicMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("duplicate key idx_unique_gcal_mapping"))
    )
    db.rollback = AsyncMock()
    badan = {
        "gcal_event_id": "evt-1",
        "project_id": "PRJ-1",
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "event_title": "Rapat",
        "is_all_day": True,
    }

    with _klien(_user(), db) as c:
        resp = c.post(f"{PREFIX}/calendar/map", json=badan)

    assert resp.status_code == 409
    assert resp.json()["message"] == "Event sudah dipetakan sebelumnya."


# ---  kolaborator


def test_tambah_kolaborator_peran_tak_dikenal_403_sebelum_menyentuh_user_target():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_hasil(SimpleNamespace(id_project="PRJ-1")))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with _klien(_user("PMO"), db) as c:
        resp = c.post(f"{PREFIX}/projects/PRJ-1/collaborators", json={"user_id": str(uuid.uuid4())})

    assert resp.status_code == 403
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    assert db.execute.await_count == 1  # hanya cek proyek


# ---  activity_logger


async def test_activity_logger_sync_calendar_placeholder_mengembalikan_daftar_kosong():
    from app.services.activity_logger import ActivityLogger

    assert await ActivityLogger(MagicMock()).sync_calendar(uuid.uuid4()) == []
