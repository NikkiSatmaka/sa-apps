# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Integrasi (Postgres nyata): daftar proyek per peran, ringkasan status, detail proyek
(qualification view baru/legacy/qualification_state Scoring), dan soft delete (tiket B8 #61).
"""

import pytest
from sqlalchemy import select

from app.models import Project, SLATracking
from tests.integration.kualifikasi_support import (  # noqa: F401
    URL,
    ambil_proyek,
    api,
    bearer,
    buat_proyek,
    jadikan_kolaborator,
    jawaban_kuat,
    jawaban_lemah,
    set_status,
    source_docs,
    user_baru,
)
from tests.integration.model_helpers import bangun_project, bangun_sla, bangun_source_doc, simpan


async def _ids(resp) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {p["id_project"] for p in resp.json()["data"]}


@pytest.fixture
async def dunia(api, db_session):
    """Proyek A1 (Sales A), B1 (Sales B, SA1 ditugaskan), B2 (Sales B, SA2 kolaborator)."""
    sales_a = await user_baru(db_session, "Sales")
    sales_b = await user_baru(db_session, "Sales")
    sa1 = await user_baru(db_session, "SA")
    sa2 = await user_baru(db_session, "SA")
    lead = await user_baru(db_session, "Lead_SA")
    admin = await user_baru(db_session, "Admin")
    a1 = bangun_project(sales_a.id, id_project="PRJ-A1", status="Intake",
        qualification_state="Need Clarification", bant_score=20,
    )
    b1 = bangun_project(
        sales_b.id, id_project="PRJ-B1", status="Assigned", assigned_sa=sa1.id, bant_score=80
    )
    b2 = bangun_project(sales_b.id, id_project="PRJ-B2", status="Awaiting Assignment", bant_score=70)
    await simpan(db_session, a1, b1, b2)
    await jadikan_kolaborator(db_session, "PRJ-B2", sa2, lead)
    await db_session.commit()
    return type(
        "Dunia",
        (),
        dict(
            api=api,
            db=db_session,
            sales_a=sales_a,
            sales_b=sales_b,
            sa1=sa1,
            sa2=sa2,
            lead=lead,
            admin=admin,
            h=lambda self, u: bearer(u),
        ),
    )()


# --------------------------------------------------------------------------- daftar per peran


@pytest.mark.parametrize("aktor", ["sales_a", "sales_b", "sa1", "sa2", "lead", "admin"])
async def test_daftar_proyek_terlihat_semua_peran(dunia, aktor):
    """Keputusan pemilik produk 2026-11-10: semua proyek dapat dilihat semua pengguna."""
    resp = await dunia.api.client.get(URL, headers=bearer(getattr(dunia, aktor)))

    assert await _ids(resp) == {"PRJ-A1", "PRJ-B1", "PRJ-B2"}


async def test_param_sales_pic_dan_assigned_to_hanya_menyempit(dunia):
    c, h = dunia.api.client, bearer(dunia.sales_b)
    assert await _ids(await c.get(URL, params={"sales_pic": "me"}, headers=h)) == {
        "PRJ-B1",
        "PRJ-B2",
    }
    # Param assigned_to=me hanya menyempit
    assert await _ids(await c.get(URL, params={"assigned_to": "me"}, headers=h)) == set()
    lead = bearer(dunia.lead)
    assert await _ids(await c.get(URL, params={"sales_pic": "me"}, headers=lead)) == set()
    assert await _ids(
        await c.get(URL, params={"assigned_to": "me"}, headers=bearer(dunia.sa1))
    ) == {"PRJ-B1"}


async def test_filter_status_dan_urutan_serta_bidang_respons(dunia):
    c, h = dunia.api.client, bearer(dunia.lead)
    assert await _ids(await c.get(URL, params={"status": "Assigned"}, headers=h)) == {"PRJ-B1"}

    naik = (await c.get(URL, params={"sort": "bant_score"}, headers=h)).json()["data"]
    turun = (await c.get(URL, params={"sort": "-bant_score"}, headers=h)).json()["data"]
    assert [p["bant_score"] for p in naik] == [20, 70, 80]
    assert [p["bant_score"] for p in turun] == [80, 70, 20]
    ngawur = await c.get(URL, params={"sort": "kolom_ngawur"}, headers=h)
    ngawur_desc = await c.get(URL, params={"sort": "-kolom_ngawur"}, headers=h)
    assert ngawur.status_code == 200 and ngawur_desc.status_code == 200
    kosong = await c.get(URL, params={"sort": ""}, headers=h)
    assert kosong.status_code == 200
    b1 = next(p for p in turun if p["id_project"] == "PRJ-B1")
    assert b1["assigned_sa"] == str(dunia.sa1.id)
    assert b1["use_case_tags"] == [] and b1["estimasi_nilai"] is None
    assert b1["created_at"] and b1["updated_at"]


async def test_status_summary_semua_peran_melihat_semua_proyek_dan_penyempit(dunia):
    c = dunia.api.client
    lead = (await c.get(f"{URL}/status-summary", headers=bearer(dunia.lead))).json()["data"]
    assert {s["status"]: s["count"] for s in lead} == {
        "Intake": 1,
        "Assigned": 1,
        "Awaiting Assignment": 1,
    }
    for aktor in (dunia.sa2, dunia.sales_a):
        data = (await c.get(f"{URL}/status-summary", headers=bearer(aktor))).json()["data"]
        assert {s["status"]: s["count"] for s in data} == {s["status"]: s["count"] for s in lead}
    mine = (
        await c.get(
            f"{URL}/status-summary", params={"sales_pic": "me"}, headers=bearer(dunia.sales_b)
        )
    ).json()["data"]
    assert sum(s["count"] for s in mine) == 2
    assigned = (
        await c.get(
            f"{URL}/status-summary", params={"assigned_to": "me"}, headers=bearer(dunia.sa1)
        )
    ).json()["data"]
    assert assigned == [{"status": "Assigned", "count": 1}]


async def test_daftar_tanpa_login_ditolak(api):
    assert (await api.client.get(URL)).status_code in (401, 403)


# --------------------------------------------------------------------------- detail & akses


@pytest.mark.parametrize("aktor", ["sales_b", "sa1", "sa2", "lead", "admin", "sales_a"])
async def test_detail_proyek_terbuka_untuk_semua_peran(dunia, aktor):
    """Keputusan 2026-11-10: Sales PIC, SA ditugaskan, pihak tak terkait, dan Lead/Admin semuanya 200."""
    resp = await dunia.api.client.get(f"{URL}/PRJ-B1", headers=bearer(getattr(dunia, aktor)))
    assert resp.status_code == 200, resp.text


async def test_detail_proyek_tidak_ada_404(dunia):
    assert (
        await dunia.api.client.get(f"{URL}/PRJ-NOPE", headers=bearer(dunia.lead))
    ).status_code == 404


async def test_detail_memuat_pic_collaborator_dan_source_document(dunia):
    await simpan(
        dunia.db,
        bangun_source_doc(
            "PRJ-B2",
            filename="rfp.pdf",
            doc_type="RFP",
            extraction_status="extracted",
            extracted_text="abcde",
            truncated=True,
        ),
    )
    await dunia.db.commit()

    data = (await dunia.api.client.get(f"{URL}/PRJ-B2", headers=bearer(dunia.lead))).json()["data"]

    assert data["sales_pic"]["id"] == str(dunia.sales_b.id)
    assert data["sales_pic"]["email"] == dunia.sales_b.email
    assert data["assigned_sa"] is None
    assert [c["user_id"] for c in data["collaborators"]] == [str(dunia.sa2.id)]
    assert data["collaborators"][0]["added_by_name"] == dunia.lead.name
    (doc,) = data["source_documents"]
    assert doc["filename"] == "rfp.pdf" and doc["text_length"] == 5 and doc["truncated"] is True
    assert "extracted_text" not in doc  # teks penuh tidak ikut ke detail

    b1 = (await dunia.api.client.get(f"{URL}/PRJ-B1", headers=bearer(dunia.lead))).json()["data"]
    assert b1["assigned_sa"]["email"] == dunia.sa1.email


# --------------------------------------------------------------------------- qualification view


async def test_detail_proyek_baru_menampilkan_jawaban_subskor_dan_feedback(api):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    id_project = (await buat_proyek(api, sales, jawaban_lemah())).json()["data"]["id_project"]

    data = (await api.client.get(f"{URL}/{id_project}", headers=sales)).json()["data"]

    q = data["qualification"]
    assert q["legacy"] is False and q["scoring_pending"] is False
    assert q["schema_version"] == 1
    assert q["answers"]["peran_pic"] == "Tidak tahu"
    assert set(q["sub_scores"]) == {"budget", "authority", "need", "timeline"}
    assert q["feedback"].startswith("Kriteria berikut perlu dilengkapi")
    assert q["override_sub_scores"] is None and q["legacy_data"] is None
    assert data["bant_score"] == sum(q["sub_scores"].values())


async def test_detail_qualification_state_scoring_menyembunyikan_skor_sementara(api, db_session):
    sales = await api.login_demo("Sales")
    id_project = (await buat_proyek(api, sales, jawaban_kuat())).json()["data"]["id_project"]
    await set_status(
        db_session,
        id_project,
        "Intake",
        qualification_state="Scoring",
        bant_detail={
            "budget": 25,
            "authority": 25,
            "need": 25,
            "timeline": 25,
            "catatan": "meta",
        },
    )

    data = (await api.client.get(f"{URL}/{id_project}", headers=sales)).json()["data"]

    assert (data["status"], data["qualification_state"]) == ("Intake", "Scoring")
    assert data["bant_score"] is None
    assert data["bant_detail"] == {"catatan": "meta"}  # sub-skor numerik disembunyikan
    q = data["qualification"]
    assert q["scoring_pending"] is True and q["sub_scores"] is None and q["feedback"] is None
    assert q["answers"] is not None  # jawaban tetap tampil


async def test_detail_proyek_legacy_menampilkan_legacy_data(api, db_session):
    lead = await api.login_demo("Lead_SA")
    sales = await user_baru(db_session, "Sales")
    legacy = bangun_project(
        sales.id,
        status="Awaiting Assignment",
        bant_score=65,
        bant_detail={
            "budget_mrr": 1000,
            "pic_name": "Siti",
            "need_description": "x",
            "catatan": "y",
        },
    )
    await simpan(db_session, legacy)
    await db_session.commit()

    q = (await api.client.get(f"{URL}/{legacy.id_project}", headers=lead)).json()["data"][
        "qualification"
    ]

    assert q["legacy"] is True
    assert q["answers"] is None and q["schema_version"] is None
    assert q["legacy_data"] == {"budget_mrr": 1000, "pic_name": "Siti", "need_description": "x"}
    assert q["sub_scores"] is None  # sub-skor numerik tidak lengkap


async def test_detail_menampilkan_override_lead_sa(api, db_session):
    await api.login_demo("Lead_SA")
    sales = await api.login_demo("Sales")
    id_project = (await buat_proyek(api, sales, jawaban_lemah())).json()["data"]["id_project"]
    lead = await api.login_demo("Lead_SA")
    await api.client.post(
        f"{URL}/{id_project}/score-manual",
        json={"budget": 25, "authority": 20, "need": 10, "timeline": 5, "reason": "uji"},
        headers=lead,
    )

    q = (await api.client.get(f"{URL}/{id_project}", headers=sales)).json()["data"]["qualification"]

    assert q["override_sub_scores"] == {"budget": 25, "authority": 20, "need": 10, "timeline": 5}


# --------------------------------------------------------------------------- soft delete


async def _sla_aktif(db, id_project: str) -> SLATracking:
    sla = bangun_sla(id_project)
    await simpan(db, sla)
    await db.commit()
    return sla


@pytest.mark.parametrize("aktor", ["lead", "admin"])
async def test_soft_delete_oleh_lead_dan_admin_menyaring_proyek_dan_menghentikan_sla(dunia, aktor):
    sla = await _sla_aktif(dunia.db, "PRJ-B1")

    resp = await dunia.api.client.delete(f"{URL}/PRJ-B1", headers=bearer(getattr(dunia, aktor)))

    assert resp.status_code == 200, resp.text
    assert "PRJ-B1" not in await _ids(await dunia.api.client.get(URL, headers=bearer(dunia.lead)))
    assert (
        await dunia.api.client.get(f"{URL}/PRJ-B1", headers=bearer(dunia.lead))
    ).status_code == 404
    # Baris tetap ada di DB (soft delete) dan dicap pelaku.
    baris = (
        await dunia.db.execute(
            select(Project.deleted_at, Project.deleted_by)
            .where(Project.id_project == "PRJ-B1")
            .execution_options(include_deleted=True)
        )
    ).one()
    pelaku = getattr(dunia, aktor)
    assert baris.deleted_at is not None and baris.deleted_by == pelaku.id
    await dunia.db.refresh(sla)
    assert sla.stopped_at is not None


@pytest.mark.parametrize("aktor", ["sales_b", "sa1", "sales_a"])
async def test_hapus_proyek_ditolak_untuk_sales_dan_sa(dunia, aktor):
    resp = await dunia.api.client.delete(f"{URL}/PRJ-B1", headers=bearer(getattr(dunia, aktor)))

    assert resp.status_code == 403
    assert (
        await dunia.api.client.get(f"{URL}/PRJ-B1", headers=bearer(dunia.lead))
    ).status_code == 200


async def test_hapus_proyek_tidak_ada_404_dan_sudah_terhapus_404(dunia):
    c, h = dunia.api.client, bearer(dunia.lead)
    assert (await c.delete(f"{URL}/PRJ-NOPE", headers=h)).status_code == 404
    assert (await c.delete(f"{URL}/PRJ-A1", headers=h)).status_code == 200
    assert (await c.delete(f"{URL}/PRJ-A1", headers=h)).status_code == 404


async def test_proyek_terhapus_tidak_muncul_di_ringkasan_status(dunia):
    c, h = dunia.api.client, bearer(dunia.lead)
    await c.delete(f"{URL}/PRJ-A1", headers=h)

    ringkas = (await c.get(f"{URL}/status-summary", headers=h)).json()["data"]

    assert "Intake" not in {s["status"] for s in ringkas}
