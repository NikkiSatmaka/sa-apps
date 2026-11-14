from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.schemas.qualification_definition import QUESTIONNAIRE_SCHEMA_VERSION, answer_questions
from scripts import seed_demo_data
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
    assert all(user["role"] != "SA" or not user.get("is_admin", False) for user in DEMO_USERS)
    assert all(user["role"] == "Lead_SA" for user in DEMO_USERS if user.get("is_admin", False))


def test_persona_admin_demo_memakai_role_lead_sa():
    from app.api.auth import DEMO_USERS as AUTH_DEMO_USERS

    assert AUTH_DEMO_USERS["Admin"]["role"] == "Lead_SA"
    assert AUTH_DEMO_USERS["Admin"]["is_admin"] is True


@pytest.mark.asyncio
async def test_seed_all_memakai_akun_sales_dan_sa_berbeda_pada_project(monkeypatch):
    captured = []
    ids = {user["email"]: uuid4() for user in DEMO_USERS}

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def fake_user(_db, user_data):
        return SimpleNamespace(id=ids[user_data["email"]])

    async def fake_project(_db, project_data, sales_id, sa_id=None, product_id=None):
        captured.append((project_data.copy(), sales_id, sa_id, product_id))

    monkeypatch.setattr(seed_demo_data, "AsyncSessionLocal", FakeDB)
    monkeypatch.setattr(seed_demo_data, "get_or_create_user", fake_user)
    monkeypatch.setattr(seed_demo_data, "get_or_create_project", fake_project)
    monkeypatch.setattr(seed_demo_data, "get_or_create_document", AsyncMock())
    monkeypatch.setattr(seed_demo_data, "get_or_create_activity_log", AsyncMock())
    await seed_demo_data.seed_all()
    mapping_first_seed = list(captured)
    captured.clear()
    await seed_demo_data.seed_all()
    mapping_second_seed = list(captured)

    sales1, sales2 = ids["demo-sales@portal-sa.local"], ids["demo-sales2@portal-sa.local"]
    sa1, sa2 = ids["demo-sa@portal-sa.local"], ids["demo-sa2@portal-sa.local"]
    product1 = ids["demo-product@portal-sa.local"]
    product2 = ids["demo-product2@portal-sa.local"]
    assert len(mapping_first_seed) >= 8
    assert [(p["id_project"], s, sa, product) for p, s, sa, product in mapping_first_seed] == [
        (p["id_project"], s, sa, product) for p, s, sa, product in mapping_second_seed
    ]
    assert {p["id_project"] for p, *_ in mapping_first_seed} >= {
        f"PRJ-DEMO-{index:03}" for index in range(1, 9)
    }
    assert all(p["qualification_answers"] and p.get("qualification_schema_version") is None
               for p, *_ in mapping_first_seed)
    assert {p["bant_score"] for p, *_ in mapping_first_seed} >= {45, 62, 75, 85, 90}
    assert len({product for _, _, _, product in mapping_first_seed}) == 2
    assert sum(sa is not None for _, _, sa, _ in mapping_first_seed) >= 4


@pytest.mark.asyncio
async def test_rerun_sinkronkan_pic_tanpa_mengubah_pembuat_atau_data_project():
    pembuat = uuid4()
    existing = Mock(
        id_project="PRJ-DEMO-001",
        sales_pic=uuid4(),
        assigned_sa=uuid4(),
        product_pic=uuid4(),
        created_by=pembuat,
        status="Submitted",
        bant_score=77,
        qualification_answers={"legacy": True},
        qualification_schema_version=3,
        bant_detail={"legacy": "tetap"},
    )
    sales, sa, product = uuid4(), uuid4(), uuid4()
    db = Mock()
    db.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=existing)))
    db.flush = AsyncMock()

    for _ in range(2):
        await get_or_create_project(
            db,
            {"id_project": "PRJ-DEMO-001", "project_name": "Fixture"},
            sales_id=sales,
            sa_id=sa,
            product_id=product,
        )

    assert (existing.sales_pic, existing.assigned_sa, existing.product_pic) == (sales, sa, product)
    assert existing.created_by == pembuat
    assert (existing.status, existing.bant_score) == ("Submitted", 77)
    assert existing.qualification_answers == {"legacy": True}
    assert existing.bant_detail == {"legacy": "tetap"}


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

    sales_id, product_id = uuid4(), uuid4()
    project = await get_or_create_project(
        db, data, sales_id=sales_id, product_id=product_id
    )

    assert project.qualification_answers == jawaban
    assert project.qualification_schema_version == QUESTIONNAIRE_SCHEMA_VERSION
    assert project.bant_detail is None
    assert project.created_by == sales_id
    assert project.product_pic == product_id


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
