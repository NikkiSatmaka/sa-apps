# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Integrasi (Postgres nyata + fake LLM): ekstraksi teks Source document (extracted / empty /
failed / truncated) dan jaminan bahwa kegagalannya tidak menahan create maupun scoring
(tiket B8 #61).
"""

import json
import uuid

import pytest

from app.models import SourceDocument
from app.services.source_document_extractor import (
    EXTRACTION_MAX_OUTPUT_TOKENS,
    EXTRACTION_PROMPT,
    extract_source_documents,
)
from tests.integration.fakes.llm import respons_error, respons_sukses, respons_terpotong
from tests.integration.kualifikasi_support import (  # noqa: F401
    URL,
    ambil_proyek,
    api,
    berkas,
    buat_proyek,
    jawaban_kuat,
    jawaban_lemah,
    json_bant,
    source_docs,
    tanpa_tunggu,
    user_baru,
)
from tests.integration.model_helpers import bangun_project, bangun_source_doc, simpan

pytestmark = pytest.mark.usefixtures("tanpa_tunggu")


async def _siapkan(db, *nama, tipe="MoM"):
    """Proyek + baris SourceDocument `pending`; kembalikan (id_project, items ekstraksi)."""
    sales = await user_baru(db, "Sales")
    proyek = bangun_project(sales.id)
    docs = [bangun_source_doc(proyek.id_project, filename=n, doc_type=tipe) for n in nama]
    await simpan(db, proyek)
    await simpan(db, *docs)
    await db.commit()
    items = [(d.id, d.filename, f"%PDF {d.filename}".encode(), "application/pdf") for d in docs]
    return proyek.id_project, items


# --------------------------------------------------------------------------- matriks status


async def test_ekstraksi_sukses_teks_tersimpan_tanpa_file_asli(api, db_session, fake_llm):
    id_project, items = await _siapkan(db_session, "mom.pdf")
    fake_llm.sukses("parse_document", "  Notulen rapat: butuh migrasi.  ")

    await extract_source_documents(id_project, items)

    (doc,) = await source_docs(db_session, id_project)
    assert doc.extraction_status == "extracted"
    assert doc.extracted_text == "Notulen rapat: butuh migrasi."
    assert doc.truncated is False
    (panggilan,) = fake_llm.panggilan_jenis("parse_document")
    assert panggilan.argumen["prompt"] == EXTRACTION_PROMPT
    assert panggilan.argumen["max_output_tokens"] == EXTRACTION_MAX_OUTPUT_TOKENS
    assert panggilan.argumen["file_content"] == b"%PDF mom.pdf"


async def test_ekstraksi_terpotong_ditandai_truncated_tapi_tetap_extracted(
    api, db_session, fake_llm
):
    id_project, items = await _siapkan(db_session, "besar.pdf")
    fake_llm.program("parse_document", respons_terpotong("separuh teks"))

    await extract_source_documents(id_project, items)

    (doc,) = await source_docs(db_session, id_project)
    assert (doc.extraction_status, doc.extracted_text, doc.truncated) == (
        "extracted",
        "separuh teks",
        True,
    )


async def test_ekstraksi_teks_kosong_status_empty(api, db_session, fake_llm):
    id_project, items = await _siapkan(db_session, "scan.pdf")
    fake_llm.sukses("parse_document", "   \n ")

    await extract_source_documents(id_project, items)

    (doc,) = await source_docs(db_session, id_project)
    assert (doc.extraction_status, doc.extracted_text) == ("empty", None)


async def test_ekstraksi_error_llm_status_failed(api, db_session, fake_llm):
    id_project, items = await _siapkan(db_session, "rusak.pdf")
    fake_llm.error("parse_document", "timeout", "habis waktu")

    await extract_source_documents(id_project, items)

    (doc,) = await source_docs(db_session, id_project)
    assert (doc.extraction_status, doc.extracted_text) == ("failed", None)


async def test_ekstraksi_exception_dari_provider_status_failed(api, db_session, fake_llm):
    id_project, items = await _siapkan(db_session, "meledak.pdf")
    fake_llm.program("parse_document", RuntimeError("koneksi putus"))

    await extract_source_documents(id_project, items)

    (doc,) = await source_docs(db_session, id_project)
    assert doc.extraction_status == "failed"


async def test_satu_file_gagal_tidak_menghentikan_file_lain_dan_hasil_per_file_benar(
    api, db_session, fake_llm
):
    id_project, items = await _siapkan(db_session, "a.pdf", "b.pdf", "c.pdf", "d.pdf")
    fake_llm.program(
        "parse_document",
        respons_sukses("isi a"),
        respons_error("unknown"),
        respons_sukses(""),
        respons_terpotong("isi d"),
    )

    await extract_source_documents(id_project, items)

    hasil = {
        d.filename: (d.extraction_status, d.truncated)
        for d in await source_docs(db_session, id_project)
    }
    assert hasil == {
        "a.pdf": ("extracted", False),
        "b.pdf": ("failed", False),
        "c.pdf": ("empty", False),
        "d.pdf": ("extracted", True),
    }


async def test_baris_source_document_hilang_dilewati_tanpa_error(api, db_session, fake_llm):
    id_project, items = await _siapkan(db_session, "ada.pdf")
    hantu = (uuid.uuid4(), "hantu.pdf", b"x", "application/pdf")
    fake_llm.sukses("parse_document", "isi", tetap=True)

    await extract_source_documents(id_project, [hantu, *items])

    (doc,) = await source_docs(db_session, id_project)
    assert doc.extraction_status == "extracted"
    assert fake_llm.jumlah("parse_document") == 1


async def test_kegagalan_sesi_db_tidak_dilempar_ke_pemanggil(api, monkeypatch, fake_llm):
    class Meledak:
        async def __aenter__(self):
            raise RuntimeError("db mati")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: Meledak())

    # Tidak boleh melempar; resummarize di akhir juga best-effort.
    await extract_source_documents("PRJ-X", [(uuid.uuid4(), "a.pdf", b"x", "application/pdf")])


async def test_kegagalan_satu_item_di_luar_llm_tidak_menghentikan_item_berikutnya(
    api, db_session, fake_llm, monkeypatch
):
    id_project, items = await _siapkan(db_session, "a.pdf", "b.pdf")
    import app.services.source_document_extractor as modul

    asli = modul._extract_one
    dipanggil = []

    async def _sebagian(db, item):
        dipanggil.append(item[1])
        if item[1] == "a.pdf":
            raise RuntimeError("di luar perlindungan LLM")
        await asli(db, item)

    monkeypatch.setattr(modul, "_extract_one", _sebagian)
    fake_llm.sukses("parse_document", "isi b")

    await extract_source_documents(id_project, items)

    status = {d.filename: d.extraction_status for d in await source_docs(db_session, id_project)}
    assert dipanggil == ["a.pdf", "b.pdf"]
    assert status == {"a.pdf": "pending", "b.pdf": "extracted"}


# --------------------------------------------------------------------------- lewat API create


async def test_create_dengan_file_ekstraksi_sukses_tersimpan_dan_muncul_di_detail(
    api, db_session, fake_llm
):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    fake_llm.program("parse_document", respons_sukses(json.dumps(json_bant())))
    fake_llm.sukses("parse_document", "Isi RFP lengkap")

    resp = await buat_proyek(
        api, sales, jawaban_lemah(), files=berkas("rfp.pdf"), file_types=["RFP"]
    )

    id_project = resp.json()["data"]["id_project"]
    (doc,) = await source_docs(db_session, id_project)
    assert (doc.doc_type, doc.extraction_status, doc.extracted_text) == (
        "RFP",
        "extracted",
        "Isi RFP lengkap",
    )
    assert doc.size_bytes == len(b"%PDF-1.4 isi rfp.pdf")
    detail = (await api.client.get(f"{URL}/{id_project}", headers=sales)).json()["data"]
    (d,) = detail["source_documents"]
    assert d["extraction_status"] == "extracted" and d["text_length"] == len("Isi RFP lengkap")


async def test_kegagalan_llm_ekstraksi_tidak_menahan_create_maupun_scoring(
    api, db_session, fake_llm
):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    # Scoring sukses (jawaban lemah diangkat AI), ekstraksi gagal.
    fake_llm.program(
        "parse_document",
        respons_sukses(json.dumps(json_bant())),
        respons_error("timeout"),
    )

    resp = await buat_proyek(api, sales, jawaban_lemah(), files=berkas("m.pdf"), file_types=["MoM"])

    assert resp.status_code == 201
    id_project = resp.json()["data"]["id_project"]
    proyek = await ambil_proyek(db_session, id_project)
    assert proyek.status == "Pending Assignment" and proyek.bant_score == 100
    (doc,) = await source_docs(db_session, id_project)
    assert (doc.extraction_status, doc.extracted_text) == ("failed", None)


async def test_kegagalan_total_llm_scoring_fallback_dan_ekstraksi_failed(api, db_session, fake_llm):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    fake_llm.program("parse_document", *[respons_error("unknown")] * 4, tetap=True)

    resp = await buat_proyek(api, sales, jawaban_kuat(), files=berkas("m.pdf"), file_types=["MoM"])

    id_project = resp.json()["data"]["id_project"]
    assert (await ambil_proyek(db_session, id_project)).status == "Pending Assignment"
    (doc,) = await source_docs(db_session, id_project)
    assert doc.extraction_status == "failed"


async def test_create_tanpa_file_tidak_membuat_source_document_dan_tanpa_tipe(
    api, db_session, fake_llm
):
    sales = await api.login_demo("Sales")

    resp = await buat_proyek(api, sales, jawaban_lemah())

    assert resp.status_code == 201
    assert await source_docs(db_session, resp.json()["data"]["id_project"]) == []
    assert fake_llm.jumlah() == 0


async def test_dua_file_tipe_berbeda_masing_masing_punya_baris(api, db_session, fake_llm):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    fake_llm.program(
        "parse_document",
        respons_sukses(json.dumps(json_bant())),
        respons_sukses(json.dumps(json_bant())),
    )
    fake_llm.sukses("parse_document", "teks", tetap=True)

    resp = await buat_proyek(
        api, sales, jawaban_lemah(), files=berkas("a.pdf", "b.pdf"), file_types=["MoM", "RFP"]
    )

    docs = await source_docs(db_session, resp.json()["data"]["id_project"])
    assert [(d.filename, d.doc_type) for d in docs] == [("a.pdf", "MoM"), ("b.pdf", "RFP")]
    assert all(isinstance(d, SourceDocument) and d.extraction_status == "extracted" for d in docs)
