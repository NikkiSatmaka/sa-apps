# ruff: noqa: F811  (fixture diimpor lalu dipakai sebagai argumen test)
"""
Unit test perilaku fake boundary (tiket B3): fake harus sukses/gagal sesuai program, merekam
panggilan, dan terpasang/ter-reset otomatis. Tanpa DB/Docker/jaringan.
"""

import pytest

from app.core.config import settings
from app.services.calendar_service import (
    CalendarAPIError,
    CalendarTimeoutError,
    calendar_service,
)
from app.services.folder_provisioner import FolderProvisioningError, folder_provisioner
from app.services.llm_provider import llm_factory
from app.services.notification_service import notification_service
from tests.integration.fakes.calendar import event_berjadwal, event_seharian
from tests.integration.fakes.fixtures import (  # noqa: F401
    fake_calendar,
    fake_drive,
    fake_gmail,
    fake_llm,
)


class _Proyek:
    id_project = "P-1"
    customer_name = "PT Contoh/Satu"
    project_name = "Proyek Alfa"


# ----------------------------------------------------------------------------- LLM


async def test_llm_sukses_per_jenis_dan_perekaman(fake_llm):
    fake_llm.sukses("complete_text", "halo")
    fake_llm.sukses("structure_text", {"a": 1})
    fake_llm.sukses("parse_document", "isi dokumen")
    provider = llm_factory.get_provider()

    teks = await provider.complete_text("prompt", temperature=0.3)
    terstruktur = await provider.structure_text("t", {"type": "object"})
    dokumen = await provider.parse_document(b"%PDF", "application/pdf", "ekstrak")

    assert (teks.status, teks.content) == ("success", "halo")
    assert terstruktur.content == {"a": 1}
    assert dokumen.content == "isi dokumen"
    assert [p.jenis for p in fake_llm.panggilan] == [
        "complete_text",
        "structure_text",
        "parse_document",
    ]
    assert fake_llm.panggilan_jenis("complete_text")[0].argumen == {
        "prompt": "prompt",
        "temperature": 0.3,
    }
    assert fake_llm.jumlah("parse_document") == 1


@pytest.mark.parametrize("tipe", ["timeout", "auth_error", "unknown"])
async def test_llm_error_membawa_tipe_dan_tanpa_content(fake_llm, tipe):
    fake_llm.error("complete_text", tipe)

    resp = await llm_factory.get_provider().complete_text("p")

    assert resp.status == "error"
    assert resp.error_type == tipe
    assert resp.content is None


async def test_llm_terpotong_melaporkan_max_tokens(fake_llm):
    fake_llm.terpotong("complete_text", "setengah kalimat")

    resp = await llm_factory.get_provider().complete_text("p")

    assert resp.status == "success"
    assert resp.metadata.finish_reason == "MAX_TOKENS"
    assert resp.content == "setengah kalimat"


async def test_llm_malformed_structure_text_error_dan_complete_text_teks_rusak(fake_llm):
    import json

    fake_llm.malformed("structure_text")
    fake_llm.malformed("complete_text")
    provider = llm_factory.get_provider()

    terstruktur = await provider.structure_text("t", {})
    teks = await provider.complete_text("p")

    assert (terstruktur.status, terstruktur.error_type) == ("error", "invalid_response")
    assert teks.status == "success"
    with pytest.raises(json.JSONDecodeError):
        json.loads(teks.content)


async def test_llm_antrean_berurutan_lalu_tetap(fake_llm):
    fake_llm.error("complete_text", "timeout")
    fake_llm.sukses("complete_text", "pulih", tetap=True)
    provider = llm_factory.get_provider()

    hasil = [(await provider.complete_text("p")).status for _ in range(3)]

    assert hasil == ["error", "success", "success"]


async def test_llm_tidak_terprogram_gagal_keras(fake_llm):
    with pytest.raises(AssertionError, match="tidak terprogram"):
        await llm_factory.get_provider().complete_text("p")


