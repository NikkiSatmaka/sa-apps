"""
Re-summarize, notifikasi "sumber berubah", dan aksi pemilik Requirement (tiket B9, spec #49).

Pemicu sumber berubah di sini: Lead_SA mengoreksi jawaban kuesioner setelah lolos gate
(`PUT .../qualification-answers`, skor tidak dihitung ulang) → background `resummarize`.
"""

import pytest

from app.services.notification_service import notification_service
from app.services.requirement_generator import MAX_GENERATE_RETRIES, compute_source_hash
from tests.integration.model_helpers import bangun_user, simpan
from tests.integration.requirement.conftest import (
    BUTIR_BARU,
    PROJECTS,
    items_json,
    jawaban_kuat,
    jawaban_lemah,
)


async def ubah_jawaban(s, id_project, role="Lead_SA", **perubahan):
    resp = await s.req(
        "PUT",
        f"{PROJECTS}/{id_project}/qualification-answers",
        role,
        json=jawaban_kuat(**perubahan),
    )
    assert resp.status_code == 200, resp.text
    return resp


async def tambah_butir(s, id_project, role="SA", teks="Butir manual SA"):
    resp = await s.req(
        "POST",
        f"{PROJECTS}/{id_project}/requirement/items",
        role,
        json={"kategori": "Asumsi", "butir": teks},
    )
    assert resp.status_code == 201, resp.text
    return resp


async def daftar_dokumen(s, id_project, role="SA"):
    resp = await s.req("GET", f"{PROJECTS}/{id_project}/documents", role)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def requirement_dari(data):
    return next(d for d in data["documents"] if d["doc_type"] == "Requirement")


