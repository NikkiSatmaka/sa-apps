"""
Unit tests untuk SLA Timer service.

Menguji logic penghitungan status SLA, start/stop timer,
proses aksi harian, dan integrasi lock/unlock.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sla_timer import (
    SLA_RED_THRESHOLD,
    SLA_YELLOW_THRESHOLD,
    SLAStatus,
    SLATimer,
    _calculate_sla_status,
    _generate_id,
)

# =============================================================================
# Test: _calculate_sla_status (pure function)
# =============================================================================


class TestCalculateSLAStatus:
    """Test fungsi kalkulasi status SLA berdasarkan hari elapsed."""

    def test_hari_0_hijau(self):
        """Hari ke-0 harus hijau."""
        assert _calculate_sla_status(0) == SLAStatus.GREEN

    def test_hari_1_hijau(self):
        """Hari ke-1 harus hijau."""
        assert _calculate_sla_status(1) == SLAStatus.GREEN

    def test_hari_2_hijau(self):
        """Hari ke-2 harus hijau."""
        assert _calculate_sla_status(2) == SLAStatus.GREEN

    def test_hari_3_kuning(self):
        """Hari ke-3 harus kuning (mulai reminder)."""
        assert _calculate_sla_status(3) == SLAStatus.YELLOW

    def test_hari_4_kuning(self):
        """Hari ke-4 masih kuning."""
        assert _calculate_sla_status(4) == SLAStatus.YELLOW

    def test_hari_5_merah(self):
        """Hari ke-5 harus merah (eskalasi + lock)."""
        assert _calculate_sla_status(5) == SLAStatus.RED

    def test_hari_10_merah(self):
        """Hari ke-10+ tetap merah."""
        assert _calculate_sla_status(10) == SLAStatus.RED

    def test_threshold_constants(self):
        """Verifikasi threshold constants sesuai requirement."""
        assert SLA_YELLOW_THRESHOLD == 3
        assert SLA_RED_THRESHOLD == 5


# =============================================================================
# Test: _generate_id
# =============================================================================


class TestGenerateId:
    """Test utility generate ID."""

    def test_default_prefix(self):
        """ID harus dimulai dengan prefix SLA."""
        result = _generate_id()
        assert result.startswith("SLA-")

    def test_custom_prefix(self):
        """ID dengan custom prefix."""
        result = _generate_id("NOTIF")
        assert result.startswith("NOTIF-")

    def test_id_unik(self):
        """Dua ID yang digenerate harus berbeda."""
        id1 = _generate_id()
        id2 = _generate_id()
        assert id1 != id2


# =============================================================================
# Test: SLATimer.start_timer
# =============================================================================


class TestStartTimer:
    """Test memulai SLA timer untuk proyek baru."""

    @pytest.fixture
    def sla_timer(self):
        return SLATimer()

    @pytest.fixture
    def mock_db(self):
        """Mock async database session."""
        db = AsyncMock()
        # Default: tidak ada SLA tracker existing
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_start_timer_buat_record_baru(self, sla_timer, mock_db):
        """Start timer membuat record SLATracking baru dengan status green."""
        assigned_at = datetime.now(timezone.utc)

        result = await sla_timer.start_timer(
            project_id="PRJ-001",
            assigned_at=assigned_at,
            db=mock_db,
        )

        # Pastikan db.add dipanggil dengan SLATracking record
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.project_id == "PRJ-001"
        assert added_obj.current_status == "green"
        assert added_obj.is_locked is False
        assert added_obj.days_elapsed == 0

        # Pastikan commit dipanggil
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_timer_skip_jika_sudah_ada(self, sla_timer):
        """Jika SLA tracker sudah ada, return existing tanpa buat baru."""
        existing_sla = MagicMock()
        existing_sla.project_id = "PRJ-001"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_sla
        mock_db.execute.return_value = mock_result

        result = await sla_timer.start_timer(
            project_id="PRJ-001",
            assigned_at=datetime.now(timezone.utc),
            db=mock_db,
        )

        # Tidak boleh add record baru
        mock_db.add.assert_not_called()
        assert result == existing_sla


# =============================================================================
# Test: SLATimer.check_sla_status
# =============================================================================


class TestCheckSLAStatus:
    """Test pengecekan status SLA saat ini."""

    @pytest.fixture
    def sla_timer(self):
        return SLATimer()

    @pytest.mark.asyncio
    async def test_return_none_jika_tidak_ada_tracker(self, sla_timer):
        """Return None jika tidak ada SLA tracker untuk proyek."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await sla_timer.check_sla_status("PRJ-NOT-EXIST", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_return_status_aktif(self, sla_timer):
        """Return status dict untuk timer yang masih aktif."""
        started = datetime.now(timezone.utc) - timedelta(days=4)

        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.started_at = started
        sla_record.stopped_at = None
        sla_record.is_locked = False
        sla_record.days_elapsed = 4
        sla_record.current_status = "yellow"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sla_record
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        result = await sla_timer.check_sla_status("PRJ-001", mock_db)

        assert result is not None
        assert result["project_id"] == "PRJ-001"
        assert result["is_active"] is True
        assert result["days_elapsed"] == 4
        assert result["status"] == "yellow"

    @pytest.mark.asyncio
    async def test_return_stopped_status(self, sla_timer):
        """Return status dict untuk timer yang sudah dihentikan."""
        started = datetime.now(timezone.utc) - timedelta(days=3)
        stopped = datetime.now(timezone.utc) - timedelta(days=1)

        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.started_at = started
        sla_record.stopped_at = stopped
        sla_record.is_locked = False
        sla_record.days_elapsed = 2
        sla_record.current_status = "green"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sla_record
        mock_db.execute.return_value = mock_result

        result = await sla_timer.check_sla_status("PRJ-001", mock_db)

        assert result is not None
        assert result["is_active"] is False
        assert result["stopped_at"] is not None


