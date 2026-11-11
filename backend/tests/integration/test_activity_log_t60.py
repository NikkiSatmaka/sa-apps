"""
Integrasi activity log terhadap Postgres nyata + fake LLM (tiket #60, spec #49; ADR 0008).

Mencakup pembuatan log (Project/Non-Project), polish AI (sukses, gagal → needs_repolish, polish
ulang), subtask maju `open → in_progress`, project story (filter, paginasi), dan ringkasan proyek
dengan fallback non-LLM. Lingkup `llm_provider`/`gemini_adapter`/guardrails ada di tiket #62.
Pasangan unit: `tests/test_activity_logger_t60.py`.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import ActivityLog
from tests.integration.helpers_t60 import (
    API,
    bearer,
    buat_kolaborator,
    buat_proyek,
    buat_user,
)
from tests.integration.model_helpers import bangun_log, bangun_subtask

LOGS = f"{API}/activity-logs"
HASIL_POLISH = {
    "discussion_points": ["Bahas arsitektur"],
    "action_items": [{"description": "Kirim BOQ", "pic": "Budi"}],
}


def _badan(id_project: str, **o) -> dict:
    dasar = {
        "id_project": id_project,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1.5",
        "raw_notes": "diskusi arsitektur, Budi kirim BOQ",
    }
    dasar.update(o)
    return dasar


async def _siap(db, **o):
    sales = await buat_user(db, "Sales")
    sa = await buat_user(db, "SA")
    proyek = await buat_proyek(db, sales, assigned_sa=sa, **o)
    return sales, sa, proyek


async def _jumlah_log(db) -> int:
    return (await db.execute(select(func.count()).select_from(ActivityLog))).scalar_one()


async def _tambah_log(db, sa, id_project, *, jam_lalu: int, **o) -> ActivityLog:
    dasar = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
    log = bangun_log(sa.id, id_project, created_at=dasar - timedelta(hours=jam_lalu), **o)
    db.add(log)
    await db.commit()
    return log


# ---  buat log & polish


async def test_buat_log_polish_sukses_tersimpan_terstruktur(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(LOGS, json=_badan(proyek.id_project), headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["needs_repolish"] is False
    assert data["ai_polished_notes"]["discussion_points"] == ["Bahas arsitektur"]
    assert data["ai_polished_notes"]["action_items"] == [
        {"description": "Kirim BOQ", "pic": "Budi"}
    ]
    assert "di-polish oleh AI" in resp.json()["message"]
    assert data["sa_id"] == str(sa.id)
    assert data["id_log"].startswith("LOG-")
    baris = (
        await db_session.execute(select(ActivityLog).where(ActivityLog.id_log == data["id_log"]))
    ).scalar_one()
    assert baris.ai_polished_notes == data["ai_polished_notes"]
    assert baris.raw_notes == "diskusi arsitektur, Budi kirim BOQ"
    assert float(baris.duration_hours) == 1.5
    assert fake_llm.jumlah("structure_text") == 1
    assert "arsitektur" in fake_llm.panggilan[0].argumen["text"]


@pytest.mark.parametrize(
    "siapkan",
    [
        lambda f: f.error("structure_text", "timeout"),
        lambda f: f.malformed("structure_text"),
        lambda f: f.terpotong("structure_text"),
        lambda f: f.sukses("structure_text", {"hasil": "bukan skema polish"}),
        lambda f: f.sukses("structure_text", ["bukan", "objek"]),
        lambda f: f.program("structure_text", RuntimeError("adapter meledak")),
    ],
    ids=["error", "malformed", "terpotong", "skema-salah", "bukan-objek", "exception"],
)
async def test_polish_gagal_log_tetap_tersimpan_needs_repolish(api, db_session, fake_llm, siapkan):
    _, sa, proyek = await _siap(db_session)
    siapkan(fake_llm)

    resp = await api.client.post(LOGS, json=_badan(proyek.id_project), headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["ai_polished_notes"] is None
    assert data["needs_repolish"] is True
    assert "Polish Ulang" in resp.json()["message"]
    assert await _jumlah_log(db_session) == 1


async def test_polish_ulang_setelah_gagal_menjadi_berhasil(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)
    fake_llm.error("structure_text", "timeout")
    fake_llm.sukses("structure_text", HASIL_POLISH)
    h = bearer(sa)
    dibuat = (await api.client.post(LOGS, json=_badan(proyek.id_project), headers=h)).json()["data"]
    assert dibuat["needs_repolish"] is True

    resp = await api.client.post(f"{LOGS}/{dibuat['id_log']}/polish", headers=h)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["needs_repolish"] is False
    assert data["ai_polished_notes"]["discussion_points"] == ["Bahas arsitektur"]
    assert "berhasil" in resp.json()["message"]
    assert fake_llm.jumlah("structure_text") == 2
    # Polish ulang memakai raw_notes asli log.
    assert fake_llm.panggilan[1].argumen["text"] == fake_llm.panggilan[0].argumen["text"]
    baris = (
        await db_session.execute(select(ActivityLog).where(ActivityLog.id_log == dibuat["id_log"]))
    ).scalar_one()
    await db_session.refresh(baris)
    assert baris.ai_polished_notes is not None


async def test_polish_ulang_masih_gagal_tetap_needs_repolish_dengan_pesan(
    api, db_session, fake_llm
):
    _, sa, proyek = await _siap(db_session)
    fake_llm.error("structure_text", "timeout", tetap=True)
    h = bearer(sa)
    dibuat = (await api.client.post(LOGS, json=_badan(proyek.id_project), headers=h)).json()["data"]

    resp = await api.client.post(f"{LOGS}/{dibuat['id_log']}/polish", headers=h)

    assert resp.status_code == 200
    assert resp.json()["data"]["needs_repolish"] is True
    assert "masih gagal" in resp.json()["message"]


async def test_polish_ulang_log_milik_orang_lain_atau_tidak_ada_404(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)
    lain = await buat_user(db_session, "SA")
    fake_llm.error("structure_text", "timeout")
    dibuat = (
        await api.client.post(LOGS, json=_badan(proyek.id_project), headers=bearer(sa))
    ).json()["data"]
    jumlah_panggilan = fake_llm.jumlah()

    orang_lain = await api.client.post(f"{LOGS}/{dibuat['id_log']}/polish", headers=bearer(lain))
    tak_ada = await api.client.post(f"{LOGS}/LOG-TIDAK-ADA/polish", headers=bearer(sa))

    assert orang_lain.status_code == 404
    assert "akses" in orang_lain.json()["message"].lower()
    assert tak_ada.status_code == 404
    assert fake_llm.jumlah() == jumlah_panggilan  # LLM tidak dipanggil untuk permintaan ditolak


async def test_buat_log_non_project_tanpa_proyek(api, db_session, fake_llm):
    sa = await buat_user(db_session, "SA")
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(
        LOGS,
        json={
            "work_type": "Non-Project",
            "subtask_category": "Training",
            "duration_hours": "2",
            "raw_notes": "ikut pelatihan",
        },
        headers=bearer(sa),
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert (data["work_type"], data["id_project"], data["project_phase"]) == (
        "Non-Project",
        None,
        None,
    )


async def test_buat_log_proyek_tidak_ada_422_dan_tidak_memanggil_llm(api, db_session, fake_llm):
    sa = await buat_user(db_session, "SA")

    resp = await api.client.post(LOGS, json=_badan("PRJ-TIDAK-ADA"), headers=bearer(sa))

    assert resp.status_code == 422
    assert "tidak ditemukan" in resp.json()["message"]
    assert fake_llm.jumlah() == 0
    assert await _jumlah_log(db_session) == 0


@pytest.mark.parametrize(
    "ubah",
    [
        {"duration_hours": "0.1"},
        {"duration_hours": "0.30"},  # bukan kelipatan 0,25
        {"duration_hours": "24.25"},
        {"raw_notes": "   "},
        {"raw_notes": "x" * 5001},
        {"subtask_category": "Training"},  # kategori Non-Project untuk Project
        {"project_phase": "Fase-Ngarang"},
        {"work_type": "Lainnya"},
        {"gcal_event_id": "g" * 256},
    ],
)
async def test_buat_log_validasi_422(api, db_session, fake_llm, ubah):
    _, sa, proyek = await _siap(db_session)

    resp = await api.client.post(
        LOGS, json={**_badan(proyek.id_project), **ubah}, headers=bearer(sa)
    )

    assert resp.status_code == 422, resp.text
    assert await _jumlah_log(db_session) == 0
    assert fake_llm.jumlah() == 0


async def test_buat_log_tanpa_login_401(api):
    assert (await api.client.post(LOGS, json=_badan("PRJ-X"))).status_code == 401


async def test_log_dengan_gcal_event_id_duplikat_ditolak_constraint_db(api, db_session, fake_llm):
    """`gcal_event_id` unik (partial unique index): log kedua dengan event sama gagal tersimpan."""
    _, sa, proyek = await _siap(db_session)
    fake_llm.error("structure_text", "timeout", tetap=True)
    badan = _badan(proyek.id_project, gcal_event_id="evt-dup")

    pertama = await api.client.post(LOGS, json=badan, headers=bearer(sa))
    kedua = await api.client.post(LOGS, json=badan, headers=bearer(sa))

    assert pertama.status_code == 201
    assert kedua.status_code == 500
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(ActivityLog)
            .where(ActivityLog.gcal_event_id == "evt-dup")
        )
    ).scalar_one() == 1


# ---  subtask (ADR 0008)


async def test_log_dengan_subtask_open_memajukan_ke_in_progress(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)
    st = bangun_subtask(proyek.id_project)
    db_session.add(st)
    await db_session.commit()
    fake_llm.error("structure_text", "timeout")

    resp = await api.client.post(
        LOGS, json=_badan(proyek.id_project, id_subtask=st.id_subtask), headers=bearer(sa)
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["id_subtask"] == st.id_subtask
    await db_session.refresh(st)
    assert st.status == "in_progress"


@pytest.mark.parametrize("status_awal", ["in_progress", "done"])
async def test_log_dengan_subtask_status_lain_tidak_diubah(api, db_session, fake_llm, status_awal):
    _, sa, proyek = await _siap(db_session)
    st = bangun_subtask(proyek.id_project, status=status_awal)
    db_session.add(st)
    await db_session.commit()
    fake_llm.error("structure_text", "timeout")

    resp = await api.client.post(
        LOGS, json=_badan(proyek.id_project, id_subtask=st.id_subtask), headers=bearer(sa)
    )

    assert resp.status_code == 201
    await db_session.refresh(st)
    assert st.status == status_awal


async def test_log_dengan_subtask_proyek_lain_ditolak_422_tanpa_log_dan_status_utuh(
    api, db_session, fake_llm
):
    sales, sa, proyek = await _siap(db_session)
    proyek_lain = await buat_proyek(db_session, sales, assigned_sa=sa)
    st = bangun_subtask(proyek_lain.id_project)
    db_session.add(st)
    await db_session.commit()

    resp = await api.client.post(
        LOGS, json=_badan(proyek.id_project, id_subtask=st.id_subtask), headers=bearer(sa)
    )

    assert resp.status_code == 422
    assert "bukan milik proyek" in resp.json()["message"]
    assert await _jumlah_log(db_session) == 0
    await db_session.refresh(st)
    assert st.status == "open"


async def test_log_dengan_subtask_tidak_ada_422(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)

    resp = await api.client.post(
        LOGS, json=_badan(proyek.id_project, id_subtask="ST-TIDAK-ADA"), headers=bearer(sa)
    )

    assert resp.status_code == 422
    assert await _jumlah_log(db_session) == 0


async def test_subtask_diabaikan_untuk_non_project(api, db_session, fake_llm):
    sales, sa, proyek = await _siap(db_session)
    st = bangun_subtask(proyek.id_project)
    db_session.add(st)
    await db_session.commit()
    fake_llm.error("structure_text", "timeout")

    resp = await api.client.post(
        LOGS,
        json={
            "work_type": "Non-Project",
            "subtask_category": "Training",
            "duration_hours": "1",
            "raw_notes": "belajar",
            "id_subtask": st.id_subtask,
        },
        headers=bearer(sa),
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["id_subtask"] is None
    await db_session.refresh(st)
    assert st.status == "open"


# ---  project story


async def test_story_urut_terbaru_dulu_dan_penanda_needs_repolish(api, db_session):
    _, sa, proyek = await _siap(db_session)
    lama = await _tambah_log(db_session, sa, proyek.id_project, jam_lalu=5)
    baru = await _tambah_log(
        db_session, sa, proyek.id_project, jam_lalu=1, ai_polished_notes={"discussion_points": []}
    )

    resp = await api.client.get(f"{API}/projects/{proyek.id_project}/story", headers=bearer(sa))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [i["id_log"] for i in data["items"]] == [baru.id_log, lama.id_log]
    assert [i["needs_repolish"] for i in data["items"]] == [False, True]
    assert (data["total"], data["page"], data["page_size"], data["total_pages"]) == (2, 1, 20, 1)


async def test_story_kosong_total_pages_satu(api, db_session):
    _, sa, proyek = await _siap(db_session)

    data = (
        await api.client.get(f"{API}/projects/{proyek.id_project}/story", headers=bearer(sa))
    ).json()["data"]

    assert (data["items"], data["total"], data["total_pages"]) == ([], 0, 1)


async def test_story_paginasi_25_log_dua_halaman(api, db_session):
    _, sa, proyek = await _siap(db_session)
    for i in range(25):
        await _tambah_log(db_session, sa, proyek.id_project, jam_lalu=i)
    url = f"{API}/projects/{proyek.id_project}/story"
    h = bearer(sa)

    h1 = (await api.client.get(url, params={"page": 1}, headers=h)).json()["data"]
    h2 = (await api.client.get(url, params={"page": 2}, headers=h)).json()["data"]
    kecil = (await api.client.get(url, params={"page_size": 10, "page": 3}, headers=h)).json()[
        "data"
    ]

    assert (len(h1["items"]), len(h2["items"])) == (20, 5)
    assert h1["total_pages"] == 2
    assert not {i["id_log"] for i in h1["items"]} & {i["id_log"] for i in h2["items"]}
    assert (len(kecil["items"]), kecil["total_pages"]) == (5, 3)
    assert (await api.client.get(url, params={"page_size": 21}, headers=h)).status_code == 422
    assert (await api.client.get(url, params={"page": 0}, headers=h)).status_code == 422


async def test_story_filter_kategori_dan_rentang_tanggal(api, db_session):
    _, sa, proyek = await _siap(db_session)
    a = await _tambah_log(
        db_session, sa, proyek.id_project, jam_lalu=48, subtask_category="Assessment"
    )
    b = await _tambah_log(
        db_session, sa, proyek.id_project, jam_lalu=24, subtask_category="Customer Meeting"
    )
    c = await _tambah_log(
        db_session, sa, proyek.id_project, jam_lalu=1, subtask_category="Assessment"
    )
    url = f"{API}/projects/{proyek.id_project}/story"
    h = bearer(sa)
    patokan = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)

    kategori = (await api.client.get(url, params={"category": "Assessment"}, headers=h)).json()[
        "data"
    ]
    rentang = (
        await api.client.get(
            url,
            params={
                "date_from": (patokan - timedelta(hours=30)).isoformat(),
                "date_to": (patokan - timedelta(hours=12)).isoformat(),
            },
            headers=h,
        )
    ).json()["data"]
    gabungan = (
        await api.client.get(
            url,
            params={
                "category": "Assessment",
                "date_from": (patokan - timedelta(hours=30)).isoformat(),
            },
            headers=h,
        )
    ).json()["data"]

    assert [i["id_log"] for i in kategori["items"]] == [c.id_log, a.id_log]
    assert [i["id_log"] for i in rentang["items"]] == [b.id_log]
    assert [i["id_log"] for i in gabungan["items"]] == [c.id_log]


async def test_story_hanya_log_proyek_itu_dan_proyek_tidak_ada_404(api, db_session):
    sales, sa, proyek = await _siap(db_session)
    lain = await buat_proyek(db_session, sales, assigned_sa=sa)
    await _tambah_log(db_session, sa, lain.id_project, jam_lalu=1)
    await _tambah_log(
        db_session,
        sa,
        None,
        jam_lalu=1,
        work_type="Non-Project",
        project_phase=None,
        subtask_category="Training",
    )
    h = bearer(sa)

    kosong = (await api.client.get(f"{API}/projects/{proyek.id_project}/story", headers=h)).json()
    tak_ada = await api.client.get(f"{API}/projects/PRJ-TIDAK-ADA/story", headers=h)

    assert kosong["data"]["total"] == 0
    assert tak_ada.status_code == 404


# Diubah di tiket #89 (spec #87): "sales_pic" DIKELUARKAN dari pembaca yang berwenang. Test ini
# dulu mengunci Story terbuka bagi Sales PIC; kebijakan baru (spec Flow 3 + ADR 0002) menutupnya.
# Penolakan Sales PIC dibuktikan di tests/integration/test_akses_k2_story_log_kalender.py.
@pytest.mark.parametrize("pembaca", ["assigned_sa", "lead", "admin", "viewer"])
async def test_story_dapat_dibaca_pihak_berwenang_termasuk_backup_sa(api, db_session, pembaca):
    """ADR 0002: Backup SA = kolaborator viewer, boleh baca Project Story."""
    sales, sa, proyek = await _siap(db_session)
    await _tambah_log(db_session, sa, proyek.id_project, jam_lalu=1)
    viewer = await buat_user(db_session, "SA")
    await buat_kolaborator(db_session, proyek, viewer, sa, "viewer")
    akses = {
        "assigned_sa": sa,
        "lead": await buat_user(db_session, "Lead_SA"),
        "admin": await buat_user(db_session, "Admin"),
        "viewer": viewer,
    }[pembaca]

    resp = await api.client.get(f"{API}/projects/{proyek.id_project}/story", headers=bearer(akses))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1


async def test_story_tanpa_login_401(api):
    assert (await api.client.get(f"{API}/projects/PRJ-X/story")).status_code == 401


# ---  summarize


async def test_summarize_llm_sukses_memakai_teks_llm_dan_mengirim_data_aktivitas(
    api, db_session, fake_llm
):
    _, sa, proyek = await _siap(db_session)
    await _tambah_log(
        db_session,
        sa,
        proyek.id_project,
        jam_lalu=2,
        duration_hours="2.00",
        raw_notes="rapat desain",
        subtask_category="Customer Meeting",
    )
    await _tambah_log(
        db_session,
        sa,
        proyek.id_project,
        jam_lalu=1,
        duration_hours="1.50",
        raw_notes="susun BOQ",
        subtask_category="Commercial Document",
    )
    fake_llm.sukses("complete_text", "Proyek berjalan baik; BOQ perlu ditindaklanjuti.")

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/summarize", headers=bearer(sa)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary"] == "Proyek berjalan baik; BOQ perlu ditindaklanjuti."
    assert (data["total_activities"], data["total_hours"]) == (2, 3.5)
    prompt = fake_llm.panggilan_jenis("complete_text")[0].argumen["prompt"]
    assert "rapat desain" in prompt and "susun BOQ" in prompt
    assert "[Customer Meeting] 2.0h" in prompt


@pytest.mark.parametrize(
    "siapkan",
    [
        lambda f: f.error("complete_text", "timeout"),
        lambda f: f.sukses("complete_text", "   "),
        lambda f: f.terpotong("complete_text", ""),
    ],
    ids=["llm-error", "ringkasan-kosong", "terpotong-kosong"],
)
async def test_summarize_fallback_non_llm_ringkasan_deterministik(
    api, db_session, fake_llm, siapkan
):
    _, sa, proyek = await _siap(db_session)
    await _tambah_log(
        db_session,
        sa,
        proyek.id_project,
        jam_lalu=50,
        duration_hours="1.00",
        subtask_category="Assessment",
    )
    await _tambah_log(
        db_session,
        sa,
        proyek.id_project,
        jam_lalu=2,
        duration_hours="2.00",
        subtask_category="Customer Meeting",
    )
    await _tambah_log(
        db_session,
        sa,
        proyek.id_project,
        jam_lalu=1,
        duration_hours="1.50",
        subtask_category="Customer Meeting",
    )
    siapkan(fake_llm)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/summarize", headers=bearer(sa)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary"] == (
        "Total 3 aktivitas dengan 4.5 jam kerja. "
        "Breakdown: Customer Meeting: 3.5 jam, Assessment: 1.0 jam. "
        "Aktivitas terakhir: 01 June 2030."
    )
    assert (data["total_activities"], data["total_hours"]) == (3, 4.5)


async def test_summarize_llm_exception_500_tanpa_membocorkan_detail(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)
    await _tambah_log(db_session, sa, proyek.id_project, jam_lalu=1)
    fake_llm.program("complete_text", RuntimeError("kunci-rahasia-bocor"))

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/summarize", headers=bearer(sa)
    )

    assert resp.status_code == 500
    assert "kunci-rahasia-bocor" not in resp.text


async def test_summarize_tanpa_log_404_dan_tidak_memanggil_llm(api, db_session, fake_llm):
    _, sa, proyek = await _siap(db_session)

    resp = await api.client.post(
        f"{API}/projects/{proyek.id_project}/summarize", headers=bearer(sa)
    )

    assert resp.status_code == 404
    assert "minimal 1 aktivitas" in resp.json()["message"]
    assert fake_llm.jumlah() == 0


async def test_summarize_proyek_tidak_ada_404_dan_tanpa_login_401(api, db_session):
    sa = await buat_user(db_session, "SA")

    assert (
        await api.client.post(f"{API}/projects/PRJ-TIDAK-ADA/summarize", headers=bearer(sa))
    ).status_code == 404
    assert (await api.client.post(f"{API}/projects/PRJ-X/summarize")).status_code == 401


# ---  ActivityLogger.map_event_to_project


async def test_service_map_event_to_project_membuat_log_dengan_event_id(db_session, fake_llm):
    from app.services.activity_logger import ActivityLogger

    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    fake_llm.error("structure_text", "timeout")

    log = await ActivityLogger(db_session).map_event_to_project(
        sa_id=sa.id,
        gcal_event_id="evt-svc",
        id_project=proyek.id_project,
        duration_hours=1,
        subtask_category="Assessment",
    )

    assert (log.gcal_event_id, log.id_project, log.sa_id) == ("evt-svc", proyek.id_project, sa.id)
    assert log.raw_notes == "[Mapped dari Google Calendar event]"
    assert log.project_phase == "Pre-Implementation"  # regresi: dulu melanggar CHECK Project+fase


async def test_service_map_event_to_project_event_sudah_dipetakan_value_error(db_session, fake_llm):
    from app.services.activity_logger import ActivityLogger

    sales = await buat_user(db_session, "Sales")
    sa = await buat_user(db_session, "SA")
    proyek = await buat_proyek(db_session, sales, assigned_sa=sa)
    fake_llm.error("structure_text", "timeout", tetap=True)
    layanan = ActivityLogger(db_session)
    kwargs = dict(
        sa_id=sa.id,
        gcal_event_id="evt-dup",
        id_project=proyek.id_project,
        duration_hours=1,
        subtask_category="Assessment",
        raw_notes="catatan",
    )
    await layanan.map_event_to_project(**kwargs)

    with pytest.raises(ValueError, match="sudah dipetakan"):
        await layanan.map_event_to_project(**kwargs)

    assert await _jumlah_log(db_session) == 1


async def test_service_story_membatasi_page_size_maksimal_20(db_session):
    from app.services.activity_logger import ActivityLogger

    sales, sa, proyek = await _siap(db_session)
    for i in range(22):
        await _tambah_log(db_session, sa, proyek.id_project, jam_lalu=i)

    hasil = await ActivityLogger(db_session).get_project_story(proyek.id_project, page_size=500)

    assert (hasil["page_size"], len(hasil["items"]), hasil["total_pages"]) == (20, 20, 2)
