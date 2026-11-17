"""
Tests untuk wiring Folder_Provisioner saat assignment (FEAT-002 / T3).

Memvalidasi bahwa:
- Background task `_trigger_folder_provisioner` benar-benar memanggil
  `folder_provisioner.provision_project_folder` dan mem-persist hasilnya:
  sukses -> `gdrive_folder_id` (master) + `gdrive_solutions_folder_id` ter-set,
  `folder_provisioning_status='provisioned'`; gagal (FolderProvisioningError
  setelah retry internal) -> `folder_provisioning_status='failed'`.
- Endpoint `assign_sa_to_project` menjadwalkan task provisioning dan
  `folder_provisioning_triggered` mencerminkan apakah task benar-benar
  dijadwalkan (bukan hardcode True).

Test terisolasi: tidak butuh Postgres live. Session DB di-mock, Google Drive
di-mock di boundary `folder_provisioner.provision_project_folder` (AsyncMock),
dan `AsyncSessionLocal` (dipakai background task) di-patch ke fake session
in-memory yang berbagi object Project yang sama sehingga persistensi teramati.
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.api.assignment import _reserve_project_folder, _trigger_folder_provisioner
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.services.folder_provisioner import (
    FolderProvisioningError,
    ProvisionedFolders,
)

# =============================================================================
# Helpers & fixtures
# =============================================================================

PROJECT_ID = "PRJ-20250101-ABC123"


def _make_user(role: str = "Lead_SA", user_id: uuid.UUID | None = None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = f"{role.lower()}@company.com"
    user.name = f"Test {role}"
    user.role = role
    return user


def _make_sa():
    sa = MagicMock()
    sa.id = uuid.uuid4()
    sa.email = "sa@company.com"
    sa.name = "SA Satu"
    sa.role = "SA"
    return sa


def _make_project(status_value: str = "Awaiting Assignment"):
    project = MagicMock()
    project.id_project = PROJECT_ID
    project.project_name = "Proyek Uji"
    project.customer_name = "Customer A"
    project.customer_id = uuid.uuid4()
    project.customer = MagicMock()
    project.customer.name = "Customer A"
    project.customer.gdrive_folder_id = "customer-drive-folder"
    project.status = status_value
    project.bant_score = 80
    project.use_case_tags = ["etl"]
    project.sales_pic = uuid.uuid4()
    project.product_pic = uuid.uuid4()
    project.assigned_sa = None
    project.assigned_at = None
    project.target_submit = date(2026, 12, 31)
    project.gdrive_folder_number = 1
    project.gdrive_folder_id = None
    project.gdrive_solutions_folder_id = None
    project.folder_provisioning_status = None
    project.dq_number = "DQ-123"
    return project


def _execute_result_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=value)
    return result


class _FakeProvisionSession:
    """
    Fake AsyncSession async-context-manager untuk background task.

    Mengembalikan object Project yang sama pada setiap query sehingga
    perubahan atribut yang dilakukan task teramati oleh test.
    """

    def __init__(self, project):
        self._project = project
        self.commits = 0
        self._execute_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        self._execute_count += 1
        if self._execute_count == 1:
            return _execute_result_scalar(self._project)
        if self._execute_count == 2:
            return _execute_result_scalar(self._project.customer)
        if self._execute_count == 3:
            result = MagicMock()
            result.scalars.return_value.all.return_value = [
                "sa-one@company.com",
                "sa-two@company.com",
            ]
            return result
        return _execute_result_scalar("product@company.com")

    async def scalar(self, _stmt):
        return 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj, attribute_names=None):
        return None


def _override_current_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _override_db(session):
    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


# =============================================================================
# Background task: persist sukses / gagal
# =============================================================================


class TestTriggerFolderProvisioner:
    """`_trigger_folder_provisioner` mem-persist hasil provisioning (ADR 0005)."""

    @pytest.mark.asyncio
    async def test_sukses_persist_master_solutions_dan_status_provisioned(self):
        project = _make_project()
        session = _FakeProvisionSession(project)

        provisioned = ProvisionedFolders(
            master="master_001",
            inventory="inv_002",
            diagram="diag_003",
            solutions="sol_004",
        )

        with patch(
            "app.core.database.AsyncSessionLocal", return_value=session
        ), patch(
            "app.api.assignment.folder_provisioner.provision_project_folder",
            new_callable=AsyncMock,
            return_value=provisioned,
        ) as mock_provision:
            await _trigger_folder_provisioner(
                PROJECT_ID,
                "sa@company.com",
                "lead_sa@company.com",
                "sales@company.com",
            )

        mock_provision.assert_awaited_once()
        assert mock_provision.await_args.kwargs["sa_team_emails"] == (
            "sa-one@company.com",
            "sa-two@company.com",
        )
        assert mock_provision.await_args.kwargs["product_email"] == "product@company.com"
        assert mock_provision.await_args.kwargs["dq_number"] == "DQ-123"
        assert project.gdrive_folder_id == "master_001"
        assert project.gdrive_solutions_folder_id == "sol_004"
        assert project.folder_provisioning_status == "provisioned"

    @pytest.mark.asyncio
    async def test_project_without_product_pic_skips_product_lookup(self):
        project = _make_project()
        project.product_pic = None
        session = _FakeProvisionSession(project)
        provisioned = ProvisionedFolders(
            master="master_001",
            inventory="inv_002",
            diagram="diag_003",
            solutions="sol_004",
        )

        with (
            patch("app.core.database.AsyncSessionLocal", return_value=session),
            patch(
                "app.api.assignment.folder_provisioner.provision_project_folder",
                new_callable=AsyncMock,
                return_value=provisioned,
            ) as mock_provision,
        ):
            await _trigger_folder_provisioner(
                PROJECT_ID,
                "sa@company.com",
                "lead_sa@company.com",
                "sales@company.com",
            )

        assert mock_provision.await_args.kwargs["product_email"] is None
        assert session._execute_count == 3

    @pytest.mark.asyncio
    async def test_gagal_set_status_failed_tanpa_persist_folder(self):
        project = _make_project()
        session = _FakeProvisionSession(project)

        with patch(
            "app.core.database.AsyncSessionLocal", return_value=session
        ), patch(
            "app.api.assignment.folder_provisioner.provision_project_folder",
            new_callable=AsyncMock,
            side_effect=FolderProvisioningError("gdrive down"),
        ):
            # Tidak boleh re-raise keluar dari task (graceful).
            await _trigger_folder_provisioner(
                PROJECT_ID,
                "sa@company.com",
                "lead_sa@company.com",
                "sales@company.com",
            )

        assert project.folder_provisioning_status == "failed"
        assert project.gdrive_folder_id is None
        assert project.gdrive_solutions_folder_id is None

    @pytest.mark.asyncio
    async def test_reservation_requires_customer_identity(self):
        project = _make_project()
        project.customer_id = None
        db = AsyncMock()

        with pytest.raises(FolderProvisioningError, match="no Customer identity"):
            await _reserve_project_folder(db, project)

        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reservation_rejects_deleted_customer_identity(self):
        project = _make_project()
        db = AsyncMock()
        db.execute.return_value = _execute_result_scalar(None)

        with pytest.raises(FolderProvisioningError, match="no longer exists"):
            await _reserve_project_folder(db, project)

    @pytest.mark.asyncio
    async def test_different_master_folder_callback_fails_closed(self):
        project = _make_project()
        session = _FakeProvisionSession(project)

        async def return_conflicting_folder(_project, *args, **kwargs):
            persist = kwargs["persist_master_folder_id"]
            await persist("master_001")
            await persist("master_002")

        with (
            patch("app.core.database.AsyncSessionLocal", return_value=session),
            patch(
                "app.api.assignment.folder_provisioner.ensure_customer_folder",
                new_callable=AsyncMock,
                return_value="customer-drive-folder",
            ),
            patch(
                "app.api.assignment.folder_provisioner.list_folder_children",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.api.assignment.folder_provisioner.provision_project_folder",
                new_callable=AsyncMock,
                side_effect=return_conflicting_folder,
            ),
        ):
            await _trigger_folder_provisioner(
                PROJECT_ID,
                "sa@company.com",
                "lead_sa@company.com",
                "sales@company.com",
            )

        assert project.gdrive_folder_id == "master_001"
        assert project.folder_provisioning_status == "failed"


# =============================================================================
# Endpoint: folder_provisioning_triggered mencerminkan penjadwalan task
# =============================================================================


class TestAssignTriggersProvisioning:
    """POST /projects/{id}/assign menjadwalkan provisioning & set flag benar."""

    @patch("app.api.assignment.sla_timer")
    def test_assign_menjadwalkan_task_flag_true(self, mock_sla_timer):
        mock_sla_timer.start_timer = AsyncMock(return_value=MagicMock())

        lead = _make_user(role="Lead_SA")
        project = _make_project()
        sa = _make_sa()
        sales = _make_user(role="Sales")

        mock_session = AsyncMock()
        # execute: 1) project, 2) SA, 3) Sales (sales_pic), 4) count subtask.
        mock_session.execute = AsyncMock(
            side_effect=[
                _execute_result_scalar(project),
                _execute_result_scalar(sa),
                _execute_result_scalar(sales),
                _execute_result_scalar(0),
            ]
        )
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        _override_db(mock_session)
        _override_current_user(lead)

        client = TestClient(app)
        # Patch background task agar tidak membuka DB nyata saat dieksekusi.
        with patch(
            "app.api.assignment._trigger_folder_provisioner",
            new_callable=AsyncMock,
        ) as mock_task:
            response = client.post(
                f"/api/v1/projects/{PROJECT_ID}/assign",
                json={"sa_id": str(sa.id)},
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()["data"]
        assert body["folder_provisioning_triggered"] is True
        # Status pending ter-set pada proyek saat assignment.
        assert project.folder_provisioning_status == "pending"
        # Task dijadwalkan dengan email SA, Lead_SA, Sales yang benar.
        mock_task.assert_awaited_once()
        args = mock_task.await_args.args
        assert args[0] == PROJECT_ID
        assert args[1] == sa.email
        assert args[2] == lead.email
        assert args[3] == sales.email

    @patch("app.api.assignment.sla_timer")
    def test_assign_tanpa_sales_flag_false(self, mock_sla_timer):
        """Bila email Sales tidak ditemukan, task tidak dijadwalkan & flag False."""
        mock_sla_timer.start_timer = AsyncMock(return_value=MagicMock())

        lead = _make_user(role="Lead_SA")
        project = _make_project()
        sa = _make_sa()

        mock_session = AsyncMock()
        # execute: 1) project, 2) SA, 3) Sales -> None, 4) count subtask.
        mock_session.execute = AsyncMock(
            side_effect=[
                _execute_result_scalar(project),
                _execute_result_scalar(sa),
                _execute_result_scalar(None),
                _execute_result_scalar(0),
            ]
        )
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        _override_db(mock_session)
        _override_current_user(lead)

        client = TestClient(app)
        with patch(
            "app.api.assignment._trigger_folder_provisioner",
            new_callable=AsyncMock,
        ) as mock_task:
            response = client.post(
                f"/api/v1/projects/{PROJECT_ID}/assign",
                json={"sa_id": str(sa.id)},
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()["data"]
        assert body["folder_provisioning_triggered"] is False
        mock_task.assert_not_awaited()


class _FolderRegistrationSession:
    def __init__(self, project):
        self.project = project
        self.audit = []
        self.commits = 0

        self.execute_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        return _execute_result_scalar(self.project if self.execute_count == 1 else None)

    async def get(self, _model, _identity):
        return self.project.customer

    def add(self, item):
        self.audit.append(item)

    async def commit(self):
        self.commits += 1


def _manual_folder_project():
    project = _make_project()
    project.gdrive_inventory_folder_id = None
    project.gdrive_diagram_folder_id = None
    project.gdrive_solutions_folder_id = None
    return project


def _manual_folder_provider():
    provider = MagicMock()
    provider.get_folder_metadata = AsyncMock(return_value={
        "id": "manual-master",
        "name": "04-Proyek Uji",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["legacy-customer-folder"],
        "trashed": False,
    })
    provider.list_folder_children = AsyncMock(return_value=[
        {"id": "inventory", "name": "Inventory"},
        {"id": "diagram", "name": "Diagram"},
        {"id": "solutions", "name": "Solutions"},
    ])
    return provider


def test_manual_drive_folder_registration_persists_ids_and_audit_without_drive_writes():
    project = _manual_folder_project()
    project.gdrive_folder_number = None
    session = _FolderRegistrationSession(project)
    _override_db(session)
    _override_current_user(_make_user())
    provider = _manual_folder_provider()

    with patch("app.api.project_lifecycle_api.folder_provisioner", provider):
        response = TestClient(app).post(
            f"/api/v1/projects/{PROJECT_ID}/register-folder",
            json={"folder_id": "manual-master", "reason": "Provisioned outside app", "confirm": True},
        )

    assert response.status_code == status.HTTP_200_OK
    assert project.gdrive_folder_id == "manual-master"
    assert project.gdrive_inventory_folder_id == "inventory"
    assert project.gdrive_diagram_folder_id == "diagram"
    assert project.gdrive_solutions_folder_id == "solutions"
    assert project.gdrive_folder_number == 4
    assert session.commits == 1
    assert session.audit[0].action == "drive_folder_registered"
    assert session.audit[0].new_value["parent_mismatch"] is True
    assert session.audit[0].new_value["reason"] == "Provisioned outside app"
    provider.get_folder_metadata.assert_awaited_once_with("manual-master")
    provider.list_folder_children.assert_awaited_once_with("manual-master")
    provider.create_folder.assert_not_called()


def test_manual_drive_registration_missing_child_fails_before_project_or_audit_mutation():
    project = _manual_folder_project()
    session = _FolderRegistrationSession(project)
    _override_db(session)
    _override_current_user(_make_user())
    provider = _manual_folder_provider()
    provider.list_folder_children.return_value = [
        {"id": "inventory", "name": "Inventory"},
        {"id": "solutions", "name": "Solutions"},
    ]

    with patch("app.api.project_lifecycle_api.folder_provisioner", provider):
        response = TestClient(app).post(
            f"/api/v1/projects/{PROJECT_ID}/register-folder",
            json={"folder_id": "manual-master", "reason": "Repair", "confirm": True},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert project.gdrive_folder_id is None
    assert session.audit == []
    assert session.commits == 0


def test_manual_drive_registration_rejects_unauthorized_user_without_mutation():
    project = _manual_folder_project()
    session = _FolderRegistrationSession(project)
    _override_db(session)
    _override_current_user(_make_user(role="Sales"))
    provider = _manual_folder_provider()

    with patch("app.api.project_lifecycle_api.folder_provisioner", provider):
        response = TestClient(app).post(
            f"/api/v1/projects/{PROJECT_ID}/register-folder",
            json={"folder_id": "manual-master", "reason": "Not authorized", "confirm": True},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert project.gdrive_folder_id is None
    assert session.audit == []
    assert session.commits == 0
    provider.get_folder_metadata.assert_not_awaited()
