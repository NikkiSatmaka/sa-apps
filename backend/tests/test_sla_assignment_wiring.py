"""
Tests untuk wiring SLA timer saat assignment (T2 / fix B11).

Memvalidasi bahwa `assign_sa_to_project` memulai SLA timer setelah
`assigned_at` di-set, sehingga:
- row SLATracking dibuat saat SA di-assign;
- GET /projects/{id}/sla-status aktif, green, days_elapsed 0 di H+0;
- assign/re-assign ulang idempoten (tidak membuat tracker kedua, tidak error).

Test terisolasi: DB session dan dependency auth di-override/mock, tidak
membutuhkan Postgres live. Perilaku end-to-end SLA diuji lewat SLATimer
asli di atas fake DB session yang mensimulasikan tabel sla_tracking.
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.sla_tracking import SLATracking
from app.services.sla_timer import SLAStatus, SLATimer

# =============================================================================
# Helpers & Fixtures
# =============================================================================


def _make_user(role: str = "Lead_SA", user_id: uuid.UUID | None = None):
    """Buat mock User untuk dependency override."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = f"{role.lower()}@company.com"
    user.name = f"Test {role}"
    user.role = role
    return user


def _make_project(status_value: str = "Awaiting Assignment"):
    """Buat mock Project dengan field yang dipakai endpoint assignment."""
    project = MagicMock()
    project.id_project = "PRJ-20250101-ABC123"
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
    return project


def _make_sa():
    """Buat mock SA user yang akan ditugaskan."""
    sa = MagicMock()
    sa.id = uuid.uuid4()
    sa.email = "sa@company.com"
    sa.name = "SA Satu"
    sa.role = "SA"
    return sa


def _execute_result_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=value)
    return result


def _override_current_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _override_db(mock_session):
    async def _override():
        yield mock_session

    app.dependency_overrides[get_db] = _override


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


# =============================================================================
# Fake DB session yang mensimulasikan tabel sla_tracking
# =============================================================================


class _FakeSLASession:
    """
    Fake AsyncSession minimal untuk menjalankan SLATimer asli.

    Hanya mengenali query SLATracking by project_id (yang dipakai
    start_timer & check_sla_status). Menyimpan row di memori sehingga
    idempotency `start_timer` bisa diuji secara nyata.
    """

    def __init__(self):
        self._rows: dict[str, SLATracking] = {}
        self._pending: list[SLATracking] = []

    async def execute(self, _stmt):
        # Semua query SLA di sini di-filter by project_id; kembalikan row
        # pertama yang cocok. Karena hanya satu proyek diuji per test,
        # cukup kembalikan satu-satunya row bila ada.
        row = next(iter(self._rows.values()), None)
        return _execute_result_scalar(row)

    def add(self, obj):
        self._pending.append(obj)

    async def commit(self):
        for obj in self._pending:
            if isinstance(obj, SLATracking):
                self._rows[obj.project_id] = obj
        self._pending.clear()

    async def refresh(self, _obj):
        return None


# =============================================================================
# End-to-end SLATimer di atas fake DB: start → sla-status → idempoten
# =============================================================================


