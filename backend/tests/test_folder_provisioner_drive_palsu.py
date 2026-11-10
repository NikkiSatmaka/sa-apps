"""
Test perilaku `FolderProvisioner` terhadap Drive API palsu BERSTATE (tiket B5 #58, spec #49).

Berbeda dari `test_folder_provisioner.py` (mock per panggilan), di sini `files()` dan
`permissions()` meniru Google Drive: folder dan izin benar-benar tercatat sehingga yang diuji
adalah hasil akhirnya (struktur folder, siapa punya akses apa), bukan urutan pemanggilan.
Sleep retry di-patch; tidak ada jaringan maupun waktu nyata.
"""

import asyncio
import itertools
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from hypothesis import given
from hypothesis import strategies as st

from app.services.folder_provisioner import (
    INVALID_FOLDER_CHARS,
    MAX_RETRIES,
    RETRY_INTERVAL_SECONDS,
    FolderProvisioner,
    FolderProvisioningError,
)


class _Permintaan:
    def __init__(self, jalankan):
        self._jalankan = jalankan

    def execute(self):
        return self._jalankan()


class DriveApiPalsu:
    """Meniru bagian Google Drive v3 yang dipakai provisioner (files & permissions)."""

    def __init__(self):
        self.folder: dict[str, dict] = {}  # id -> {name, parents}
        self.izin: dict[str, dict[str, dict]] = {}  # folder -> {perm_id: {email, role}}
        self.panggilan_api = 0
        self.antrian_gagal: list[Exception] = []
        self._id = itertools.count(1)

    def gagal_berikutnya(self, *kesalahan: Exception) -> None:
        self.antrian_gagal.extend(kesalahan)

    def _coba(self):
        self.panggilan_api += 1
        if self.antrian_gagal:
            raise self.antrian_gagal.pop(0)

    # --- files()
    def files(self):
        return SimpleNamespace(create=self._files_create)

    def _files_create(self, body, fields):
        def jalan():
            self._coba()
            fid = f"folder-{next(self._id)}"
            self.folder[fid] = {"name": body["name"], "parents": body.get("parents", [])}
            self.izin[fid] = {}
            return {"id": fid}

        return _Permintaan(jalan)

    # --- permissions()
    def permissions(self):
        return SimpleNamespace(
            create=self._izin_create, list=self._izin_list, delete=self._izin_delete
        )

    def _izin_create(self, fileId, body, sendNotificationEmail, fields):  # noqa: N803
        def jalan():
            self._coba()
            assert sendNotificationEmail is False  # tidak boleh mengirim email Google
            pid = f"perm-{next(self._id)}"
            self.izin[fileId][pid] = {"email": body["emailAddress"], "role": body["role"]}
            return {"id": pid}

        return _Permintaan(jalan)

    def _izin_list(self, fileId, fields):  # noqa: N803
        def jalan():
            self._coba()
            return {
                "permissions": [
                    {"id": pid, "emailAddress": p["email"]} for pid, p in self.izin[fileId].items()
                ]
            }

        return _Permintaan(jalan)

    def _izin_delete(self, fileId, permissionId):  # noqa: N803
        def jalan():
            self._coba()
            del self.izin[fileId][permissionId]

        return _Permintaan(jalan)

    # --- pembacaan hasil akhir
    def peran(self, folder_id: str, email: str) -> str | None:
        for p in self.izin[folder_id].values():
            if p["email"].lower() == email.lower():
                return p["role"]
        return None

    def id_nama(self, nama: str) -> str:
        (hasil,) = [i for i, f in self.folder.items() if f["name"] == nama]
        return hasil


def _http_error(status: int = 500) -> HttpError:
    return HttpError(resp=MagicMock(status=status, reason="gagal"), content=b"gagal")


@dataclass
class ProyekPalsu:
    customer_name: str = "PT Acme"
    project_name: str = "Migrasi"
    id_project: str = "PRJ-1"


@pytest.fixture
def drive():
    return DriveApiPalsu()


@pytest.fixture
def tidur(monkeypatch):
    """Catat durasi sleep retry tanpa menunggu."""
    durasi: list[float] = []

    async def _tidur(detik):
        durasi.append(detik)

    monkeypatch.setattr(asyncio, "sleep", _tidur)
    return durasi


@pytest.fixture
def provisioner(drive, tidur):
    p = FolderProvisioner()
    p._drive_service = drive
    return p


async def _provision(provisioner):
    return await provisioner.provision_project_folder(
        ProyekPalsu(), "sa@co.com", "lead@co.com", "sales@co.com"
    )


