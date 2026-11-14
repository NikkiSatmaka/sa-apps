"""
Test seam tiket 5B-3 (#35): re-summarize otomatis Requirement saat sumber berubah.

Seam: (1) titik masuk background `resummarize_if_source_changed` dengan sesi DB dan LLM
di-mock di boundary; (2) HTTP API PUT qualification-answers (TestClient) untuk pemicu
edit jawaban; (3) `extract_source_documents` untuk pemicu ekstraksi selesai.
Hanya menegaskan perilaku eksternal: isi/hash Requirement, jumlah panggilan LLM.
"""

import asyncio
import json
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import Document
from app.models.project import Project
from app.services import requirement_generator as rg
from app.services.llm_provider import LLMResponse
from tests.test_projects_questionnaire_api import FakeSession, _result, jawaban_kuat
from tests.test_requirement_generate_api import (
    _Ctx,
    _source,
    llm_ok,
)

BARU = [{"kategori": "Teknis", "butir": "Butir hasil re-summarize"}]


def _proyek(status="Awaiting Assignment", answers=None):
    return Project(
        id_project="PRJ-X",
        project_name="P",
        customer_name="C",
        status=status,
        sales_pic=uuid.uuid4(),
        target_submit=date.today() + timedelta(days=30),
        qualification_answers=answers if answers is not None else jawaban_kuat(),
        qualification_schema_version=1,
        requirement_generation_status="ready",
    )


def _requirement(answers, sources, status="Draft", overridden=False, stale=False):
    pairs = [(s.doc_type, s.extracted_text) for s in sources if s.extraction_status == "extracted"]
    h = rg.compute_source_hash(answers, pairs)
    return Document(
        id_doc="DOC-REQ",
        id_project="PRJ-X",
        doc_type="Requirement",
        folder_type="Inventory",
        status=status,
        content=[{"id": "lama0001", "kategori": "Fungsional", "butir": "Butir lama"}],
        is_overridden=overridden,
        source_hash="0" * 64 if stale else h,
    )


def _jalankan(proyek, requirement, sources, llm=None, panggil=1):
    """Jalankan titik masuk `panggil` kali berurutan; return (provider, requirement)."""
    bg = FakeSession()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sources)
        if "FROM documents" in sql:
            return _result(one=requirement)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    provider = MagicMock()
    provider.complete_text = AsyncMock(return_value=llm or llm_ok(BARU))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
    ), patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()):
        for _ in range(panggil):
            asyncio.run(rg.resummarize_if_source_changed("PRJ-X"))
    return provider, requirement


def _butir(doc):
    return [i["butir"] for i in doc.content]


# --------------------------------------------------------------------------- hash berubah
def test_hash_berubah_dan_belum_override_di_resummarize_dan_hash_baru_disimpan():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, stale=True)
    provider, req = _jalankan(_proyek(), req, sumber)
    assert _butir(req) == ["Butir hasil re-summarize"]
    assert req.source_hash == rg.compute_source_hash(jawaban_kuat(), [("MoM", "MoM baru")])
    assert req.generated_at is not None
    assert req.is_overridden is False
    provider.complete_text.assert_awaited_once()


def test_hash_sama_tidak_memicu_apa_pun():
    sumber = [_source(text="MoM")]
    req = _requirement(jawaban_kuat(), sumber)
    provider, req = _jalankan(_proyek(), req, sumber)
    provider.complete_text.assert_not_called()
    assert _butir(req) == ["Butir lama"]


def test_perubahan_field_header_tidak_mengubah_hash_dan_tidak_memicu():
    sumber = [_source(text="MoM")]
    req = _requirement(jawaban_kuat(), sumber)
    proyek = _proyek()
    proyek.project_name = "Nama proyek diganti"
    proyek.customer_name = "Customer diganti"
    proyek.target_submit = date.today() + timedelta(days=90)
    provider, req = _jalankan(proyek, req, sumber)
    provider.complete_text.assert_not_called()


# --------------------------------------------------------------------------- tidak diubah
def test_requirement_sudah_di_override_tidak_diubah():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, overridden=True, stale=True)
    provider, req = _jalankan(_proyek(), req, sumber)
    provider.complete_text.assert_not_called()
    assert _butir(req) == ["Butir lama"]
    assert req.source_hash == "0" * 64


def test_dokumen_final_tidak_diubah():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, status="Final", stale=True)
    provider, req = _jalankan(_proyek(), req, sumber)
    provider.complete_text.assert_not_called()
    assert _butir(req) == ["Butir lama"]


@pytest.mark.parametrize("status", ["Won", "Lost", "Handed Over"])
def test_status_terminal_tidak_di_resummarize(status):
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, stale=True)
    provider, req = _jalankan(_proyek(status=status), req, sumber)
    provider.complete_text.assert_not_called()
    assert _butir(req) == ["Butir lama"]


