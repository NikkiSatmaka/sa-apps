"""
Test seam utama tiket 5A-1 (#26): create opportunity dengan Kuesioner kualifikasi,
skor dihitung backend. Lewat HTTP API (TestClient) dengan sesi DB dan LLM di-mock di boundary.
Hanya menegaskan perilaku eksternal: respons, status akhir, skor, baris tersimpan, notifikasi.
"""

import json
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.notification_log import NotificationLog
from app.models.project import Project

URL = "/api/v1/projects"


# --------------------------------------------------------------------------- helpers
def _user(role="Sales"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "sales@company.com"
    u.name = "Sales"
    u.role = role
    return u


def _result(items=None, one=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=one)
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items or [])
    r.scalars = MagicMock(return_value=scalars)
    return r


class FakeSession:
    """Sesi DB palsu: menyimpan yang di-add; execute selalu mengembalikan hasil yang dikonfigurasi."""

    def __init__(self, execute_result=None):
        self.added = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.execute = AsyncMock(return_value=execute_result or _result())

    def add(self, obj):
        self.added.append(obj)

    def of_type(self, cls):
        return [o for o in self.added if isinstance(o, cls)]


@contextmanager
def _api(user=None, execute_result=None):
    user = user or _user()
    session = FakeSession(execute_result)

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()


def _lead():
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.role = "Lead_SA"
    return lead


def jawaban_kuat(**override):
    data = {
        "mrr": 5_000_000,
        "budget_dialokasikan": "Ya",
        "pic_nama": "Budi",
        "pic_jabatan": "CTO",
        "pic_email": "budi@contoh.co.id",
        "peran_pic": "Pengambil keputusan",
        "stakeholder_lain": "Tim keuangan",
        "masalah_bisnis": "Data center lama sering down dan biaya operasional membengkak " * 2,
        "jenis_workload": "Migrasi ke cloud",
        "lingkungan": "On-prem",
        "skala": "40 server, 20 TB",
        "persyaratan_khusus": "Data residency Indonesia",
        "kompetitor": "Vendor X",
        "target_go_live": "≤ 3 bulan",
    }
    data.update(override)
    return data


def jawaban_lemah():
    """Hanya field wajib, semua serba 'Tidak tahu' → total 22."""
    return {
        "budget_dialokasikan": "Tidak tahu",
        "peran_pic": "Tidak tahu",
        "masalah_bisnis": "Butuh cloud",
        "jenis_workload": "Lainnya",
        "lingkungan": "Cloud",
        "skala": "5 server",
        "target_go_live": "Tidak tahu",
    }


def _form(answers=None, **override):
    data = {
        "project_name": "Proyek Uji",
        "customer_name": "PT Uji",
        "target_submit": str(date.today() + timedelta(days=30)),
        "estimasi_nilai": "500000000",
    }
    if answers is not None:
        data["qualification_answers"] = json.dumps(answers)
    data.update(override)
    return data


def _errors(resp):
    return {e["field"]: e["reason"] for e in resp.json()["data"]}


# --------------------------------------------------------------------------- create tanpa file
def test_create_jawaban_kuat_lolos_gate_dan_notifikasi_lead_sa():
    lead = _lead()
    with _api(execute_result=_result(items=[lead])) as (client, session):
        resp = client.post(URL, data=_form(jawaban_kuat()))
    assert resp.status_code == 201
    d = resp.json()["data"]
    assert d["status"] == "Pending Assignment"
    assert d["bant_score"] == 100
    assert d["sub_scores"] == {"budget": 25, "authority": 25, "need": 25, "timeline": 25}
    assert d["scoring_triggered"] is False
    assert "message_bant" not in d

    proyek = session.of_type(Project)[0]
    assert proyek.status == "Pending Assignment"
    assert proyek.bant_score == 100
    assert proyek.qualification_schema_version == 1
    assert proyek.qualification_answers["budget_dialokasikan"] == "Ya"
    notif = session.of_type(NotificationLog)
    assert [n.recipient_user_id for n in notif] == [lead.id]
    assert notif[0].reference_id == proyek.id_project


def test_create_jawaban_lemah_need_clarification_dengan_feedback_tanpa_notifikasi():
    with _api(execute_result=_result(items=[_lead()])) as (client, session):
        resp = client.post(URL, data=_form(jawaban_lemah()))
    assert resp.status_code == 201
    d = resp.json()["data"]
    assert d["status"] == "Need Clarification"
    assert d["bant_score"] == 22  # budget 0 + authority 0 + need 12 + timeline 10
    assert "Budget" in d["feedback"] and "Authority" in d["feedback"]
    assert "Need" in d["feedback"] and "Timeline" in d["feedback"]
    assert session.of_type(NotificationLog) == []
    assert session.of_type(Project)[0].status == "Need Clarification"


