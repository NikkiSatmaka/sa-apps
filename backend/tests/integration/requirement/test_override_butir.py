"""Override per butir Requirement: hak akses, penguncian Final, efek di Postgres (tiket B9)."""

import pytest

from tests.integration.requirement.conftest import BUTIR_AWAL, PROJECTS, jawaban_lemah


def url_items(id_project, item_id=None):
    dasar = f"{PROJECTS}/{id_project}/requirement/items"
    return dasar if item_id is None else f"{dasar}/{item_id}"


BODY = {"kategori": "Kepatuhan", "butir": "Wajib ISO 27001"}


async def siapkan(s):
    id_project = await s.proyek_lolos_gate()
    sa = await s.tugaskan_sa(id_project)
    return id_project, sa


# --- hak akses (matriks)
@pytest.mark.parametrize("role", ["SA", "Lead_SA", "Admin"])
async def test_sa_ditugaskan_lead_sa_dan_admin_dapat_menambah_mengubah_dan_menghapus_butir(
    skenario, role
):
    s = skenario
    id_project, _ = await siapkan(s)
    awal = await s.requirement(id_project)
    hash_awal = awal.source_hash
    id_pertama = s.butir_id(awal)[0]
    pengguna = await s.user(role)

    tambah = await s.req("POST", url_items(id_project), role, json=BODY)
    assert tambah.status_code == 201, tambah.text
    doc = await s.requirement(id_project)
    assert doc.is_overridden is True and doc.updated_by == pengguna.id
    assert [i["butir"] for i in doc.content][-1] == "Wajib ISO 27001"
    id_baru = doc.content[-1]["id"]
    assert len(id_baru) == 8 and len(doc.content) == len(BUTIR_AWAL) + 1

    ubah = await s.req(
        "PUT",
        url_items(id_project, id_pertama),
        role,
        json={"kategori": "Teknis", "butir": "Diubah"},
    )
    assert ubah.status_code == 200, ubah.text
    doc = await s.requirement(id_project)
    assert doc.content[0] == {"id": id_pertama, "kategori": "Teknis", "butir": "Diubah"}

    hapus = await s.req("DELETE", url_items(id_project, id_baru), role)
    assert hapus.status_code == 200, hapus.text
    doc = await s.requirement(id_project)
    assert id_baru not in s.butir_id(doc) and len(doc.content) == len(BUTIR_AWAL)
    assert doc.source_hash == hash_awal  # edit manual tidak menyentuh hash sumber
    assert s.llm.jumlah("complete_text") == 1


@pytest.mark.parametrize("metode", ["POST", "PUT", "DELETE"])
async def test_sales_pic_ditolak_403_dan_data_tidak_berubah(skenario, metode):
    s = skenario
    id_project, _ = await siapkan(s)
    awal = await s.requirement(id_project)
    konten = awal.content
    url = url_items(id_project) if metode == "POST" else url_items(id_project, konten[0]["id"])

    resp = await s.req(metode, url, "Sales", json=BODY if metode != "DELETE" else None)

    assert resp.status_code == 403
    akhir = await s.requirement(id_project)
    assert akhir.content == konten and akhir.is_overridden is False


@pytest.mark.parametrize("peran_lain", ["SA", "collaborator"])
async def test_sa_tidak_ditugaskan_dan_kolaborator_hanya_baca(skenario, peran_lain):
    s = skenario
    id_project, _ = await siapkan(s)
    if peran_lain == "SA":
        _, header = await s.pengguna_baru("SA")
    else:
        user, header = await s.pengguna_baru("SA")
        await s.kolaborator(id_project, user, "contributor")
    konten = (await s.requirement(id_project)).content

    resp = await s.api.client.post(url_items(id_project), headers=header, json=BODY)

    assert resp.status_code == 403
    assert (await s.requirement(id_project)).content == konten


async def test_tanpa_autentikasi_ditolak(skenario):
    s = skenario
    id_project, _ = await siapkan(s)
    resp = await s.api.client.post(url_items(id_project), json=BODY)
    assert resp.status_code in (401, 403)