async def test_llm_exception_terprogram_di_raise(fake_llm):
    fake_llm.program("complete_text", RuntimeError("adapter meledak"))

    with pytest.raises(RuntimeError, match="meledak"):
        await llm_factory.get_provider().complete_text("p")


def test_llm_dipulihkan_setelah_test_pertama(fake_llm):
    assert "fake" in llm_factory.registered_adapters
    assert settings.LLM_PROVIDER == "fake"


def test_llm_tidak_bocor_ke_test_berikutnya():
    # Dijalankan setelah test di atas (urutan berkas), tetapi benar apa pun urutannya:
    # tanpa fixture, registry/provider tidak boleh memuat fake dari test lain.
    assert "fake" not in llm_factory.registered_adapters
    assert settings.LLM_PROVIDER != "fake"
    assert (
        llm_factory._current_provider is None
        or "Fake" not in type(llm_factory._current_provider).__name__
    )


# ----------------------------------------------------------------------------- Drive


async def test_drive_provision_merekam_id_dan_permission(fake_drive):
    hasil = await folder_provisioner.provision_project_folder(
        _Proyek(), "sa@x.id", "lead@x.id", "sales@x.id"
    )

    assert fake_drive.folder[hasil.master]["name"] == "PT Contoh_Satu - Proyek Alfa"
    assert {
        fake_drive.folder[i]["name"] for i in (hasil.inventory, hasil.diagram, hasil.solutions)
    } == {
        "Inventory",
        "Diagram",
        "Solutions",
    }
    assert fake_drive.peran(hasil.master, "sa@x.id") == "writer"
    assert fake_drive.peran(hasil.master, "lead@x.id") == "writer"
    assert fake_drive.peran(hasil.inventory, "sales@x.id") == "reader"
    assert fake_drive.peran(hasil.solutions, "sales@x.id") is None
    assert len({hasil.master, hasil.inventory, hasil.diagram, hasil.solutions}) == 4


async def test_drive_lock_unlock_solutions(fake_drive):
    await folder_provisioner.unlock_solutions_folder("sol-1", "sales@x.id")
    assert fake_drive.peran("sol-1", "sales@x.id") == "reader"

    await folder_provisioner.lock_solutions_folder("sol-1", "sales@x.id")

    assert fake_drive.peran("sol-1", "sales@x.id") is None
    assert [p.operasi for p in fake_drive.panggilan] == [
        "unlock_solutions_folder",
        "lock_solutions_folder",
    ]


async def test_drive_handover_membuat_final_deliverables(fake_drive):
    id_folder = await folder_provisioner.provision_handover("sol-1", "pmo@x.id", "dlv@x.id")

    assert fake_drive.folder[id_folder] == {"name": "Final_Deliverables", "parent": "sol-1"}
    assert fake_drive.peran(id_folder, "pmo@x.id") == "reader"
    assert fake_drive.peran(id_folder, "dlv@x.id") == "reader"


async def test_drive_fail_next_sekali_lalu_pulih_dan_tak_ada_efek_saat_gagal(fake_drive):
    fake_drive.fail_next("provision_handover", pesan="kuota habis")

    with pytest.raises(FolderProvisioningError, match="kuota habis"):
        await folder_provisioner.provision_handover("sol-1", "a@x.id", "b@x.id")
    assert fake_drive.folder == {}
    id_folder = await folder_provisioner.provision_handover("sol-1", "a@x.id", "b@x.id")

    assert id_folder in fake_drive.folder
    assert [p.berhasil for p in fake_drive.panggilan] == [False, True]


async def test_drive_fail_hanya_operasi_target(fake_drive):
    fake_drive.fail_always("lock_solutions_folder")

    await folder_provisioner.unlock_solutions_folder("sol-1", "s@x.id")  # tidak terpengaruh
    for _ in range(2):
        with pytest.raises(FolderProvisioningError):
            await folder_provisioner.lock_solutions_folder("sol-1", "s@x.id")


