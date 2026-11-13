"""
Contoh pemakaian fake boundary (tiket B3) lewat API nyata + Postgres sementara: satu skenario
sukses dan satu gagal per fake. Test lain dapat menyalin pola ini.
"""

import json
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Project, User
from tests.integration.fakes.calendar import event_berjadwal
from tests.integration.kualifikasi_support import id_product_demo
from tests.test_projects_questionnaire_api import jawaban_kuat

PROYEK = "/api/v1/projects"


def _form(product_pic: str | None = None) -> dict:
    return {
        "product_pic": product_pic,
        "project_name": "Proyek Fake",
        "customer_name": "PT Fake",
        "target_submit": str(date.today() + timedelta(days=30)),
        "estimasi_nilai": "500000000",
        "qualification_answers": json.dumps(jawaban_kuat()),
    }


async def _proyek_pending(api) -> tuple[str, dict, dict]:
    lead = await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    resp = await api.client.post(PROYEK, data=_form(await id_product_demo(api)), headers=sales)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id_project"], lead, sales


async def _tugaskan_sa(api, id_project: str, db_session, *, status: str = "Assigned") -> User:
    """
    Tugaskan SA demo langsung lewat DB.

    Endpoint `assign` memicu background task yang memakai sesi sendiri; pada harness satu koneksi
    (B2) sesi request yang masih terbuka dapat me-rollback hasil task tersebut, jadi test yang
    perlu hasil provisioning memakai jalur `provision-folder` setelah proyek ditugaskan di sini.
    """
    await api.login_demo("SA")
    sa = (
        await db_session.execute(select(User).where(User.email == "demo-sa@portal-sa.local"))
    ).scalar_one()
    proyek = (
        await db_session.execute(select(Project).where(Project.id_project == id_project))
    ).scalar_one()
    proyek.assigned_sa = sa.id
    proyek.status = status
    await db_session.commit()
    return sa


# ----------------------------------------------------------------------------- LLM


LOG_NON_PROYEK = {
    "work_type": "Non-Project",
    "subtask_category": "Training",
    "duration_hours": "1.5",
    "raw_notes": "bahas rencana pelatihan, minta Budi siapkan materi",
}


async def test_llm_fake_sukses_catatan_dipoles_tersimpan(api, db_session, fake_llm):
    fake_llm.sukses(
        "structure_text",
        {
            "discussion_points": ["Rencana pelatihan"],
            "action_items": [{"description": "Siapkan materi", "pic": "Budi"}],
        },
    )
    sa = await api.login_demo("SA")

    resp = await api.client.post("/api/v1/activity-logs", json=LOG_NON_PROYEK, headers=sa)

    assert resp.status_code == 201, resp.text
    polished = resp.json()["data"]["ai_polished_notes"]
    assert polished["discussion_points"] == ["Rencana pelatihan"]
    assert polished["action_items"][0] == {"description": "Siapkan materi", "pic": "Budi"}
    assert fake_llm.jumlah("structure_text") == 1
    assert "pelatihan" in fake_llm.panggilan[0].argumen["text"]


async def test_llm_fake_error_log_tetap_tersimpan_tanpa_polish(api, fake_llm):
    fake_llm.error("structure_text", "timeout")
    sa = await api.login_demo("SA")

    resp = await api.client.post("/api/v1/activity-logs", json=LOG_NON_PROYEK, headers=sa)

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["ai_polished_notes"] is None
    assert fake_llm.jumlah("structure_text") == 1


# ----------------------------------------------------------------------------- Drive


