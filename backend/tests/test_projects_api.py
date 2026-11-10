"""
Unit tests untuk API endpoint POST /api/v1/projects.
Memverifikasi validasi input, file upload, pembuatan record, dan trigger scoring.
"""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app

# Jawaban kuesioner minimal valid (skor rubrik 22 → Need Clarification, tanpa notifikasi)
QA = json.dumps(
    {
        "budget_dialokasikan": "Tidak tahu",
        "peran_pic": "Tidak tahu",
        "masalah_bisnis": "Butuh cloud",
        "jenis_workload": "Lainnya",
        "lingkungan": "Cloud",
        "skala": "5 server",
        "target_go_live": "Tidak tahu",
    }
)

# =============================================================================
# Fixtures & Helpers
# =============================================================================


def _mock_user():
    """Buat mock User object untuk dependency injection."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "sales@company.com"
    user.name = "Test Sales"
    user.role = "Sales"
    return user


def _create_fake_file(
    filename: str, content: bytes = b"fake content", content_type: str = "application/pdf"
):
    """Buat tuple file upload untuk TestClient."""
    return ("files", (filename, BytesIO(content), content_type))


@pytest.fixture
def client():
    """TestClient untuk FastAPI tanpa database nyata."""
    return TestClient(app)


@pytest.fixture
def mock_auth_and_db():
    """Patch auth dependency dan database session."""
    mock_user = _mock_user()

    # Patch get_current_user dependency
    with patch("app.api.projects.get_current_user", return_value=mock_user) as auth_mock:
        # Patch database session
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        with patch("app.api.projects.get_db") as db_mock:
            # Override dependency
            async def override_get_db():
                yield mock_session

            app.dependency_overrides[
                __import__("app.core.database", fromlist=["get_db"]).get_db
            ] = override_get_db
            app.dependency_overrides[
                __import__("app.core.dependencies", fromlist=["get_current_user"]).get_current_user
            ] = lambda: mock_user

            yield mock_user, mock_session

    # Cleanup overrides
    app.dependency_overrides.clear()


# =============================================================================
# Test: Validasi Input Form
# =============================================================================


class TestProjectFormValidation:
    """Test validasi input form project submission."""

    def test_project_name_kosong_ditolak(self, mock_auth_and_db):
        """Project name kosong menghasilkan error validasi."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "   ",  # Hanya whitespace
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        assert body["status"] == "error"

    def test_project_name_melebihi_150_chars_ditolak(self, mock_auth_and_db):
        """Project name > 150 karakter ditolak."""
        client = TestClient(app)
        long_name = "A" * 151
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": long_name,
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_target_submit_masa_lalu_ditolak(self, mock_auth_and_db):
        """Target submit di masa lalu menghasilkan error."""
        client = TestClient(app)
        yesterday = date.today() - timedelta(days=1)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Valid",
                "customer_name": "PT Test",
                "target_submit": str(yesterday),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        assert body["status"] == "error"
        # Cek bahwa error ada di field target_submit
        errors = body.get("data", [])
        field_names = [e["field"] for e in errors]
        assert "target_submit" in field_names

    def test_estimasi_nilai_terlalu_kecil_ditolak(self, mock_auth_and_db):
        """Estimasi nilai < 0.01 ditolak."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Valid",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "0.001",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        errors = body.get("data", [])
        field_names = [e["field"] for e in errors]
        assert "estimasi_nilai" in field_names

    def test_estimasi_nilai_terlalu_besar_ditolak(self, mock_auth_and_db):
        """Estimasi nilai > 999,999,999,999.00 ditolak."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Valid",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "9999999999999.00",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_estimasi_nilai_bukan_angka_ditolak(self, mock_auth_and_db):
        """Estimasi nilai non-numeric ditolak."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Valid",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "bukan-angka",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_input_valid_tanpa_file_berhasil(self, mock_auth_and_db):
        """Input valid tanpa file: skor dihitung backend dari kuesioner (tanpa form BANT manual)."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Valid",
                "customer_name": "PT Customer",
                "target_submit": str(date.today() + timedelta(days=30)),
                "estimasi_nilai": "500000000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["status"] == "Need Clarification"
        assert body["data"]["bant_score"] == 22
        assert body["data"]["scoring_triggered"] is False
        assert "message_bant" not in body["data"]


# =============================================================================
# Test: File Upload Validation
# =============================================================================