async def test_drive_fail_next_times_menghabiskan_jatah(fake_drive):
    fake_drive.fail_next(times=2)

    for _ in range(2):
        with pytest.raises(FolderProvisioningError):
            await folder_provisioner.unlock_solutions_folder("sol-1", "s@x.id")
    await folder_provisioner.unlock_solutions_folder("sol-1", "s@x.id")

    assert fake_drive.peran("sol-1", "s@x.id") == "reader"


# ----------------------------------------------------------------------------- Gmail


async def test_gmail_sukses_merekam_pesan(fake_gmail):
    ok = await notification_service.send_email("a@x.id", "Subjek", "tmpl", {"k": 1})

    assert ok is True
    assert [(s.to, s.subject, s.template, s.context) for s in fake_gmail.terkirim] == [
        ("a@x.id", "Subjek", "tmpl", {"k": 1})
    ]
    assert notification_service._is_gmail_configured() is True


async def test_gmail_fail_next_mengembalikan_false_lalu_pulih(fake_gmail):
    fake_gmail.fail_next(times=2)

    hasil = [await notification_service.send_email("a@x.id", "S", "t", {}) for _ in range(3)]

    assert hasil == [False, False, True]
    assert len(fake_gmail.gagal) == 2
    assert len(fake_gmail.terkirim) == 1


async def test_gmail_fail_always(fake_gmail):
    fake_gmail.fail_always()

    assert await notification_service.send_email("a@x.id", "S", "t", {}) is False
    assert fake_gmail.terkirim == []


async def test_gmail_tidak_terkonfigurasi_tidak_mengirim(fake_gmail):
    fake_gmail.terkonfigurasi = False

    assert await notification_service.send_email("a@x.id", "S", "t", {}) is False
    assert fake_gmail.percobaan == []
    assert notification_service._is_gmail_configured() is False


async def test_gmail_tunggu_percobaan_gagal_bila_tidak_cukup(fake_gmail):
    with pytest.raises(AssertionError, match="diharapkan 1"):
        await fake_gmail.tunggu_percobaan(1, batas_detik=0.05)


def test_gmail_dipulihkan_tanpa_fixture():
    # Tanpa fixture, send_email tetap method kelas asli (bukan fake).
    assert "send_email" not in vars(notification_service)


# ----------------------------------------------------------------------------- Calendar


async def test_calendar_event_terprogram_di_parse_logika_produksi(fake_calendar):
    fake_calendar.set_events(
        event_berjadwal("e1", "Rapat", "2025-01-06T09:00:00+07:00", "2025-01-06T10:30:00+07:00"),
        event_seharian("e2", "Cuti", "2025-01-07", "2025-01-08"),
        {"summary": "tanpa id"},
    )

    events = await calendar_service.fetch_events("token-abc")

    assert [e.gcal_event_id for e in events] == ["e1", "e2"]
    assert float(events[0].duration_hours) == 1.5 and events[0].is_all_day is False
    assert float(events[1].duration_hours) == 8 and events[1].is_all_day is True
    assert fake_calendar.access_token_diterima == ["token-abc"]


async def test_calendar_kegagalan_timeout_dan_api_sekali_lalu_pulih(fake_calendar):
    fake_calendar.set_events(event_seharian("e1", "Cuti", "2025-01-07", "2025-01-08"))
    fake_calendar.fail_next("timeout")
    fake_calendar.fail_next("api", "quota")

    with pytest.raises(CalendarTimeoutError):
        await calendar_service.fetch_events("t")
    with pytest.raises(CalendarAPIError, match="quota"):
        await calendar_service.fetch_events("t")
    pulih = await calendar_service.fetch_events("t")

    assert len(pulih) == 1


async def test_calendar_fail_always(fake_calendar):
    fake_calendar.fail_always("api")

    for _ in range(2):
        with pytest.raises(CalendarAPIError):
            await calendar_service.fetch_events("t")
