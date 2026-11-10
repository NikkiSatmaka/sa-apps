"""
Integrasi Google Calendar terhadap Postgres nyata + fake Calendar (tiket #60, spec #49; ADR 0007).

Mencakup `auth-url`, `sync` (read-only, token Google, kegagalan timeout/API) dan `map` (pemetaan
event → ActivityLog: durasi, notes otomatis, work_type, unique constraint `gcal_event_id`).
Pasangan unit: `tests/test_calendar_service_t60.py` (service + parsing murni).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ActivityLog
from tests.integration.fakes.calendar import event_berjadwal, event_seharian
from tests.integration.helpers_t60 import API, bearer, buat_proyek, buat_user

CAL = f"{API}/calendar"


def _map(**o) -> dict:
    dasar = {
        "gcal_event_id": "evt-1",
        "work_type": "Project",
        "project_id": None,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Diskusi kebutuhan",
    }
    dasar.update(o)
    return {k: v for k, v in dasar.items() if v is not None}


async def _jumlah_log(db, **filter_) -> int:
    stmt = select(func.count()).select_from(ActivityLog)
    for k, v in filter_.items():
        stmt = stmt.where(getattr(ActivityLog, k) == v)
    return (await db.execute(stmt)).scalar_one()


# ---  auth-url


async def test_auth_url_belum_dikonfigurasi_503(api, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")

    resp = await api.client.get(f"{CAL}/auth-url")

    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


async def test_auth_url_scope_readonly_dan_state_menuju_halaman_calendar(api, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid-123")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "rahasia")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://portal.contoh.id/")

    resp = await api.client.get(f"{CAL}/auth-url")

    assert resp.status_code == 200, resp.text
    url = resp.json()["data"]["auth_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid-123" in url
    assert "scope=https://www.googleapis.com/auth/calendar.readonly" in url
    assert "state=calendar_auth|https://portal.contoh.id/activity-logs/calendar" in url
    assert "rahasia" not in url


# ---  sync


async def test_sync_mengembalikan_event_ter_parse_dan_meneruskan_token(
    api, db_session, fake_calendar
):
    fake_calendar.set_events(
        event_berjadwal(
            "e1", "Weekly sync", "2030-01-01T09:00:00+07:00", "2030-01-01T10:30:00+07:00", "Agenda"
        ),
        event_seharian("e2", "Workshop", "2030-01-02", "2030-01-03"),
    )
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(
        f"{CAL}/sync", json={"access_token": "ya29.token-uji"}, headers=bearer(sa)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_events"] == 2
    e1, e2 = data["events"]
    assert (e1["gcal_event_id"], e1["title"], e1["is_all_day"]) == ("e1", "Weekly sync", False)
    assert float(e1["duration_hours"]) == 1.5
    assert e1["description"] == "Agenda"
    assert (e2["is_all_day"], float(e2["duration_hours"])) == (True, 8.0)
    assert fake_calendar.access_token_diterima == ["ya29.token-uji"]


async def test_sync_read_only_tidak_menulis_activity_log(api, db_session, fake_calendar):
    fake_calendar.set_events(event_seharian("e1", "Cuti", "2030-01-02", "2030-01-03"))
    sa = await buat_user(db_session, "SA")

    await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=bearer(sa))

    assert await _jumlah_log(db_session) == 0


async def test_sync_tanpa_event_total_nol(api, db_session, fake_calendar):
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=bearer(sa))

    assert resp.json()["data"] == {"events": [], "total_events": 0}


async def test_sync_timeout_google_504(api, db_session, fake_calendar):
    fake_calendar.fail_next("timeout")
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=bearer(sa))

    assert resp.status_code == 504
    assert resp.json()["message"] == "Google Calendar API timeout"


async def test_sync_error_api_google_502_dengan_pesan_spesifik(api, db_session, fake_calendar):
    fake_calendar.fail_next("api", "Google Calendar API error (401): token kedaluwarsa")
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=bearer(sa))

    assert resp.status_code == 502
    assert "token kedaluwarsa" in resp.json()["message"]


async def test_sync_gagal_sekali_lalu_berhasil_pada_percobaan_berikutnya(
    api, db_session, fake_calendar
):
    fake_calendar.set_events(event_seharian("e1", "Cuti", "2030-01-02", "2030-01-03"))
    fake_calendar.fail_next("timeout")
    sa = await buat_user(db_session, "SA")
    h = bearer(sa)

    pertama = await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=h)
    kedua = await api.client.post(f"{CAL}/sync", json={"access_token": "t"}, headers=h)

    assert (pertama.status_code, kedua.status_code) == (504, 200)
    assert kedua.json()["data"]["total_events"] == 1


async def test_sync_tanpa_login_401_dan_tanpa_access_token_422(api, db_session, fake_calendar):
    sa = await buat_user(db_session, "SA")

    assert (await api.client.post(f"{CAL}/sync", json={"access_token": "t"})).status_code == 401
    assert (await api.client.post(f"{CAL}/sync", json={}, headers=bearer(sa))).status_code == 422
    assert fake_calendar.access_token_diterima == []


# ---  map: sukses


async def test_map_proyek_event_berjadwal_durasi_dari_waktu_dan_notes_otomatis(api, db_session):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    mulai = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)

    resp = await api.client.post(
        f"{CAL}/map",
        json=_map(
            project_id=proyek.id_project,
            event_start=mulai.isoformat(),
            event_end=(mulai + timedelta(minutes=90)).isoformat(),
            event_description="Bahas BOQ",
        ),
        headers=bearer(sa),
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["id_log"].startswith("LOG-")
    assert data["id_project"] == proyek.id_project
    assert float(data["duration_hours"]) == 1.5
    assert data["raw_notes"] == "[Calendar] Diskusi kebutuhan — Bahas BOQ"
    baris = (
        await db_session.execute(select(ActivityLog).where(ActivityLog.id_log == data["id_log"]))
    ).scalar_one()
    assert baris.sa_id == sa.id
    assert (baris.work_type, baris.project_phase, baris.subtask_category) == (
        "Project",
        "Pre-Implementation",
        "Customer Meeting",
    )
    assert baris.gcal_event_id == "evt-1"
    assert baris.ai_polished_notes is None  # mapping kalender tidak memicu polish AI


@pytest.mark.parametrize(
    ("override", "all_day", "menit", "diharapkan"),
    [
        (None, True, None, 8.0),  # all-day: 8 jam
        ("3.5", True, None, 3.5),  # override pengguna menang atas all-day
        (None, False, 5, 0.25),  # minimum 0,25 jam
        (None, False, 36 * 60, 24.0),  # maksimum 24 jam
        (None, False, None, 1.0),  # tanpa data waktu → fallback 1 jam
    ],
)
async def test_map_aturan_durasi(api, db_session, override, all_day, menit, diharapkan):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    mulai = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    badan = _map(project_id=proyek.id_project, is_all_day=all_day, duration_hours=override)
    if menit is not None:
        badan["event_start"] = mulai.isoformat()
        badan["event_end"] = (mulai + timedelta(minutes=menit)).isoformat()

    resp = await api.client.post(f"{CAL}/map", json=badan, headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert float(resp.json()["data"]["duration_hours"]) == diharapkan
    tersimpan = (
        await db_session.execute(
            select(ActivityLog.duration_hours).where(ActivityLog.gcal_event_id == "evt-1")
        )
    ).scalar_one()
    assert float(tersimpan) == diharapkan


async def test_map_raw_notes_eksplisit_dipakai_apa_adanya(api, db_session):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)

    resp = await api.client.post(
        f"{CAL}/map",
        json=_map(project_id=proyek.id_project, raw_notes="catatan saya", is_all_day=True),
        headers=bearer(sa),
    )

    assert resp.json()["data"]["raw_notes"] == "catatan saya"


async def test_map_non_project_tanpa_proyek_dan_fase(api, db_session):
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(
        f"{CAL}/map",
        json=_map(
            work_type="Non-Project",
            project_phase=None,
            subtask_category="Training",
            is_all_day=True,
        ),
        headers=bearer(sa),
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["work_type"] == "Non-Project"
    assert data["id_project"] is None and data["project_phase"] is None
    baris = (
        await db_session.execute(select(ActivityLog).where(ActivityLog.gcal_event_id == "evt-1"))
    ).scalar_one()
    assert baris.id_project is None and baris.project_phase is None


async def test_event_terpetakan_muncul_di_project_story(api, db_session):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    await api.client.post(
        f"{CAL}/map", json=_map(project_id=proyek.id_project, is_all_day=True), headers=bearer(sa)
    )

    resp = await api.client.get(f"{API}/projects/{proyek.id_project}/story", headers=bearer(sa))

    items = resp.json()["data"]["items"]
    assert [(i["gcal_event_id"], i["raw_notes"]) for i in items] == [
        ("evt-1", "[Calendar] Diskusi kebutuhan")
    ]


# ---  map: validasi & konflik


async def test_map_proyek_tidak_ada_404_tanpa_log(api, db_session):
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(
        f"{CAL}/map", json=_map(project_id="PRJ-TIDAK-ADA"), headers=bearer(sa)
    )

    assert resp.status_code == 404
    assert await _jumlah_log(db_session) == 0


@pytest.mark.parametrize(
    "ubah",
    [
        {"project_id": None},  # Project tanpa proyek
        {"project_phase": None},  # Project tanpa fase
        {"project_phase": "Fase-Ngarang"},
        {"subtask_category": "Training"},  # kategori Non-Project untuk Project
        {"work_type": "Lainnya"},
        {"duration_hours": "0.1"},
        {"duration_hours": "25"},
        {"gcal_event_id": ""},
    ],
)
async def test_map_validasi_request_422(api, db_session, ubah):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    badan = _map(project_id=proyek.id_project)
    badan.update(ubah)
    badan = {k: v for k, v in badan.items() if v is not None}

    resp = await api.client.post(f"{CAL}/map", json=badan, headers=bearer(sa))

    assert resp.status_code == 422, resp.text
    assert await _jumlah_log(db_session) == 0


async def test_map_non_project_dengan_proyek_atau_kategori_proyek_422(api, db_session):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    h = bearer(sa)

    punya_proyek = _map(work_type="Non-Project", project_phase=None, subtask_category="Training")
    punya_proyek["project_id"] = proyek.id_project
    kategori_salah = _map(work_type="Non-Project", project_phase=None)  # Customer Meeting

    assert (await api.client.post(f"{CAL}/map", json=punya_proyek, headers=h)).status_code == 422
    assert (await api.client.post(f"{CAL}/map", json=kategori_salah, headers=h)).status_code == 422


async def test_map_event_sama_dua_kali_409_menyebut_nama_proyek_dan_hanya_satu_log(api, db_session):
    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    sa2 = await buat_user(db_session, "SA")
    p1 = await buat_proyek(db_session, sales, assigned_sa=sa, project_name="Proyek Pertama")
    p2 = await buat_proyek(db_session, sales, assigned_sa=sa2, project_name="Proyek Kedua")

    pertama = await api.client.post(
        f"{CAL}/map", json=_map(project_id=p1.id_project, is_all_day=True), headers=bearer(sa)
    )
    kedua = await api.client.post(
        f"{CAL}/map", json=_map(project_id=p2.id_project, is_all_day=True), headers=bearer(sa2)
    )

    assert pertama.status_code == 201
    assert kedua.status_code == 409
    assert "Proyek Pertama" in kedua.json()["message"]
    assert await _jumlah_log(db_session, gcal_event_id="evt-1") == 1


async def test_map_event_non_project_duplikat_409_tanpa_menyebut_proyek_none(api, db_session):
    """Regresi: pesan konflik untuk event Non-Project tidak boleh berbunyi '...proyek None'."""
    sa = await buat_user(db_session, "SA")
    badan = _map(
        work_type="Non-Project", project_phase=None, subtask_category="Training", is_all_day=True
    )

    pertama = await api.client.post(f"{CAL}/map", json=badan, headers=bearer(sa))
    kedua = await api.client.post(f"{CAL}/map", json=badan, headers=bearer(sa))

    assert (pertama.status_code, kedua.status_code) == (201, 409)
    assert "None" not in kedua.json()["message"]
    assert "Non-Project" in kedua.json()["message"]


async def test_map_tanpa_login_401(api):
    resp = await api.client.post(f"{CAL}/map", json=_map(project_id="PRJ-X"))

    assert resp.status_code == 401
