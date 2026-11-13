"""
Test seam tiket 5A-6 (#31): Source document — tipe MoM/RFP per file dan ekstraksi teks via LLM.
Lewat HTTP API (TestClient); sesi DB dan Gemini di-mock di boundary. Background task
(BackgroundTasks) dijalankan TestClient sebelum `post` kembali.
"""

import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import Document
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.services.llm_provider import LLMMetadata, LLMResponse
from tests.test_projects_questionnaire_api import (
    URL,
    FakeSession,
    _api,
    _errors,
    _form,
    _result,
    _user,
    jawaban_kuat,
)

PDF = "application/pdf"


def _pdf(name="mom.pdf", content=b"%PDF-1.4 isi"):
    return ("files", (name, BytesIO(content), PDF))


def _form_tipe(*tipe, **override):
    """Form create dengan `file_types` paralel terhadap `files` (indeks yang sama)."""
    data = _form(jawaban_kuat(), **override)
    data["file_types"] = list(tipe)
    return data


def _llm_ok(teks="Isi dokumen", finish="STOP"):
    return LLMResponse(
        status="success", content=teks, metadata=LLMMetadata(finish_reason=finish)
    )


class _BgSession(FakeSession):
    """Sesi background: `get` mencari baris SourceDocument yang di-add sesi request."""

    def __init__(self, request_session):
        super().__init__()
        self._req = request_session

    async def get(self, model, key):
        for o in self._req.of_type(model):
            if o.id == key:
                return o
        return None


class _Env:
    def __init__(self):
        self.provider = MagicMock()
        self.provider.parse_document = AsyncMock(return_value=_llm_ok())


def _jalankan(files, data, provider_response=None, provider_exc=None, user=None):
    """Create dengan file; ekstraksi memakai provider palsu. Return (resp, session, provider)."""
    env = _Env()
    if provider_response is not None:
        env.provider.parse_document = AsyncMock(return_value=provider_response)
    if provider_exc is not None:
        env.provider.parse_document = AsyncMock(side_effect=provider_exc)

    holder = {}

    class _Ctx:
        async def __aenter__(self):
            return _BgSession(holder["session"])

        async def __aexit__(self, *exc):
            return False

    with patch("app.api.projects._trigger_scoring_engine", new=AsyncMock()) as scoring, patch(
        "app.core.database.AsyncSessionLocal", new=lambda: _Ctx()
    ), patch(
        "app.services.source_document_extractor.llm_factory.get_provider",
        return_value=env.provider,
    ):
        with _api(user=user) as (client, session):
            holder["session"] = session
            resp = client.post(URL, data=data, files=files)
    return resp, session, env.provider, scoring


# --------------------------------------------------------------------------- tipe wajib per file
def test_tipe_wajib_per_file_422_per_file():
    resp, session, _, scoring = _jalankan([_pdf("a.pdf"), _pdf("b.pdf")], _form_tipe("MoM"))
    assert resp.status_code == 422
    errors = _errors(resp)
    assert "files[1].type" in errors and "files[0].type" not in errors
    assert session.of_type(Project) == []
    scoring.assert_not_awaited()


def test_tipe_selain_mom_rfp_ditolak():
    resp, _, _, _ = _jalankan([_pdf()], _form_tipe("Proposal"))
    assert resp.status_code == 422
    assert "files[0].type" in _errors(resp)


def test_tanpa_file_tidak_butuh_tipe_dan_tidak_ada_source_document():
    with _api() as (client, session):
        resp = client.post(URL, data=_form(jawaban_kuat()))
    assert resp.status_code == 201
    assert session.of_type(SourceDocument) == []


# --------------------------------------------------------------------------- ekstraksi
def test_ekstraksi_sukses_menyimpan_teks_dan_metadata_tanpa_file_asli():
    isi = b"%PDF-1.4 isi mom"
    resp, session, provider, _ = _jalankan(
        [_pdf("mom.pdf", isi)], _form_tipe("MoM"), provider_response=_llm_ok("Teks MoM lengkap")
    )
    assert resp.status_code == 201
    [doc] = session.of_type(SourceDocument)
    assert doc.id_project == resp.json()["data"]["id_project"]
    assert (doc.filename, doc.doc_type, doc.size_bytes) == ("mom.pdf", "MoM", len(isi))
    assert doc.extraction_status == "extracted"
    assert doc.extracted_text == "Teks MoM lengkap"
    assert doc.truncated is False
    # File asli tidak disimpan; tidak membuat baris Document
    assert session.of_type(Document) == []
    assert not any(isinstance(v, bytes) for v in vars(doc).values())
    # Panggilan terpisah dengan batas output 32768
    assert provider.parse_document.await_args.kwargs["max_output_tokens"] == 32768


def test_tipe_disimpan_per_file():
    resp, session, _, _ = _jalankan(
        [_pdf("a.pdf"), _pdf("b.pdf")], _form_tipe("MoM", "RFP")
    )
    assert resp.status_code == 201
    assert {d.filename: d.doc_type for d in session.of_type(SourceDocument)} == {
        "a.pdf": "MoM",
        "b.pdf": "RFP",
    }


@pytest.mark.parametrize("konten", ["", "   \n "])
def test_pdf_tanpa_teks_berstatus_empty(konten):
    _, session, _, _ = _jalankan([_pdf()], _form_tipe("RFP"), provider_response=_llm_ok(konten))
    [doc] = session.of_type(SourceDocument)
    assert doc.extraction_status == "empty"
    assert not doc.extracted_text