class TestFileUploadValidation:
    """Test validasi file upload."""

    def test_file_pdf_valid_diterima(self, mock_auth_and_db):
        """File PDF valid berhasil diupload."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek PDF",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
                "file_types": ["MoM"]*1,
            },
            files=[_create_fake_file("proposal.pdf")],
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        files = body["data"]["files"]
        assert len(files) == 1
        assert files[0]["success"] is True
        assert body["data"]["scoring_triggered"] is True

    def test_file_docx_valid_diterima(self, mock_auth_and_db):
        """File DOCX valid berhasil diupload."""
        client = TestClient(app)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek DOCX",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
                "file_types": ["MoM"]*1,
            },
            files=[("files", ("document.docx", BytesIO(b"docx content"), mime))],
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        files = body["data"]["files"]
        assert len(files) == 1
        assert files[0]["success"] is True

    def test_file_format_invalid_ditolak(self, mock_auth_and_db):
        """File dengan format selain PDF/DOCX ditolak per-file."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Invalid File",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
                "file_types": ["MoM"]*1,
            },
            files=[("files", ("image.png", BytesIO(b"png data"), "image/png"))],
        )
        # Proyek tetap dibuat (201), tapi file ditolak
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        files = body["data"]["files"]
        assert len(files) == 1
        assert files[0]["success"] is False
        assert "Format file tidak valid" in files[0]["error"]

    def test_partial_failure_file_valid_disimpan(self, mock_auth_and_db):
        """File valid tetap disimpan meskipun ada file yang gagal (partial failure)."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Mixed Files",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
                "file_types": ["MoM"]*3,
            },
            files=[
                _create_fake_file("valid.pdf"),
                ("files", ("invalid.txt", BytesIO(b"text data"), "text/plain")),
                _create_fake_file("another_valid.pdf"),
            ],
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        files = body["data"]["files"]
        assert len(files) == 3

        # File valid berhasil
        valid_files = [f for f in files if f["success"]]
        failed_files = [f for f in files if not f["success"]]
        assert len(valid_files) == 2
        assert len(failed_files) == 1
        # Scoring tetap di-trigger karena ada file valid
        assert body["data"]["scoring_triggered"] is True

    def test_maks_5_file_divalidasi(self, mock_auth_and_db):
        """Upload lebih dari 5 file ditolak."""
        client = TestClient(app)
        many_files = [_create_fake_file(f"file{i}.pdf") for i in range(6)]
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Banyak File",
                "customer_name": "PT Test",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "1000000",
                "qualification_answers": QA,
            },
            files=many_files,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        errors = body.get("data", [])
        field_names = [e["field"] for e in errors]
        assert "files" in field_names


# =============================================================================
# Test: Project Record Creation
# =============================================================================


class TestProjectRecordCreation:
    """Test pembuatan record project."""

    def test_project_dibuat_dengan_status_new(self, mock_auth_and_db):
        """Proyek baru dengan file berstatus 'New' sampai scoring AI selesai."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            files=[_create_fake_file("proposal.pdf")],
            data={
                "file_types": ["MoM"],
                "project_name": "Proyek Baru",
                "customer_name": "PT Baru",
                "target_submit": str(date.today() + timedelta(days=14)),
                "estimasi_nilai": "250000000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["status"] == "New"

    def test_project_id_format_prj(self, mock_auth_and_db):
        """ID proyek mengikuti format PRJ-{date}-{random}."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek ID Test",
                "customer_name": "PT ID",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "100000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        project_id = body["data"]["id_project"]
        assert project_id.startswith("PRJ-")
        # Format: PRJ-YYYYMMDD-XXXXXX (total panjang = 4+8+6+2 separators = 20)
        parts = project_id.split("-")
        assert len(parts) == 3
        assert parts[0] == "PRJ"
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # Random

    def test_project_memiliki_timestamp(self, mock_auth_and_db):
        """Proyek baru memiliki created_at yang tidak null."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Timestamp",
                "customer_name": "PT Timestamp",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "100000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["created_at"] is not None

    def test_project_memiliki_sales_pic(self, mock_auth_and_db):
        """Proyek baru memiliki sales_pic yang sesuai user login."""
        mock_user, _ = mock_auth_and_db
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Sales PIC",
                "customer_name": "PT Sales",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "100000",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["sales_pic"] == str(mock_user.id)


# =============================================================================
# Test: Response Format
# =============================================================================


class TestResponseFormat:
    """Test format response API standar."""

    def test_response_sukses_format_standar(self, mock_auth_and_db):
        """Response sukses mengikuti format standar."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Format",
                "customer_name": "PT Format",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "100000",
                "qualification_answers": QA,
            },
        )
        body = response.json()
        # Format standar: status, data, message
        assert "status" in body
        assert "data" in body
        assert "message" in body
        assert body["status"] == "success"

    def test_response_error_format_standar(self, mock_auth_and_db):
        """Response error validasi mengikuti format standar."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "",
                "customer_name": "PT Test",
                "target_submit": str(date.today() - timedelta(days=1)),
                "estimasi_nilai": "abc",
                "qualification_answers": QA,
            },
        )
        body = response.json()
        assert "status" in body
        assert body["status"] == "error"
        assert "message" in body