def test_mrr_dinilai_tetapi_estimasi_nilai_tidak():
    with _api() as (client, _):
        tanpa_mrr = client.post(URL, data=_form(jawaban_lemah())).json()["data"]
    with _api() as (client, _):
        dengan_mrr = client.post(URL, data=_form({**jawaban_lemah(), "mrr": 1_000_000})).json()["data"]
    with _api() as (client, _):
        estimasi_besar = client.post(
            URL, data=_form(jawaban_lemah(), estimasi_nilai="900000000000")
        ).json()["data"]
    assert dengan_mrr["bant_score"] == tanpa_mrr["bant_score"] + 10
    assert estimasi_besar["bant_score"] == tanpa_mrr["bant_score"]


def test_skor_mentah_dari_klien_diabaikan_di_form_dan_ditolak_di_jawaban():
    # Field form tak dikenal diabaikan: skor tetap dari rubrik
    with _api() as (client, _):
        resp = client.post(
            URL, data=_form(jawaban_lemah(), bant_score="100", bant_detail='{"budget":25}')
        )
    assert resp.status_code == 201
    assert resp.json()["data"]["bant_score"] == 22
    assert resp.json()["data"]["status"] == "Need Clarification"
    # Kunci tak dikenal di dalam jawaban ditolak
    with _api() as (client, session):
        resp = client.post(URL, data=_form({**jawaban_lemah(), "bant_score": 100}))
    assert resp.status_code == 422
    assert "qualification_answers.bant_score" in _errors(resp)
    assert session.of_type(Project) == []


# --------------------------------------------------------------------------- validasi 422
def test_jawaban_wajib_kurang_422_daftar_field_reason_tanpa_proyek():
    with _api() as (client, session):
        resp = client.post(URL, data=_form({"mrr": 1000}))
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "error"
    errors = _errors(resp)
    for f in (
        "budget_dialokasikan", "peran_pic", "masalah_bisnis",
        "jenis_workload", "lingkungan", "skala", "target_go_live",
    ):
        assert f"qualification_answers.{f}" in errors, f
    assert all(isinstance(r, str) and r for r in errors.values())
    assert session.of_type(Project) == []
    session.commit.assert_not_awaited()


def test_qualification_answers_hilang_422():
    with _api() as (client, session):
        resp = client.post(URL, data=_form())
    assert resp.status_code == 422
    assert "qualification_answers" in _errors(resp)
    assert session.of_type(Project) == []


def test_qualification_answers_bukan_json_422():
    with _api() as (client, _):
        resp = client.post(URL, data=_form(qualification_answers="{bukan json"))
    assert resp.status_code == 422
    assert "qualification_answers" in _errors(resp)


@pytest.mark.parametrize(
    "override,field",
    [
        ({"budget_dialokasikan": "Mungkin"}, "budget_dialokasikan"),
        ({"peran_pic": "Bos"}, "peran_pic"),
        ({"jenis_workload": "Lain-lain"}, "jenis_workload"),
        ({"lingkungan": "Edge"}, "lingkungan"),
        ({"target_go_live": "1 tahun"}, "target_go_live"),
        ({"mrr": -5}, "mrr"),
        ({"mrr": "banyak"}, "mrr"),
        ({"masalah_bisnis": "   "}, "masalah_bisnis"),
        ({"pic_email": "bukan-email"}, "pic_email"),
    ],
)
def test_nilai_tidak_valid_422_per_field(override, field):
    with _api() as (client, session):
        resp = client.post(URL, data=_form({**jawaban_kuat(), **override}))
    assert resp.status_code == 422
    assert f"qualification_answers.{field}" in _errors(resp)
    assert session.of_type(Project) == []


def test_error_header_dan_kuesioner_dilaporkan_bersama():
    with _api() as (client, _):
        resp = client.post(URL, data=_form({"mrr": 1}, project_name="   "))
    errors = _errors(resp)
    assert "project_name" in errors
    assert "qualification_answers.masalah_bisnis" in errors


# --------------------------------------------------------------------------- dengan file (perilaku file tidak berubah)
def test_create_dengan_file_status_scoring_pending_trigger_scoring_dan_jawaban_tersimpan():
    pdf = ("files", ("mom.pdf", BytesIO(b"%PDF-1.4 isi"), "application/pdf"))
    with patch("app.api.projects._trigger_scoring_engine", new=AsyncMock()) as trigger:
        with _api() as (client, session):
            resp = client.post(URL, data=_form(jawaban_kuat(), file_types=["MoM"]), files=[pdf])
    assert resp.status_code == 201
    d = resp.json()["data"]
    assert d["status"] == "Scoring Pending"
    assert d["scoring_triggered"] is True
    trigger.assert_awaited_once()
    proyek = session.of_type(Project)[0]
    assert proyek.qualification_answers is not None
    assert proyek.qualification_schema_version == 1
    assert session.of_type(NotificationLog) == []


