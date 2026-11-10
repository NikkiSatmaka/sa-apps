"""
Akses `GET /documents` per peran, generate ulang manual, sweep `pending` saat startup, dan
constraint Requirement di Postgres (tiket B9, spec #49).
"""

import pytest

from app.services.requirement_generator import (
    MAX_GENERATE_RETRIES,
    sweep_stale_pending_requirements,
)
from tests.integration.model_helpers import bangun_document, ditolak
from tests.integration.requirement.conftest import (
    BUTIR_AWAL,
    BUTIR_BARU,
    PROJECTS,
    items_json,
    jawaban_lemah,
)


async def ambil_dokumen(s, id_project, role=None, header=None):
    url = f"{PROJECTS}/{id_project}/documents"
    if header is not None:
        return await s.api.client.get(url, headers=header)
    return await s.req("GET", url, role)


# --- GET /documents per peran
@pytest.mark.parametrize(
    ("role", "boleh_generate_ulang"),
    [("Sales", False), ("SA", True), ("Lead_SA", True), ("Admin", True)],
)
async def test_get_documents_peran_berhak_melihat_requirement_dan_flag_generate_ulang(
    skenario, role, boleh_generate_ulang
):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)  # Sales demo = PIC, SA demo = ditugaskan

    resp = await ambil_dokumen(s, id_project, role)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1 and data["documents"][0]["doc_type"] == "Requirement"
    assert data["requirement_generation_status"] == "ready"
    assert data["can_regenerate_requirement"] is boleh_generate_ulang
    assert [(i["kategori"], i["butir"]) for i in data["documents"][0]["content"]] == list(
        BUTIR_AWAL
    )