def test_requirement_belum_ada_tidak_ada_yang_dilakukan():
    provider, _ = _jalankan(_proyek(), None, [_source(text="MoM")])
    provider.complete_text.assert_not_called()


def test_proyek_tidak_ada_tidak_melempar():
    provider, _ = _jalankan(None, None, [])
    provider.complete_text.assert_not_called()


# --------------------------------------------------------------------------- kegagalan & idempoten
def test_gagal_llm_mempertahankan_requirement_lama_dan_tidak_menandai_failed():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, stale=True)
    proyek = _proyek()
    provider, req = _jalankan(
        proyek, req, sumber, llm=LLMResponse(status="error", error_type="timeout", error_message="x")
    )
    assert _butir(req) == ["Butir lama"]
    assert req.source_hash == "0" * 64  # hash lama → pemicu berikutnya mencoba lagi
    assert proyek.requirement_generation_status == "ready"


def test_dua_pemicu_berurutan_hanya_satu_generate():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, stale=True)
    provider, req = _jalankan(_proyek(), req, sumber, panggil=2)
    assert provider.complete_text.await_count == 1


def test_dua_pemicu_bersamaan_tidak_membuat_dua_generate_bersamaan():
    sumber = [_source(text="MoM baru")]
    req = _requirement(jawaban_kuat(), sumber, stale=True)
    bg = FakeSession()
    proyek = _proyek()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sumber)
        if "FROM documents" in sql:
            return _result(one=req)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    aktif = {"sekarang": 0, "maks": 0}

    async def _llm(*a, **k):
        aktif["sekarang"] += 1
        aktif["maks"] = max(aktif["maks"], aktif["sekarang"])
        await asyncio.sleep(0.01)
        aktif["sekarang"] -= 1
        return llm_ok(BARU)

    provider = MagicMock()
    provider.complete_text = AsyncMock(side_effect=_llm)

    async def _dua():
        await asyncio.gather(
            rg.resummarize_if_source_changed("PRJ-X"), rg.resummarize_if_source_changed("PRJ-X")
        )

    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
    ):
        asyncio.run(_dua())
    assert aktif["maks"] == 1
    assert provider.complete_text.await_count == 1


# --------------------------------------------------------------------------- pemicu API: edit jawaban
def test_koreksi_jawaban_lead_sa_setelah_gate_memicu_resummarize():
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.core.dependencies import get_current_user
    from app.main import app
    from tests.test_projects_questionnaire_api import _lead

    lead = _lead()
    proyek = _proyek()
    session = FakeSession()
    session.execute = AsyncMock(return_value=_result(one=proyek))

    async def _db():
        yield session

    spy = AsyncMock()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: lead
    try:
        with patch("app.api.projects.resummarize_if_source_changed", new=spy):
            resp = TestClient(app).put(
                "/api/v1/projects/PRJ-X/qualification-answers",
                json=jawaban_kuat(pic_nama="Budi Baru"),
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    spy.assert_awaited_once_with("PRJ-X")


# --------------------------------------------------------------------------- pemicu: ekstraksi selesai
def test_ekstraksi_selesai_memicu_resummarize_requirement_yang_dibuat_sebelumnya():
    from app.models.source_document import SourceDocument
    from app.services.source_document_extractor import extract_source_documents

    doc = SourceDocument(
        id=uuid.uuid4(),
        id_project="PRJ-X",
        filename="mom.pdf",
        doc_type="MoM",
        size_bytes=5,
        extraction_status="pending",
    )
    bg = FakeSession()
    bg.get = AsyncMock(return_value=doc)
    provider = MagicMock()
    provider.parse_document = AsyncMock(
        return_value=LLMResponse(status="success", content="Isi MoM hasil ekstraksi")
    )
    spy = AsyncMock()
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.source_document_extractor.llm_factory.get_provider", return_value=provider
    ), patch("app.services.source_document_extractor.resummarize_if_source_changed", new=spy):
        asyncio.run(
            extract_source_documents("PRJ-X", [(doc.id, "mom.pdf", b"%PDF-1.4 x", "application/pdf")])
        )
    assert doc.extraction_status == "extracted"
    spy.assert_awaited_once_with("PRJ-X")


def test_ekstraksi_setelah_requirement_ada_end_to_end_memperbarui_isi():
    """Requirement dibuat tanpa sumber (ekstraksi belum selesai); ekstraksi selesai → diperbarui."""
    req = _requirement(jawaban_kuat(), [])
    sumber_baru = [_source(text="Isi MoM hasil ekstraksi")]
    provider, req = _jalankan(_proyek(), req, sumber_baru)
    assert _butir(req) == ["Butir hasil re-summarize"]
