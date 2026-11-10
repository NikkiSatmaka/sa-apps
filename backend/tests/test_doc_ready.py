"""
Unit tests untuk emit doc_ready + buka akses Solutions saat dokumen Reviewed.

Fase 2A — T4 (fix B13). Spec Flow 2 ("< 5 hari"): saat Sales sudah input DQ dan
dokumen SA berstatus `Reviewed`, link Google Drive Solutions terbuka otomatis
untuk Sales disertai notifikasi.

Aturan yang diuji:
- Transisi → `Reviewed` saat DQ terisi: emit notifikasi `doc_ready` (in-app) ke
  Sales DAN buka permission Drive Solutions untuk Sales.
- DQ kosong: tidak emit doc_ready, tidak buka akses.
- Transisi lain (Reviewed → Final, transisi mundur): tidak emit doc_ready.

Semua test terisolasi: DB session, notification_service, dan folder_provisioner
di-mock; tidak membutuhkan Postgres live.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.services.notification_service import NotificationEventType

# =============================================================================
# Fixtures & Helpers
# =============================================================================


def _make_user(role: str = "SA", user_id: uuid.UUID | None = None):
    """Buat mock User untuk dependency override."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = f"{role.lower()}@company.com"
    user.name = f"Test {role}"
    user.role = role
    return user


def _make_document(status: str = "Draft", folder_type: str = "Solutions"):
    """Buat mock Document dengan field yang dibutuhkan response."""
    doc = MagicMock()
    doc.id_doc = "DOC-20250101-ABC123"
    doc.id_project = "PRJ-20250101-XYZ789"
    doc.doc_type = "PropTek"
    doc.status = status
    doc.gdrive_link = "https://drive.google.com/doc"
    doc.folder_type = folder_type
    doc.notes = None
    doc.created_by = uuid.uuid4()
    doc.updated_by = None
    doc.created_at = datetime.now(timezone.utc)
    doc.updated_at = datetime.now(timezone.utc)
    # Kolom Requirement (default untuk dokumen jenis lain)
    doc.content = None
    doc.is_overridden = False
    doc.source_hash = None
    doc.generated_at = None
    doc.source_truncated = False
    return doc


def _make_project(
    dq_number=None,
    sales_pic=None,
    gdrive_folder_id="folder_123",
    gdrive_solutions_folder_id="solutions_123",
):
    """Buat mock Project dengan field yang relevan untuk gating."""
    project = MagicMock()
    project.id_project = "PRJ-20250101-XYZ789"
    project.project_name = "Test Project"
    project.customer_name = "Customer A"
    project.dq_number = dq_number
    project.sales_pic = sales_pic or uuid.uuid4()
    project.gdrive_folder_id = gdrive_folder_id
    project.gdrive_solutions_folder_id = gdrive_solutions_folder_id
    return project