async def test_get_documents_kolaborator_boleh_lihat_tetapi_tidak_boleh_generate_ulang(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    user, header = await s.pengguna_baru("SA")
    await s.kolaborator(id_project, user)

    resp = await ambil_dokumen(s, id_project, header=header)

    assert resp.status_code == 200
    assert resp.json()["data"]["can_regenerate_requirement"] is False


@pytest.mark.parametrize("role", ["Sales", "SA"])
async def test_get_documents_pengguna_tanpa_akses_403_tanpa_membocorkan_dokumen(skenario, role):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    _, header = await s.pengguna_baru(role)

    resp = await ambil_dokumen(s, id_project, header=header)

    assert resp.status_code == 403
    assert "documents" not in resp.text and "Login terpusat" not in resp.text


async def test_get_documents_tanpa_login_dan_proyek_tidak_ada(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()

    assert (await ambil_dokumen(s, id_project, header={})).status_code in (401, 403)
    assert (await ambil_dokumen(s, "PRJ-TIDAK-ADA", "Lead_SA")).status_code == 404


async def test_get_documents_status_pending_failed_dan_none_tampil_untuk_ui(skenario):
    s = skenario
    id_nc = await s.buat_proyek(jawaban_lemah())
    data = (await ambil_dokumen(s, id_nc, "Lead_SA")).json()["data"]
    assert data["requirement_generation_status"] is None and data["total"] == 0

    id_project = await s.proyek_lolos_gate()
    for status in ("pending", "failed"):
        await s.tetapkan(id_project, requirement_generation_status=status)
        data = (await ambil_dokumen(s, id_project, "Lead_SA")).json()["data"]
        assert data["requirement_generation_status"] == status


# --- generate ulang manual
@pytest.mark.parametrize("role", ["SA", "Lead_SA", "Admin"])
async def test_generate_ulang_menimpa_konten_dan_menghapus_override(skenario, role):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    await s.req(
        "POST",
        f"{PROJECTS}/{id_project}/requirement/items",
        "SA",
        json={"kategori": "Asumsi", "butir": "Manual"},
    )
    assert (await s.requirement(id_project)).is_overridden is True
    s.llm.sukses("complete_text", items_json(*BUTIR_BARU))

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/regenerate", role)

    assert resp.status_code == 202, resp.text
    assert resp.json()["data"]["requirement_generation_status"] == "pending"
    doc = await s.requirement(id_project)
    assert [(i["kategori"], i["butir"]) for i in doc.content] == list(BUTIR_BARU)
    assert doc.is_overridden is False
    assert (await s.proyek(id_project)).requirement_generation_status == "ready"
    assert await s.jumlah_requirement(id_project) == 1


@pytest.mark.parametrize("peran_lain", ["Sales", "SA-lain", "kolaborator"])
async def test_generate_ulang_peran_tanpa_hak_403_dan_tanpa_llm(skenario, peran_lain):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    if peran_lain == "Sales":
        header = await s.header("Sales")
    else:
        user, header = await s.pengguna_baru("SA")
        if peran_lain == "kolaborator":
            await s.kolaborator(id_project, user, "contributor")

    resp = await s.api.client.post(
        f"{PROJECTS}/{id_project}/requirement/regenerate", headers=header
    )

    assert resp.status_code == 403
    assert s.llm.jumlah("complete_text") == 1
    assert (await s.proyek(id_project)).requirement_generation_status == "ready"


async def test_generate_ulang_belum_lolos_gate_409_dan_pending_409_tanpa_generate_ganda(skenario):
    s = skenario
    id_nc = await s.buat_proyek(jawaban_lemah())
    assert (
        await s.req("POST", f"{PROJECTS}/{id_nc}/requirement/regenerate", "Lead_SA")
    ).status_code == 409

    id_project = await s.proyek_lolos_gate()
    await s.tetapkan(id_project, requirement_generation_status="pending")
    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/regenerate", "Lead_SA")
    assert resp.status_code == 409
    assert (await s.proyek(id_project)).requirement_generation_status == "pending"
    assert s.llm.jumlah("complete_text") == 1


async def test_generate_ulang_proyek_tidak_ada_404(skenario):
    resp = await skenario.req("POST", f"{PROJECTS}/PRJ-X/requirement/regenerate", "Lead_SA")
    assert resp.status_code == 404


async def test_coba_lagi_setelah_gagal_membuat_requirement_pertama(skenario):
    s = skenario
    await s.header("Lead_SA")
    for _ in range(MAX_GENERATE_RETRIES):
        s.llm.malformed("complete_text")
    id_project = await s.buat_proyek()
    assert (await s.proyek(id_project)).requirement_generation_status == "failed"
    assert await s.requirement(id_project) is None
    s.llm.sukses("complete_text", items_json(*BUTIR_AWAL))

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/regenerate", "Lead_SA")

    assert resp.status_code == 202, resp.text
    assert (await s.proyek(id_project)).requirement_generation_status == "ready"
    assert len((await s.requirement(id_project)).content) == len(BUTIR_AWAL)


async def test_generate_ulang_gagal_mempertahankan_konten_lama_dan_menandai_failed(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    lama = (await s.requirement(id_project)).content
    s.llm.malformed("complete_text", tetap=True)

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/regenerate", "Lead_SA")

    assert resp.status_code == 202
    assert (await s.proyek(id_project)).requirement_generation_status == "failed"
    doc = await s.requirement(id_project)
    assert doc.content == lama and doc.is_overridden is False
    # Status failed + dokumen lama: UI menampilkan tombol coba lagi dan tetap bisa melihat dokumen.
    data = (await ambil_dokumen(s, id_project, "Lead_SA")).json()["data"]
    assert data["requirement_generation_status"] == "failed" and data["total"] == 1


# --- sweep startup
async def _proyek_dengan_status(s, status):
    id_project = await s.proyek_lolos_gate()
    await s.tetapkan(id_project, requirement_generation_status=status)
    return id_project


async def test_sweep_mengubah_hanya_pending_menjadi_failed_dan_idempoten(skenario):
    s = skenario
    p1 = await _proyek_dengan_status(s, "pending")
    p2 = await _proyek_dengan_status(s, "pending")
    siap = await _proyek_dengan_status(s, "ready")
    gagal = await _proyek_dengan_status(s, "failed")
    id_nc = await s.buat_proyek(jawaban_lemah())

    assert await sweep_stale_pending_requirements() == 2

    status = {
        i: (await s.proyek(i)).requirement_generation_status for i in (p1, p2, siap, gagal, id_nc)
    }
    assert status == {p1: "failed", p2: "failed", siap: "ready", gagal: "failed", id_nc: None}
    assert await sweep_stale_pending_requirements() == 0


async def test_startup_aplikasi_menjalankan_sweep(skenario):
    from app.main import startup_register_adapters

    s = skenario
    pending = await _proyek_dengan_status(s, "pending")

    await startup_register_adapters()

    assert (await s.proyek(pending)).requirement_generation_status == "failed"


async def test_sweep_yang_gagal_tidak_melempar_dan_melaporkan_nol(skenario, monkeypatch):
    s = skenario
    pending = await _proyek_dengan_status(s, "pending")

    def rusak():
        raise ConnectionError("db mati")

    with monkeypatch.context() as mp:
        mp.setattr("app.core.database.AsyncSessionLocal", rusak)
        assert await sweep_stale_pending_requirements() == 0

    # Kegagalan sweep tidak mengubah data apa pun.
    assert (await s.proyek(pending)).requirement_generation_status == "pending"


# --- constraint Postgres
async def test_satu_requirement_per_proyek_ditegakkan_unique_index(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()

    duplikat = bangun_document(
        id_project, None, doc_type="Requirement", folder_type="Inventory", gdrive_link=None
    )
    await ditolak(s.db, "uq_documents_requirement_per_project", duplikat)
    assert await s.jumlah_requirement(id_project) == 1


async def test_dokumen_non_requirement_tetap_wajib_link_dan_pembuat(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    sales = await s.user("Sales")

    await ditolak(
        s.db,
        "chk_documents_gdrive_link_required",
        bangun_document(id_project, sales.id, gdrive_link=None),
    )
    await ditolak(s.db, "chk_documents_created_by_required", bangun_document(id_project, None))


async def test_status_requirement_di_luar_himpunan_ditolak_check(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    doc = await s.requirement(id_project)
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as err:
        async with s.db.begin_nested():
            await s.db.execute(
                text("UPDATE documents SET status = 'Ngawur' WHERE id_doc = :d"), {"d": doc.id_doc}
            )
    assert "chk_documents_status" in str(err.value)
