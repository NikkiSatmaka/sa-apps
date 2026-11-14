"""
Test seam utama tiket 5A-2 (#28): opportunity dengan file → Intake + `Scoring`, skor akhir
per kriteria = max(rubrik, AI), fallback ke rubrik bila AI gagal. Lewat HTTP API (TestClient)
dengan sesi DB dan provider LLM di-mock di boundary.

Nilai yang diharapkan ditulis sebagai literal (worked example dari rubrik di ADR 0010):
- jawaban_kuat  → rubrik budget 25 / authority 25 / need 25 / timeline 25 (total 100)
- jawaban_lemah → rubrik budget 0 / authority 0 / need 12 / timeline 10 (total 22)
"""

import json
import uuid
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification_log import NotificationLog
from app.models.project import Project
from app.services.llm_provider import LLMResponse
from tests.test_projects_questionnaire_api import (
    URL,
    FakeSession,
    _api,
    _form,
    _lead,
    _result,
    jawaban_kuat,
    jawaban_lemah,
)


def ai_json(budget=0, authority=0, need=0, timeline=0, tags=("cloud",)):
    def k(score):
        return {"score": score, "evidence": "x"}

    return json.dumps(
        {
            "budget": k(budget),
            "authority": k(authority),
            "need": k(need),
            "timeline": k(timeline),
            "use_case_tags": list(tags),
        }
    )


def _pdf():
    return ("files", ("mom.pdf", BytesIO(b"%PDF-1.4 isi"), "application/pdf"))


# --------------------------------------------------------------------------- create dengan file
def test_create_dengan_file_qualification_state_scoring_dan_skor_rubrik_tersimpan():
    with patch("app.api.projects._trigger_scoring_engine", new=AsyncMock()) as trigger:
        with _api() as (client, session):
            resp = client.post(URL, data=_form(jawaban_lemah(), file_types=["MoM"]), files=[_pdf()])
    assert resp.status_code == 201
    d = resp.json()["data"]
    assert (d["status"], d["qualification_state"]) == ("Intake", "Scoring")
    assert d["scoring_triggered"] is True
    trigger.assert_awaited_once()
    proyek = session.of_type(Project)[0]
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Scoring")
    assert proyek.bant_score == 22
    assert proyek.bant_detail["budget"] == 0
    assert proyek.bant_detail["need"] == 12
    assert proyek.bant_detail["timeline"] == 10
    assert proyek.ai_scoring_result is None
    assert session.of_type(NotificationLog) == []  # gate baru diterapkan setelah AI selesai


# --------------------------------------------------------------------------- background scoring
def _jalankan_background(
    *,
    status_awal="Intake",
    state_awal="Scoring",
    jawaban=None,
    ai_response=None,
    ai_lama=None,
    provider_error=None,
):
    """
    Create dengan file lalu jalankan background scoring. Proyek di DB background dibuat
    seolah-olah sudah tersimpan oleh create (status `status_awal` + `state_awal`, skor rubrik terhitung).
    Return (proyek, sesi_background, provider).
    """
    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status=status_awal,
        qualification_state=state_awal if status_awal == "Intake" else "Qualified",
        target_submit=date.today() + timedelta(days=30),
        qualification_answers=jawaban,
        qualification_schema_version=1 if jawaban is not None else None,
        bant_score=22,
        bant_detail={"budget": 0, "authority": 0, "need": 12, "timeline": 10},
        ai_scoring_result=ai_lama,
        sales_pic=uuid.uuid4(),
    )
    bg = FakeSession()
    lead = _lead()

    async def _execute(stmt, *a, **k):
        if "FROM users" in str(stmt):
            return _result(items=[lead])
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)

    class _Ctx:
        async def __aenter__(self):
            return bg

        async def __aexit__(self, *exc):
            return False

    provider = MagicMock()
    provider.parse_document = AsyncMock(return_value=ai_response)
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx()), patch(
        "app.services.scoring_engine.llm_factory.get_provider",
        return_value=provider,
        side_effect=provider_error,
    ), patch("app.services.scoring_engine.asyncio.sleep", new=AsyncMock()):
        with _api() as (client, _):
            resp = client.post(
                URL, data=_form(
                    jawaban if jawaban is not None else jawaban_lemah(), file_types=["MoM"]
                ),
                files=[_pdf()]
            )
    assert resp.status_code == 201
    return proyek, bg, provider


def _sukses(**kw):
    return LLMResponse(status="success", content=ai_json(**kw))


def _gagal():
    return LLMResponse(status="error", error_type="timeout", error_message="timeout")


def test_skor_akhir_per_kriteria_adalah_max_rubrik_dan_ai_lalu_gate_lolos_dan_lead_sa_dinotifikasi():
    # Rubrik 0/0/12/10 (22, tidak lolos) + AI 25/25/5/5 → gabungan 25/25/12/10 = 72
    proyek, bg, _ = _jalankan_background(
        jawaban=jawaban_lemah(), ai_response=_sukses(budget=25, authority=25, need=5, timeline=5)
    )
    assert (proyek.status, proyek.qualification_state) == ("Awaiting Assignment", "Qualified")
    assert proyek.bant_score == 72
    assert proyek.bant_detail["budget"] == 25
    assert proyek.bant_detail["authority"] == 25
    assert proyek.bant_detail["need"] == 12  # rubrik lebih tinggi dari AI
    assert proyek.bant_detail["timeline"] == 10
    assert len(bg.of_type(NotificationLog)) == 1


