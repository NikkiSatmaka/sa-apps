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

from app.api.assignment import _trigger_folder_provisioner
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
    project.status = status_value
    project.bant_score = 80
    project.use_case_tags = ["etl"]
    project.sales_pic = uuid.uuid4()
    project.assigned_sa = None
    project.assigned_at = None
    project.target_submit = date(2026, 12, 31)
    project.gdrive_folder_id = None
    project.gdrive_solutions_folder_id = None
    project.folder_provisioning_status = None
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _execute_result_scalar(self._project)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
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
        assert project.gdrive_folder_id == "master_001"
        assert project.gdrive_solutions_folder_id == "sol_004"
        assert project.folder_provisioning_status == "provisioned"

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
