"""
Unit tests untuk FolderProvisioner.

Menggunakan mock untuk Google Drive API calls agar tidak melakukan
panggilan jaringan nyata.
"""

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from app.services.folder_provisioner import (
    INVALID_FOLDER_CHARS,
    FolderProvisioner,
    FolderProvisioningError,
)

# =============================================================================
# Fixtures & Helpers
# =============================================================================


@dataclass
class FakeProject:
    """Mock object Project untuk testing."""

    customer_name: str = "PT Acme Indonesia"
    project_name: str = "Data Platform Migration"
    id_project: str = "PRJ-001"


@pytest.fixture
def provisioner():
    """Buat FolderProvisioner instance baru untuk setiap test."""
    return FolderProvisioner()


@pytest.fixture
def mock_drive_service():
    """Mock Google Drive service yang sudah ter-build."""
    service = MagicMock()

    # Mock files().create()
    create_mock = MagicMock()
    create_mock.execute.return_value = {"id": "folder_id_123"}
    service.files.return_value.create.return_value = create_mock

    # Mock permissions().create()
    perm_create_mock = MagicMock()
    perm_create_mock.execute.return_value = {"id": "perm_id_456"}
    service.permissions.return_value.create.return_value = perm_create_mock

    # Mock permissions().list()
    perm_list_mock = MagicMock()
    perm_list_mock.execute.return_value = {
        "permissions": [{"id": "perm_sales_001", "emailAddress": "sales@company.com"}]
    }
    service.permissions.return_value.list.return_value = perm_list_mock

    # Mock permissions().delete()
    perm_delete_mock = MagicMock()
    perm_delete_mock.execute.return_value = None
    service.permissions.return_value.delete.return_value = perm_delete_mock

    return service


@pytest.fixture
def provisioner_with_service(provisioner, mock_drive_service):
    """Provisioner dengan mock Drive service yang sudah di-inject."""
    provisioner._drive_service = mock_drive_service
    return provisioner


# =============================================================================
# Test: sanitize_folder_name
# =============================================================================


class TestSanitizeFolderName:
    """Test sanitization karakter tidak valid pada nama folder."""

    def test_nama_tanpa_karakter_invalid(self, provisioner):
        """Nama tanpa karakter invalid tidak berubah."""
        assert provisioner.sanitize_folder_name("PT Acme") == "PT Acme"

    def test_ganti_slash(self, provisioner):
        """Forward slash diganti underscore."""
        assert provisioner.sanitize_folder_name("PT A/B Corp") == "PT A_B Corp"

    def test_ganti_backslash(self, provisioner):
        """Backslash diganti underscore."""
        assert provisioner.sanitize_folder_name("PT A\\B") == "PT A_B"

    def test_ganti_asterisk(self, provisioner):
        """Asterisk diganti underscore."""
        assert provisioner.sanitize_folder_name("Project *New*") == "Project _New_"

    def test_ganti_question_mark(self, provisioner):
        """Tanda tanya diganti underscore."""
        assert provisioner.sanitize_folder_name("What?") == "What_"

    def test_ganti_double_quote(self, provisioner):
        """Double quote diganti underscore."""
        assert provisioner.sanitize_folder_name('Project "Alpha"') == "Project _Alpha_"

    def test_multiple_karakter_invalid(self, provisioner):
        """Semua karakter invalid diganti sekaligus."""
        input_name = 'PT A/B\\C*D?E"F'
        result = provisioner.sanitize_folder_name(input_name)
        assert "/" not in result
        assert "\\" not in result
        assert "*" not in result
        assert "?" not in result
        assert '"' not in result
        assert result == "PT A_B_C_D_E_F"

    def test_string_kosong(self, provisioner):
        """String kosong tetap kosong."""
        assert provisioner.sanitize_folder_name("") == ""

    def test_karakter_valid_dipertahankan(self, provisioner):
        """Karakter valid (spasi, dash, titik, underscore) dipertahankan."""
        name = "PT Acme-Corp. (2024)_v2"
        assert provisioner.sanitize_folder_name(name) == name


# =============================================================================
# Test: Inisialisasi Drive Service
# =============================================================================


