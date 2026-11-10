"""
Test tiket #41 (5A-8): override Lead SA menjadi batas bawah skor.

Skor akhir per kriteria = max(rubrik, AI, override) di semua jalur tulis skor
(edit jawaban, hasil AI terlambat, fallback saat AI gagal). Override disimpan terpisah
di `projects.override_sub_scores`. Lewat seam API (TestClient), DB/LLM di-mock.

Nilai ekspektasi ditulis sebagai literal (worked example), bukan dihitung ulang.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.notification_log import NotificationLog
from app.services.scoring_engine import scoring_engine
from tests.test_project_detail_qualification import _baru, _get
from tests.test_project_detail_qualification import _user as _detail_user
from tests.test_questionnaire_edit import (
    ANSWERS_LEMAH,
    _notifs,
    _project as _edit_project,
    _put,
    _setup as _edit_setup,
    _user,
)
from tests.test_scoring_pending_ai_merge_api import _jalankan_background, _sukses, _gagal
from tests.test_projects_questionnaire_api import jawaban_lemah
from tests.test_score_override import (
    BODY,
    URL as OVERRIDE_URL,
    _audits,
    _project as _override_project,
    _setup as _override_setup,
)

# Rubrik ANSWERS_LEMAH = budget 15 / authority 15 / need 12 / timeline 15 (57)
OVERRIDE_TINGGI = {"budget": 20, "authority": 20, "need": 20, "timeline": 20}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------------- simpan override
def test_override_disimpan_terpisah_dari_subskor_akhir():
    project = _override_project()
    project.override_sub_scores = None
    project.ai_scoring_result = None
    project.qualification_answers = None
    _override_setup(_user("Lead_SA"), project)

    r = TestClient(app).post(OVERRIDE_URL, json=BODY)

    assert r.status_code == 200
    assert project.override_sub_scores == OVERRIDE_TINGGI
    assert project.bant_detail["budget"] == 20


def test_override_baru_menggantikan_lama_dan_audit_mencatat_lama_baru_serta_alasan():
    project = _override_project()
    project.override_sub_scores = {"budget": 5, "authority": 5, "need": 5, "timeline": 5}
    project.ai_scoring_result = None
    project.qualification_answers = None
    session = _override_setup(_user("Lead_SA"), project)

    r = TestClient(app).post(OVERRIDE_URL, json=BODY)

    assert r.status_code == 200
    assert project.override_sub_scores == OVERRIDE_TINGGI  # bukan max dengan override lama
    a = _audits(session)[0]
    assert a.old_value["override_sub_scores"] == {
        "budget": 5, "authority": 5, "need": 5, "timeline": 5
    }
    assert a.new_value["override_sub_scores"] == OVERRIDE_TINGGI
    assert a.new_value["reason"] == BODY["reason"]


def test_override_menurunkan_nilai_lama_tidak_mengangkat_nilai_lama_kembali():
    project = _override_project()
    project.override_sub_scores = {"budget": 25, "authority": 25, "need": 25, "timeline": 25}
    project.ai_scoring_result = None
    project.qualification_answers = None
    _override_setup(_user("Lead_SA"), project)

    TestClient(app).post(
        OVERRIDE_URL, json={**BODY, "budget": 10, "authority": 10, "need": 10, "timeline": 10}
    )

    assert project.override_sub_scores["budget"] == 10
    assert project.bant_score == 40


def test_override_ditolak_guard_status_tidak_mengubah_override_tersimpan():
    project = _override_project(status="Assigned")
    project.override_sub_scores = {"budget": 5, "authority": 5, "need": 5, "timeline": 5}
    _override_setup(_user("Lead_SA"), project)

    r = TestClient(app).post(OVERRIDE_URL, json=BODY)

    assert r.status_code == 400
    assert project.override_sub_scores == {"budget": 5, "authority": 5, "need": 5, "timeline": 5}


def test_override_menjadi_batas_bawah_terhadap_rubrik_dan_ai_tersimpan():
    # Rubrik 15/15/12/15, AI need 25, override 20 semua → max = 20/20/25/20 = 85
    project = _override_project()
    project.qualification_answers = dict(ANSWERS_LEMAH)
    project.qualification_schema_version = 1
    project.target_submit = None
    project.ai_scoring_result = {
        "sub_scores": {"budget": 0, "authority": 0, "need": 25, "timeline": 0}
    }
    project.override_sub_scores = None
    _override_setup(_user("Lead_SA"), project)

    TestClient(app).post(OVERRIDE_URL, json=BODY)

    assert project.bant_detail["need"] == 25
    assert project.bant_detail["budget"] == 20
    assert project.bant_score == 85


# ----------------------------------------------------------------------------- re-score edit
def test_override_tinggi_tetap_berlaku_setelah_sales_mengedit_jawaban():
    user = _user("Sales")
    project = _edit_project(sales_pic=user.id)
    project.override_sub_scores = OVERRIDE_TINGGI
    session = _edit_setup(user, project)

    # Jawaban baru: budget "Belum" → rubrik budget 5; override 20 tetap berlaku
    r = _put({**ANSWERS_LEMAH, "budget_dialokasikan": "Belum"})

    assert r.status_code == 200
    assert project.bant_detail["budget"] == 20
    assert project.bant_detail["authority"] == 20
    assert project.bant_detail["need"] == 20
    assert project.bant_detail["timeline"] == 20
    assert project.bant_score == 80
    assert project.status == "Pending Assignment"
    assert len(_notifs(session)) == 1
    assert project.override_sub_scores == OVERRIDE_TINGGI  # tidak berubah


def test_rescore_rubrik_lebih_tinggi_dari_override_dan_ai_dipakai():
    user = _user("Sales")
    project = _edit_project(sales_pic=user.id)
    project.override_sub_scores = {"budget": 1, "authority": 1, "need": 1, "timeline": 1}
    project.ai_scoring_result = {
        "sub_scores": {"budget": 2, "authority": 2, "need": 2, "timeline": 2}
    }
    _edit_setup(user, project)

    _put(ANSWERS_LEMAH)

    assert project.bant_score == 57  # rubrik 15/15/12/15


def test_rescore_override_tanpa_ai_dan_override_none_tidak_error():
    user = _user("Sales")
    project = _edit_project(sales_pic=user.id)
    project.override_sub_scores = None
    _edit_setup(user, project)

    assert _put(ANSWERS_LEMAH).status_code == 200
    assert project.bant_score == 57


# ----------------------------------------------------------------------------- AI terlambat
def _background_dengan_override(override, **kw):
    """Seperti _jalankan_background, tetapi proyek sudah punya override."""
    from app.models.project import Project

    original_init = Project.__init__

    def _init(self, *a, **k):
        original_init(self, *a, **k)
        self.override_sub_scores = override

    with patch.object(Project, "__init__", _init):
        return _jalankan_background(**kw)


def test_hasil_ai_terlambat_digabung_max_dengan_override_bukan_menimpa():
    # Rubrik 0/0/12/10; AI 5/5/5/5; override 25/25/25/25 → akhir 25 semua = 100
    proyek, bg, _ = _background_dengan_override(
        {"budget": 25, "authority": 25, "need": 25, "timeline": 25},
        jawaban=jawaban_lemah(),
        ai_response=_sukses(budget=5, authority=5, need=5, timeline=5),
    )
    assert proyek.bant_detail["budget"] == 25
    assert proyek.bant_detail["need"] == 25
    assert proyek.bant_score == 100
    assert proyek.status == "Pending Assignment"
    assert proyek.ai_scoring_result["sub_scores"]["budget"] == 5  # AI mentah tetap terpisah
    assert proyek.override_sub_scores["budget"] == 25
    assert len(bg.of_type(NotificationLog)) == 1


def test_hasil_ai_lebih_tinggi_dari_override_tetap_dipakai():
    proyek, _, _ = _background_dengan_override(
        {"budget": 5, "authority": 5, "need": 5, "timeline": 5},
        jawaban=jawaban_lemah(),
        ai_response=_sukses(budget=25, authority=25, need=0, timeline=0),
    )
    # max(rubrik 0/0/12/10, AI 25/25/0/0, override 5 semua) = 25/25/12/10
    assert proyek.bant_score == 72


# ----------------------------------------------------------------------------- fallback
def test_ai_gagal_fallback_tetap_menghormati_override():
    # Rubrik 0/0/12/10 (22); override 20 semua → 20/20/20/20 = 80
    proyek, bg, _ = _background_dengan_override(
        OVERRIDE_TINGGI, jawaban=jawaban_lemah(), ai_response=_gagal()
    )
    assert proyek.bant_score == 80
    assert proyek.status == "Pending Assignment"
    assert len(bg.of_type(NotificationLog)) == 1


def test_exception_tak_terduga_fallback_menghormati_override():
    proyek, _, _ = _background_dengan_override(
        OVERRIDE_TINGGI, jawaban=jawaban_lemah(), provider_error=RuntimeError("x")
    )
    assert proyek.bant_score == 80


def test_fallback_after_failure_langsung_menghormati_override():
    from app.models.project import Project

    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status="Scoring Pending",
        qualification_answers=jawaban_lemah(),
        qualification_schema_version=1,
        override_sub_scores=OVERRIDE_TINGGI,
    )
    db = AsyncMock()
    db.add = MagicMock()
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=proyek)
    res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=res)

    asyncio.run(scoring_engine.fallback_after_failure(db, proyek.id_project))

    assert proyek.bant_score == 80
    assert proyek.status == "Pending Assignment"


# ----------------------------------------------------------------------------- koreksi pasca-gate
@pytest.mark.parametrize("status", ["Pending Assignment", "Assigned"])
def test_koreksi_pasca_gate_tanpa_rescore_tidak_menyentuh_override(status):
    user = _user("Lead_SA")
    project = _edit_project(status=status)
    project.override_sub_scores = OVERRIDE_TINGGI
    _edit_setup(user, project)

    r = _put({**ANSWERS_LEMAH, "budget_dialokasikan": "Belum"})

    assert r.status_code == 200
    assert project.bant_score == 57
    assert project.bant_detail == {"budget": 15, "authority": 15, "need": 12, "timeline": 15}
    assert project.override_sub_scores == OVERRIDE_TINGGI


# ----------------------------------------------------------------------------- detail proyek
def test_detail_proyek_menampilkan_subskor_akhir_dan_override():
    p = _baru(score=80)
    p.override_sub_scores = {"budget": 20, "authority": 20, "need": 20, "timeline": 20}
    q = _get(p, _detail_user("Admin")).json()["data"]["qualification"]
    assert q["sub_scores"] == {"budget": 20, "authority": 20, "need": 20, "timeline": 20}
    assert q["override_sub_scores"] == {"budget": 20, "authority": 20, "need": 20, "timeline": 20}


def test_detail_proyek_tanpa_override_menampilkan_none():
    q = _get(_baru(), _detail_user("Admin")).json()["data"]["qualification"]
    assert q["override_sub_scores"] is None
