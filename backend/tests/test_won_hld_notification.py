"""
Test notifikasi wajib buat HLD saat proyek menjadi Won (fix B14).

Spec Flow 4 langkah 1: saat proyek Won, SA menerima notifikasi wajib
membuat HLD. DB dan notification_service di-mock; tidak butuh Postgres live.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.services.notification_service import NotificationEventType


def _user(role: str, user_id: uuid.UUID | None = None):
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = f"{role.lower()}@company.com"
    u.role = role
    return u


def _project(status: str, assigned_sa):
    p = MagicMock()
    p.id_project = "PRJ-20250101-XYZ789"
    p.project_name = "Test Project"
    p.customer_name = "Customer A"
    p.status = status
    p.assigned_sa = assigned_sa
    p.sales_pic = uuid.uuid4()
    return p


def _scalar(value):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


def _setup(current_user, results):
    session = AsyncMock()
    session.execute.side_effect = results
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    async def _override():
        yield session

    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = _override
    return session


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _patch_status_response():
    # Hindari validasi response model terhadap MagicMock pada updated_at dsb.
    return patch("app.api.workflow.notification_service.send_notification", new_callable=AsyncMock)


class TestClosedWinNotifikasiHLD:
    def test_closed_win_kirim_notifikasi_wajib_hld_ke_sa(self, client):
        sa = _user("SA")
        project = _project("Submitted", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _scalar(sa)])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        notify.assert_called_once()
        event = notify.call_args[0][0]
        assert event.event_type == NotificationEventType.STATUS_CHANGE
        assert event.recipient_user_id == sa.id
        assert event.recipient_email == sa.email
        assert event.metadata["mandatory_hld"] is True

    def test_status_lain_tidak_kirim_notifikasi_hld(self, client):
        sa = _user("SA")
        project = _project("Assigned", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project)])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Submitted"},
            )

        assert resp.status_code == 200
        notify.assert_not_called()

    def test_tanpa_sa_transisi_tetap_berhasil_tanpa_notifikasi(self, client):
        project = _project("Submitted", None)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project)])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        notify.assert_not_called()

    def test_notifikasi_gagal_tidak_menggagalkan_transisi(self, client):
        sa = _user("SA")
        project = _project("Submitted", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _scalar(sa)])

        with _patch_status_response() as notify:
            notify.side_effect = RuntimeError("boom")
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