class TestStartTimerEndToEnd:
    """Perilaku SLA nyata yang dijamin wiring assignment."""

    @pytest.mark.asyncio
    async def test_start_timer_membuat_tracking_green_h0(self):
        """Start timer di H+0 membuat row SLATracking green, days_elapsed 0."""
        timer = SLATimer()
        db = _FakeSLASession()
        now = datetime.now(timezone.utc)

        created = await timer.start_timer(project_id="PRJ-20250101-ABC123", assigned_at=now, db=db)

        assert created.project_id == "PRJ-20250101-ABC123"
        assert created.current_status == SLAStatus.GREEN.value
        assert created.days_elapsed == 0
        assert created.is_locked is False
        assert "PRJ-20250101-ABC123" in db._rows

    @pytest.mark.asyncio
    async def test_sla_status_active_green_h0(self):
        """Setelah start di H+0, check_sla_status aktif, green, H+0."""
        timer = SLATimer()
        db = _FakeSLASession()
        now = datetime.now(timezone.utc)

        await timer.start_timer(project_id="PRJ-20250101-ABC123", assigned_at=now, db=db)
        sla_status = await timer.check_sla_status("PRJ-20250101-ABC123", db)

        assert sla_status is not None
        assert sla_status["is_active"] is True
        assert sla_status["status"] == SLAStatus.GREEN.value
        assert sla_status["days_elapsed"] == 0

    @pytest.mark.asyncio
    async def test_start_timer_idempoten_tidak_buat_duplikat(self):
        """Start timer dua kali (re-assign) tidak membuat tracker kedua."""
        timer = SLATimer()
        db = _FakeSLASession()
        now = datetime.now(timezone.utc)

        first = await timer.start_timer(project_id="PRJ-20250101-ABC123", assigned_at=now, db=db)
        second = await timer.start_timer(project_id="PRJ-20250101-ABC123", assigned_at=now, db=db)

        # Hanya satu row, dan pemanggilan kedua mengembalikan row yang sama.
        assert len(db._rows) == 1
        assert second.id == first.id


# =============================================================================
# Endpoint assignment benar-benar men-start SLA timer (wiring)
# =============================================================================


class TestAssignmentWiresStartTimer:
    """POST /projects/{id}/assign memanggil sla_timer.start_timer."""

    @patch("app.api.assignment.sla_timer")
    def test_assign_memanggil_start_timer(self, mock_sla_timer):
        """Assignment sukses memanggil start_timer dengan assigned_at proyek."""
        mock_sla_timer.start_timer = AsyncMock(return_value=MagicMock())

        lead = _make_user(role="Lead_SA")
        project = _make_project(status_value="Awaiting Assignment")
        sa = _make_sa()

        mock_session = AsyncMock()
        # execute() dipanggil: 1) load project, 2) load SA user,
        # 3) lookup Sales (sales_pic) untuk provisioning, 4) count subtask seed.
        mock_session.execute = AsyncMock(
            side_effect=[
                _execute_result_scalar(project),
                _execute_result_scalar(sa),
                _execute_result_scalar(_make_sa()),
                # count subtask untuk auto-seed checklist (0 → seeding jalan)
                _execute_result_scalar(0),
            ]
        )
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        _override_db(mock_session)
        _override_current_user(lead)

        client = TestClient(app)
        response = client.post(
            "/api/v1/projects/PRJ-20250101-ABC123/assign",
            json={"sa_id": str(sa.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_sla_timer.start_timer.assert_awaited_once()
        kwargs = mock_sla_timer.start_timer.await_args.kwargs
        assert kwargs["project_id"] == "PRJ-20250101-ABC123"
        assert kwargs["assigned_at"] == project.assigned_at
        assert kwargs["db"] is mock_session

    @patch("app.api.assignment.sla_timer")
    def test_assign_gagal_start_timer_tidak_menggagalkan_assignment(self, mock_sla_timer):
        """Error saat start_timer tidak menggagalkan response assignment."""
        mock_sla_timer.start_timer = AsyncMock(side_effect=RuntimeError("boom"))

        lead = _make_user(role="Lead_SA")
        project = _make_project(status_value="Awaiting Assignment")
        sa = _make_sa()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                _execute_result_scalar(project),
                _execute_result_scalar(sa),
                _execute_result_scalar(_make_sa()),
                # count subtask untuk auto-seed checklist (0 → seeding jalan)
                _execute_result_scalar(0),
            ]
        )
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        _override_db(mock_session)
        _override_current_user(lead)

        client = TestClient(app)
        response = client.post(
            "/api/v1/projects/PRJ-20250101-ABC123/assign",
            json={"sa_id": str(sa.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "success"