# ----------------------------------------------------------------------------- struktur & izin


async def test_provisioning_membuat_struktur_dan_izin_sesuai_spec(provisioner, drive):
    hasil = await _provision(provisioner)

    assert drive.folder[hasil.master] == {"name": "PT Acme - Migrasi", "parents": []}
    for nama, fid in [
        ("Inventory", hasil.inventory),
        ("Diagram", hasil.diagram),
        ("Solutions", hasil.solutions),
    ]:
        assert drive.folder[fid] == {"name": nama, "parents": [hasil.master]}
    # SA dan Lead_SA editor di master (diwarisi subfolder); Sales viewer hanya di Inventory.
    assert drive.peran(hasil.master, "sa@co.com") == "writer"
    assert drive.peran(hasil.master, "lead@co.com") == "writer"
    assert drive.peran(hasil.inventory, "sales@co.com") == "reader"
    for tanpa_akses in (hasil.master, hasil.diagram, hasil.solutions):
        assert drive.peran(tanpa_akses, "sales@co.com") is None
    assert len({hasil.master, hasil.inventory, hasil.diagram, hasil.solutions}) == 4


async def test_nama_folder_disanitasi_di_drive(provisioner, drive):
    proyek = ProyekPalsu(customer_name='PT "A/B"', project_name="Q1*2?\\Rev")

    hasil = await provisioner.provision_project_folder(proyek, "a@co.com", "b@co.com", "c@co.com")

    assert drive.folder[hasil.master]["name"] == "PT _A_B_ - Q1_2__Rev"


# ----------------------------------------------------------------------------- retry & kegagalan


async def test_gagal_sementara_dicoba_ulang_dengan_jeda_dan_akhirnya_berhasil(
    provisioner, drive, tidur
):
    drive.gagal_berikutnya(_http_error(), RuntimeError("koneksi putus"))

    hasil = await _provision(provisioner)

    assert hasil.master in drive.folder
    assert tidur == [RETRY_INTERVAL_SECONDS, RETRY_INTERVAL_SECONDS]
    assert len(drive.folder) == 4  # percobaan gagal tidak meninggalkan folder ganda


async def test_semua_percobaan_gagal_raise_dan_tidak_ada_folder_dibuat(provisioner, drive, tidur):
    drive.gagal_berikutnya(*[_http_error(503) for _ in range(MAX_RETRIES)])

    with pytest.raises(FolderProvisioningError, match=f"Gagal setelah {MAX_RETRIES}"):
        await _provision(provisioner)

    assert drive.folder == {}
    assert len(tidur) == MAX_RETRIES - 1  # tidak tidur setelah percobaan terakhir


async def test_kegagalan_di_tengah_meninggalkan_folder_yatim_sesuai_adr_0006(provisioner, drive):
    """ADR 0006: bila gagal di tengah, folder yang sudah dibuat tidak dibersihkan otomatis."""
    master = await provisioner._execute_with_retry(
        "buat master", provisioner._create_folder_sync, "PT Acme - Migrasi"
    )
    drive.gagal_berikutnya(*[_http_error() for _ in range(MAX_RETRIES)])

    with pytest.raises(FolderProvisioningError):
        await provisioner._execute_with_retry(
            "buat sub", provisioner._create_folder_sync, "Inventory", master
        )

    assert list(drive.folder) == [master]


# ----------------------------------------------------------------------------- lock / unlock


async def test_lock_mencabut_hanya_akses_sales_pada_solutions(provisioner, drive):
    hasil = await _provision(provisioner)
    await provisioner._execute_with_retry(
        "beri sales", provisioner._set_permission_sync, hasil.solutions, "sales@co.com", "reader"
    )
    await provisioner._execute_with_retry(
        "beri sa", provisioner._set_permission_sync, hasil.solutions, "sa@co.com", "writer"
    )

    await provisioner.lock_solutions_folder(hasil.solutions, "sales@co.com")

    assert drive.peran(hasil.solutions, "sales@co.com") is None
    assert drive.peran(hasil.solutions, "sa@co.com") == "writer"
    assert drive.peran(hasil.inventory, "sales@co.com") == "reader"  # folder lain utuh


async def test_lock_mencocokkan_email_tanpa_peka_huruf_besar_kecil(provisioner, drive):
    hasil = await _provision(provisioner)
    await provisioner._execute_with_retry(
        "beri", provisioner._set_permission_sync, hasil.solutions, "Sales@Co.com", "reader"
    )

    await provisioner.lock_solutions_folder(hasil.solutions, "sales@co.COM")

    assert drive.peran(hasil.solutions, "sales@co.com") is None


