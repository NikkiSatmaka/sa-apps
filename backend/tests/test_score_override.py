"""
Test override skor BANT oleh Lead_SA/Admin (#30) lewat seam API.

POST /projects/{id}/score-manual kini berarti override: empat sub-skor 0-25 +
alasan wajib, hanya Lead_SA/Admin, hanya pada Intake dengan qualification_state
Need Clarification / Manual Review, dan dicatat di audit log. DB di-mock; scoring_engine nyata.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.audit_log import AuditLog
from tests._auth_support import terapkan_persona

URL = "/api/v1/projects/PRJ-20250101-ABC123/score-manual"
BODY = {
    "budget": 20,
    "authority": 20,
    "need": 20,
    "timeline": 20,
    "reason": "Klarifikasi via telepon dengan customer",
}


def _user(role):
    u = MagicMock()
    u.id = uuid.uuid4()
    terapkan_persona(u, role)
    return u


def _project(status="Intake", sales_pic=None, assigned_sa=None, state="Need Clarification"):
    p = MagicMock()
    p.id_project = "PRJ-20250101-ABC123"
    p.sales_pic = sales_pic
    p.assigned_sa = assigned_sa
    p.status = status
    p.qualification_state = state if status == "Intake" else "Qualified"
    p.bant_score = 40
    p.bant_detail = {
        "budget": 10,
        "authority": 10,
        "need": 10,
        "timeline": 10,
        "budget_mrr": 5000,
    }
    p.use_case_tags = []
    return p


def _setup(user, project):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=project)
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


def _audits(session):
    return [
        c.args[0]
        for c in session.add.call_args_list
        if isinstance(c.args[0], AuditLog)
    ]


@pytest.mark.parametrize("role", ["Sales", "SA"])
def test_non_lead_sa_ditolak_403_termasuk_pic_dan_assigned_sa(role):
    user = _user(role)
    project = _project(sales_pic=user.id, assigned_sa=user.id)
    session = _setup(user, project)

    r = TestClient(app).post(URL, json=BODY)

    assert r.status_code == 403
    assert _audits(session) == []
    assert project.bant_score == 40


def test_tanpa_autentikasi_401():
    assert TestClient(app).post(URL, json=BODY).status_code == 401


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_alasan_wajib_422(reason):
    user = _user("Lead_SA")
    project = _project()
    session = _setup(user, project)
    body = {k: v for k, v in BODY.items() if k != "reason"}
    if reason is not None:
        body["reason"] = reason

    r = TestClient(app).post(URL, json=body)

    assert r.status_code == 422
    assert _audits(session) == []
    assert project.bant_score == 40


def test_skor_di_luar_rentang_422():
    _setup(_user("Admin"), _project())
    r = TestClient(app).post(URL, json={**BODY, "budget": 26})
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("Intake", "Scoring"),
        ("Awaiting Assignment", "Qualified"),
        ("Assigned", "Qualified"),
        ("Won", "Qualified"),
    ],
)
def test_status_selain_relevan_ditolak_400(status, state):
    user = _user("Lead_SA")
    project = _project(status=status, state=state)
    session = _setup(user, project)

    r = TestClient(app).post(URL, json=BODY)

    assert r.status_code == 400
    assert project.bant_score == 40
    assert (project.status, project.qualification_state) == (status, state)
    assert _audits(session) == []


def test_proyek_tidak_ada_404():
    _setup(_user("Lead_SA"), None)
    assert TestClient(app).post(URL, json=BODY).status_code == 404


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
@pytest.mark.parametrize("state", ["Need Clarification", "Manual Review"])
def test_override_sukses_lolos_gate_dan_tulis_audit(role, state):
    user = _user(role)
    project = _project(state=state)
    session = _setup(user, project)

    r = TestClient(app).post(URL, json=BODY)

    assert r.status_code == 200
    assert r.json()["data"]["total_score"] == 80
    assert project.bant_score == 80
    assert (project.status, project.qualification_state) == ("Awaiting Assignment", "Qualified")
    # metadata legacy tidak hilang
    assert project.bant_detail["budget_mrr"] == 5000
    assert project.bant_detail["budget"] == 20

    audits = _audits(session)
    assert len(audits) == 1
    a = audits[0]
    assert a.entity_type == "project"
    assert a.entity_id == "PRJ-20250101-ABC123"
    assert a.action == "bant_override"
    assert a.performed_by == user.id
    assert a.old_value["bant_score"] == 40
    assert (a.old_value["status"], a.old_value["qualification_state"]) == ("Intake", state)
    assert a.old_value["sub_scores"]["budget"] == 10
    assert a.new_value["bant_score"] == 80
    assert (a.new_value["status"], a.new_value["qualification_state"]) == (
        "Awaiting Assignment",
        "Qualified",
    )
    assert a.new_value["sub_scores"]["timeline"] == 20
    assert a.new_value["reason"] == BODY["reason"]


def test_override_di_bawah_gate_tetap_need_clarification():
    user = _user("Lead_SA")
    project = _project(state="Manual Review")
    session = _setup(user, project)

    r = TestClient(app).post(
        URL, json={**BODY, "budget": 5, "authority": 5, "need": 5, "timeline": 5}
    )

    assert r.status_code == 200
    assert project.bant_score == 20
    assert (project.status, project.qualification_state) == ("Intake", "Need Clarification")
    new_value = _audits(session)[0].new_value
    assert (new_value["status"], new_value["qualification_state"]) == (
        "Intake",
        "Need Clarification",
    )


def test_metadata_deskriptif_tidak_lagi_diterima():
    project = _project()
    _setup(_user("Lead_SA"), project)
    body = {**BODY, "budget_detail": {"mrr": 1}, "need_detail": "x", "pic_name": "y"}

    r = TestClient(app).post(URL, json=body)

    assert r.status_code == 200
    assert "need_description" not in project.bant_detail
    assert project.bant_detail["budget_mrr"] == 5000  # tak tertimpa


@pytest.mark.parametrize("state", ["Need Clarification", "Manual Review"])
def test_override_mempertahankan_use_case_tags_hasil_ai(state):
    project = _project(state=state)
    project.use_case_tags = ["cloud-migration", "dr"]
    _setup(_user("Lead_SA"), project)

    r = TestClient(app).post(URL, json=BODY)

    assert r.status_code == 200
    assert project.use_case_tags == ["cloud-migration", "dr"]