async def test_drive_fake_sukses_id_folder_tersimpan_di_proyek(api, db_session, fake_drive):
    id_project, lead, _ = await _proyek_pending(api)
    await _tugaskan_sa(api, id_project, db_session)

    resp = await api.client.post(f"{PROYEK}/{id_project}/provision-folder", headers=lead)

    assert resp.status_code == 200, resp.text
    proyek = (
        await db_session.execute(select(Project).where(Project.id_project == id_project))
    ).scalar_one()
    await db_session.refresh(proyek)
    panggilan = fake_drive.panggilan_operasi("provision_project_folder")
    assert len(panggilan) == 1 and panggilan[0].berhasil
    assert proyek.folder_provisioning_status == "provisioned"
    assert fake_drive.folder[proyek.gdrive_folder_id]["name"] == "PT Fake - Proyek Fake"
    assert fake_drive.folder[proyek.gdrive_solutions_folder_id]["name"] == "Solutions"
    # Sales tidak punya akses ke Solutions; SA editor di master.
    assert fake_drive.peran(proyek.gdrive_solutions_folder_id, "demo-sales@portal-sa.local") is None
    assert fake_drive.peran(proyek.gdrive_folder_id, "demo-sa@portal-sa.local") == "writer"


async def test_drive_fake_gagal_status_provisioning_failed(api, db_session, fake_drive):
    fake_drive.fail_next("provision_project_folder")
    id_project, lead, _ = await _proyek_pending(api)
    await _tugaskan_sa(api, id_project, db_session)

    resp = await api.client.post(f"{PROYEK}/{id_project}/provision-folder", headers=lead)

    assert resp.status_code == 200, resp.text
    proyek = (
        await db_session.execute(select(Project).where(Project.id_project == id_project))
    ).scalar_one()
    await db_session.refresh(proyek)
    assert proyek.folder_provisioning_status == "failed"
    assert proyek.gdrive_folder_id is None
    assert fake_drive.folder == {}


# ----------------------------------------------------------------------------- Gmail


async def _closed_win(api, db_session, lead: dict) -> tuple[str, User]:
    """Proyek 'Ready' ditugaskan ke SA, lalu Lead_SA menaikkannya ke Closed-Win (notifikasi HLD)."""
    id_project, _, _ = await _proyek_pending(api)
    sa = await _tugaskan_sa(api, id_project, db_session, status="Ready")
    resp = await api.client.patch(
        f"{PROYEK}/{id_project}/status", json={"new_status": "Closed-Win"}, headers=lead
    )
    assert resp.status_code == 200, resp.text
    return id_project, sa


async def test_gmail_fake_email_hld_terekam(api, db_session, fake_gmail):
    lead = await api.login_demo("Lead_SA")
    fake_gmail.tahan_email()

    id_project, sa = await _closed_win(api, db_session, lead)
    fake_gmail.lepaskan_email()

    await fake_gmail.tunggu_percobaan(1)
    surat = fake_gmail.terkirim[0]
    assert surat.to == sa.email
    assert "HLD" in surat.subject
    assert surat.context["reference_id"] == id_project


async def test_gmail_fake_gagal_dicoba_ulang_sampai_pulih(api, db_session, fake_gmail):
    fake_gmail.fail_next(times=2)
    lead = await api.login_demo("Lead_SA")
    fake_gmail.tahan_email()

    await _closed_win(api, db_session, lead)
    fake_gmail.lepaskan_email()

    await fake_gmail.tunggu_percobaan(3)
    assert [s.berhasil for s in fake_gmail.percobaan] == [False, False, True]


# ----------------------------------------------------------------------------- Calendar


async def test_calendar_fake_sync_mengembalikan_event_terprogram(api, fake_calendar):
    fake_calendar.set_events(
        event_berjadwal(
            "g1", "Demo ke pelanggan", "2025-01-06T09:00:00+07:00", "2025-01-06T11:00:00+07:00"
        )
    )
    sa = await api.login_demo("SA")

    resp = await api.client.post(
        "/api/v1/calendar/sync", json={"access_token": "tok-sa"}, headers=sa
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_events"] == 1
    assert data["events"][0]["gcal_event_id"] == "g1"
    assert float(data["events"][0]["duration_hours"]) == 2
    assert fake_calendar.access_token_diterima == ["tok-sa"]


async def test_calendar_fake_timeout_dipetakan_ke_504(api, fake_calendar):
    fake_calendar.fail_next("timeout")
    sa = await api.login_demo("SA")

    resp = await api.client.post("/api/v1/calendar/sync", json={"access_token": "t"}, headers=sa)

    assert resp.status_code == 504