# =============================================================================
# Test: Persistensi estimasi_nilai (regresi B4)
# =============================================================================


class TestEstimasiNilaiPersist:
    """
    Test regresi: estimasi_nilai harus ikut dipersist ke record Project saat
    create, bukan sekadar muncul di response (fix B4).
    """

    def test_create_mempersist_estimasi_nilai_ke_record(self, mock_auth_and_db):
        """
        Nilai estimasi_nilai yang dikirim harus di-set pada object Project yang
        di-add ke session (yang akan di-commit ke DB), bukan hanya di response.
        """
        mock_user, mock_session = mock_auth_and_db
        client = TestClient(app)
        response = client.post(
            "/api/v1/projects",
            data={
                "project_name": "Proyek Estimasi",
                "customer_name": "PT Estimasi",
                "target_submit": str(date.today() + timedelta(days=7)),
                "estimasi_nilai": "750000000.50",
                "qualification_answers": QA,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        # Ambil object Project yang di-add ke session (akan di-commit ke DB)
        assert mock_session.add.call_count == 1
        added_project = mock_session.add.call_args.args[0]
        assert added_project.estimasi_nilai == Decimal("750000000.50")

        # Nilai juga tercermin di response
        body = response.json()
        assert Decimal(str(body["data"]["estimasi_nilai"])) == Decimal("750000000.50")


# =============================================================================
# Test: PATCH /projects/{id} benar-benar mempersist (regresi bant_detail & estimasi_nilai)
# =============================================================================


def _real_project(**overrides):
    """Buat object Project nyata (bukan mock) untuk test readback persistensi."""
    from app.models.project import Project

    defaults = dict(
        id_project="PRJ-20250101-ABC123",
        project_name="Proyek Lama",
        customer_name="PT Lama",
        status="New",
        target_submit=date.today() + timedelta(days=7),
        sales_pic=uuid.uuid4(),
        bant_detail=None,
        estimasi_nilai=None,
    )
    defaults.update(overrides)
    return Project(**defaults)


@pytest.fixture
def mock_patch_db():
    """
    Patch auth (role Lead_SA agar lolos ensure_project_access) + session untuk
    endpoint PATCH /projects/{id}. db.execute mengembalikan project pada panggilan
    pertama (lookup), lalu None (cek collaborator di ensure_project_access).
    """
    mock_user = _mock_user()
    mock_user.role = "Lead_SA"

    project = _real_project()

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    def _make_result(value):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=value)
        return result

    # Panggilan 1: lookup Project. Panggilan 2: cek collaborator (None).
    mock_session.execute = AsyncMock(side_effect=[_make_result(project), _make_result(None)])

    async def override_get_db():
        yield mock_session

    import app.core.database as database_module
    import app.core.dependencies as dependencies_module

    app.dependency_overrides[database_module.get_db] = override_get_db
    app.dependency_overrides[dependencies_module.get_current_user] = lambda: mock_user

    yield mock_user, mock_session, project

    app.dependency_overrides.clear()


class TestFolderProvisioningStatusInResponse:
    """
    Test FEAT-003/T6: folder_provisioning_status harus muncul di response list
    dan detail proyek, tanpa merusak field gdrive_folder_id yang sudah ada.
    """

    def test_list_mengandung_folder_provisioning_status(self):
        """Response list proyek memuat folder_provisioning_status + gdrive_folder_id."""
        mock_user = _mock_user()
        mock_user.role = "Lead_SA"  # akses seluruh proyek

        project = _real_project(
            gdrive_folder_id="gdrive_master_123",
            gdrive_solutions_folder_id="gdrive_sol_123",
            folder_provisioning_status="provisioned",
        )

        mock_session = AsyncMock()

        def _make_scalars_result(items):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=items)
            result.scalars = MagicMock(return_value=scalars)
            return result

        mock_session.execute = AsyncMock(return_value=_make_scalars_result([project]))

        async def override_get_db():
            yield mock_session

        import app.core.database as database_module
        import app.core.dependencies as dependencies_module

        app.dependency_overrides[database_module.get_db] = override_get_db
        app.dependency_overrides[dependencies_module.get_current_user] = lambda: mock_user
        try:
            client = TestClient(app)
            response = client.get("/api/v1/projects")
            assert response.status_code == status.HTTP_200_OK
            body = response.json()
            item = body["data"][0]
            assert item["folder_provisioning_status"] == "provisioned"
            # Field lama tetap ada dan tidak rusak
            assert item["gdrive_folder_id"] == "gdrive_master_123"
        finally:
            app.dependency_overrides.clear()

    def test_detail_mengandung_folder_provisioning_status(self):
        """Response detail proyek memuat folder_provisioning_status + gdrive_folder_id."""
        mock_user = _mock_user()
        mock_user.role = "Lead_SA"  # privileged → lolos cek akses

        project = _real_project(
            gdrive_folder_id="gdrive_master_456",
            gdrive_solutions_folder_id="gdrive_sol_456",
            folder_provisioning_status="failed",
        )

        mock_session = AsyncMock()

        def _make_scalar_result(value):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=value)
            return result

        def _make_scalars_result(items):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=items)
            result.scalars = MagicMock(return_value=scalars)
            return result

        # Urutan execute di get_project_detail:
        # 1) lookup Project, 2) cek collaborator (None),
        # 3) lookup Sales PIC (None), 4) lookup SA assigned (skip: assigned_sa None),
        # 5) daftar collaborators (kosong), 6) daftar Source document (kosong).
        mock_session.execute = AsyncMock(
            side_effect=[
                _make_scalar_result(project),
                _make_scalar_result(None),
                _make_scalar_result(None),
                _make_scalars_result([]),
                _make_scalars_result([]),
            ]
        )

        async def override_get_db():
            yield mock_session

        import app.core.database as database_module
        import app.core.dependencies as dependencies_module

        app.dependency_overrides[database_module.get_db] = override_get_db
        app.dependency_overrides[dependencies_module.get_current_user] = lambda: mock_user
        try:
            client = TestClient(app)
            response = client.get(f"/api/v1/projects/{project.id_project}")
            assert response.status_code == status.HTTP_200_OK
            body = response.json()
            data = body["data"]
            assert data["folder_provisioning_status"] == "failed"
            # Field lama tetap ada dan tidak rusak
            assert data["gdrive_folder_id"] == "gdrive_master_456"
        finally:
            app.dependency_overrides.clear()