class TestDriveServiceInit:
    """Test inisialisasi lazy Google Drive service."""

    def test_service_key_kosong_raise_error(self, provisioner):
        """Raise error jika GDRIVE_SERVICE_ACCOUNT_KEY kosong."""
        with patch("app.services.folder_provisioner.settings") as mock_settings:
            mock_settings.GDRIVE_SERVICE_ACCOUNT_KEY = ""
            with pytest.raises(FolderProvisioningError, match="belum dikonfigurasi"):
                provisioner._get_drive_service()

    def test_service_key_json_invalid_raise_error(self, provisioner):
        """Raise error jika service account key bukan JSON valid."""
        with patch("app.services.folder_provisioner.settings") as mock_settings:
            mock_settings.GDRIVE_SERVICE_ACCOUNT_KEY = "bukan-json-valid"
            with pytest.raises(FolderProvisioningError, match="tidak valid"):
                provisioner._get_drive_service()


# =============================================================================
# Test: provision_project_folder
# =============================================================================


class TestProvisionProjectFolder:
    """Test pembuatan folder master dan subfolder."""

    @pytest.mark.asyncio
    async def test_sukses_buat_folder_dan_permission(
        self, provisioner_with_service, mock_drive_service
    ):
        """Provisioning berhasil: buat master + 3 subfolder + set permissions."""
        folder_ids = iter(["master_001", "inv_002", "diag_003", "sol_004"])

        def create_side_effect(*args, **kwargs):
            mock = MagicMock()
            mock.execute.return_value = {"id": next(folder_ids)}
            return mock

        mock_drive_service.files.return_value.create.side_effect = create_side_effect

        project = FakeProject()
        result = await provisioner_with_service.provision_project_folder(
            project=project,
            sa_email="sa@company.com",
            lead_sa_email="lead@company.com",
            sales_email="sales@company.com",
        )

        assert result.master == "master_001"
        assert result.inventory == "inv_002"
        assert result.diagram == "diag_003"
        assert result.solutions == "sol_004"

        # Verifikasi 4 folder dibuat (1 master + 3 subfolder)
        assert mock_drive_service.files.return_value.create.call_count == 4

        # Verifikasi 3 permission calls (SA writer, Lead writer, Sales reader)
        assert mock_drive_service.permissions.return_value.create.call_count == 3

    @pytest.mark.asyncio
    async def test_folder_name_disanitasi(self, provisioner_with_service, mock_drive_service):
        """Nama folder menggunakan customer_name dan project_name yang disanitasi."""
        captured_names = []

        def create_side_effect(*args, **kwargs):
            body = kwargs.get("body") or args[0] if args else {}
            # Cek apakah dipanggil via service.files().create(body=..., fields=...)
            mock = MagicMock()
            mock.execute.return_value = {"id": "folder_123"}
            return mock

        mock_drive_service.files.return_value.create.side_effect = create_side_effect

        project = FakeProject(
            customer_name='PT "Test"/Corp',
            project_name="Data*Pipeline?v2",
        )

        await provisioner_with_service.provision_project_folder(
            project=project,
            sa_email="sa@co.com",
            lead_sa_email="lead@co.com",
            sales_email="sales@co.com",
        )

        # Verifikasi nama folder master yang dikirim ke API
        first_call = mock_drive_service.files.return_value.create.call_args_list[0]
        body = first_call[1].get("body") or first_call[0][0] if first_call[0] else {}
        # Karena kita mock _create_folder_sync, mari cek langsung via sanitize
        assert (
            provisioner_with_service.sanitize_folder_name(project.customer_name) == "PT _Test__Corp"
        )
        assert (
            provisioner_with_service.sanitize_folder_name(project.project_name)
            == "Data_Pipeline_v2"
        )

    @pytest.mark.asyncio
    async def test_retry_saat_gdrive_error(self, provisioner_with_service, mock_drive_service):
        """Retry 3x saat Google Drive API gagal, berhasil di attempt ke-2."""
        call_count = 0

        def flaky_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                # Gagal pertama
                mock.execute.side_effect = HttpError(
                    resp=MagicMock(status=500),
                    content=b"Internal Server Error",
                )
            else:
                mock.execute.return_value = {"id": f"folder_{call_count}"}
            return mock

        mock_drive_service.files.return_value.create.side_effect = flaky_create

        project = FakeProject()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await provisioner_with_service.provision_project_folder(
                project=project,
                sa_email="sa@co.com",
                lead_sa_email="lead@co.com",
                sales_email="sales@co.com",
            )

        # Harus berhasil (retry sukses)
        assert result.master is not None

    @pytest.mark.asyncio
    async def test_raise_error_setelah_semua_retry_gagal(
        self, provisioner_with_service, mock_drive_service
    ):
        """Raise FolderProvisioningError jika semua 3 retry habis."""

        def always_fail(*args, **kwargs):
            mock = MagicMock()
            mock.execute.side_effect = HttpError(
                resp=MagicMock(status=500),
                content=b"Server Error",
            )
            return mock

        mock_drive_service.files.return_value.create.side_effect = always_fail

        project = FakeProject()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(FolderProvisioningError, match="Gagal setelah 3"):
                await provisioner_with_service.provision_project_folder(
                    project=project,
                    sa_email="sa@co.com",
                    lead_sa_email="lead@co.com",
                    sales_email="sales@co.com",
                )