def test_kegagalan_llm_berstatus_failed_dan_create_tetap_201():
    err = LLMResponse(status="error", error_type="timeout", error_message="lambat")
    resp, session, _, scoring = _jalankan([_pdf()], _form_tipe("MoM"), provider_response=err)
    assert resp.status_code == 201
    [doc] = session.of_type(SourceDocument)
    assert doc.extraction_status == "failed"
    assert doc.extracted_text is None
    scoring.assert_awaited_once()


def test_exception_provider_berstatus_failed():
    resp, session, _, scoring = _jalankan(
        [_pdf()], _form_tipe("MoM"), provider_exc=RuntimeError("boom")
    )
    assert resp.status_code == 201
    assert session.of_type(SourceDocument)[0].extraction_status == "failed"
    scoring.assert_awaited_once()


def test_respons_terpotong_batas_token_set_truncated():
    _, session, _, _ = _jalankan(
        [_pdf()], _form_tipe("MoM"), provider_response=_llm_ok("Setengah", finish="MAX_TOKENS")
    )
    [doc] = session.of_type(SourceDocument)
    assert doc.extraction_status == "extracted"
    assert doc.truncated is True
    assert doc.extracted_text == "Setengah"


def test_guardrail_ukuran_dokumen_dipakai_sebelum_dikirim_ke_llm():
    with patch("app.utils.guardrails.settings") as s:
        s.LLM_MAX_DOCUMENT_BYTES = 5
        _, _, provider, _ = _jalankan([_pdf("mom.pdf", b"0123456789")], _form_tipe("MoM"))
    assert provider.parse_document.await_args.kwargs["file_content"] == b"01234"


# --------------------------------------------------------------------------- tidak menahan create / scoring
def test_kegagalan_total_ekstraksi_tidak_mempengaruhi_create_dan_scoring():
    def _sesi_rusak():
        raise RuntimeError("DB background tidak tersedia")

    with patch("app.core.database.AsyncSessionLocal", new=_sesi_rusak), patch(
        "app.api.projects._trigger_scoring_engine", new=AsyncMock()
    ) as scoring:
        with _api() as (client, session):
            resp = client.post(URL, data=_form_tipe("MoM"), files=[_pdf()])
    assert resp.status_code == 201
    assert resp.json()["data"]["scoring_triggered"] is True
    scoring.assert_awaited_once()


def test_ekstraksi_dijadwalkan_background_setelah_commit_bukan_inline():
    """Saat ekstraksi mulai, baris sudah `pending` dan commit sudah terjadi."""
    seen = {}

    async def _spy(project_id, items):
        seen["items"] = items

    with patch("app.api.projects.extract_source_documents", new=_spy), patch(
        "app.api.projects._trigger_scoring_engine", new=AsyncMock()
    ):
        with _api() as (client, session):
            resp = client.post(URL, data=_form_tipe("MoM"), files=[_pdf()])
            [doc] = session.of_type(SourceDocument)
            commit_dipanggil = session.commit.await_count
    assert resp.status_code == 201
    assert doc.extraction_status == "pending"
    assert commit_dipanggil >= 1
    assert len(seen["items"]) == 1


def test_file_ditolak_validasi_tidak_dibuat_source_document():
    png = ("files", ("x.png", BytesIO(b"png"), "image/png"))
    resp, session, _, _ = _jalankan([png], _form_tipe("MoM"))
    assert resp.status_code == 201
    assert session.of_type(SourceDocument) == []


# --------------------------------------------------------------------------- detail proyek
def _detail(user, proyek, docs):
    async def _execute(stmt, *a, **k):
        text = str(stmt)
        if "FROM source_documents" in text:
            return _result(items=docs)
        if "FROM projects" in text:
            return _result(one=proyek)
        return _result()

    with _api(user=user) as (client, session):
        session.execute = AsyncMock(side_effect=_execute)
        return client.get(f"{URL}/{proyek.id_project}")


def _proyek(sales_pic):
    return Project(id_project="PRJ-1", project_name="P", customer_name="C", status="New", sales_pic=sales_pic)


def test_detail_proyek_menampilkan_daftar_source_document_tanpa_teks_penuh():
    user = _user("Sales")
    doc = SourceDocument(
        id=uuid.uuid4(), id_project="PRJ-1", filename="mom.pdf", doc_type="MoM",
        size_bytes=1234, extraction_status="extracted", extracted_text="abc" * 10, truncated=True,
    )
    resp = _detail(user, _proyek(user.id), [doc])
    assert resp.status_code == 200
    [item] = resp.json()["data"]["source_documents"]
    assert item["filename"] == "mom.pdf" and item["doc_type"] == "MoM"
    assert item["size_bytes"] == 1234 and item["extraction_status"] == "extracted"
    assert item["truncated"] is True and item["text_length"] == 30
    assert "extracted_text" not in item


def test_detail_proyek_terbuka_untuk_orang_lain():
    """Keputusan 2026-11-10: semua proyek dapat dibaca semua pengguna terautentikasi."""
    resp = _detail(_user("Sales"), _proyek(uuid.uuid4()), [])
    assert resp.status_code == 200
    assert resp.json()["data"]["source_documents"] == []