async def test_lock_tanpa_akses_sales_tidak_error_dan_tidak_mengubah_izin(provisioner, drive):
    hasil = await _provision(provisioner)
    sebelum = {f: dict(p) for f, p in drive.izin.items()}

    await provisioner.lock_solutions_folder(hasil.solutions, "sales@co.com")

    assert drive.izin == sebelum


async def test_unlock_memberi_sales_viewer_pada_solutions(provisioner, drive):
    hasil = await _provision(provisioner)
    assert drive.peran(hasil.solutions, "sales@co.com") is None

    await provisioner.unlock_solutions_folder(hasil.solutions, "sales@co.com")

    assert drive.peran(hasil.solutions, "sales@co.com") == "reader"


async def test_lock_gagal_permanen_raise_dan_akses_tetap_ada(provisioner, drive):
    hasil = await _provision(provisioner)
    await provisioner.unlock_solutions_folder(hasil.solutions, "sales@co.com")
    drive.gagal_berikutnya(*[_http_error() for _ in range(MAX_RETRIES)])

    with pytest.raises(FolderProvisioningError):
        await provisioner.lock_solutions_folder(hasil.solutions, "sales@co.com")

    assert drive.peran(hasil.solutions, "sales@co.com") == "reader"


async def test_handover_membuat_final_deliverables_dengan_viewer_pmo_dan_delivery(
    provisioner, drive
):
    hasil = await _provision(provisioner)

    fid = await provisioner.provision_handover(hasil.solutions, "pmo@co.com", "delivery@co.com")

    assert drive.folder[fid] == {"name": "Final_Deliverables", "parents": [hasil.solutions]}
    assert drive.peran(fid, "pmo@co.com") == "reader"
    assert drive.peran(fid, "delivery@co.com") == "reader"


# ----------------------------------------------------------------------------- service account


class TestInisialisasiLayananDrive:
    def test_kunci_valid_membangun_layanan_sekali_lalu_dipakai_ulang(self):
        provisioner = FolderProvisioner()
        layanan = object()
        with (
            patch("app.services.folder_provisioner.settings") as pengaturan,
            patch(
                "app.services.folder_provisioner.service_account.Credentials"
                ".from_service_account_info",
                return_value="kredensial",
            ) as dari_info,
            patch("app.services.folder_provisioner.build", return_value=layanan) as bangun,
        ):
            pengaturan.GDRIVE_SERVICE_ACCOUNT_KEY = '{"type": "service_account"}'

            pertama = provisioner._get_drive_service()
            kedua = provisioner._get_drive_service()

        assert pertama is kedua is layanan
        bangun.assert_called_once()
        assert dari_info.call_args.kwargs["scopes"] == ["https://www.googleapis.com/auth/drive"]

    def test_kunci_json_valid_tetapi_isi_ditolak_google_menjadi_error_provisioning(self):
        provisioner = FolderProvisioner()
        with (
            patch("app.services.folder_provisioner.settings") as pengaturan,
            patch(
                "app.services.folder_provisioner.service_account.Credentials"
                ".from_service_account_info",
                side_effect=ValueError("kunci rusak"),
            ),
        ):
            pengaturan.GDRIVE_SERVICE_ACCOUNT_KEY = "{}"

            with pytest.raises(FolderProvisioningError, match="tidak valid"):
                provisioner._get_drive_service()

        assert provisioner._drive_service is None


async def test_tanpa_kunci_service_account_provisioning_gagal_graceful_sebagai_error_provisioning(
    tidur,
):
    provisioner = FolderProvisioner()
    with patch("app.services.folder_provisioner.settings") as pengaturan:
        pengaturan.GDRIVE_SERVICE_ACCOUNT_KEY = ""

        with pytest.raises(FolderProvisioningError, match="Gagal setelah"):
            await provisioner.provision_project_folder(ProyekPalsu(), "a@c", "b@c", "c@c")


# ----------------------------------------------------------------------------- properti


@given(st.text())
def test_sanitasi_menghilangkan_semua_karakter_terlarang_dan_menjaga_panjang(nama):
    hasil = FolderProvisioner().sanitize_folder_name(nama)

    assert not INVALID_FOLDER_CHARS.search(hasil)
    assert len(hasil) == len(nama)
    assert FolderProvisioner().sanitize_folder_name(hasil) == hasil  # idempoten


@given(st.text(alphabet=st.characters(blacklist_characters='/\\*?"')))
def test_sanitasi_tidak_mengubah_nama_yang_sudah_valid(nama):
    assert FolderProvisioner().sanitize_folder_name(nama) == nama
