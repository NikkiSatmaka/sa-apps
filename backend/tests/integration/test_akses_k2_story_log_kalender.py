"""
Akses Project Story, ringkasan AI, activity log, dan pemetaan kalender (tiket #89, spec #87).

Matriks peran × aksi di Postgres nyata:
- STORY (GET story, POST summarize): Lead_SA, Admin, SA ditugaskan, collaborator viewer+contributor.
  Sales PIC TIDAK (spec Flow 3 + ADR 0002); pihak luar ditolak.
- TULIS (POST /activity-logs, POST /calendar/map): Lead_SA, Admin, SA ditugaskan, contributor.
  Viewer, Sales PIC, SA tak ditugaskan, dan pihak luar ditolak.

Penolakan = 403 pesan generik TANPA efek samping: tidak ada log tertulis, subtask tidak maju,
tidak ada panggilan LLM/Drive/Gmail. `komit_sesi_request` membuat penulisan-lalu-403 terdeteksi.
"""

import pytest
from sqlalchemy import func, select

from app.models import ActivityLog, Subtask
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_log, bangun_subtask
from tests.integration.support_akses import ID_PROYEK

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

PESAN_403 = "Anda tidak memiliki akses ke proyek ini."
HASIL_POLISH = {
    "discussion_points": ["Bahas arsitektur"],
    "action_items": [{"description": "Kirim BOQ", "pic": "Budi"}],
}

AKTOR_STORY_BERHAK = ["lead", "admin", "sa", "kolab_viewer", "kolab_contrib"]
AKTOR_STORY_DITOLAK = ["sales_pic", "kolab_lain", "sales_luar", "sa_luar"]
AKTOR_TULIS_BERHAK = ["lead", "admin", "sa", "kolab_contrib"]
AKTOR_TULIS_DITOLAK = ["kolab_viewer", "sales_pic", "kolab_lain", "sales_luar", "sa_luar"]


def _body_log(**o) -> dict:
    dasar = {
        "id_project": ID_PROYEK,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1.5",
        "raw_notes": "diskusi arsitektur",
    }
    dasar.update(o)
    return dasar


def _body_kalender(**o) -> dict:
    dasar = {
        "gcal_event_id": "evt-akses",
        "work_type": "Project",
        "project_id": ID_PROYEK,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Diskusi kebutuhan",
        "is_all_day": True,
    }
    dasar.update(o)
    return dasar


async def _jumlah_log(db) -> int:
    return (await db.execute(select(func.count()).select_from(ActivityLog))).scalar_one()


async def _tambah_log(db, sa_id) -> None:
    db.add(bangun_log(sa_id, ID_PROYEK))
    await db.commit()


def _tak_ada_efek_luar(fake_llm, fake_drive, fake_gmail) -> None:
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


# ---------------------------------------------------------------------------- Story + ringkasan


