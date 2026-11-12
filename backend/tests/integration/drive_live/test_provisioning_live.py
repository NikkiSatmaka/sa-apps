"""
Verifikasi `folder_provisioner` ASLI terhadap Google Drive NYATA (#27, skenario a–d).

BELUM PERNAH DIJALANKAN terhadap Drive sungguhan oleh penulisnya (tanpa kredensial); ekspektasi
ditulis dari spec/glossary ("Folder proyek": Inventory = Viewer Sales, Diagram & Solutions = tanpa
akses Sales sampai DQ). Bila hasil live berbeda, itu temuan: JANGAN melonggarkan assertion;
laporkan sebagai gap.

Setiap hasil dibaca ulang lewat klien `Verifikator` (googleapiclient milik test, key yang sama),
bukan dari nilai kembalian provisioner. "Akses efektif" didefinisikan di `izin.py`: peran tertinggi
dari permission user pada folder itu ATAU leluhurnya (permission folder diwarisi anak).
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from app.services.folder_provisioner import FolderProvisioningError

pytestmark = pytest.mark.drive_live

# `app.services` mengekspor singleton bernama sama; ambil MODUL-nya lewat importlib.
modul_provisioner = importlib.import_module("app.services.folder_provisioner")

NAMA_SUBFOLDER = {"Inventory", "Diagram", "Solutions"}


def _proyek(awalan: str) -> SimpleNamespace:
    return SimpleNamespace(customer_name=f"{awalan}PT Uji", project_name="Proyek Live")


async def _provision(provisioner, cfg, pembersih, awalan):
    hasil = await asyncio.wait_for(
        provisioner.provision_project_folder(
            _proyek(awalan), cfg.email_sa, cfg.email_lead, cfg.email_sales
        ),
        cfg.timeout,
    )
    pembersih.append(hasil.master)
    return hasil


def _emails_langsung(verifikator, folder_id: str) -> set[str]:
    """Email user yang muncul di `permissions.list` folder itu (langsung maupun turunan)."""
    return {
        p["emailAddress"].lower()
        for p in verifikator.daftar_izin(folder_id)
        if p.get("type") == "user" and p.get("emailAddress")
    }


async def test_struktur_master_dan_izin_awal(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)

    # Struktur: master berisi tepat Inventory / Diagram / Solutions.
    assert verifikator.ambil(hasil.master)["name"] == f"{awalan}PT Uji - Proyek Live"
    anak = {f["name"]: f["id"] for f in verifikator.anak(hasil.master)}
    assert set(anak) == NAMA_SUBFOLDER
    assert anak == {
        "Inventory": hasil.inventory,
        "Diagram": hasil.diagram,
        "Solutions": hasil.solutions,
    }

    # SA dan Lead_SA: writer di master (dan, lewat pewarisan, di semua subfolder).
    for folder in (hasil.master, hasil.inventory, hasil.diagram, hasil.solutions):
        assert verifikator.peran_efektif(folder, cfg.email_sa) == "writer", folder
        assert verifikator.peran_efektif(folder, cfg.email_lead) == "writer", folder

    # Sales: reader HANYA di Inventory; tidak ada akses efektif ke master, Diagram, Solutions.
    assert verifikator.peran_efektif(hasil.inventory, cfg.email_sales) == "reader"
    for folder in (hasil.master, hasil.diagram, hasil.solutions):
        assert verifikator.peran_efektif(folder, cfg.email_sales) is None, folder
    # Dan Sales juga tidak muncul sama sekali di daftar izin folder-folder tersebut.
    for folder in (hasil.master, hasil.diagram, hasil.solutions):
        assert cfg.email_sales.lower() not in _emails_langsung(verifikator, folder), folder

    # PMO/Delivery belum diberi akses apa pun sebelum handover.
    for email in (cfg.email_pmo, cfg.email_delivery):
        assert verifikator.peran_efektif(hasil.master, email) is None


async def test_unlock_lalu_lock_solutions_untuk_sales(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sales) is None

    await asyncio.wait_for(
        provisioner.unlock_solutions_folder(hasil.solutions, cfg.email_sales), cfg.timeout
    )

    # Unlock: Sales reader di Solutions, dan HANYA di sana (bukan master/Diagram).
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sales) == "reader"
    assert verifikator.peran_efektif(hasil.diagram, cfg.email_sales) is None
    assert verifikator.peran_efektif(hasil.master, cfg.email_sales) is None
    assert verifikator.peran_efektif(hasil.inventory, cfg.email_sales) == "reader"

    await asyncio.wait_for(
        provisioner.lock_solutions_folder(hasil.solutions, cfg.email_sales), cfg.timeout
    )

    # Lock: akses Solutions dicabut; akses Inventory TIDAK ikut tercabut; SA/Lead tetap writer.
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sales) is None
    assert cfg.email_sales.lower() not in _emails_langsung(verifikator, hasil.solutions)
    assert verifikator.peran_efektif(hasil.inventory, cfg.email_sales) == "reader"
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sa) == "writer"
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_lead) == "writer"


async def test_unlock_dua_kali_tetap_satu_izin_reader(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    """`doc_ready` memanggil unlock tiap dokumen Reviewed; panggilan ulang tidak boleh menumpuk."""
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)

    for _ in range(2):
        await asyncio.wait_for(
            provisioner.unlock_solutions_folder(hasil.solutions, cfg.email_sales), cfg.timeout
        )

    izin_sales = [
        p
        for p in verifikator.daftar_izin(hasil.solutions)
        if str(p.get("emailAddress", "")).lower() == cfg.email_sales.lower()
    ]
    assert [p["role"] for p in izin_sales] == ["reader"]


async def test_lock_tanpa_akses_sales_adalah_noop(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)
    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sales) is None

    # Tidak boleh raise, dan tidak boleh mengubah izin siapa pun.
    await asyncio.wait_for(
        provisioner.lock_solutions_folder(hasil.solutions, cfg.email_sales), cfg.timeout
    )

    assert verifikator.peran_efektif(hasil.solutions, cfg.email_sales) is None
    assert verifikator.peran_efektif(hasil.inventory, cfg.email_sales) == "reader"
    assert verifikator.peran_efektif(hasil.master, cfg.email_sa) == "writer"
    assert verifikator.peran_efektif(hasil.master, cfg.email_lead) == "writer"


async def test_handover_final_deliverables_di_solutions(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)

    deliverables = await asyncio.wait_for(
        provisioner.provision_handover(hasil.solutions, cfg.email_pmo, cfg.email_delivery),
        cfg.timeout,
    )

    berkas = verifikator.ambil(deliverables)
    assert berkas["name"] == "Final_Deliverables"
    assert berkas["parents"] == [hasil.solutions]
    assert "Final_Deliverables" in {f["name"] for f in verifikator.anak(hasil.solutions)}
    # PMO dan Delivery: reader (tepat reader) di Final_Deliverables.
    assert verifikator.peran_efektif(deliverables, cfg.email_pmo) == "reader"
    assert verifikator.peran_efektif(deliverables, cfg.email_delivery) == "reader"
    # Izin handover diberikan di Final_Deliverables saja, tidak naik ke Solutions/master.
    for folder in (hasil.solutions, hasil.master):
        assert verifikator.peran_efektif(folder, cfg.email_pmo) is None, folder
        assert verifikator.peran_efektif(folder, cfg.email_delivery) is None, folder
    # SA/Lead tetap writer (diwarisi) dan Sales tetap tak punya akses ke Solutions.
    assert verifikator.peran_efektif(deliverables, cfg.email_sa) == "writer"
    assert verifikator.peran_efektif(deliverables, cfg.email_sales) is None


@pytest.mark.parametrize("sa_email", ["bukan-email", "tidak-ada-akun@example.invalid"])
async def test_email_tidak_valid_gagal_setelah_retry(
    sa_email, provisioner, konfigurasi_live, pembersih, awalan, monkeypatch
):
    cfg = konfigurasi_live
    # Hanya di test ini: persingkat jeda retry (default 5 detik x 3 percobaan per operasi).
    monkeypatch.setattr(modul_provisioner, "RETRY_INTERVAL_SECONDS", 0.05)

    with pytest.raises(FolderProvisioningError):
        await asyncio.wait_for(
            provisioner.provision_project_folder(
                _proyek(awalan), sa_email, cfg.email_lead, cfg.email_sales
            ),
            cfg.timeout,
        )
    # Folder master/subfolder yang sempat dibuat sebelum izin gagal disapu fixture `pembersih`
    # (berdasarkan awalan unik test ini), sehingga tidak ada sisa di Drive.