# --- re-summarize biasa
async def test_koreksi_jawaban_memperbarui_requirement_biasa_dengan_hash_baru(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    lama = await s.requirement(id_project)
    id_lama, hash_lama, ids_lama = lama.id_doc, lama.source_hash, s.butir_id(lama)
    s.llm.sukses("complete_text", items_json(*BUTIR_BARU))

    await ubah_jawaban(s, id_project, skala="200 server, 80 TB")

    proyek = await s.proyek(id_project)
    baru = await s.requirement(id_project)
    assert baru.id_doc == id_lama  # satu dokumen, diperbarui di tempat
    assert [(i["kategori"], i["butir"]) for i in baru.content] == list(BUTIR_BARU)
    assert baru.source_hash != hash_lama
    assert baru.source_hash == compute_source_hash(proyek.qualification_answers, [])
    assert not set(ids_lama) & set(s.butir_id(baru))
    assert baru.is_overridden is False
    assert (proyek.status, proyek.bant_score) == ("Awaiting Assignment", proyek.bant_score)
    assert s.llm.jumlah("complete_text") == 2
    assert await s.notifikasi_sumber_berubah(id_project) == []


async def test_koreksi_dengan_jawaban_identik_tidak_memanggil_llm(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    sebelum = await s.requirement(id_project)
    konten, hash_awal = sebelum.content, sebelum.source_hash

    await ubah_jawaban(s, id_project)  # nilai sama persis

    sesudah = await s.requirement(id_project)
    assert s.llm.jumlah("complete_text") == 1
    assert (sesudah.content, sesudah.source_hash) == (konten, hash_awal)


async def test_urutan_kunci_jawaban_tidak_mengubah_hash_dan_tidak_memicu_llm(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    terbalik = dict(reversed(list(jawaban_kuat().items())))

    resp = await s.req(
        "PUT", f"{PROJECTS}/{id_project}/qualification-answers", "Lead_SA", json=terbalik
    )

    assert resp.status_code == 200, resp.text
    assert s.llm.jumlah("complete_text") == 1


async def test_resummarize_gagal_mempertahankan_konten_dan_hash_lama_lalu_dicoba_lagi(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    lama = await s.requirement(id_project)
    konten, hash_lama = lama.content, lama.source_hash
    for _ in range(MAX_GENERATE_RETRIES):
        s.llm.malformed("complete_text")

    await ubah_jawaban(s, id_project, skala="gagal-dulu")

    tertahan = await s.requirement(id_project)
    assert (tertahan.content, tertahan.source_hash) == (konten, hash_lama)
    assert (await s.proyek(id_project)).requirement_generation_status == "ready"
    assert s.llm.jumlah("complete_text") == 1 + MAX_GENERATE_RETRIES

    # Pemicu berikutnya berhasil karena hash tersimpan masih yang lama.
    s.llm.sukses("complete_text", items_json(*BUTIR_BARU))
    await ubah_jawaban(s, id_project, skala="gagal-dulu")
    pulih = await s.requirement(id_project)
    assert [(i["kategori"], i["butir"]) for i in pulih.content] == list(BUTIR_BARU)
    assert pulih.source_hash != hash_lama


async def test_tanpa_requirement_karena_generate_gagal_koreksi_jawaban_tidak_memanggil_llm(
    skenario,
):
    s = skenario
    await s.header("Lead_SA")
    s.llm.malformed("complete_text", tetap=True)
    id_project = await s.buat_proyek(jawaban_kuat())
    assert (await s.proyek(id_project)).requirement_generation_status == "failed"
    dipanggil = s.llm.jumlah("complete_text")

    await ubah_jawaban(s, id_project, skala="lain")

    assert s.llm.jumlah("complete_text") == dipanggil
    assert await s.requirement(id_project) is None


# --- dilindungi: override
async def test_requirement_override_tidak_ditimpa_dan_sa_diberi_tahu_sekali_per_hash_basi(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    sa = await s.tugaskan_sa(id_project)
    await tambah_butir(s, id_project)
    sebelum = await s.requirement(id_project)
    konten, hash_awal = sebelum.content, sebelum.source_hash
    assert sebelum.is_overridden is True

    await ubah_jawaban(s, id_project, skala="basi-1")

    dokumen = await s.requirement(id_project)
    assert dokumen.content == konten and dokumen.source_hash == hash_awal  # tidak disentuh
    assert s.llm.jumlah("complete_text") == 1
    notif = await s.notifikasi_sumber_berubah(id_project)
    assert [n.recipient_user_id for n in notif] == [sa.id]
    assert notif[0].event_type == "status_change" and notif[0].channel == "in-app"
    assert "Sumber Requirement" in notif[0].notification_metadata["message"]
    assert dokumen.source_changed_notified_hash is not None

    # Hash basi yang sama dipicu lagi → tidak ada notifikasi tambahan.
    await ubah_jawaban(s, id_project, skala="basi-1")
    assert len(await s.notifikasi_sumber_berubah(id_project)) == 1

    # Hash basi BARU → notifikasi baru.
    await ubah_jawaban(s, id_project, skala="basi-2")
    assert len(await s.notifikasi_sumber_berubah(id_project)) == 2


async def test_banner_sumber_berubah_hanya_untuk_requirement_dilindungi_yang_basi(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    assert requirement_dari(await daftar_dokumen(s, id_project))["source_changed"] is False

    await tambah_butir(s, id_project)
    assert requirement_dari(await daftar_dokumen(s, id_project))["source_changed"] is False

    await ubah_jawaban(s, id_project, skala="berubah")
    data = await daftar_dokumen(s, id_project)
    assert requirement_dari(data)["source_changed"] is True
    assert requirement_dari(data)["is_overridden"] is True


async def test_tanpa_sa_ditugaskan_semua_lead_sa_diberi_tahu(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    lead = await s.user("Lead_SA")
    lead_lain = bangun_user(role="Lead_SA")
    sales_lain = bangun_user(role="Sales")
    await simpan(s.db, lead_lain, sales_lain)
    await tambah_butir(s, id_project, role="Lead_SA")

    await ubah_jawaban(s, id_project, skala="basi")

    penerima = {n.recipient_user_id for n in await s.notifikasi_sumber_berubah(id_project)}
    assert penerima == {lead.id, lead_lain.id}


async def test_requirement_final_tidak_ditimpa_dan_memicu_notifikasi(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    sa = await s.tugaskan_sa(id_project)
    doc = await s.requirement(id_project)
    for status in ("Reviewed", "Final"):
        resp = await s.req(
            "PATCH",
            f"/api/v1/documents/{doc.id_doc}/status",
            "Lead_SA",
            json={"new_status": status},
        )
        assert resp.status_code == 200, resp.text
    konten = (await s.requirement(id_project)).content

    await ubah_jawaban(s, id_project, skala="basi-final")

    akhir = await s.requirement(id_project)
    assert akhir.content == konten and akhir.is_overridden is False
    assert s.llm.jumlah("complete_text") == 1
    assert [n.recipient_user_id for n in await s.notifikasi_sumber_berubah(id_project)] == [sa.id]
    assert requirement_dari(await daftar_dokumen(s, id_project))["source_changed"] is True


@pytest.mark.parametrize("status_terminal", ["Won", "Lost", "Handed Over", "Closed"])
@pytest.mark.parametrize("dilindungi", [False, True], ids=["biasa", "override"])
async def test_proyek_terminal_tidak_di_resummarize_dan_tidak_diberi_tahu(
    skenario, status_terminal, dilindungi
):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    if dilindungi:
        await tambah_butir(s, id_project)
    await s.tetapkan(id_project, status=status_terminal)
    sebelum = await s.requirement(id_project)
    konten, hash_awal = sebelum.content, sebelum.source_hash

    await ubah_jawaban(s, id_project, skala="setelah-terminal")

    sesudah = await s.requirement(id_project)
    assert (sesudah.content, sesudah.source_hash) == (konten, hash_awal)
    assert s.llm.jumlah("complete_text") == 1
    assert await s.notifikasi_sumber_berubah(id_project) == []


async def test_notifikasi_gagal_tidak_menandai_hash_dan_dicoba_lagi_pemicu_berikutnya(
    skenario, monkeypatch
):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    await tambah_butir(s, id_project)
    asli = notification_service.send_notification

    async def meledak(event):
        raise RuntimeError("smtp mati")

    monkeypatch.setattr(notification_service, "send_notification", meledak)
    await ubah_jawaban(s, id_project, skala="basi")
    assert (await s.requirement(id_project)).source_changed_notified_hash is None
    assert await s.notifikasi_sumber_berubah(id_project) == []

    monkeypatch.setattr(notification_service, "send_notification", asli)
    await ubah_jawaban(s, id_project, skala="basi")
    assert len(await s.notifikasi_sumber_berubah(id_project)) == 1


# --- aksi pemilik
async def test_pertahankan_versi_saya_memajukan_hash_tanpa_mengubah_konten(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    await tambah_butir(s, id_project)
    await ubah_jawaban(s, id_project, skala="basi")
    dokumen = await s.requirement(id_project)
    konten, hash_basi = dokumen.content, dokumen.source_hash
    proyek = await s.proyek(id_project)

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/keep-version", "SA")

    assert resp.status_code == 200, resp.text
    akhir = await s.requirement(id_project)
    assert akhir.content == konten and akhir.is_overridden is True
    assert akhir.source_hash == compute_source_hash(proyek.qualification_answers, [])
    assert akhir.source_hash != hash_basi
    assert resp.json()["data"]["source_changed"] is False
    assert requirement_dari(await daftar_dokumen(s, id_project))["source_changed"] is False
    # Setelah dipertahankan, pemicu dengan sumber sama tidak memberi tahu lagi...
    await ubah_jawaban(s, id_project, skala="basi")
    assert len(await s.notifikasi_sumber_berubah(id_project)) == 1
    # ...tetapi perubahan sumber berikutnya basi lagi dan diberitahukan.
    await ubah_jawaban(s, id_project, skala="basi-baru")
    assert len(await s.notifikasi_sumber_berubah(id_project)) == 2


async def test_pertahankan_versi_pada_requirement_biasa_ditolak_409_hash_tak_berubah(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    hash_awal = (await s.requirement(id_project)).source_hash

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/keep-version", "SA")

    assert resp.status_code == 409
    assert (await s.requirement(id_project)).source_hash == hash_awal


@pytest.mark.parametrize("role", ["Sales", "Lead_SA", "Admin"])
async def test_pertahankan_versi_hak_akses(skenario, role):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    await tambah_butir(s, id_project)
    await ubah_jawaban(s, id_project, skala="basi")

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/keep-version", role)

    assert resp.status_code == (403 if role == "Sales" else 200), resp.text


async def test_pertahankan_versi_sa_tidak_ditugaskan_403_dan_requirement_belum_ada_404(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    assert (
        await s.req("POST", f"{PROJECTS}/{id_project}/requirement/keep-version", "SA")
    ).status_code == 403
    assert (
        await s.req("POST", f"{PROJECTS}/PRJ-TIDAK-ADA/requirement/keep-version", "Lead_SA")
    ).status_code == 404
    id_nc = await s.buat_proyek(jawaban_lemah())
    assert (
        await s.req("POST", f"{PROJECTS}/{id_nc}/requirement/keep-version", "Lead_SA")
    ).status_code == 404


async def test_generate_ulang_setelah_sumber_berubah_menghapus_override_dan_banner(skenario):
    s = skenario
    id_project = await s.proyek_lolos_gate()
    await s.tugaskan_sa(id_project)
    await tambah_butir(s, id_project)
    await ubah_jawaban(s, id_project, skala="basi")
    assert (await s.requirement(id_project)).source_changed_notified_hash is not None
    s.llm.sukses("complete_text", items_json(*BUTIR_BARU))

    resp = await s.req("POST", f"{PROJECTS}/{id_project}/requirement/regenerate", "SA")

    assert resp.status_code == 202, resp.text
    proyek = await s.proyek(id_project)
    dokumen = await s.requirement(id_project)
    assert [(i["kategori"], i["butir"]) for i in dokumen.content] == list(BUTIR_BARU)
    assert dokumen.is_overridden is False and dokumen.source_changed_notified_hash is None
    assert dokumen.source_hash == compute_source_hash(proyek.qualification_answers, [])
    assert proyek.requirement_generation_status == "ready"
    assert requirement_dari(await daftar_dokumen(s, id_project))["source_changed"] is False