def _result_scalar(value):
    """Mock hasil db.execute() untuk .scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
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


@pytest.fixture
def client():
    return TestClient(app)


# =============================================================================
# Test: transisi → Reviewed dengan DQ terisi memicu doc_ready + buka akses
# =============================================================================


class TestReviewedDenganDQ:
    """Transisi Draft → Reviewed saat DQ terisi harus emit doc_ready + unlock."""

    def test_emit_doc_ready_dan_buka_akses_solutions(self, client):
        sales_id = uuid.uuid4()
        document = _make_document(status="Draft", folder_type="Solutions")
        project = _make_project(dq_number="DQ-12345", sales_pic=sales_id)
        sales_user = _make_user(role="Sales", user_id=sales_id)
        sa_user = _make_user(role="SA")

        mock_session = AsyncMock()
        # execute() dipanggil: 1) lookup dokumen, 2) lookup project, 3) lookup sales user
        mock_session.execute.side_effect = [
            _result_scalar(document),
            _result_scalar(project),
            _result_scalar(sales_user),
        ]
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        _override_current_user(sa_user)
        _override_db(mock_session)

        with (
            patch(
                "app.api.documents.notification_service.send_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch(
                "app.api.documents.folder_provisioner.unlock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            response = client.patch(
                "/api/v1/documents/DOC-20250101-ABC123/status",
                json={"new_status": "Reviewed"},
            )

        assert response.status_code == 200

        # doc_ready ter-emit ke Sales (sales_pic)
        mock_notify.assert_called_once()
        event = mock_notify.call_args[0][0]
        assert event.event_type == NotificationEventType.DOC_READY
        assert event.recipient_user_id == sales_id
        assert event.recipient_email == sales_user.email

        # Permission Drive Solutions dibuka untuk Sales (ADR 0005: id Solutions)
        mock_unlock.assert_called_once_with(
            solutions_folder_id="solutions_123",
            sales_email=sales_user.email,
        )


# =============================================================================
# Test: DQ kosong tidak memicu doc_ready
# =============================================================================


class TestReviewedTanpaDQ:
    """Transisi → Reviewed saat DQ kosong TIDAK boleh emit doc_ready."""

    def test_dq_kosong_tidak_emit(self, client):
        document = _make_document(status="Draft", folder_type="Solutions")
        project = _make_project(dq_number=None)
        sa_user = _make_user(role="SA")

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _result_scalar(document),
            _result_scalar(project),
        ]
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        _override_current_user(sa_user)
        _override_db(mock_session)

        with (
            patch(
                "app.api.documents.notification_service.send_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch(
                "app.api.documents.folder_provisioner.unlock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            response = client.patch(
                "/api/v1/documents/DOC-20250101-ABC123/status",
                json={"new_status": "Reviewed"},
            )

        assert response.status_code == 200
        mock_notify.assert_not_called()
        mock_unlock.assert_not_called()


# =============================================================================
# Test: transisi lain tidak memicu doc_ready
# =============================================================================


class TestTransisiLainTidakEmit:
    """Transisi selain → Reviewed tidak boleh emit doc_ready."""

    def test_reviewed_ke_final_tidak_emit(self, client):
        # Reviewed → Final (maju) — bukan transisi ke Reviewed, jadi tidak
        # memicu lookup project (hanya 1 execute: lookup dokumen).
        document = _make_document(status="Reviewed", folder_type="Solutions")
        sa_user = _make_user(role="SA")

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _result_scalar(document),
        ]
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        _override_current_user(sa_user)
        _override_db(mock_session)

        with (
            patch(
                "app.api.documents.notification_service.send_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch(
                "app.api.documents.folder_provisioner.unlock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            response = client.patch(
                "/api/v1/documents/DOC-20250101-ABC123/status",
                json={"new_status": "Final"},
            )

        assert response.status_code == 200
        mock_notify.assert_not_called()
        mock_unlock.assert_not_called()

    def test_transisi_mundur_ke_draft_tidak_emit(self, client):
        # Reviewed → Draft (mundur, hanya Lead_SA) — bukan transisi ke Reviewed.
        document = _make_document(status="Reviewed", folder_type="Solutions")
        lead_user = _make_user(role="Lead_SA")

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _result_scalar(document),
        ]
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        _override_current_user(lead_user)
        _override_db(mock_session)

        with (
            patch(
                "app.api.documents.notification_service.send_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch(
                "app.api.documents.folder_provisioner.unlock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            response = client.patch(
                "/api/v1/documents/DOC-20250101-ABC123/status",
                json={"new_status": "Draft"},
            )

        assert response.status_code == 200
        mock_notify.assert_not_called()
        mock_unlock.assert_not_called()


# =============================================================================
# Test: kegagalan side-effect tidak menggagalkan transisi utama
# =============================================================================


class TestSideEffectTidakMenggagalkanTransisi:
    """Error pada notifikasi/unlock tidak boleh menggagalkan transisi dokumen."""

    def test_unlock_gagal_transisi_tetap_sukses(self, client):
        sales_id = uuid.uuid4()
        document = _make_document(status="Draft", folder_type="Solutions")
        project = _make_project(dq_number="DQ-12345", sales_pic=sales_id)
        sales_user = _make_user(role="Sales", user_id=sales_id)
        sa_user = _make_user(role="SA")

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _result_scalar(document),
            _result_scalar(project),
            _result_scalar(sales_user),
        ]
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        _override_current_user(sa_user)
        _override_db(mock_session)

        with (
            patch(
                "app.api.documents.notification_service.send_notification",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.documents.folder_provisioner.unlock_solutions_folder",
                new_callable=AsyncMock,
                side_effect=Exception("GDrive error"),
            ),
        ):
            response = client.patch(
                "/api/v1/documents/DOC-20250101-ABC123/status",
                json={"new_status": "Reviewed"},
            )

        # Transisi utama tetap sukses meski unlock gagal
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "Reviewed"
