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
    return SimpleNamespace(
        customer_name=f"{awalan}PT Uji",
        project_name="Proyek Live",
        id_project=f"{awalan}project",
        customer=SimpleNamespace(gdrive_folder_id=None),
        gdrive_folder_number=1,
        gdrive_folder_id=None,
    )


async def _proyek_dengan_customer(provisioner, awalan: str) -> SimpleNamespace:
    project = _proyek(awalan)
    project.customer.gdrive_folder_id = await provisioner.ensure_customer_folder(
        project.customer_name
    )
    return project


async def _provision(provisioner, cfg, pembersih, awalan):
    project = await _proyek_dengan_customer(provisioner, awalan)
    hasil = await asyncio.wait_for(
        provisioner.provision_project_folder(
            project,
            cfg.email_sa,
            cfg.email_lead,
            cfg.email_sales,
            sa_team_emails=cfg.email_sa_team,
            product_email=cfg.email_product,
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
    project = await _proyek_dengan_customer(provisioner, awalan)
    hasil = await asyncio.wait_for(
        provisioner.provision_project_folder(
            project,
            cfg.email_sa,
            cfg.email_lead,
            cfg.email_sales,
            sa_team_emails=cfg.email_sa_team,
            product_email=cfg.email_product,
        ),
        cfg.timeout,
    )
    pembersih.append(hasil.master)

    # Hierarchy is rooted under the configured isolated parent, not flat under Shared Drive.
    customer = verifikator.ambil(project.customer.gdrive_folder_id)
    assert customer["parents"] == [cfg.parent_folder_id]
    assert customer["name"] == project.customer_name
    assert verifikator.ambil(hasil.master)["parents"] == [project.customer.gdrive_folder_id]
    assert verifikator.ambil(hasil.master)["name"] == "01-Proyek Live"
    anak = {f["name"]: f["id"] for f in verifikator.anak(hasil.master)}
    assert set(anak) == NAMA_SUBFOLDER
    assert anak == {
        "Inventory": hasil.inventory,
        "Diagram": hasil.diagram,
        "Solutions": hasil.solutions,
    }

    # Every configured SA identity (including Lead SA) has Editor effective access.
    for folder in (hasil.master, hasil.inventory, hasil.diagram, hasil.solutions):
        for email in cfg.email_sa_team:
            assert verifikator.peran_efektif(folder, email) == "writer", (folder, email)

    # Sales and Product: Viewer only on Inventory before DQ; no project-level access.
    for email in (cfg.email_sales, cfg.email_product):
        assert verifikator.peran_efektif(hasil.inventory, email) == "reader"
        for folder in (hasil.master, hasil.diagram, hasil.solutions):
            assert verifikator.peran_efektif(folder, email) is None, (folder, email)

    # PMO/Delivery belum diberi akses apa pun sebelum handover.
    for email in (cfg.email_pmo, cfg.email_delivery):
        assert verifikator.peran_efektif(hasil.master, email) is None


async def test_dq_memberi_sales_dan_product_viewer_hanya_pada_solutions(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    project = await _proyek_dengan_customer(provisioner, awalan)
    project.dq_number = "DQ-12345"
    hasil = await asyncio.wait_for(
        provisioner.provision_project_folder(
            project,
            cfg.email_sa,
            cfg.email_lead,
            cfg.email_sales,
            sa_team_emails=cfg.email_sa_team,
            product_email=cfg.email_product,
            dq_number=project.dq_number,
        ),
        cfg.timeout,
    )
    pembersih.append(hasil.master)

    for email in (cfg.email_sales, cfg.email_product):
        assert verifikator.peran_efektif(hasil.inventory, email) == "reader"
        assert verifikator.peran_efektif(hasil.solutions, email) == "reader"
        assert verifikator.peran_efektif(hasil.master, email) is None
        assert verifikator.peran_efektif(hasil.diagram, email) is None


async def test_unlock_lalu_lock_solutions_untuk_sales_dan_product(
    provisioner, konfigurasi_live, verifikator, pembersih, awalan
):
    cfg = konfigurasi_live
    hasil = await _provision(provisioner, cfg, pembersih, awalan)
    for email in (cfg.email_sales, cfg.email_product):
        assert verifikator.peran_efektif(hasil.solutions, email) is None

    await asyncio.wait_for(
        provisioner.unlock_solutions_folder(
            hasil.solutions, cfg.email_sales, cfg.email_product
        ),
        cfg.timeout,
    )

    for email in (cfg.email_sales, cfg.email_product):
        assert verifikator.peran_efektif(hasil.solutions, email) == "reader"
        assert verifikator.peran_efektif(hasil.diagram, email) is None
        assert verifikator.peran_efektif(hasil.master, email) is None
        assert verifikator.peran_efektif(hasil.inventory, email) == "reader"

    await asyncio.wait_for(
        provisioner.lock_solutions_folder(
            hasil.solutions, cfg.email_sales, cfg.email_product
        ),
        cfg.timeout,
    )

    for email in (cfg.email_sales, cfg.email_product):
        assert verifikator.peran_efektif(hasil.solutions, email) is None
        assert email.lower() not in _emails_langsung(verifikator, hasil.solutions)
        assert verifikator.peran_efektif(hasil.inventory, email) == "reader"
    for email in cfg.email_sa_team:
        assert verifikator.peran_efektif(hasil.solutions, email) == "writer"


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
                await _proyek_dengan_customer(provisioner, awalan),
                sa_email,
                cfg.email_lead,
                cfg.email_sales,
            ),
            cfg.timeout,
        )
    # Folder master/subfolder yang sempat dibuat sebelum izin gagal disapu fixture `pembersih`
    # (berdasarkan awalan unik test ini), sehingga tidak ada sisa di Drive.
