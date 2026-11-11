# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Integrasi (Postgres nyata): edit jawaban kuesioner + re-score, kunci pasca-gate, override
Lead_SA/Admin (alasan wajib, audit log, status terbatas, authz per peran), PATCH proyek yang
tidak boleh menimpa sub-skor, dan endpoint baca bant-result/recommendations (tiket B8 #61).
"""

import json

import pytest
from sqlalchemy import select

from app.models import Project, User
from app.services.scoring_engine import scoring_engine
from tests.integration.fakes.llm import respons_error, respons_sukses
from tests.integration.kualifikasi_support import (  # noqa: F401
    URL,
    ambil_proyek,
    api,
    audit_proyek,
    bearer,
    buat_proyek,
    gen_req_scoring,
    jadikan_kolaborator,
    jawaban_kuat,
    jawaban_lemah,
    json_bant,
    notif_untuk,
    set_status,
    tanpa_tunggu,
    user_baru,
)
from tests.integration.model_helpers import bangun_project, simpan

pytestmark = pytest.mark.usefixtures("tanpa_tunggu", "gen_req_scoring")

OVERRIDE_OK = {
    "budget": 25,
    "authority": 25,
    "need": 25,
    "timeline": 25,
    "reason": "Konfirmasi telepon",
}


class Skenario:
    """Proyek Need Clarification milik Sales demo + aktor lain."""

    def __init__(self, api, id_project, sales, lead, admin, sa, db):
        self.api, self.id, self.db = api, id_project, db
        self.sales, self.lead, self.admin, self.sa = sales, lead, admin, sa

    @property
    def edit(self):
        return f"{URL}/{self.id}/qualification-answers"

    @property
    def override(self):
        return f"{URL}/{self.id}/score-manual"

    async def put(self, headers, jawaban):
        return await self.api.client.put(self.edit, json=jawaban, headers=headers)

    async def post_override(self, headers, body=None):
        return await self.api.client.post(self.override, json=body or OVERRIDE_OK, headers=headers)

    async def proyek(self) -> Project:
        return await ambil_proyek(self.db, self.id)


@pytest.fixture
async def skenario(api, db_session):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    resp = await buat_proyek(api, sales, jawaban_lemah())
    assert resp.json()["data"]["status"] == "Need Clarification"
    api.generate_requirement.reset_mock()
    return Skenario(
        api,
        resp.json()["data"]["id_project"],
        sales,
        await api.login_demo("Lead_SA"),
        await api.login_demo("Admin"),
        await api.login_demo("SA"),
        db_session,
    )


# --------------------------------------------------------------------------- edit + re-score


async def test_sales_pic_edit_saat_need_clarification_rescore_lolos_gate(skenario):
    resp = await skenario.put(skenario.sales, jawaban_kuat())

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "Pending Assignment"
    p = await skenario.proyek()
    assert p.status == "Pending Assignment"
    assert p.qualification_answers["budget_dialokasikan"] == "Ya"
    assert p.bant_score == resp.json()["data"]["total_score"] >= 60
    assert p.requirement_generation_status == "pending"
    skenario.api.generate_requirement.assert_awaited_once_with(skenario.id)
    assert len(await notif_untuk(skenario.db, skenario.id)) == 1


async def test_edit_yang_masih_lemah_tetap_need_clarification_tanpa_notifikasi(skenario):
    jawaban = jawaban_lemah()
    jawaban["budget_dialokasikan"] = "Belum"

    resp = await skenario.put(skenario.sales, jawaban)

    assert resp.status_code == 200
    p = await skenario.proyek()
    assert p.status == "Need Clarification"
    assert p.bant_detail["budget"] == 5
    assert await notif_untuk(skenario.db, skenario.id) == []
    skenario.api.generate_requirement.assert_not_awaited()


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_lead_sa_dan_admin_diperlakukan_sama_saat_need_clarification(skenario, peran):
    resp = await skenario.put(getattr(skenario, peran), jawaban_kuat())

    assert resp.status_code == 200
    assert (await skenario.proyek()).status == "Pending Assignment"


async def test_rescore_tidak_menurunkan_di_bawah_override_tersimpan(skenario):
    await _override_langsung(skenario, authority=25, need=25)
    # jawaban tetap lemah: rubrik authority/need kecil, tetapi override jadi batas bawah
    await skenario.put(skenario.sales, jawaban_lemah())

    p = await skenario.proyek()
    assert p.bant_detail["authority"] == 25 and p.bant_detail["need"] == 25


async def _override_langsung(skenario, **nilai):
    p = await skenario.proyek()
    dasar = {"budget": 0, "authority": 0, "need": 0, "timeline": 0}
    dasar.update(nilai)
    p.override_sub_scores = dasar
    await skenario.db.commit()


async def test_rescore_memakai_hasil_ai_tersimpan_sebagai_batas_bawah(skenario):
    p = await skenario.proyek()
    p.ai_scoring_result = {
        "sub_scores": {"budget": 25, "authority": 25, "need": 25, "timeline": 25}
    }
    await skenario.db.commit()

    resp = await skenario.put(skenario.sales, jawaban_lemah())

    assert resp.json()["data"]["total_score"] == 100
    assert (await skenario.proyek()).status == "Pending Assignment"


@pytest.mark.parametrize("aktor", ["Sales lain", "SA", "kolaborator"])
async def test_selain_sales_pic_dan_privileged_ditolak_edit(skenario, aktor):
    if aktor == "Sales lain":
        headers = bearer(await user_baru(skenario.db, "Sales"))
    elif aktor == "SA":
        headers = skenario.sa
    else:
        kolab = await user_baru(skenario.db, "Sales")
        await jadikan_kolaborator(skenario.db, skenario.id, kolab, kolab)
        headers = bearer(kolab)

    resp = await skenario.put(headers, jawaban_kuat())

    assert resp.status_code == 403
    assert (await skenario.proyek()).qualification_answers["budget_dialokasikan"] == "Tidak tahu"


async def test_edit_proyek_tidak_ada_404(skenario):
    resp = await skenario.api.client.put(
        f"{URL}/PRJ-TIDAK-ADA/qualification-answers", json=jawaban_kuat(), headers=skenario.lead
    )

    assert resp.status_code == 404


async def test_edit_jawaban_invalid_422_dan_tidak_menyimpan(skenario):
    jawaban = jawaban_lemah()
    jawaban["bant_score"] = 100
    jawaban["peran_pic"] = "Raja"

    resp = await skenario.put(skenario.sales, jawaban)

    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["data"]}
    assert {"qualification_answers.bant_score", "qualification_answers.peran_pic"} <= fields
    p = await skenario.proyek()
    assert p.qualification_answers["peran_pic"] == "Tidak tahu" and p.status == "Need Clarification"


async def test_edit_body_bukan_objek_422(skenario):
    resp = await skenario.api.client.put(skenario.edit, json=["x"], headers=skenario.sales)

    assert resp.status_code in (400, 422)


@pytest.mark.parametrize("status", ["Pending Assignment", "Assigned", "Ready", "Closed-Win"])
async def test_sales_pic_tidak_boleh_edit_setelah_gate(skenario, status):
    await set_status(skenario.db, skenario.id, status)

    resp = await skenario.put(skenario.sales, jawaban_kuat())

    assert resp.status_code == 403


@pytest.mark.parametrize("peran", ["lead", "admin"])
@pytest.mark.parametrize("status", ["Pending Assignment", "Assigned"])
async def test_koreksi_pasca_gate_tanpa_rescore(skenario, peran, status):
    await set_status(skenario.db, skenario.id, status, bant_score=61)

    resp = await skenario.put(getattr(skenario, peran), jawaban_kuat())

    assert resp.status_code == 200
    assert resp.json()["data"] == {"total_score": 61, "status": status, "rescored": False}
    p = await skenario.proyek()
    assert (p.status, p.bant_score) == (status, 61)
    assert p.qualification_answers["budget_dialokasikan"] == "Ya"


@pytest.mark.parametrize("status", ["New", "Scoring Pending", "Manual Review Required"])
async def test_privileged_edit_sebelum_gate_selesai_400(skenario, status):
    await set_status(skenario.db, skenario.id, status)

    resp = await skenario.put(skenario.lead, jawaban_kuat())

    assert resp.status_code == 400


async def test_edit_proyek_legacy_tanpa_jawaban_400(api, db_session):
    lead = await api.login_demo("Lead_SA")
    sales = await user_baru(db_session, "Sales")
    legacy = bangun_project(sales.id, status="Need Clarification", bant_detail={"budget": 10})
    await simpan(db_session, legacy)
    await db_session.commit()

    resp = await api.client.put(
        f"{URL}/{legacy.id_project}/qualification-answers", json=jawaban_kuat(), headers=lead
    )

    assert resp.status_code == 400
    assert "legacy" in resp.text


# --------------------------------------------------------------------------- override


async def test_override_lead_sa_lolos_gate_dengan_audit_log(skenario):
    p0 = await skenario.proyek()
    skor_lama = p0.bant_score

    resp = await skenario.post_override(skenario.lead)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total_score"] == 100
    p = await skenario.proyek()
    assert p.status == "Pending Assignment"
    assert p.bant_score == 100
    assert p.override_sub_scores == {"budget": 25, "authority": 25, "need": 25, "timeline": 25}
    assert p.requirement_generation_status == "pending"
    skenario.api.generate_requirement.assert_not_awaited()
    log = await audit_proyek(skenario.db, skenario.id)
    assert len(log) == 1
    assert log[0].entity_type == "project"
    assert log[0].old_value["bant_score"] == skor_lama
    assert log[0].old_value["status"] == "Need Clarification"
    assert log[0].old_value["override_sub_scores"] is None
    assert log[0].new_value["bant_score"] == 100
    assert log[0].new_value["status"] == "Pending Assignment"
    assert log[0].new_value["reason"] == "Konfirmasi telepon"
    assert log[0].new_value["override_sub_scores"]["need"] == 25
    assert len(await notif_untuk(skenario.db, skenario.id)) == 1


async def test_override_lolos_gate_memicu_generate_requirement_di_router_scoring(
    skenario, gen_req_scoring
):
    await skenario.post_override(skenario.admin)

    gen_req_scoring.assert_awaited_once_with(skenario.id)


async def test_override_admin_juga_diizinkan_dan_pelaku_tercatat(skenario):
    resp = await skenario.post_override(skenario.admin)

    assert resp.status_code == 200
    log = (await audit_proyek(skenario.db, skenario.id))[0]
    admin = (await skenario.db.execute(select(User).where(User.role == "Admin"))).scalar_one()
    assert log.performed_by == admin.id


async def test_override_di_bawah_gate_tetap_need_clarification_dan_batas_bawah(skenario):
    body = {"budget": 3, "authority": 3, "need": 3, "timeline": 3, "reason": "uji"}

    resp = await skenario.post_override(skenario.lead, body)

    assert resp.status_code == 200
    p = await skenario.proyek()
    assert p.status == "Need Clarification"
    # Rubrik jawaban lemah (>3 pada beberapa kriteria) tidak diturunkan oleh override rendah.
    skor = p.bant_detail
    assert all(skor[k] >= 3 for k in ("budget", "authority", "need", "timeline"))
    assert p.bant_score == sum(skor[k] for k in ("budget", "authority", "need", "timeline"))
    assert p.bant_score >= 22


async def test_override_baru_menggantikan_override_lama_pada_audit(skenario):
    await skenario.post_override(
        skenario.lead, {"budget": 5, "authority": 5, "need": 5, "timeline": 5, "reason": "pertama"}
    )
    await skenario.post_override(
        skenario.lead, {"budget": 7, "authority": 6, "need": 5, "timeline": 5, "reason": "kedua"}
    )

    p = await skenario.proyek()
    assert p.override_sub_scores == {"budget": 7, "authority": 6, "need": 5, "timeline": 5}
    log = sorted(await audit_proyek(skenario.db, skenario.id), key=lambda a: a.new_value["reason"])
    assert [a.new_value["reason"] for a in log] == ["kedua", "pertama"]
    kedua = log[0]
    assert kedua.old_value["override_sub_scores"] == {
        "budget": 5,
        "authority": 5,
        "need": 5,
        "timeline": 5,
    }


async def test_override_manual_review_required_diizinkan(skenario):
    await set_status(skenario.db, skenario.id, "Manual Review Required")

    resp = await skenario.post_override(skenario.lead)

    assert resp.status_code == 200
    assert (await skenario.proyek()).status == "Pending Assignment"


@pytest.mark.parametrize(
    "status", ["New", "Scoring Pending", "Pending Assignment", "Assigned", "Ready", "Closed-Win"]
)
async def test_override_hanya_untuk_need_clarification_dan_manual_review(skenario, status):
    await set_status(skenario.db, skenario.id, status, bant_score=42)

    resp = await skenario.post_override(skenario.lead)

    assert resp.status_code == 400
    p = await skenario.proyek()
    assert (p.status, p.bant_score, p.override_sub_scores) == (status, 42, None)
    assert await audit_proyek(skenario.db, skenario.id) == []


@pytest.mark.parametrize("aktor", ["Sales PIC", "SA", "kolaborator", "Sales lain"])
async def test_override_ditolak_403_untuk_selain_lead_sa_admin(skenario, aktor):
    if aktor == "Sales PIC":
        headers = skenario.sales
    elif aktor == "SA":
        headers = skenario.sa
    elif aktor == "kolaborator":
        kolab = await user_baru(skenario.db, "SA")
        await jadikan_kolaborator(skenario.db, skenario.id, kolab, kolab)
        headers = bearer(kolab)
    else:
        headers = bearer(await user_baru(skenario.db, "Sales"))

    resp = await skenario.post_override(headers)

    assert resp.status_code == 403
    p = await skenario.proyek()
    assert p.status == "Need Clarification" and p.override_sub_scores is None
    assert await audit_proyek(skenario.db, skenario.id) == []


async def test_override_tanpa_login_ditolak(skenario):
    resp = await skenario.api.client.post(skenario.override, json=OVERRIDE_OK)

    assert resp.status_code in (401, 403)


async def test_override_proyek_tidak_ada_404(skenario):
    resp = await skenario.api.client.post(
        f"{URL}/PRJ-TIDAK-ADA/score-manual", json=OVERRIDE_OK, headers=skenario.lead
    )

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "mutasi",
    [
        {"reason": ""},
        {"reason": "    "},
        {"budget": 26},
        {"need": -1},
        {"timeline": "banyak"},
        {"authority": 12.5},
    ],
    ids=["alasan-kosong", "alasan-spasi", "di-atas-25", "negatif", "bukan-angka", "pecahan"],
)
async def test_override_input_tidak_valid_422_tanpa_efek(skenario, mutasi):
    body = {**OVERRIDE_OK, **mutasi}

    resp = await skenario.post_override(skenario.lead, body)

    assert resp.status_code == 422
    assert (await skenario.proyek()).override_sub_scores is None
    assert await audit_proyek(skenario.db, skenario.id) == []


@pytest.mark.parametrize("hilang", ["reason", "budget"])
async def test_override_field_wajib(skenario, hilang):
    body = {k: v for k, v in OVERRIDE_OK.items() if k != hilang}

    assert (await skenario.post_override(skenario.lead, body)).status_code == 422


async def test_override_menjadi_batas_bawah_saat_hasil_ai_datang_belakangan(skenario, fake_llm):
    await skenario.post_override(
        skenario.lead, {"budget": 25, "authority": 25, "need": 25, "timeline": 25, "reason": "a"}
    )
    await set_status(skenario.db, skenario.id, "Need Clarification")
    fake_llm.program("parse_document", respons_sukses(json.dumps(json_bant(0, 0, 0, 0))))

    await scoring_engine.score_documents(
        skenario.id, [(b"%PDF", "application/pdf", "a.pdf")], skenario.db
    )

    p = await skenario.proyek()
    assert p.bant_score == 100 and p.status == "Pending Assignment"


async def test_fallback_after_failure_menghormati_override(skenario, fake_llm):
    await skenario.post_override(skenario.lead)
    await set_status(skenario.db, skenario.id, "Need Clarification")
    fake_llm.program("parse_document", *[respons_error()] * 3)

    await scoring_engine.score_documents(
        skenario.id, [(b"%PDF", "application/pdf", "a.pdf")], skenario.db
    )

    assert (await skenario.proyek()).bant_score == 100


# --------------------------------------------------------------------------- PATCH proyek


async def test_patch_tidak_boleh_menimpa_sub_skor(skenario):
    sebelum = (await skenario.proyek()).bant_detail

    resp = await skenario.api.client.patch(
        f"{URL}/{skenario.id}",
        json={"bant_detail": {"budget": 25, "need": 25}},
        headers=skenario.sales,
    )

    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["data"]}
    assert fields == {"bant_detail.budget", "bant_detail.need"}
    p = await skenario.proyek()
    assert p.bant_detail == sebelum and p.status == "Need Clarification"


async def test_patch_bant_detail_bukan_objek_422(skenario):
    resp = await skenario.api.client.patch(
        f"{URL}/{skenario.id}", json={"bant_detail": ["x"]}, headers=skenario.sales
    )

    assert resp.status_code == 422


async def test_patch_metadata_legacy_dimerge_tanpa_menyentuh_sub_skor(skenario):
    sebelum = (await skenario.proyek()).bant_detail

    resp = await skenario.api.client.patch(
        f"{URL}/{skenario.id}", json={"bant_detail": {"catatan": "ok"}}, headers=skenario.sales
    )

    assert resp.status_code == 200
    p = await skenario.proyek()
    assert p.bant_detail["catatan"] == "ok"
    assert {k: p.bant_detail[k] for k in sebelum} == sebelum


async def test_patch_field_umum_dan_validasi(skenario):
    """DIUBAH (review kebijakan akses): DQ lewat PATCH proyek kini mengikuti aturan
    /dq-number, jadi proyek disiapkan di status "Assigned" (sebelumnya "Pending Assignment"
    menerima DQ -> kini 400) dan Sales PIC tidak lagi boleh MENGOSONGKAN DQ (-> 403; yang
    mengosongkan kini Lead_SA). Assertion field umum lain tidak berubah."""
    c = skenario.api.client
    await set_status(skenario.db, skenario.id, "Assigned")
    resp = await c.patch(
        f"{URL}/{skenario.id}",
        json={
            "project_name": "Nama Baru",
            "customer_name": "Cust Baru",
            "dq_number": "DQ-99999",
            "target_submit": "2031-01-31",
            "estimasi_nilai": "123.45",
        },
        headers=skenario.sales,
    )
    assert resp.status_code == 200
    p = await skenario.proyek()
    assert (p.project_name, p.customer_name, p.dq_number) == ("Nama Baru", "Cust Baru", "DQ-99999")
    assert str(p.target_submit) == "2031-01-31" and str(p.estimasi_nilai) == "123.45"

    # Sales PIC tidak boleh mengosongkan DQ yang sudah ada
    resp = await c.patch(f"{URL}/{skenario.id}", json={"dq_number": ""}, headers=skenario.sales)
    assert resp.status_code == 403
    assert (await skenario.proyek()).dq_number == "DQ-99999"

    # Lead_SA boleh mengosongkan; target_submit tak valid diabaikan
    resp = await c.patch(
        f"{URL}/{skenario.id}",
        json={"dq_number": "", "target_submit": "bukan-tanggal"},
        headers=skenario.lead,
    )
    assert resp.status_code == 200
    p = await skenario.proyek()
    assert p.dq_number is None and str(p.target_submit) == "2031-01-31"

    for nilai in ("abc", "0", "1000000000000"):
        r = await c.patch(
            f"{URL}/{skenario.id}", json={"estimasi_nilai": nilai}, headers=skenario.sales
        )
        assert r.status_code == 422, nilai
    assert str((await skenario.proyek()).estimasi_nilai) == "123.45"


async def test_patch_pihak_luar_403_dan_proyek_tidak_ada_404(skenario):
    luar = bearer(await user_baru(skenario.db, "Sales"))
    r = await skenario.api.client.patch(
        f"{URL}/{skenario.id}", json={"project_name": "X"}, headers=luar
    )
    assert r.status_code == 403
    assert (await skenario.proyek()).project_name == "Proyek Uji"
    r = await skenario.api.client.patch(f"{URL}/PRJ-NOPE", json={}, headers=skenario.lead)
    assert r.status_code == 404


async def test_patch_tidak_mengubah_skor_atau_status(skenario):
    p0 = await skenario.proyek()

    await skenario.api.client.patch(
        f"{URL}/{skenario.id}",
        json={"bant_score": 100, "status": "Assigned", "override_sub_scores": {"budget": 25}},
        headers=skenario.lead,
    )

    p = await skenario.proyek()
    assert (p.bant_score, p.status, p.override_sub_scores) == (p0.bant_score, p0.status, None)


# ----------------------------------------------------------------- bant-result & rekomendasi


async def test_bant_result_proyek_skor_rendah_menyertakan_feedback(skenario):
    resp = await skenario.api.client.get(f"{URL}/{skenario.id}/bant-result", headers=skenario.sales)

    data = resp.json()["data"]
    assert resp.status_code == 200
    assert data["status"] == "Need Clarification"
    assert data["total_score"] < 60
    assert data["feedback"].startswith("Kriteria berikut perlu dilengkapi")
    assert set(data["sub_scores"]) == {"budget", "authority", "need", "timeline"}


async def test_bant_result_lolos_gate_tanpa_feedback_dan_belum_ada_skor(skenario, db_session):
    await skenario.put(skenario.sales, jawaban_kuat())
    ok = (
        await skenario.api.client.get(f"{URL}/{skenario.id}/bant-result", headers=skenario.sales)
    ).json()["data"]
    assert ok["feedback"] is None and ok["total_score"] >= 60

    sales = await user_baru(db_session, "Sales")
    kosong = bangun_project(sales.id)
    await simpan(db_session, kosong)
    await db_session.commit()
    resp = await skenario.api.client.get(
        f"{URL}/{kosong.id_project}/bant-result", headers=skenario.lead
    )
    assert resp.json()["data"] is None


async def test_bant_result_dan_rekomendasi_404_proyek_tidak_ada(skenario):
    for path in ("bant-result", "recommendations"):
        r = await skenario.api.client.get(f"{URL}/PRJ-NOPE/{path}", headers=skenario.lead)
        assert r.status_code == 404


async def test_rekomendasi_proyek_closed_win_serupa_urut_tag_dan_maks_lima(skenario, db_session):
    sales = await user_baru(db_session, "Sales")
    await simpan(
        db_session,
        *[
            bangun_project(
                sales.id,
                id_project=f"PRJ-CW-{i}",
                status="Closed-Win",
                use_case_tags=["cloud", "migrasi", "dr"][: (i % 3) + 1] if i != 6 else ["lain"],
            )
            for i in range(7)
        ],
        bangun_project(sales.id, id_project="PRJ-LOST", status="Lost", use_case_tags=["cloud"]),
    )
    p = await skenario.proyek()
    p.use_case_tags = ["Cloud", "migrasi", "dr"]
    await db_session.commit()

    resp = await skenario.api.client.get(
        f"{URL}/{skenario.id}/recommendations", headers=skenario.sales
    )

    data = resp.json()["data"]
    assert resp.status_code == 200
    assert len(data) == 5
    cocok = [d["matching_tags"] for d in data]
    assert cocok == sorted(cocok, reverse=True) and cocok[0] == 3
    assert all(d["status"] == "Closed-Win" and d["id_project"] != skenario.id for d in data)
    assert "PRJ-LOST" not in {d["id_project"] for d in data}


async def test_rekomendasi_tanpa_tag_atau_tanpa_kecocokan(skenario, db_session):
    r = await skenario.api.client.get(
        f"{URL}/{skenario.id}/recommendations", headers=skenario.sales
    )
    assert r.json()["data"] == []
    assert "setelah scoring" in r.json()["message"]

    p = await skenario.proyek()
    p.use_case_tags = ["unik"]
    await db_session.commit()
    r = await skenario.api.client.get(
        f"{URL}/{skenario.id}/recommendations", headers=skenario.sales
    )
    assert r.json()["data"] == [] and r.json()["message"] == "Belum ada referensi serupa."


async def test_bant_result_tanpa_kriteria_lemah_tidak_memberi_feedback(db_session, api):
    lead = await api.login_demo("Lead_SA")
    sales = await user_baru(db_session, "Sales")
    p = bangun_project(
        sales.id,
        status="Need Clarification",
        bant_score=40,
        bant_detail={"budget": 20, "authority": 20, "need": 20, "timeline": 20},
    )
    await simpan(db_session, p)
    await db_session.commit()

    resp = await api.client.get(f"{URL}/{p.id_project}/bant-result", headers=lead)

    assert resp.json()["data"]["feedback"] is None