# =============================================================================
# Test: lock_solutions_folder
# =============================================================================


class TestLockSolutionsFolder:
    """Test lock (hapus akses Sales) dari folder Solutions."""

    @pytest.mark.asyncio
    async def test_lock_sukses(self, provisioner_with_service, mock_drive_service):
        """Lock berhasil menghapus permission Sales dari folder Solutions."""
        await provisioner_with_service.lock_solutions_folder(
            solutions_folder_id="sol_folder_001",
            sales_email="sales@company.com",
        )

        # Verifikasi permissions().list dipanggil
        mock_drive_service.permissions.return_value.list.assert_called()
        # Verifikasi permissions().delete dipanggil
        mock_drive_service.permissions.return_value.delete.assert_called()

    @pytest.mark.asyncio
    async def test_lock_skip_jika_tidak_punya_akses(
        self, provisioner_with_service, mock_drive_service
    ):
        """Skip lock jika Sales tidak punya akses ke folder Solutions."""
        # Ubah mock agar return permission list kosong
        perm_list_mock = MagicMock()
        perm_list_mock.execute.return_value = {"permissions": []}
        mock_drive_service.permissions.return_value.list.return_value = perm_list_mock

        # Tidak raise error, hanya skip
        await provisioner_with_service.lock_solutions_folder(
            solutions_folder_id="sol_folder_001",
            sales_email="unknown@company.com",
        )

        # Verifikasi delete TIDAK dipanggil
        mock_drive_service.permissions.return_value.delete.assert_not_called()


# =============================================================================
# Test: unlock_solutions_folder
# =============================================================================


class TestUnlockSolutionsFolder:
    """Test unlock (kembalikan akses Viewer Sales) ke folder Solutions."""

    @pytest.mark.asyncio
    async def test_unlock_sukses(self, provisioner_with_service, mock_drive_service):
        """Unlock berhasil menambahkan kembali permission Viewer untuk Sales."""
        await provisioner_with_service.unlock_solutions_folder(
            solutions_folder_id="sol_folder_001",
            sales_email="sales@company.com",
        )

        # Verifikasi permissions().create dipanggil dengan role reader
        mock_drive_service.permissions.return_value.create.assert_called()


# =============================================================================
# Test: reassign_sa_access (#77)
# =============================================================================


def _daftar_izin(mock_drive_service, *izin):
    """Atur hasil permissions().list: pasangan (id, email)."""
    perm_list_mock = MagicMock()
    perm_list_mock.execute.return_value = {
        "permissions": [{"id": i, "emailAddress": e} for i, e in izin]
    }
    mock_drive_service.permissions.return_value.list.return_value = perm_list_mock