class TestUpdateProjectPersist:
    """
    Test regresi: PATCH harus benar-benar mengubah object yang di-commit
    (bukan sekadar mengembalikan 200). bant_detail sebelumnya gagal persist
    karena JSONB tanpa MutableDict.
    """

    def test_patch_bant_detail_tersimpan(self, mock_patch_db):
        """
        PATCH bant_detail harus ter-set pada object Project (readback), bukan
        hanya 200. Ini test yang gagal sebelum fix MutableDict.
        """
        mock_user, mock_session, project = mock_patch_db
        client = TestClient(app)
        response = client.patch(
            "/api/v1/projects/PRJ-20250101-ABC123",
            json={"bant_detail": {"budget_mrr": 8, "pic_name": "Budi"}},
        )
        assert response.status_code == status.HTTP_200_OK
        # commit dipanggil
        mock_session.commit.assert_awaited()
        # Readback dari object yang di-commit
        assert project.bant_detail == {"budget_mrr": 8, "pic_name": "Budi"}

    def test_patch_bant_detail_merge_dengan_existing(self, mock_patch_db):
        """PATCH bant_detail melakukan merge terhadap nilai existing."""
        mock_user, mock_session, project = mock_patch_db
        project.bant_detail = {"budget_mrr": 2}
        client = TestClient(app)
        response = client.patch(
            "/api/v1/projects/PRJ-20250101-ABC123",
            json={"bant_detail": {"pic_name": "Siti"}},
        )
        assert response.status_code == status.HTTP_200_OK
        assert project.bant_detail == {"budget_mrr": 2, "pic_name": "Siti"}

    def test_patch_estimasi_nilai_valid_tersimpan(self, mock_patch_db):
        """PATCH estimasi_nilai valid ter-set pada object (readback)."""
        mock_user, mock_session, project = mock_patch_db
        client = TestClient(app)
        response = client.patch(
            "/api/v1/projects/PRJ-20250101-ABC123",
            json={"estimasi_nilai": "123456.78"},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_session.commit.assert_awaited()
        assert project.estimasi_nilai == Decimal("123456.78")

    def test_patch_estimasi_nilai_di_luar_range_ditolak(self, mock_patch_db):
        """PATCH estimasi_nilai di luar range (terlalu besar) ditolak 422."""
        mock_user, mock_session, project = mock_patch_db
        client = TestClient(app)
        response = client.patch(
            "/api/v1/projects/PRJ-20250101-ABC123",
            json={"estimasi_nilai": "9999999999999.00"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        # Nilai tidak berubah
        assert project.estimasi_nilai is None

    def test_patch_estimasi_nilai_terlalu_kecil_ditolak(self, mock_patch_db):
        """PATCH estimasi_nilai < 0.01 ditolak 422."""
        mock_user, mock_session, project = mock_patch_db
        client = TestClient(app)
        response = client.patch(
            "/api/v1/projects/PRJ-20250101-ABC123",
            json={"estimasi_nilai": "0.001"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert project.estimasi_nilai is None
