"""
Test edit jawaban kuesioner + re-score (#32) lewat seam API.

PUT /projects/{id}/qualification-answers: Sales PIC hanya saat qualification_state Need Clarification
(re-score = max per kriteria antara rubrik baru dan hasil AI tersimpan, lalu gate 60);
Lead_SA/Admin: sama saat Need Clarification, dan koreksi TANPA re-score setelah lolos gate.
DB di-mock; scoring_engine dan rubrik nyata.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.notification_log import NotificationLog
from tests._auth_support import terapkan_persona

URL = "/api/v1/projects/PRJ-20250101-ABC123/qualification-answers"

# Rubrik: budget 15, authority 15, need 12, timeline 15 = 57 (< 60)
ANSWERS_LEMAH = {
    "budget_dialokasikan": "Ya",
    "peran_pic": "Pengambil keputusan",
    "masalah_bisnis": "Singkat",
    "jenis_workload": "Keamanan",
    "lingkungan": "Cloud",
    "skala": "10 server",
    "target_go_live": "≤ 3 bulan",
}
# Tambah MRR (+10 budget) dan PIC lengkap (+10 authority): 25+25+12+15 = 77
ANSWERS_KUAT = {
    **ANSWERS_LEMAH,
    "mrr": 5000,
    "pic_nama": "Budi",
    "pic_jabatan": "CTO",
    "pic_email": "budi@contoh.id",
}


def _user(role):
    u = MagicMock()
    u.id = uuid.uuid4()
    terapkan_persona(u, role)
    return u


def _project(status="Intake", sales_pic=None, ai=None, answers=None, state="Need Clarification"):
    p = MagicMock()
    p.id_project = "PRJ-20250101-ABC123"
    p.sales_pic = sales_pic
    p.product_pic = None  # MagicMock otomatis akan cocok dengan `in`; tegaskan tanpa Product PIC
    p.assigned_sa = None
    p.collaborators = []
    p.status = status
    p.qualification_state = state if status == "Intake" else "Qualified"
    p.bant_score = 57
    p.bant_detail = {"budget": 15, "authority": 15, "need": 12, "timeline": 15}
    p.use_case_tags = []
    p.target_submit = None
    p.qualification_answers = answers if answers is not None else dict(ANSWERS_LEMAH)
    p.qualification_schema_version = 1
    p.ai_scoring_result = ai
    return p


def _setup(user, project, lead_sa=None):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=project)
    result.scalars.return_value.all.return_value = [lead_sa or _user("Lead_SA")]
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return session


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _notifs(session):
    return [
        c.args[0]
        for c in session.add.call_args_list
        if isinstance(c.args[0], NotificationLog)
    ]


def _put(answers):
    return TestClient(app).put(URL, json=answers)


def test_sales_pic_edit_saat_need_clarification_rescore_lolos_gate_dan_notifikasi():
    user = _user("Sales")
    project = _project(sales_pic=user.id)
    session = _setup(user, project)

    r = _put(ANSWERS_KUAT)

    assert r.status_code == 200
    assert project.qualification_answers["mrr"] == 5000
    assert project.bant_score == 77
    assert project.bant_detail["budget"] == 25
    assert project.status == "Awaiting Assignment"
    assert len(_notifs(session)) == 1
    assert r.json()["data"]["status"] == "Awaiting Assignment"


def test_edit_tetap_di_bawah_gate_status_tetap_need_clarification_tanpa_notifikasi():
    user = _user("Sales")
    project = _project(sales_pic=user.id)
    session = _setup(user, project)

    r = _put({**ANSWERS_LEMAH, "budget_dialokasikan": "Belum"})  # budget 5

    assert r.status_code == 200
    assert project.bant_score == 47
    assert (project.status, project.qualification_state) == ("Intake", "Need Clarification")
    assert _notifs(session) == []
    assert r.json()["data"]["feedback"]


def test_hasil_ai_tersimpan_ikut_diperhitungkan_pada_rescore():
    user = _user("Sales")
    ai = {"sub_scores": {"budget": 0, "authority": 0, "need": 25, "timeline": 0}}
    project = _project(sales_pic=user.id, ai=ai)
    _setup(user, project)

    # Rubrik saja = 57; need AI 25 > rubrik 12 → 15+15+25+15 = 70
    r = _put(ANSWERS_LEMAH)

    assert r.status_code == 200
    assert project.bant_detail["need"] == 25
    assert project.bant_score == 70
    assert project.status == "Awaiting Assignment"
    # hasil AI tersimpan tidak ditimpa
    assert project.ai_scoring_result is ai


def test_hasil_ai_lebih_rendah_dari_rubrik_tidak_menurunkan_skor():
    user = _user("Sales")
    ai = {"sub_scores": {"budget": 0, "authority": 0, "need": 0, "timeline": 0}}
    project = _project(sales_pic=user.id, ai=ai)
    _setup(user, project)

    _put(ANSWERS_LEMAH)

    assert project.bant_score == 57


@pytest.mark.parametrize(
    "mutasi,field",
    [
        ({"budget_dialokasikan": None}, "qualification_answers.budget_dialokasikan"),
        ({"peran_pic": "Bos besar"}, "qualification_answers.peran_pic"),
        ({"pic_email": "bukan-email"}, "qualification_answers.pic_email"),
        ({"skor_budget": 25}, "qualification_answers.skor_budget"),
    ],
)
def test_jawaban_tervalidasi_422_dan_data_tidak_berubah(mutasi, field):
    user = _user("Sales")
    project = _project(sales_pic=user.id)
    session = _setup(user, project)

    r = _put({**ANSWERS_LEMAH, **mutasi})

    assert r.status_code == 422
    assert field in [e["field"] for e in r.json()["data"]]
    assert project.qualification_answers == ANSWERS_LEMAH
    assert project.bant_score == 57
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("Awaiting Assignment", "Qualified"),
        ("Assigned", "Qualified"),
        ("Won", "Qualified"),
        ("Intake", "Scoring"),
        ("Intake", "Manual Review"),
    ],
)
def test_sales_ditolak_403_setelah_lolos_gate_atau_status_terkunci(status, state):
    user = _user("Sales")
    project = _project(status=status, sales_pic=user.id, state=state)
    session = _setup(user, project)

    r = _put(ANSWERS_KUAT)

    assert r.status_code == 403
    assert project.qualification_answers == ANSWERS_LEMAH
    assert project.bant_score == 57
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("role", ["Sales", "SA"])
def test_bukan_pic_atau_peran_lain_ditolak_403(role):
    user = _user(role)
    project = _project(sales_pic=uuid.uuid4())
    project.assigned_sa = None
    _setup(user, project)

    assert _put(ANSWERS_KUAT).status_code == 403
    assert project.bant_score == 57


def test_sa_yang_ditugaskan_dan_collaborator_ditolak_403():
    sa = _user("SA")
    project = _project(sales_pic=uuid.uuid4())
    project.assigned_sa = sa.id
    _setup(sa, project)
    assert _put(ANSWERS_KUAT).status_code == 403


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
def test_lead_sa_admin_saat_need_clarification_diperlakukan_seperti_sales(role):
    project = _project(sales_pic=uuid.uuid4())
    session = _setup(_user(role), project)

    r = _put(ANSWERS_KUAT)

    assert r.status_code == 200
    assert project.bant_score == 77
    assert project.status == "Awaiting Assignment"
    assert len(_notifs(session)) == 1


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
@pytest.mark.parametrize("status", ["Awaiting Assignment", "Assigned"])
def test_koreksi_setelah_gate_tanpa_rescore(role, status):
    project = _project(status=status, sales_pic=uuid.uuid4())
    project.bant_score = 80
    project.bant_detail = {"budget": 20, "authority": 20, "need": 20, "timeline": 20}
    session = _setup(_user(role), project)

    r = _put({**ANSWERS_LEMAH, "masalah_bisnis": "Koreksi teks"})

    assert r.status_code == 200
    assert project.qualification_answers["masalah_bisnis"] == "Koreksi teks"
    assert project.bant_score == 80
    assert project.bant_detail["budget"] == 20
    assert project.status == status
    assert _notifs(session) == []
    session.commit.assert_awaited()


def test_proyek_legacy_tanpa_jawaban_ditolak_dengan_pesan_jelas():
    user = _user("Sales")
    project = _project(sales_pic=user.id)
    project.qualification_answers = None
    session = _setup(user, project)

    r = _put(ANSWERS_KUAT)

    assert r.status_code == 400
    assert "legacy" in r.json()["message"].lower()
    session.commit.assert_not_awaited()


def test_proyek_tidak_ada_404():
    _setup(_user("Lead_SA"), None)
    assert _put(ANSWERS_KUAT).status_code == 404


def test_tanpa_autentikasi_401():
    assert TestClient(app).put(URL, json=ANSWERS_KUAT).status_code == 401