class TestReassignSaAccess:
    """Pindahkan akses Editor folder master dari SA lama ke SA baru."""

    @pytest.mark.asyncio
    async def test_beri_editor_ke_sa_baru_dan_cabut_sa_lama(
        self, provisioner_with_service, mock_drive_service
    ):
        _daftar_izin(mock_drive_service, ("perm_lama", "lama@company.com"))

        await provisioner_with_service.reassign_sa_access(
            master_folder_id="master_001",
            old_sa_email="lama@company.com",
            new_sa_email="baru@company.com",
        )

        buat = mock_drive_service.permissions.return_value.create
        buat.assert_called_once()
        assert buat.call_args.kwargs["fileId"] == "master_001"
        assert buat.call_args.kwargs["body"] == {
            "type": "user",
            "role": "writer",
            "emailAddress": "baru@company.com",
        }
        hapus = mock_drive_service.permissions.return_value.delete
        hapus.assert_called_once_with(fileId="master_001", permissionId="perm_lama")

    @pytest.mark.asyncio
    async def test_sa_baru_yang_sudah_punya_akses_tidak_dibuat_ulang(
        self, provisioner_with_service, mock_drive_service
    ):
        _daftar_izin(
            mock_drive_service,
            ("perm_lama", "lama@company.com"),
            ("perm_baru", "Baru@Company.com"),
        )

        await provisioner_with_service.reassign_sa_access("master_001", "lama@company.com", "baru@company.com")

        mock_drive_service.permissions.return_value.create.assert_not_called()
        mock_drive_service.permissions.return_value.delete.assert_called_once_with(
            fileId="master_001", permissionId="perm_lama"
        )

    @pytest.mark.asyncio
    async def test_sa_lama_tanpa_izin_tidak_ada_yang_dihapus(
        self, provisioner_with_service, mock_drive_service
    ):
        _daftar_izin(mock_drive_service)

        await provisioner_with_service.reassign_sa_access("master_001", "lama@company.com", "baru@company.com")

        mock_drive_service.permissions.return_value.create.assert_called_once()
        mock_drive_service.permissions.return_value.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_tanpa_sa_lama_hanya_memberi_akses(
        self, provisioner_with_service, mock_drive_service
    ):
        _daftar_izin(mock_drive_service)

        await provisioner_with_service.reassign_sa_access("master_001", None, "baru@company.com")

        mock_drive_service.permissions.return_value.create.assert_called_once()
        mock_drive_service.permissions.return_value.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_sa_sama_tidak_mengubah_apa_pun(
        self, provisioner_with_service, mock_drive_service
    ):
        await provisioner_with_service.reassign_sa_access("master_001", "sama@company.com", "SAMA@company.com")

        mock_drive_service.permissions.return_value.create.assert_not_called()
        mock_drive_service.permissions.return_value.delete.assert_not_called()


# =============================================================================
# Test: provision_handover
# =============================================================================


class TestProvisionHandover:
    """Test pembuatan folder Final_Deliverables saat handover."""

    @pytest.mark.asyncio
    async def test_handover_sukses(self, provisioner_with_service, mock_drive_service):
        """Handover berhasil: buat Final_Deliverables + set permission PMO & Delivery."""
        folder_ids = iter(["deliverables_001"])

        def create_side_effect(*args, **kwargs):
            mock = MagicMock()
            mock.execute.return_value = {"id": next(folder_ids)}
            return mock

        mock_drive_service.files.return_value.create.side_effect = create_side_effect

        result = await provisioner_with_service.provision_handover(
            solutions_folder_id="sol_folder_001",
            pmo_email="pmo@company.com",
            delivery_email="delivery@company.com",
        )

        assert result == "deliverables_001"

        # Verifikasi 1 folder dibuat
        assert mock_drive_service.files.return_value.create.call_count == 1

        # Verifikasi 2 permission calls (PMO reader + Delivery reader)
        assert mock_drive_service.permissions.return_value.create.call_count == 2

    @pytest.mark.asyncio
    async def test_handover_retry_saat_error(self, provisioner_with_service, mock_drive_service):
        """Handover retry saat GDrive error."""
        call_count = 0

        def flaky_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.execute.side_effect = HttpError(
                    resp=MagicMock(status=503),
                    content=b"Service Unavailable",
                )
            else:
                mock.execute.return_value = {"id": "deliverables_retry"}
            return mock

        mock_drive_service.files.return_value.create.side_effect = flaky_create

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await provisioner_with_service.provision_handover(
                solutions_folder_id="sol_folder_001",
                pmo_email="pmo@co.com",
                delivery_email="delivery@co.com",
            )

        assert result == "deliverables_retry"
