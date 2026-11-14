from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.schemas.qualification_definition import QUESTIONNAIRE_SCHEMA_VERSION, answer_questions
from scripts.seed_demo_data import DEMO_USERS, get_or_create_project


def test_seed_menyediakan_dua_user_untuk_setiap_persona_fungsional():
    jumlah = {
        role: sum(
            user["role"] == role and user.get("is_admin", False) is False
            for user in DEMO_USERS
        )
        for role in ("Sales", "Product", "SA", "Lead_SA")
    }
    jumlah["Admin"] = sum(user.get("is_admin", False) for user in DEMO_USERS)
    assert jumlah == {"Sales": 2, "Product": 2, "SA": 2, "Lead_SA": 2, "Admin": 2}


@pytest.mark.asyncio
async def test_proyek_baru_menyimpan_jawaban_kualifikasi_dan_versi_skema():
    jawaban = {question.name: None for question in answer_questions()}
    jawaban.update(
        budget_dialokasikan="Ya",
        peran_pic="Pengambil keputusan",
        masalah_bisnis="Membangun analitik data customer terpusat untuk kebutuhan operasional.",
        jenis_workload="Data warehouse/analytics",
        lingkungan="Hybrid",
        skala="40 server, 20 TB",
        target_go_live="≤ 6 bulan",
    )
    data = {
        "id_project": "PRJ-TEST-QUALIFICATION",
        "project_name": "Proyek qualification",
        "customer_name": "PT Contoh",
        "status": "Intake",
        "target_submit": date(2026, 12, 1),
        "qualification_answers": jawaban,
    }
    db = Mock()
    db.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))
    db.flush = AsyncMock()

    project = await get_or_create_project(db, data, sales_id=uuid4())

    assert project.qualification_answers == jawaban
    assert project.qualification_schema_version == QUESTIONNAIRE_SCHEMA_VERSION
    assert project.bant_detail is None


@pytest.mark.asyncio
async def test_proyek_existing_tidak_diubah_oleh_seed_kualifikasi():
    existing = Mock(bant_detail={"legacy": True}, qualification_answers=None)
    db = Mock()
    db.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=existing)))
    db.flush = AsyncMock()

    result = await get_or_create_project(
        db,
        {
            "id_project": "PRJ-EXISTING",
            "project_name": "Existing",
        },
        sales_id=uuid4(),
    )

    assert result is existing
    assert existing.qualification_answers is None
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_proyek_existing_diperbarui_dengan_jawaban_dan_versi_schema_saja():
    jawaban = {question.name: None for question in answer_questions()}
    jawaban.update(
        budget_dialokasikan="Ya",
        peran_pic="Pengambil keputusan",
        masalah_bisnis="Membangun analitik data customer terpusat untuk kebutuhan operasional.",
        jenis_workload="Data warehouse/analytics",
        lingkungan="Hybrid",
        skala="40 server, 20 TB",
        target_go_live="≤ 6 bulan",
    )
    bant_detail_lama = {"budget_mrr": 5000000, "pic_name": "PIC Lama"}
    existing = Mock(
        bant_detail=bant_detail_lama,
        qualification_answers=None,
        qualification_schema_version=None,
        bant_score=71,
        status="Assigned",
    )
    db = Mock()
    db.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=existing)))
    db.flush = AsyncMock()

    result = await get_or_create_project(
        db,
        {
            "id_project": "PRJ-EXISTING",
            "project_name": "Existing",
            "qualification_answers": jawaban,
        },
        sales_id=uuid4(),
    )

    assert result is existing
    assert existing.qualification_answers == jawaban
    assert existing.qualification_schema_version == QUESTIONNAIRE_SCHEMA_VERSION
    assert existing.bant_detail == bant_detail_lama
    assert existing.bant_score == 71
    assert existing.status == "Assigned"
    db.flush.assert_awaited_once()