# --------------------------------------------------------------------------- guard status pada hasil scoring AI
AI_JSON = json.dumps(
    {
        "budget": {"score": 25, "evidence": "ada"},
        "authority": {"score": 25, "evidence": "ada"},
        "need": {"score": 25, "evidence": "ada"},
        "timeline": {"score": 25, "evidence": "ada"},
        "use_case_tags": ["cloud"],
    }
)


def _jalankan_create_dengan_file_dan_scoring_ai(status_saat_hasil_tiba, bant_detail=None):
    """
    Create dengan file; saat background scoring AI selesai, proyek sudah berstatus
    `status_saat_hasil_tiba` (simulasi hasil terlambat). Return (proyek, sesi_background).
    """
    from app.services.llm_provider import LLMResponse

    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status=status_saat_hasil_tiba,
        bant_score=70 if status_saat_hasil_tiba != "New" else None,
        bant_detail=bant_detail,
        sales_pic=uuid.uuid4(),
    )
    bg = FakeSession()
    lead = _lead()

    async def _execute(stmt, *a, **k):
        text = str(stmt)
        if "FROM users" in text:
            return _result(items=[lead])
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)

    class _Ctx:
        async def __aenter__(self):
            return bg

        async def __aexit__(self, *exc):
            return False

    provider = MagicMock()
    provider.parse_document = AsyncMock(return_value=LLMResponse(status="success", content=AI_JSON))
    pdf = ("files", ("mom.pdf", BytesIO(b"%PDF-1.4 isi"), "application/pdf"))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx()), patch(
        "app.services.scoring_engine.llm_factory.get_provider", return_value=provider
    ):
        with _api() as (client, _):
            resp = client.post(URL, data=_form(jawaban_kuat(), file_types=["MoM"]), files=[pdf])
    assert resp.status_code == 201
    return proyek, bg


@pytest.mark.parametrize(
    "status", ["Assigned", "In Progress", "Pending Assignment", "Manual Review Required"]
)
def test_hasil_scoring_terlambat_tidak_menimpa_status_lanjutan(status):
    proyek, bg = _jalankan_create_dengan_file_dan_scoring_ai(status)
    assert proyek.status == status
    assert proyek.bant_score == 70  # skor lama tidak ditimpa
    assert bg.of_type(NotificationLog) == []


def test_hasil_scoring_ai_pada_status_new_diterapkan_dan_lead_sa_dinotifikasi():
    proyek, bg = _jalankan_create_dengan_file_dan_scoring_ai("New")
    assert proyek.status == "Pending Assignment"
    assert proyek.bant_score == 100
    assert len(bg.of_type(NotificationLog)) == 1


def test_scoring_ai_tidak_menimpa_metadata_legacy_di_bant_detail():
    proyek, _ = _jalankan_create_dengan_file_dan_scoring_ai(
        "New", bant_detail={"budget_mrr": 123, "pic_name": "Lama"}
    )
    assert proyek.bant_detail["budget_mrr"] == 123
    assert proyek.bant_detail["pic_name"] == "Lama"
    assert proyek.bant_detail["budget"] == 25


# --------------------------------------------------------------------------- PATCH tidak boleh menimpa sub-skor
def _patch(body):
    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status="Need Clarification",
        bant_score=22,
        bant_detail={"budget": 0, "authority": 0, "need": 12, "timeline": 10, "budget_mrr": 5},
        sales_pic=uuid.uuid4(),
    )
    with _api(user=_user("Lead_SA"), execute_result=_result(one=proyek)) as (client, _):
        resp = client.patch(f"{URL}/{proyek.id_project}", json=body)
    return resp, proyek


@pytest.mark.parametrize("kunci", ["budget", "authority", "need", "timeline"])
def test_patch_bant_detail_tidak_boleh_menimpa_subskor(kunci):
    resp, proyek = _patch({"bant_detail": {kunci: 25}})
    assert resp.status_code == 422
    assert f"bant_detail.{kunci}" in _errors(resp)
    assert proyek.bant_detail[kunci] in (0, 12, 10)  # tidak berubah


def test_patch_bant_detail_metadata_legacy_tetap_boleh():
    resp, proyek = _patch({"bant_detail": {"budget_mrr": 99, "pic_name": "Baru"}})
    assert resp.status_code == 200
    assert proyek.bant_detail["budget_mrr"] == 99
    assert proyek.bant_detail["budget"] == 0
