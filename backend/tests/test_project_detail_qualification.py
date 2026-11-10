"""
Seam tiket 5A-3 (#29): GET /projects/{id} memuat jawaban kuesioner, sub-skor, feedback,
dan bagian legacy untuk proyek lama. Lewat TestClient, DB di-mock di boundary.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.project import Project

PID = "PRJ-20250101-ABC123"
URL = f"/api/v1/projects/{PID}"

JAWABAN = {
    "mrr": 12.5,
    "budget_dialokasikan": "Sudah disetujui",
    "peran_pic": "Pengambil keputusan",
    "masalah_bisnis": "Migrasi data center",
    "jenis_workload": "Migrasi",
    "lingkungan": "Hybrid",
    "skala": "50 VM",
    "target_go_live": "< 3 bulan",
}


def _user(role="Sales"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = role
    return u


def _res(one=None, items=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=one)
    s = MagicMock()
    s.all = MagicMock(return_value=items or [])
    r.scalars = MagicMock(return_value=s)
    return r


def _project(**kw):
    d = dict(
        id_project=PID,
        project_name="P",
        customer_name="C",
        status="Pending Assignment",
        target_submit=date.today() + timedelta(days=7),
        sales_pic=None,
        assigned_sa=None,
        bant_score=None,
        bant_detail=None,
        qualification_answers=None,
        qualification_schema_version=None,
    )
    d.update(kw)
    return Project(**d)


def _get(project, user, *, collaborator=False, extra_lookups=0):
    """Urutan execute: project, cek collaborator, [lookup user...], daftar collaborators, Source document."""
    session = AsyncMock()
    seq = [_res(project), _res(MagicMock() if collaborator else None)]
    seq += [_res(None)] * extra_lookups
    seq += [_res(items=[]), _res(items=[])]
    session.execute = AsyncMock(side_effect=seq)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        return TestClient(app).get(URL)
    finally:
        app.dependency_overrides.clear()


def _baru(score=80, **kw):
    sub = {"budget": 20, "authority": 20, "need": 20, "timeline": 20}
    return _project(
        bant_score=score,
        bant_detail=sub,
        qualification_answers=JAWABAN,
        qualification_schema_version=1,
        **kw,
    )


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
def test_proyek_baru_menampilkan_jawaban_dan_subskor_untuk_privileged(role):
    r = _get(_baru(), _user(role))
    assert r.status_code == 200
    q = r.json()["data"]["qualification"]
    assert q["legacy"] is False
    assert q["schema_version"] == 1
    assert q["answers"]["masalah_bisnis"] == "Migrasi data center"
    assert q["sub_scores"] == {"budget": 20, "authority": 20, "need": 20, "timeline": 20}
    assert q["feedback"] is None
    assert q["legacy_data"] is None


def test_sales_pic_bisa_melihat():
    u = _user("Sales")
    r = _get(_baru(sales_pic=u.id), u, extra_lookups=1)
    assert r.status_code == 200
    assert r.json()["data"]["qualification"]["answers"]["jenis_workload"] == "Migrasi"


def test_assigned_sa_bisa_melihat():
    u = _user("SA")
    r = _get(_baru(assigned_sa=u.id), u, extra_lookups=1)
    assert r.status_code == 200
    assert r.json()["data"]["qualification"]["sub_scores"]["need"] == 20


def test_collaborator_bisa_membaca():
    r = _get(_baru(), _user("SA"), collaborator=True)
    assert r.status_code == 200
    assert r.json()["data"]["qualification"]["answers"]["lingkungan"] == "Hybrid"


def test_user_tanpa_akses_ditolak_dan_tidak_bocor():
    r = _get(_baru(), _user("Sales"))
    assert r.status_code == 403
    assert "qualification" not in r.text


def test_skor_di_bawah_60_menyertakan_feedback():
    p = _baru(score=40)
    p.bant_detail = {"budget": 5, "authority": 15, "need": 10, "timeline": 10}
    q = _get(p, _user("Admin")).json()["data"]["qualification"]
    assert "Budget" in q["feedback"]
    assert "Need" in q["feedback"]
    assert "Authority" not in q["feedback"]


def test_proyek_lama_menampilkan_data_legacy_tanpa_mengubah_data():
    lama = {
        "budget_mrr": 8,
        "pic_name": "Budi",
        "pic_position": "CTO",
        "pic_email": "b@x.id",
        "need_description": "Butuh DR",
        "timeline_target": "Q3",
        "budget": 20,
        "authority": 15,
        "need": 20,
        "timeline": 10,
    }
    p = _project(bant_score=65, bant_detail=dict(lama))
    r = _get(p, _user("Admin"))
    q = r.json()["data"]["qualification"]
    assert q["legacy"] is True
    assert q["answers"] is None
    assert q["schema_version"] is None
    assert q["legacy_data"] == {
        "budget_mrr": 8,
        "pic_name": "Budi",
        "pic_position": "CTO",
        "pic_email": "b@x.id",
        "need_description": "Butuh DR",
        "timeline_target": "Q3",
    }
    assert q["sub_scores"] == {"budget": 20, "authority": 15, "need": 20, "timeline": 10}
    assert p.bant_detail == lama  # tidak ada perubahan data
    assert p.qualification_answers is None


def test_proyek_lama_tanpa_bant_detail():
    q = _get(_project(), _user("Admin")).json()["data"]["qualification"]
    assert q["legacy"] is True
    assert q["legacy_data"] is None
    assert q["sub_scores"] is None
    assert q["feedback"] is None


def test_scoring_pending_tidak_menampilkan_skor_dan_feedback_sebagai_hasil_final():
    p = _baru(score=40, status="Scoring Pending")
    p.bant_detail = {"budget": 5, "authority": 15, "need": 10, "timeline": 10}
    d = _get(p, _user("Admin")).json()["data"]
    assert d["bant_score"] is None
    assert "budget" not in d["bant_detail"]
    q = d["qualification"]
    assert q["scoring_pending"] is True
    assert q["feedback"] is None
    assert q["sub_scores"] is None
    assert q["answers"]["masalah_bisnis"] == "Migrasi data center"  # jawaban tetap tampil


def test_status_selain_scoring_pending_tidak_ditandai_pending():
    d = _get(_baru(score=40), _user("Admin")).json()["data"]
    assert d["bant_score"] == 40
    assert d["qualification"]["scoring_pending"] is False
