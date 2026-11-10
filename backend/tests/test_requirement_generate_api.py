"""
Test seam utama tiket 5B-1 (#33): Requirement ter-generate otomatis saat proyek lolos gate.

Lewat HTTP API (TestClient); sesi DB dan provider LLM di-mock di boundary. Hanya
menegaskan perilaku eksternal: baris Document tersimpan, status generate di proyek,
respons, dan prompt yang dikirim ke LLM.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import Document
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.services.llm_provider import LLMResponse
from tests.test_projects_questionnaire_api import (
    URL,
    FakeSession,
    _api,
    _form,
    _lead,
    _result,
    _user,
    jawaban_kuat,
    jawaban_lemah,
)

ITEMS = [
    {"kategori": "Fungsional", "butir": "Migrasi 40 server ke cloud"},
    {"kategori": "Kepatuhan", "butir": "Data residency Indonesia"},
]


def llm_ok(items=None):
    return LLMResponse(status="success", content=json.dumps({"items": items or ITEMS}))


def _source(status="extracted", text="Isi MoM", tipe="MoM", truncated=False):
    return SourceDocument(
        id=uuid.uuid4(),
        id_project="PRJ-X",
        filename="mom.pdf",
        doc_type=tipe,
        size_bytes=10,
        extraction_status=status,
        extracted_text=text if status == "extracted" else None,
        truncated=truncated,
    )


class _Ctx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _bg_session(project_getter, sources=None, existing=None):
    """Sesi background: dispatch query berdasarkan tabel."""
    bg = FakeSession()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sources or [])
        if "FROM documents" in sql:
            return _result(one=existing)
        if "FROM projects" in sql:
            return _result(one=project_getter())
        return _result()

    bg.execute = AsyncMock(side_effect=_execute)
    return bg


def _create(
    jawaban,
    llm,
    sources=None,
    existing=None,
    max_source_chars=None,
):
    """Create tanpa file; jalankan background generate. Return (resp, req_session, bg, provider)."""
    provider = MagicMock()
    provider.complete_text = AsyncMock(side_effect=llm if isinstance(llm, list) else None,
                                       return_value=None if isinstance(llm, list) else llm)
    holder = {}
    bg = _bg_session(lambda: holder["session"].of_type(Project)[0], sources, existing)
    patches = [
        patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)),
        patch("app.services.requirement_generator.llm_factory.get_provider", return_value=provider),
        patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()),
    ]
    if max_source_chars is not None:
        patches.append(
            patch("app.services.requirement_generator.settings.LLM_MAX_SOURCE_CHARS", max_source_chars)
        )
    for p in patches:
        p.start()
    try:
        with _api(execute_result=_result(items=[_lead()])) as (client, session):
            holder["session"] = session
            resp = client.post(URL, data=_form(jawaban))
    finally:
        for p in reversed(patches):
            p.stop()
    return resp, session, bg, provider


def _docs(bg):
    return bg.of_type(Document)


# --------------------------------------------------------------------------- lolos / gagal gate
def test_proyek_lolos_gate_memiliki_requirement_terstruktur():
    resp, session, bg, provider = _create(jawaban_kuat(), llm_ok())
    assert resp.status_code == 201
    proyek = session.of_type(Project)[0]
    assert proyek.status == "Pending Assignment"
    assert proyek.requirement_generation_status == "ready"
    [doc] = _docs(bg)
    assert doc.doc_type == "Requirement"
    assert doc.folder_type == "Inventory"
    assert doc.status == "Draft"
    assert doc.gdrive_link is None
    assert doc.created_by is None
    assert doc.id_project == proyek.id_project
    assert [(i["kategori"], i["butir"]) for i in doc.content] == [
        (i["kategori"], i["butir"]) for i in ITEMS
    ]
    assert doc.is_overridden is False
    assert doc.source_truncated is False
    assert len(doc.source_hash) == 64
    assert doc.generated_at is not None


def test_prompt_memuat_jawaban_berlabel_dibungkus_delimiter():
    _, _, _, provider = _create(jawaban_kuat(), llm_ok())
    prompt = provider.complete_text.call_args.args[0]
    assert "<<<USER_CONTENT_START>>>" in prompt
    assert "Data residency Indonesia" in prompt
    assert "Fungsional, Teknis, Kepatuhan, Integrasi, Timeline, Asumsi" in prompt


def test_proyek_gagal_gate_tidak_punya_requirement_dan_llm_tidak_dipanggil():
    resp, session, bg, provider = _create(jawaban_lemah(), llm_ok())
    assert resp.status_code == 201
    proyek = session.of_type(Project)[0]
    assert proyek.status == "Need Clarification"
    assert proyek.requirement_generation_status is None
    assert _docs(bg) == []
    provider.complete_text.assert_not_called()


# --------------------------------------------------------------------------- keluaran malformed / gagal
@pytest.mark.parametrize(
    "respons",
    [
        LLMResponse(status="success", content="bukan json sama sekali"),
        LLMResponse(status="success", content=json.dumps({"items": []})),
        LLMResponse(
            status="success",
            content=json.dumps({"items": [{"kategori": "Lainnya", "butir": "x"}]}),
        ),
        LLMResponse(status="error", error_type="timeout", error_message="timeout"),
    ],
)
def test_keluaran_malformed_ditolak_tidak_tersimpan_dan_alur_proyek_utuh(respons):
    resp, session, bg, provider = _create(jawaban_kuat(), respons)
    assert resp.status_code == 201  # alur proyek tidak rusak
    proyek = session.of_type(Project)[0]
    assert proyek.status == "Pending Assignment"
    assert proyek.requirement_generation_status == "failed"
    assert _docs(bg) == []
    assert provider.complete_text.await_count == 3  # retry mengikuti pola panggilan LLM


def test_exception_provider_ditangani_sebagai_gagal():
    resp, session, bg, _ = _create(
        jawaban_kuat(), [RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")]
    )
    assert resp.status_code == 201
    assert session.of_type(Project)[0].requirement_generation_status == "failed"
    assert _docs(bg) == []


def test_percobaan_kedua_valid_tetap_tersimpan():
    _, session, bg, provider = _create(
        jawaban_kuat(), [LLMResponse(status="success", content="rusak"), llm_ok()]
    )
    assert session.of_type(Project)[0].requirement_generation_status == "ready"
    assert len(_docs(bg)) == 1
    assert provider.complete_text.await_count == 2


# --------------------------------------------------------------------------- idempoten
def test_requirement_sudah_ada_tidak_dibuat_dua_kali():
    ada = Document(id_doc="DOC-1", id_project="PRJ-X", doc_type="Requirement")
    _, session, bg, provider = _create(jawaban_kuat(), llm_ok(), existing=ada)
    assert _docs(bg) == []
    provider.complete_text.assert_not_called()
    assert session.of_type(Project)[0].requirement_generation_status == "ready"


# --------------------------------------------------------------------------- sumber & pemotongan
def test_hanya_source_document_extracted_masuk_prompt():
    sources = [
        _source(text="ISI-MOM-EXTRACTED"),
        _source(status="pending"),
        _source(status="failed", tipe="RFP"),
    ]
    _, _, bg, provider = _create(jawaban_kuat(), llm_ok(), sources=sources)
    prompt = provider.complete_text.call_args.args[0]
    assert "ISI-MOM-EXTRACTED" in prompt
    assert len(_docs(bg)) == 1


def test_teks_terpotong_menyetel_source_truncated_dan_anggaran_dihormati():
    sources = [_source(text="x" * 5000, tipe="MoM"), _source(text="y" * 5000, tipe="RFP")]
    _, _, bg, provider = _create(
        jawaban_kuat(), llm_ok(), sources=sources, max_source_chars=2000
    )
    [doc] = _docs(bg)
    assert doc.source_truncated is True
    prompt = provider.complete_text.call_args.args[0]
    # Kuesioner pendek utuh; dua sumber panjang membagi sisa anggaran secara merata.
    assert prompt.count("x") <= 1000 and prompt.count("y") <= 1000
    assert "x" * 400 in prompt and "y" * 400 in prompt


def test_tanpa_pemotongan_flag_false():
    _, _, bg, _ = _create(jawaban_kuat(), llm_ok(), sources=[_source(text="pendek")])
    assert _docs(bg)[0].source_truncated is False


def test_source_document_terpotong_ekstraksi_menyetel_flag():
    _, _, bg, _ = _create(jawaban_kuat(), llm_ok(), sources=[_source(truncated=True)])
    assert _docs(bg)[0].source_truncated is True


def test_hash_tidak_bergantung_urutan_source_document():
    s1, s2 = _source(text="satu", tipe="MoM"), _source(text="dua", tipe="RFP")
    _, _, bg_a, _ = _create(jawaban_kuat(), llm_ok(), sources=[s1, s2])
    _, _, bg_b, _ = _create(jawaban_kuat(), llm_ok(), sources=[s2, s1])
    assert _docs(bg_a)[0].source_hash == _docs(bg_b)[0].source_hash


# --------------------------------------------------------------------------- jalur lain menuju Pending Assignment
def _put_rescore(jawaban_baru, llm):
    """Sales mengedit jawaban saat Need Clarification → lolos gate → generate."""
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.core.dependencies import get_current_user
    from app.main import app

    user = _user("Sales")
    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status="Need Clarification",
        sales_pic=user.id,
        target_submit=date.today() + timedelta(days=30),
        qualification_answers=jawaban_lemah(),
        qualification_schema_version=1,
        bant_score=22,
        bant_detail={"budget": 0, "authority": 0, "need": 12, "timeline": 10},
    )
    req = FakeSession()
    req.execute = AsyncMock(side_effect=_exec_req(_lead(), proyek))
    bg = _bg_session(lambda: proyek)
    provider = MagicMock()
    provider.complete_text = AsyncMock(return_value=llm)

    async def _db():
        yield req

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
            "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
        ), patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()):
            resp = TestClient(app).put(
                f"{URL}/{proyek.id_project}/qualification-answers", json=jawaban_baru
            )
    finally:
        app.dependency_overrides.clear()
    return resp, proyek, bg, provider


def _exec_req(lead, proyek):
    async def _execute(stmt, *a, **k):
        return _result(items=[lead]) if "FROM users" in str(stmt) else _result(one=proyek)

    return _execute


def test_rescore_edit_jawaban_yang_lolos_gate_men_generate_requirement():
    resp, proyek, bg, _ = _put_rescore(jawaban_kuat(), llm_ok())
    assert resp.status_code == 200
    assert proyek.status == "Pending Assignment"
    assert proyek.requirement_generation_status == "ready"
    assert len(_docs(bg)) == 1


def test_rescore_yang_tetap_gagal_gate_tidak_men_generate():
    resp, proyek, bg, provider = _put_rescore(jawaban_lemah(), llm_ok())
    assert resp.status_code == 200
    assert proyek.status == "Need Clarification"
    assert proyek.requirement_generation_status is None
    assert _docs(bg) == []
    provider.complete_text.assert_not_called()


def test_override_skor_lead_sa_yang_lolos_gate_men_generate_requirement():
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.core.dependencies import get_current_user
    from app.main import app

    lead = _lead()
    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status="Need Clarification",
        sales_pic=uuid.uuid4(),
        target_submit=date.today() + timedelta(days=30),
        qualification_answers=jawaban_lemah(),
        qualification_schema_version=1,
        bant_score=22,
        bant_detail={"budget": 0, "authority": 0, "need": 12, "timeline": 10},
    )
    req = FakeSession()
    req.execute = AsyncMock(side_effect=_exec_req(lead, proyek))
    bg = _bg_session(lambda: proyek)
    provider = MagicMock()
    provider.complete_text = AsyncMock(return_value=llm_ok())

    async def _db():
        yield req

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: lead
    try:
        with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
            "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
        ), patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()):
            resp = TestClient(app).post(
                f"/api/v1/projects/{proyek.id_project}/score-manual",
                json={"budget": 25, "authority": 25, "need": 25, "timeline": 25, "reason": "Override uji"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    assert proyek.status == "Pending Assignment"
    assert proyek.requirement_generation_status == "ready"
    assert len(_docs(bg)) == 1


def test_jalur_dengan_file_scoring_ai_lolos_gate_men_generate_requirement():
    from io import BytesIO

    from tests.test_scoring_pending_ai_merge_api import ai_json

    proyek = Project(
        id_project="PRJ-20250101-ABC123",
        project_name="P",
        customer_name="C",
        status="Scoring Pending",
        sales_pic=uuid.uuid4(),
        target_submit=date.today() + timedelta(days=30),
        qualification_answers=jawaban_lemah(),
        qualification_schema_version=1,
        bant_score=22,
        bant_detail={"budget": 0, "authority": 0, "need": 12, "timeline": 10},
    )
    bg = FakeSession()
    lead = _lead()
    sources = [_source(text="ISI-RFP-EKSTRAKSI", tipe="RFP")]

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM users" in sql:
            return _result(items=[lead])
        if "FROM source_documents" in sql:
            return _result(items=sources)
        if "FROM documents" in sql:
            return _result(one=None)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    provider = MagicMock()
    provider.parse_document = AsyncMock(
        return_value=LLMResponse(status="success", content=ai_json(25, 25, 25, 25))
    )
    provider.complete_text = AsyncMock(return_value=llm_ok())
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.scoring_engine.llm_factory.get_provider", return_value=provider
    ), patch("app.services.requirement_generator.llm_factory.get_provider", return_value=provider), patch(
        "app.api.projects.extract_source_documents", new=AsyncMock()
    ):
        with _api() as (client, _):
            resp = client.post(
                URL,
                data=_form(jawaban_lemah(), file_types=["RFP"]),
                files=[("files", ("rfp.pdf", BytesIO(b"%PDF-1.4 isi"), "application/pdf"))],
            )
    assert resp.status_code == 201
    assert proyek.status == "Pending Assignment"
    assert proyek.requirement_generation_status == "ready"
    assert len(_docs(bg)) == 1
    assert "ISI-RFP-EKSTRAKSI" in provider.complete_text.call_args.args[0]