def test_rubrik_lebih_tinggi_dari_ai_tetap_dipakai():
    proyek, bg, _ = _jalankan_background(jawaban=jawaban_kuat(), ai_response=_sukses())
    assert proyek.bant_score == 100
    assert (proyek.status, proyek.qualification_state) == ("Awaiting Assignment", "Qualified")
    assert len(bg.of_type(NotificationLog)) == 1


def test_gabungan_di_bawah_60_need_clarification_dengan_feedback_tanpa_notifikasi():
    proyek, bg, _ = _jalankan_background(
        jawaban=jawaban_lemah(), ai_response=_sukses(budget=5, authority=5)
    )
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Need Clarification")
    assert proyek.bant_score == 5 + 5 + 12 + 10
    assert bg.of_type(NotificationLog) == []


def test_hasil_ai_tersimpan_terpisah_dari_skor_rubrik_dan_gabungan():
    proyek, _, _ = _jalankan_background(
        jawaban=jawaban_lemah(),
        ai_response=_sukses(budget=25, authority=20, need=5, timeline=5, tags=("dr", "backup")),
    )
    ai = proyek.ai_scoring_result
    assert ai["sub_scores"] == {"budget": 25, "authority": 20, "need": 5, "timeline": 5}
    assert ai["use_case_tags"] == ["dr", "backup"]
    # skor gabungan di bant_detail, bukan skor mentah AI
    assert proyek.bant_detail["need"] == 12


def test_ai_gagal_semua_retry_gate_memakai_skor_rubrik_lolos():
    proyek, bg, provider = _jalankan_background(jawaban=jawaban_kuat(), ai_response=_gagal())
    assert provider.parse_document.await_count == 3  # semua retry terpakai
    assert (proyek.status, proyek.qualification_state) == ("Awaiting Assignment", "Qualified")
    assert proyek.bant_score == 100
    assert len(bg.of_type(NotificationLog)) == 1


def test_ai_gagal_semua_retry_gate_memakai_skor_rubrik_tidak_lolos_tidak_menggantung():
    proyek, bg, _ = _jalankan_background(jawaban=jawaban_lemah(), ai_response=_gagal())
    # bukan qualification_state Scoring / Manual Review
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Need Clarification")
    assert proyek.bant_score == 22
    assert proyek.ai_scoring_result is None
    assert bg.of_type(NotificationLog) == []


def test_ai_gagal_dan_rubrik_tidak_dapat_dihitung_manual_review():
    # Proyek legacy tanpa jawaban kuesioner: rubrik tidak bisa dihitung
    proyek = Project(
        id_project="PRJ-20250101-LEG001",
        project_name="P",
        customer_name="C",
        status="Intake",
        qualification_state="Scoring",
        qualification_answers=None,
        sales_pic=uuid.uuid4(),
    )
    bg = FakeSession()
    lead = _lead()

    async def _execute(stmt, *a, **k):
        if "FROM users" in str(stmt):
            return _result(items=[lead])
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    provider = MagicMock()
    provider.parse_document = AsyncMock(return_value=_gagal())

    import asyncio

    from app.services.scoring_engine import scoring_engine

    with patch("app.services.scoring_engine.llm_factory.get_provider", return_value=provider), patch(
        "app.services.scoring_engine.asyncio.sleep", new=AsyncMock()
    ):
        asyncio.run(
            scoring_engine.score_documents(
                proyek.id_project, [(b"%PDF-1.4", "application/pdf", "mom.pdf")], bg
            )
        )
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Manual Review")


def test_exception_tak_terduga_di_luar_retry_llm_jatuh_ke_rubrik_lolos():
    proyek, bg, _ = _jalankan_background(
        jawaban=jawaban_kuat(), provider_error=RuntimeError("DB/tak terduga")
    )
    # tidak menggantung di qualification_state Scoring
    assert (proyek.status, proyek.qualification_state) == ("Awaiting Assignment", "Qualified")
    assert proyek.bant_score == 100
    assert len(bg.of_type(NotificationLog)) == 1


def test_exception_tak_terduga_jatuh_ke_rubrik_tidak_lolos():
    proyek, bg, _ = _jalankan_background(
        jawaban=jawaban_lemah(), provider_error=RuntimeError("DB/tak terduga")
    )
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Need Clarification")
    assert proyek.bant_score == 22
    assert bg.of_type(NotificationLog) == []


def test_exception_tak_terduga_tidak_menimpa_status_assigned():
    proyek, bg, _ = _jalankan_background(
        status_awal="Assigned", jawaban=jawaban_kuat(), provider_error=RuntimeError("x")
    )
    assert proyek.status == "Assigned"
    assert bg.of_type(NotificationLog) == []


@pytest.mark.parametrize("status", ["Assigned", "Submitted", "Won"])
def test_hasil_ai_terlambat_tidak_menimpa_assigned_dan_sesudahnya(status):
    ai_lama = {"sub_scores": {"budget": 1, "authority": 1, "need": 1, "timeline": 1}}
    proyek, bg, _ = _jalankan_background(
        status_awal=status,
        jawaban=jawaban_lemah(),
        ai_response=_sukses(budget=25, authority=25, need=25, timeline=25),
        ai_lama=ai_lama,
    )
    assert proyek.status == status
    assert proyek.bant_score == 22
    assert proyek.ai_scoring_result == ai_lama
    assert bg.of_type(NotificationLog) == []


def test_ai_gagal_terlambat_tidak_menimpa_assigned():
    proyek, bg, _ = _jalankan_background(
        status_awal="Assigned", jawaban=jawaban_kuat(), ai_response=_gagal()
    )
    assert proyek.status == "Assigned"
    assert proyek.bant_score == 22
    assert bg.of_type(NotificationLog) == []
