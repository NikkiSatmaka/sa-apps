# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Integrasi (Postgres nyata + fake LLM): pembuatan proyek dengan/tanpa file, qualification_state `Scoring`,
fallback rubrik, guard status, dan penyimpanan hasil scoring (tiket B8 #61, ADR 0010).

Background task (scoring AI + ekstraksi Source document) selesai sebelum respons HTTP kembali
pada transport ASGI, jadi status akhir bisa langsung diperiksa di DB.
"""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import NotificationLog, Project
from app.services.scoring_engine import scoring_engine
from tests.integration.fakes.llm import respons_error, respons_sukses
from tests.integration.kualifikasi_support import (  # noqa: F401
    URL,
    ambil_proyek,
    api,
    bearer,
    berkas,
    buat_proyek,
    form,
    gen_req_scoring,
    jawaban_kuat,
    jawaban_lemah,
    json_bant,
    notif_untuk,
    set_status,
    source_docs,
    tanpa_tunggu,
    user_baru,
)
from tests.integration.model_helpers import bangun_project, simpan

pytestmark = pytest.mark.usefixtures("tanpa_tunggu")


def _ai(*a, **kw) -> str:
    return json.dumps(json_bant(*a, **kw))


async def _sales_dan_lead(api):
    await api.login_demo("Lead_SA")  # penerima notifikasi
    return await api.login_demo("Sales")


# --------------------------------------------------------------------------- tanpa file


async def test_tanpa_file_jawaban_kuat_langsung_pending_assignment(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)

    resp = await buat_proyek(api, sales, jawaban_kuat())

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "Awaiting Assignment"
    assert data["scoring_triggered"] is False
    assert data["bant_score"] >= 60
    assert set(data["sub_scores"]) == {"budget", "authority", "need", "timeline"}
    proyek = await ambil_proyek(db_session, data["id_project"])
    assert proyek.status == "Awaiting Assignment"
    assert proyek.bant_score == data["bant_score"]
    assert proyek.requirement_generation_status == "pending"
    assert proyek.qualification_schema_version == 1
    assert len(await notif_untuk(db_session, proyek.id_project)) == 1
    assert fake_llm.jumlah() == 0  # tanpa file tidak ada panggilan LLM
    api.generate_requirement.assert_awaited_once_with(proyek.id_project)


async def test_tanpa_file_jawaban_lemah_need_clarification_dengan_feedback(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)

    resp = await buat_proyek(api, sales, jawaban_lemah())

    data = resp.json()["data"]
    assert (data["status"], data["qualification_state"]) == ("Intake", "Need Clarification")
    assert data["feedback"] and "perlu dilengkapi" in data["feedback"]
    proyek = await ambil_proyek(db_session, data["id_project"])
    assert proyek.bant_score < 60
    assert proyek.requirement_generation_status is None
    assert await notif_untuk(db_session, proyek.id_project) == []
    api.generate_requirement.assert_not_awaited()


async def test_tanpa_lead_sa_create_tetap_berhasil(api, db_session):
    sales = await api.login_demo("Sales")

    resp = await buat_proyek(api, sales, jawaban_kuat())

    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "Awaiting Assignment"


# --------------------------------------------------------------------------- dengan file


async def test_dengan_file_respons_scoring_pending_lalu_ai_mengangkat_skor(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)
    # Jawaban lemah (rubrik < 60) tetapi dokumen memuat bukti kuat → max per kriteria.
    fake_llm.program("parse_document", respons_sukses(_ai(tags=["cloud", "migrasi"])))
    fake_llm.sukses("parse_document", "teks MoM")

    resp = await buat_proyek(
        api, sales, jawaban_lemah(), files=berkas("mom.pdf"), file_types=["MoM"]
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    # keadaan yang dijanjikan di respons
    assert (data["status"], data["qualification_state"]) == ("Intake", "Scoring")
    assert data["scoring_triggered"] is True
    assert data["bant_score"] is None and data["sub_scores"] is None
    proyek = await ambil_proyek(db_session, data["id_project"])
    assert proyek.status == "Awaiting Assignment"
    assert proyek.bant_score == 100
    assert proyek.bant_detail["budget"] == 25
    assert proyek.use_case_tags == ["cloud", "migrasi"]
    assert proyek.ai_scoring_result["sub_scores"] == {
        "budget": 25,
        "authority": 25,
        "need": 25,
        "timeline": 25,
    }
    assert proyek.requirement_generation_status == "pending"
    api.generate_requirement.assert_awaited_with(proyek.id_project)
    assert len(await notif_untuk(db_session, proyek.id_project)) == 1


async def test_ai_lebih_rendah_dari_rubrik_tidak_menurunkan_skor(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", respons_sukses(_ai(0, 0, 0, 0, tags=[])))
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(
        api, sales, jawaban_kuat(), files=berkas("rfp.pdf"), file_types=["RFP"]
    )

    id_project = resp.json()["data"]["id_project"]
    proyek = await ambil_proyek(db_session, id_project)
    assert proyek.status == "Awaiting Assignment"
    # Skor akhir tetap sama dengan rubrik (batas bawah), AI nol tidak menurunkan.
    assert proyek.bant_score >= 60


async def test_beberapa_file_mengambil_skor_tertinggi_dan_tag_unik_maks_lima(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)
    fake_llm.program(
        "parse_document",
        respons_sukses(_ai(25, 0, 0, 0, tags=["a", "b", "c"])),
        respons_sukses(_ai(0, 25, 25, 25, tags=["B", "d", "e", "f"])),
    )
    fake_llm.sukses("parse_document", "t1", tetap=True)

    resp = await buat_proyek(
        api, sales, jawaban_lemah(), files=berkas("a.pdf", "b.pdf"), file_types=["MoM", "RFP"]
    )

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert proyek.ai_scoring_result["sub_scores"] == {
        "budget": 25,
        "authority": 25,
        "need": 25,
        "timeline": 25,
    }
    assert proyek.use_case_tags == ["a", "b", "c", "d", "e"]


async def test_ai_gagal_tiga_kali_fallback_rubrik_kuat_lolos_gate(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", *[respons_error("timeout")] * 3)
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(api, sales, jawaban_kuat(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert fake_llm.jumlah("parse_document") == 4  # 3 percobaan skor + 1 ekstraksi
    assert proyek.status == "Awaiting Assignment"
    assert proyek.ai_scoring_result is None
    assert proyek.requirement_generation_status == "pending"


async def test_ai_gagal_fallback_rubrik_lemah_need_clarification(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", *[respons_error("auth_error")] * 3)
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(api, sales, jawaban_lemah(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Need Clarification")
    assert proyek.bant_score < 60
    api.generate_requirement.assert_awaited()  # no-op bagi proyek tak bertanda, tetap dipanggil


@pytest.mark.parametrize(
    "respons",
    [
        respons_sukses("{ bukan json"),
        respons_sukses(json.dumps({"budget": {"score": 99, "evidence": "x"}})),
        respons_sukses(""),
    ],
    ids=["json-rusak", "kontrak-tidak-valid", "kosong"],
)
async def test_keluaran_ai_tidak_valid_diperlakukan_gagal_lalu_fallback_rubrik(
    api, db_session, fake_llm, respons
):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", respons, respons, respons)
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(api, sales, jawaban_kuat(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert proyek.status == "Awaiting Assignment"
    assert proyek.ai_scoring_result is None


async def test_ai_pulih_pada_percobaan_kedua(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", respons_error("timeout"), respons_sukses(_ai()))
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(api, sales, jawaban_lemah(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert proyek.status == "Awaiting Assignment"
    assert proyek.ai_scoring_result is not None


async def test_exception_tak_terduga_di_scoring_tetap_fallback_rubrik(
    api, db_session, fake_llm, monkeypatch
):
    sales = await _sales_dan_lead(api)

    def _meledak():
        raise RuntimeError("provider tak terduga")

    monkeypatch.setattr("app.services.llm_provider.llm_factory.get_provider", _meledak)

    resp = await buat_proyek(api, sales, jawaban_kuat(), files=berkas("m.pdf"), file_types=["MoM"])

    assert resp.status_code == 201
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    # Tidak menggantung di qualification_state Scoring; skor rubrik dipakai.
    assert proyek.status == "Awaiting Assignment"
    docs = await source_docs(db_session, proyek.id_project)
    assert [d.extraction_status for d in docs] == ["failed"]


async def test_exception_tak_terduga_rubrik_lemah_need_clarification(api, db_session, monkeypatch):
    sales = await _sales_dan_lead(api)
    monkeypatch.setattr(
        "app.services.llm_provider.llm_factory.get_provider",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = await buat_proyek(api, sales, jawaban_lemah(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert (proyek.status, proyek.qualification_state) == ("Intake", "Need Clarification")


# --------------------------------------------------------------------------- validasi file/form


async def test_file_tanpa_tipe_ditolak_422_dan_tidak_ada_proyek(api, db_session, fake_llm):
    sales = await api.login_demo("Sales")

    resp = await buat_proyek(api, sales, jawaban_kuat(), files=berkas("m.pdf"))

    assert resp.status_code == 422
    assert resp.json()["data"][0]["field"] == "files[0].type"
    assert (await db_session.execute(select(Project))).scalars().all() == []


async def test_enam_file_ditolak(api, db_session):
    sales = await api.login_demo("Sales")

    resp = await buat_proyek(
        api,
        sales,
        jawaban_kuat(),
        files=berkas(*[f"{i}.pdf" for i in range(6)]),
        file_types=["MoM"] * 6,
    )

    assert resp.status_code == 422
    assert any(e["field"] == "files" for e in resp.json()["data"])


async def test_sebagian_file_tidak_valid_tetap_membuat_proyek_dan_hanya_valid_diproses(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)
    fake_llm.program("parse_document", respons_sukses(_ai()))
    fake_llm.sukses("parse_document", "teks")
    files = (
        berkas("ok.pdf")
        + berkas("buruk.txt", mime="text/plain")
        + [("files", ("kosong.pdf", b"", "application/pdf"))]
    )

    resp = await buat_proyek(
        api, sales, jawaban_lemah(), files=files, file_types=["MoM", "MoM", "RFP"]
    )

    assert resp.status_code == 201, resp.text
    hasil = {f["filename"]: f for f in resp.json()["data"]["files"]}
    assert hasil["ok.pdf"]["success"] is True
    assert hasil["buruk.txt"]["success"] is False
    assert hasil["kosong.pdf"]["success"] is False
    docs = await source_docs(db_session, resp.json()["data"]["id_project"])
    assert [d.filename for d in docs] == ["ok.pdf"]
    assert fake_llm.jumlah("parse_document") == 2  # hanya satu file: skor + ekstraksi


async def test_semua_file_tidak_valid_diperlakukan_seperti_tanpa_file(api, db_session, fake_llm):
    sales = await _sales_dan_lead(api)

    resp = await buat_proyek(
        api,
        sales,
        jawaban_kuat(),
        files=berkas("buruk.txt", mime="text/plain"),
        file_types=["MoM"],
    )

    data = resp.json()["data"]
    assert resp.status_code == 201
    assert data["status"] == "Awaiting Assignment"
    assert data["scoring_triggered"] is False
    assert fake_llm.jumlah() == 0


async def test_kunci_tak_dikenal_dan_skor_mentah_dari_klien_ditolak_saat_create(api, db_session):
    sales = await api.login_demo("Sales")
    jawaban = jawaban_kuat()
    jawaban["budget"] = 25
    jawaban["bant_score"] = 100

    resp = await buat_proyek(api, sales, jawaban)

    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["data"]}
    assert {"qualification_answers.budget", "qualification_answers.bant_score"} <= fields
    assert (await db_session.execute(select(Project))).scalars().all() == []


@pytest.mark.parametrize(
    ("mutasi", "field"),
    [
        ({"project_name": "   "}, "project_name"),
        ({"customer_name": "   "}, "customer_name"),
        ({"target_submit": "2000-01-01"}, "target_submit"),
        ({"estimasi_nilai": "abc"}, "estimasi_nilai"),
        ({"estimasi_nilai": "0"}, "estimasi_nilai"),
        ({"estimasi_nilai": "9999999999999"}, "estimasi_nilai"),
        ({"dq_number": "x!"}, "dq_number"),
    ],
)
async def test_validasi_header_create_422(api, db_session, mutasi, field):
    sales = await api.login_demo("Sales")

    resp = await buat_proyek(api, sales, jawaban_kuat(), **mutasi)

    assert resp.status_code == 422, resp.text
    assert field in {e["field"] for e in resp.json()["data"]}


async def test_dq_number_valid_disimpan_dan_kuesioner_wajib(api, db_session):
    sales = await api.login_demo("Sales")

    ok = await buat_proyek(api, sales, jawaban_kuat(), dq_number=" DQ-12345 ")
    tanpa = await api.client.post(URL, data=form(), headers=sales)

    assert ok.status_code == 201
    proyek = await ambil_proyek(db_session, ok.json()["data"]["id_project"])
    assert proyek.dq_number == "DQ-12345"
    assert tanpa.status_code == 422


async def test_create_tanpa_login_ditolak(api, db_session):
    resp = await api.client.post(URL, data={"project_name": "x"})

    assert resp.status_code in (401, 403)


# --------------------------------------------------------------------------- guard status


async def _proyek_db(db_session, status, **kolom):
    sales = await user_baru(db_session, "Sales")
    proyek = bangun_project(sales.id, status=status, **kolom)
    await simpan(db_session, proyek)
    await db_session.commit()
    return sales, proyek


@pytest.mark.parametrize("status", ["Assigned", "Submitted", "Awaiting Assignment", "Won"])
async def test_hasil_ai_terlambat_tidak_menimpa_status_pasca_gate(db_session, fake_llm, status):
    _, proyek = await _proyek_db(
        db_session, status, bant_score=77, qualification_answers=jawaban_kuat()
    )
    fake_llm.program("parse_document", respons_sukses(_ai(0, 0, 0, 0, tags=["x"])))

    hasil = await scoring_engine.score_documents(
        proyek.id_project, [(b"%PDF", "application/pdf", "a.pdf")], db_session
    )

    p = await ambil_proyek(db_session, proyek.id_project)
    assert p.status == status
    assert p.bant_score == 77
    assert p.ai_scoring_result is None
    assert (hasil.status, hasil.qualification_state) == (status, "Qualified")  # status sebenarnya
    assert await notif_untuk(db_session, proyek.id_project) == []


async def test_fallback_pada_proyek_assigned_tidak_menimpa(db_session, fake_llm):
    _, proyek = await _proyek_db(
        db_session, "Assigned", bant_score=88, qualification_answers=jawaban_kuat()
    )
    fake_llm.program("parse_document", *[respons_error()] * 3)

    await scoring_engine.score_documents(
        proyek.id_project, [(b"%PDF", "application/pdf", "a.pdf")], db_session
    )
    await scoring_engine.fallback_after_failure(db_session, proyek.id_project)

    p = await ambil_proyek(db_session, proyek.id_project)
    assert (p.status, p.bant_score) == ("Assigned", 88)


# ----------------------------------------------------------------- proyek legacy (tanpa rubrik)


async def test_tanpa_file_dan_tanpa_jawaban_need_clarification_nol(db_session, fake_llm):
    _, proyek = await _proyek_db(db_session, "Intake")

    hasil = await scoring_engine.score_documents(proyek.id_project, [], db_session)

    assert (hasil.status, hasil.qualification_state) == ("Intake", "Need Clarification")
    assert hasil.total_score == 0
    p = await ambil_proyek(db_session, proyek.id_project)
    assert (p.status, p.qualification_state, p.bant_score) == ("Intake", "Need Clarification", 0)


async def test_file_non_pdf_docx_dilewati_oleh_scoring(db_session, fake_llm):
    _, proyek = await _proyek_db(db_session, "Intake", qualification_answers=jawaban_kuat())

    hasil = await scoring_engine.score_documents(
        proyek.id_project, [(b"x", "text/plain", "a.txt")], db_session
    )

    assert (hasil.status, hasil.qualification_state) == ("Awaiting Assignment", "Qualified")  # rubrik
    assert fake_llm.jumlah() == 0


async def test_ai_gagal_tanpa_rubrik_manual_review_dan_notifikasi_lead(
    db_session, fake_llm
):
    lead = await user_baru(db_session, "Lead_SA")
    _, proyek = await _proyek_db(db_session, "Intake")
    fake_llm.program("parse_document", *[respons_error("timeout")] * 3)

    hasil = await scoring_engine.score_documents(
        proyek.id_project, [(b"%PDF", "application/pdf", "a.pdf")], db_session
    )

    assert (hasil.status, hasil.qualification_state) == ("Intake", "Manual Review")
    p = await ambil_proyek(db_session, proyek.id_project)
    assert (p.status, p.qualification_state) == ("Intake", "Manual Review")
    notif = await notif_untuk(db_session, proyek.id_project)
    assert [n.recipient_user_id for n in notif] == [lead.id]
    assert notif[0].notification_metadata["reason"].startswith("Scoring otomatis gagal")


async def test_fallback_after_failure_tanpa_rubrik_manual_review(db_session):
    _, proyek = await _proyek_db(db_session, "Intake")

    await scoring_engine.fallback_after_failure(db_session, proyek.id_project)

    p = await ambil_proyek(db_session, proyek.id_project)
    assert (p.status, p.qualification_state) == ("Intake", "Manual Review")


async def test_manual_review_tidak_menimpa_proyek_assigned(db_session):
    _, proyek = await _proyek_db(db_session, "Assigned")

    await scoring_engine.fallback_after_failure(db_session, proyek.id_project)

    assert (await ambil_proyek(db_session, proyek.id_project)).status == "Assigned"


async def test_proyek_tidak_ada_scoring_tidak_melempar(db_session):
    hasil = await scoring_engine.score_documents("PRJ-TIDAKADA", [], db_session)

    assert (hasil.status, hasil.qualification_state) == ("Intake", "Need Clarification")
    await scoring_engine.fallback_after_failure(db_session, "PRJ-TIDAKADA")


async def test_scoring_tidak_mengubah_notifikasi_tanpa_lead_sa(db_session, fake_llm):
    _, proyek = await _proyek_db(
        db_session, "Intake", qualification_answers=jawaban_kuat()
    )
    fake_llm.program("parse_document", *[respons_error()] * 3)

    hasil = await scoring_engine.score_documents(
        proyek.id_project, [(b"%PDF", "application/pdf", "a.pdf")], db_session
    )

    assert (hasil.status, hasil.qualification_state) == ("Awaiting Assignment", "Qualified")
    assert (await db_session.execute(select(NotificationLog))).scalars().all() == []


# --------------------------------------------------------------------------- jalur tambahan


async def test_exception_provider_pada_percobaan_dihitung_gagal_lalu_pulih(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)
    fake_llm.program(
        "parse_document", RuntimeError("koneksi putus"), RuntimeError("lagi"), respons_sukses(_ai())
    )
    fake_llm.sukses("parse_document", "teks")

    resp = await buat_proyek(api, sales, jawaban_lemah(), files=berkas("m.pdf"), file_types=["MoM"])

    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert proyek.status == "Awaiting Assignment"
    assert proyek.ai_scoring_result is not None


async def test_file_berekstensi_pdf_dengan_mime_asing_tidak_menggantung_di_scoring_pending(
    api, db_session, fake_llm
):
    sales = await _sales_dan_lead(api)
    fake_llm.sukses("parse_document", "teks", tetap=True)

    resp = await buat_proyek(
        api,
        sales,
        jawaban_kuat(),
        files=berkas("m.pdf", mime="application/octet-stream"),
        file_types=["MoM"],
    )

    assert resp.json()["data"]["qualification_state"] == "Scoring"
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    # Scoring melewati MIME tak didukung dan jatuh ke rubrik, bukan menggantung.
    assert proyek.status == "Awaiting Assignment"


async def test_kegagalan_notifikasi_new_opportunity_tidak_menggagalkan_create(
    api, db_session, monkeypatch
):
    sales = await _sales_dan_lead(api)
    monkeypatch.setattr(
        scoring_engine, "notify_new_opportunity", AsyncMock(side_effect=RuntimeError("smtp mati"))
    )

    resp = await buat_proyek(api, sales, jawaban_kuat())

    assert resp.status_code == 201
    proyek = await ambil_proyek(db_session, resp.json()["data"]["id_project"])
    assert proyek.status == "Awaiting Assignment"
    api.generate_requirement.assert_awaited_once_with(proyek.id_project)


async def test_file_melebihi_batas_ukuran_ditolak_per_file_proyek_tetap_dibuat(
    api, db_session, fake_llm, monkeypatch
):
    sales = await _sales_dan_lead(api)
    monkeypatch.setattr("app.api.projects.MAX_FILE_SIZE_BYTES", 10)

    resp = await buat_proyek(
        api, sales, jawaban_kuat(), files=berkas("besar.pdf"), file_types=["MoM"]
    )

    assert resp.status_code == 201
    (f,) = resp.json()["data"]["files"]
    assert f["success"] is False and "melebihi batas" in f["error"]
    assert resp.json()["data"]["scoring_triggered"] is False