# =============================================================================
# Test: SLATimer.stop_timer
# =============================================================================


class TestStopTimer:
    """Test penghentian SLA timer saat DQ Number diinput."""

    @pytest.fixture
    def sla_timer(self):
        return SLATimer()

    @pytest.mark.asyncio
    async def test_stop_timer_tanpa_lock(self, sla_timer):
        """Stop timer normal (belum di-lock) — hanya set stopped_at."""
        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.stopped_at = None
        sla_record.is_locked = False
        sla_record.days_elapsed = 2

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sla_record
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await sla_timer.stop_timer("PRJ-001", mock_db)

        assert result == sla_record
        assert sla_record.stopped_at is not None
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_timer_dengan_unlock(self, sla_timer):
        """Stop timer setelah lock — harus trigger auto-unlock."""
        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.stopped_at = None
        sla_record.is_locked = True
        sla_record.locked_at = datetime.now(timezone.utc) - timedelta(days=1)
        sla_record.days_elapsed = 6

        # Mock project dan user data
        mock_project = MagicMock()
        mock_project.id_project = "PRJ-001"
        mock_project.gdrive_folder_id = "gdrive_master_123"
        mock_project.gdrive_solutions_folder_id = "gdrive_solutions_123"
        mock_project.sales_pic = uuid.uuid4()

        mock_sales = MagicMock()
        mock_sales.email = "sales@company.com"

        mock_db = AsyncMock()

        # Responses untuk execute calls:
        # 1. SLATracking lookup
        # 2. Project lookup (dari _unlock_solutions_with_retry)
        # 3. User lookup (dari _unlock_solutions_with_retry)
        sla_result = MagicMock()
        sla_result.scalar_one_or_none.return_value = sla_record

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = mock_project

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_sales

        mock_db.execute.side_effect = [sla_result, project_result, user_result]
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.begin_nested = MagicMock()  # SAVEPOINT penulisan audit log

        with patch(
            "app.services.sla_timer.folder_provisioner.unlock_solutions_folder",
            new_callable=AsyncMock,
        ) as mock_unlock:
            result = await sla_timer.stop_timer("PRJ-001", mock_db)

        # Verifikasi unlock dipanggil dengan id folder Solutions (ADR 0005)
        mock_unlock.assert_called_once_with(
            solutions_folder_id="gdrive_solutions_123",
            sales_email="sales@company.com",
        )

        # Verifikasi SLA record di-update
        assert sla_record.is_locked is False
        assert sla_record.unlocked_at is not None

    @pytest.mark.asyncio
    async def test_stop_timer_return_none_jika_tidak_ada(self, sla_timer):
        """Return None jika tidak ada SLA tracker untuk proyek."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await sla_timer.stop_timer("PRJ-NOT-EXIST", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_stop_timer_skip_jika_sudah_stopped(self, sla_timer):
        """Skip jika timer sudah dihentikan sebelumnya."""
        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.stopped_at = datetime.now(timezone.utc)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sla_record
        mock_db.execute.return_value = mock_result

        result = await sla_timer.stop_timer("PRJ-001", mock_db)
        assert result == sla_record
        # Tidak boleh commit ulang
        mock_db.commit.assert_not_called()


# =============================================================================
# Test: SLATimer.process_sla_actions
# =============================================================================


class TestProcessSLAActions:
    """Test cron job proses SLA harian."""

    @pytest.fixture
    def sla_timer(self):
        return SLATimer()

    @pytest.mark.asyncio
    async def test_proses_reminder_hari_3(self, sla_timer):
        """Proyek yang baru masuk hari ke-3 mendapat reminder."""
        started_at = datetime.now(timezone.utc) - timedelta(days=3)

        sla_record = MagicMock()
        sla_record.project_id = "PRJ-001"
        sla_record.started_at = started_at
        sla_record.current_status = "green"  # Status lama (belum di-update)
        sla_record.is_locked = False
        sla_record.days_elapsed = 0

        mock_project = MagicMock()
        mock_project.id_project = "PRJ-001"
        mock_project.project_name = "Test Project"
        mock_project.customer_name = "Customer A"
        mock_project.sales_pic = uuid.uuid4()
        mock_project.gdrive_folder_id = None

        # Mock AsyncSessionLocal context manager
        mock_session = AsyncMock()
        sla_list_result = MagicMock()
        sla_list_result.scalars.return_value.all.return_value = [sla_record]

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = mock_project

        mock_session.execute.side_effect = [sla_list_result, project_result]
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        with patch(
            "app.services.sla_timer.AsyncSessionLocal",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            stats = await sla_timer.process_sla_actions()

        assert stats["total_checked"] == 1
        assert stats["reminders_sent"] == 1
        assert stats["escalations_sent"] == 0

    @pytest.mark.asyncio
    async def test_proses_eskalasi_dan_lock_hari_5(self, sla_timer):
        """Proyek yang mencapai hari ke-5 mendapat eskalasi dan auto-lock."""
        started_at = datetime.now(timezone.utc) - timedelta(days=5)

        sla_record = MagicMock()
        sla_record.project_id = "PRJ-002"
        sla_record.started_at = started_at
        sla_record.current_status = "yellow"
        sla_record.is_locked = False
        sla_record.days_elapsed = 4

        mock_project = MagicMock()
        mock_project.id_project = "PRJ-002"
        mock_project.project_name = "Urgent Project"
        mock_project.customer_name = "Customer B"
        mock_project.sales_pic = uuid.uuid4()
        mock_project.gdrive_folder_id = "folder_123"
        mock_project.gdrive_solutions_folder_id = "solutions_123"

        mock_sales = MagicMock()
        mock_sales.email = "sales@company.com"
        mock_sales.id = mock_project.sales_pic

        mock_manager = MagicMock()
        mock_manager.id = uuid.uuid4()
        mock_manager.email = "lead@company.com"

        # Mock session
        mock_session = AsyncMock()
        sla_list_result = MagicMock()
        sla_list_result.scalars.return_value.all.return_value = [sla_record]

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = mock_project

        manager_result = MagicMock()
        manager_result.scalars.return_value.all.return_value = [mock_manager]

        sales_result = MagicMock()
        sales_result.scalar_one_or_none.return_value = mock_sales

        mock_session.execute.side_effect = [
            sla_list_result,  # Query active SLAs
            project_result,  # Query project
            manager_result,  # Query managers (eskalasi)
            sales_result,  # Query sales user (lock)
        ]
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.begin_nested = MagicMock()  # SAVEPOINT penulisan audit log

        with (
            patch(
                "app.services.sla_timer.AsyncSessionLocal",
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=False),
                ),
            ),
            patch(
                "app.services.sla_timer.folder_provisioner.lock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_lock,
        ):
            stats = await sla_timer.process_sla_actions()

        assert stats["total_checked"] == 1
        assert stats["escalations_sent"] == 1
        assert stats["locks_performed"] == 1
        mock_lock.assert_called_once()

    @pytest.mark.asyncio
    async def test_proses_tanpa_proyek_aktif(self, sla_timer):
        """Proses tanpa proyek aktif mengembalikan stats kosong."""
        mock_session = AsyncMock()
        sla_list_result = MagicMock()
        sla_list_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = sla_list_result
        mock_session.commit = AsyncMock()

        with patch(
            "app.services.sla_timer.AsyncSessionLocal",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            stats = await sla_timer.process_sla_actions()

        assert stats["total_checked"] == 0
        assert stats["reminders_sent"] == 0
        assert stats["escalations_sent"] == 0
        assert stats["locks_performed"] == 0