@pytest.mark.parametrize("aktor", AKTOR_STORY_BERHAK)
async def test_story_pihak_berhak_200(api, db_session, skenario_akses, aktor):
    await _tambah_log(db_session, skenario_akses.aktor["sa"].id)

    resp = await api.client.get(
        f"/api/v1/projects/{ID_PROYEK}/story", headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1


@pytest.mark.parametrize("aktor", AKTOR_STORY_DITOLAK)
async def test_story_ditolak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    await _tambah_log(db_session, skenario_akses.aktor["sa"].id)

    resp = await api.client.get(
        f"/api/v1/projects/{ID_PROYEK}/story", headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    _tak_ada_efek_luar(fake_llm, fake_drive, fake_gmail)


@pytest.mark.parametrize("aktor", AKTOR_STORY_BERHAK)
async def test_summarize_pihak_berhak_200_memanggil_llm(
    api, db_session, skenario_akses, fake_llm, aktor
):
    await _tambah_log(db_session, skenario_akses.aktor["sa"].id)
    fake_llm.sukses("complete_text", "Ringkasan proyek berjalan baik.")

    resp = await api.client.post(
        f"/api/v1/projects/{ID_PROYEK}/summarize", headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["summary"] == "Ringkasan proyek berjalan baik."
    assert fake_llm.jumlah("complete_text") == 1


@pytest.mark.parametrize("aktor", AKTOR_STORY_DITOLAK)
async def test_summarize_ditolak_403_tanpa_panggilan_llm(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    await _tambah_log(db_session, skenario_akses.aktor["sa"].id)

    resp = await api.client.post(
        f"/api/v1/projects/{ID_PROYEK}/summarize", headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    _tak_ada_efek_luar(fake_llm, fake_drive, fake_gmail)


@pytest.mark.parametrize("rute", ["story", "summarize"])
async def test_story_dan_summarize_proyek_tak_ada_tetap_404(api, skenario_akses, rute):
    """Kontrak lama dipertahankan: proyek tidak ada → 404 (bukan 403)."""
    metode = api.client.get if rute == "story" else api.client.post
    resp = await metode(
        f"/api/v1/projects/PRJ-TIDAK-ADA/{rute}", headers=skenario_akses.header("sa_luar")
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------- POST /activity-logs


@pytest.mark.parametrize("aktor", AKTOR_TULIS_BERHAK)
async def test_buat_log_pihak_berhak_201(api, db_session, skenario_akses, fake_llm, aktor):
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(
        "/api/v1/activity-logs", json=_body_log(), headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 201, resp.text
    assert await _jumlah_log(db_session) == 1
    assert fake_llm.jumlah("structure_text") == 1


@pytest.mark.parametrize("aktor", AKTOR_TULIS_DITOLAK)
async def test_buat_log_ditolak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    resp = await api.client.post(
        "/api/v1/activity-logs", json=_body_log(), headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403  # bukan 500: 403 tidak boleh tertelan try/except Exception
    assert resp.json()["message"] == PESAN_403
    assert await _jumlah_log(db_session) == 0
    _tak_ada_efek_luar(fake_llm, fake_drive, fake_gmail)


@pytest.mark.parametrize("aktor", AKTOR_TULIS_DITOLAK)
async def test_log_ditolak_tidak_memajukan_subtask(
    api, db_session, skenario_akses, fake_llm, aktor
):
    subtask = bangun_subtask(ID_PROYEK)
    db_session.add(subtask)
    await db_session.commit()

    resp = await api.client.post(
        "/api/v1/activity-logs",
        json=_body_log(id_subtask=subtask.id_subtask),
        headers=skenario_akses.header(aktor),
    )

    assert resp.status_code == 403
    baris = (
        await db_session.execute(select(Subtask).where(Subtask.id_subtask == subtask.id_subtask))
    ).scalar_one()
    await db_session.refresh(baris)
    assert baris.status == "open"
    assert await _jumlah_log(db_session) == 0


@pytest.mark.parametrize("aktor", AKTOR_TULIS_BERHAK)
async def test_log_pihak_berhak_memajukan_subtask(api, db_session, skenario_akses, fake_llm, aktor):
    fake_llm.sukses("structure_text", HASIL_POLISH)
    subtask = bangun_subtask(ID_PROYEK)
    db_session.add(subtask)
    await db_session.commit()

    resp = await api.client.post(
        "/api/v1/activity-logs",
        json=_body_log(id_subtask=subtask.id_subtask),
        headers=skenario_akses.header(aktor),
    )

    assert resp.status_code == 201, resp.text
    baris = (
        await db_session.execute(select(Subtask).where(Subtask.id_subtask == subtask.id_subtask))
    ).scalar_one()
    await db_session.refresh(baris)
    assert baris.status == "in_progress"


@pytest.mark.parametrize("aktor", ["kolab_viewer", "sales_pic", "sa_luar", "sa"])
async def test_log_non_project_tidak_terkait_proyek_tetap_201(
    api, skenario_akses, fake_llm, aktor
):
    """Non-Project tidak punya proyek → tidak boleh diblok cek akses proyek."""
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(
        "/api/v1/activity-logs",
        json={
            "work_type": "Non-Project",
            "subtask_category": "Training",
            "duration_hours": "1",
            "raw_notes": "belajar",
        },
        headers=skenario_akses.header(aktor),
    )

    assert resp.status_code == 201, resp.text


async def test_log_proyek_tak_ada_tetap_422(api, skenario_akses, fake_llm):
    resp = await api.client.post(
        "/api/v1/activity-logs",
        json=_body_log(id_project="PRJ-TIDAK-ADA"),
        headers=skenario_akses.header("sa_luar"),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------- POST /calendar/map


@pytest.mark.parametrize("aktor", AKTOR_TULIS_BERHAK)
async def test_map_kalender_pihak_berhak_201(api, db_session, skenario_akses, aktor):
    resp = await api.client.post(
        "/api/v1/calendar/map", json=_body_kalender(), headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 201, resp.text
    assert await _jumlah_log(db_session) == 1


@pytest.mark.parametrize("aktor", AKTOR_TULIS_DITOLAK)
async def test_map_kalender_ditolak_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    resp = await api.client.post(
        "/api/v1/calendar/map", json=_body_kalender(), headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    assert await _jumlah_log(db_session) == 0
    _tak_ada_efek_luar(fake_llm, fake_drive, fake_gmail)


@pytest.mark.parametrize("aktor", ["kolab_viewer", "sales_pic", "sa_luar"])
async def test_map_kalender_non_project_tetap_201(api, skenario_akses, aktor):
    resp = await api.client.post(
        "/api/v1/calendar/map",
        json=_body_kalender(
            work_type="Non-Project",
            project_id=None,
            project_phase=None,
            subtask_category="Training",
        ),
        headers=skenario_akses.header(aktor),
    )
    assert resp.status_code == 201, resp.text


async def test_map_kalender_proyek_tak_ada_tetap_404(api, skenario_akses):
    resp = await api.client.post(
        "/api/v1/calendar/map",
        json=_body_kalender(project_id="PRJ-TIDAK-ADA"),
        headers=skenario_akses.header("sa_luar"),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------- polish


async def test_polish_ulang_kepemilikan_log_tetap_ditegakkan(
    api, db_session, skenario_akses, fake_llm
):
    """Kepemilikan log tetap: penulis yang masih berhak tulis bisa polish ulang log miliknya;
    orang lain (walau Lead_SA) → 404.

    DIUBAH di #92: versi lama memakai penulis `kolab_viewer` dan mengunci "viewer masih bisa
    polish ulang" (akses terbuka). Kini penulis harus masih berhak TULIS; penolakan viewer diuji
    di `test_akses_k5_penyelarasan_akhir.py`. Assertion kepemilikan (orang lain → 404) tidak berubah.
    """
    penulis = skenario_akses.aktor["kolab_contrib"]
    log = bangun_log(penulis.id, ID_PROYEK, ai_polished_notes=None)
    db_session.add(log)
    await db_session.commit()
    fake_llm.sukses("structure_text", HASIL_POLISH)

    milik = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish",
        headers=skenario_akses.header("kolab_contrib"),
    )
    orang_lain = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish", headers=skenario_akses.header("lead")
    )

    assert milik.status_code == 200, milik.text
    assert orang_lain.status_code == 404