# --- Final terkunci
async def test_requirement_final_terkunci_409_untuk_semua_operasi_sampai_diturunkan_lead_sa(
    skenario,
):
    s = skenario
    id_project, _ = await siapkan(s)
    doc = await s.requirement(id_project)
    id_butir = s.butir_id(doc)[0]
    for status in ("Reviewed", "Final"):
        resp = await s.req(
            "PATCH",
            f"/api/v1/documents/{doc.id_doc}/status",
            "Lead_SA",
            json={"new_status": status},
        )
        assert resp.status_code == 200, resp.text
    konten = (await s.requirement(id_project)).content

    for role in ("SA", "Lead_SA", "Admin"):
        assert (await s.req("POST", url_items(id_project), role, json=BODY)).status_code == 409
        assert (
            await s.req("PUT", url_items(id_project, id_butir), role, json=BODY)
        ).status_code == 409
        assert (await s.req("DELETE", url_items(id_project, id_butir), role)).status_code == 409
    assert (await s.requirement(id_project)).content == konten

    turun = await s.req(
        "PATCH",
        f"/api/v1/documents/{doc.id_doc}/status",
        "Lead_SA",
        json={"new_status": "Reviewed"},
    )
    assert turun.status_code == 200
    assert (await s.req("POST", url_items(id_project), "SA", json=BODY)).status_code == 201


async def test_403_didahulukan_atas_409_untuk_sales_pada_requirement_final(skenario):
    s = skenario
    id_project, _ = await siapkan(s)
    doc = await s.requirement(id_project)
    doc.status = "Final"
    await s.db.flush()

    assert (await s.req("POST", url_items(id_project), "Sales", json=BODY)).status_code == 403


# --- tidak ditemukan & validasi
async def test_proyek_requirement_dan_butir_tidak_ada_404(skenario):
    s = skenario
    id_project, _ = await siapkan(s)
    id_nc = await s.buat_proyek(jawaban_lemah())  # tidak punya Requirement

    assert (
        await s.req("POST", url_items("PRJ-TIDAK-ADA"), "Lead_SA", json=BODY)
    ).status_code == 404
    assert (await s.req("POST", url_items(id_nc), "Lead_SA", json=BODY)).status_code == 404
    assert (
        await s.req("PUT", url_items(id_project, "zzzzzzzz"), "Lead_SA", json=BODY)
    ).status_code == 404
    assert (await s.req("DELETE", url_items(id_project, "zzzzzzzz"), "Lead_SA")).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kategori": "Ngawur", "butir": "x"},
        {"kategori": "Teknis", "butir": ""},
        {"kategori": "Teknis", "butir": "   "},
        {"kategori": "Teknis", "butir": "x" * 1001},
        {"kategori": "Teknis"},
        {},
    ],
)
async def test_body_tidak_valid_422_dan_tidak_menyimpan(skenario, body):
    s = skenario
    id_project, _ = await siapkan(s)
    konten = (await s.requirement(id_project)).content

    resp = await s.req("POST", url_items(id_project), "Lead_SA", json=body)

    assert resp.status_code == 422
    akhir = await s.requirement(id_project)
    assert akhir.content == konten and akhir.is_overridden is False


async def test_semua_butir_boleh_dihapus_sampai_kosong(skenario):
    s = skenario
    id_project, _ = await siapkan(s)
    for id_butir in s.butir_id(await s.requirement(id_project)):
        resp = await s.req("DELETE", url_items(id_project, id_butir), "SA")
        assert resp.status_code == 200, resp.text

    doc = await s.requirement(id_project)
    assert doc.content == [] and doc.is_overridden is True


async def test_butir_dengan_unicode_dan_teks_panjang_tersimpan_utuh(skenario):
    s = skenario
    id_project, _ = await siapkan(s)
    teks = "Kebutuhan 日本語 🙂 é " + "x" * 900

    resp = await s.req(
        "POST", url_items(id_project), "SA", json={"kategori": "Asumsi", "butir": teks}
    )

    assert resp.status_code == 201
    assert (await s.requirement(id_project)).content[-1]["butir"] == teks
