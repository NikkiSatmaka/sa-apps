"""
Satu jalur API nyata terhadap Postgres nyata: demo login → buat proyek dengan kuesioner →
status dan constraint ditegakkan di database. Tanpa file, sehingga LLM tidak dipakai; background
task Requirement diganti mock oleh fixture `api` (Gemini nyata tidak pernah dipanggil).
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Document, Project, User
from tests.test_projects_questionnaire_api import jawaban_kuat, jawaban_lemah

URL = "/api/v1/projects"


def _form(jawaban: dict) -> dict:
    return {
        "project_name": "Proyek Integrasi",
        "customer_name": "PT Integrasi",
        "target_submit": str(date.today() + timedelta(days=30)),
        "estimasi_nilai": "500000000",
        "qualification_answers": json.dumps(jawaban),
    }


async def test_demo_login_buat_proyek_lolos_gate_tersimpan_di_postgres(api, db_session):
    await api.login_demo("Lead_SA")  # agar ada penerima notifikasi New Opportunity
    sales = await api.login_demo("Sales")

    resp = await api.client.post(URL, data=_form(jawaban_kuat()), headers=sales)

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "Pending Assignment"
    assert data["bant_score"] >= 60

    proyek = (
        await db_session.execute(select(Project).where(Project.id_project == data["id_project"]))
    ).scalar_one()
    sales_user = (
        await db_session.execute(select(User).where(User.email == "demo-sales@portal-sa.local"))
    ).scalar_one()
    assert proyek.status == "Pending Assignment"
    assert proyek.sales_pic == sales_user.id
    assert proyek.bant_score == data["bant_score"]
    assert proyek.qualification_answers["budget_dialokasikan"] == "Ya"
    # Hanya penanda `pending`: generate dipicu lewat mock, tidak ada baris Requirement/Gemini.
    assert proyek.requirement_generation_status == "pending"
    api.generate_requirement.assert_awaited_once_with(proyek.id_project)
    dokumen = (await db_session.execute(select(Document))).scalars().all()
    assert dokumen == []
    # Notifikasi in-app untuk Lead_SA tertulis lewat sesi yang sama.
    jumlah_notif = (
        await db_session.execute(text("SELECT count(*) FROM notification_logs"))
    ).scalar_one()
    assert jumlah_notif >= 1


async def test_jawaban_lemah_need_clarification_tanpa_generate_requirement(api, db_session):
    sales = await api.login_demo("Sales")

    resp = await api.client.post(URL, data=_form(jawaban_lemah()), headers=sales)

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "Need Clarification"
    proyek = (
        await db_session.execute(select(Project).where(Project.id_project == data["id_project"]))
    ).scalar_one()
    assert proyek.status == "Need Clarification"
    assert proyek.requirement_generation_status is None
    api.generate_requirement.assert_not_awaited()


async def test_tanpa_login_ditolak_dan_tidak_ada_proyek_tersimpan(api, db_session):
    resp = await api.client.post(URL, data=_form(jawaban_kuat()))

    assert resp.status_code in (401, 403)
    jumlah = (await db_session.execute(text("SELECT count(*) FROM projects"))).scalar_one()
    assert jumlah == 0


@pytest.mark.parametrize(
    ("kolom", "nilai", "constraint"),
    [
        ("status", "Status Ngawur", "chk_projects_status"),
        ("requirement_generation_status", "ngawur", "chk_projects_requirement_generation_status"),
        ("bant_score", 101, "chk_projects_bant_score"),
    ],
)
async def test_constraint_proyek_ditegakkan_postgres_pada_proyek_hasil_api(
    api, db_session, kolom, nilai, constraint
):
    sales = await api.login_demo("Sales")
    resp = await api.client.post(URL, data=_form(jawaban_kuat()), headers=sales)
    id_project = resp.json()["data"]["id_project"]

    with pytest.raises(IntegrityError) as err:
        async with db_session.begin_nested():
            await db_session.execute(
                text(f"UPDATE projects SET {kolom} = :v WHERE id_project = :p"),
                {"v": nilai, "p": id_project},
            )
    assert constraint in str(err.value)
