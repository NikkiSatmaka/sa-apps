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


def _daftar(nilai):
    """Hasil `db.execute` untuk query yang dibaca lewat `.scalars().all()`."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(nilai)
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


class TestWonNotifikasiHLD:
    def test_won_kirim_notifikasi_wajib_hld_ke_sa(self, client):
        sa = _user("SA")
        project = _project("Submitted", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _daftar([]), _daftar([sa])])

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
        project = _project("Submitted", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project)])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "In Progress"},
            )

        assert resp.status_code == 200
        notify.assert_not_called()

    def test_tanpa_sa_transisi_tetap_berhasil_tanpa_notifikasi(self, client):
        project = _project("Submitted", None)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _daftar([])])

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
        _setup(lead, [_scalar(project), _daftar([]), _daftar([sa])])

        with _patch_status_response() as notify:
            notify.side_effect = RuntimeError("boom")
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200

    def test_won_kirim_ke_sa_utama_dan_semua_sa_tambahan_sekali_per_orang(self, client):
        utama, tambahan_1, tambahan_2 = _user("SA"), _user("SA"), _user("Lead_SA")
        project = _project("Submitted", utama.id)
        lead = _user("Lead_SA")
        # Urutan query: proyek, id SA tambahan (utama ikut muncul = duplikat), lalu user penerima.
        _setup(
            lead,
            [
                _scalar(project),
                _daftar([tambahan_1.id, tambahan_2.id, utama.id]),
                _daftar([tambahan_2, utama, tambahan_1]),
            ],
        )

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        penerima = [c.args[0].recipient_user_id for c in notify.call_args_list]
        assert penerima == [utama.id, tambahan_1.id, tambahan_2.id]  # urut: utama dulu, tanpa ganda
        assert all(c.args[0].metadata["mandatory_hld"] is True for c in notify.call_args_list)

    def test_won_hanya_sa_tambahan_tanpa_sa_utama_tetap_terkirim(self, client):
        tambahan = _user("SA")
        project = _project("Submitted", None)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _daftar([tambahan.id]), _daftar([tambahan])])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        assert [c.args[0].recipient_user_id for c in notify.call_args_list] == [tambahan.id]

    def test_satu_penerima_gagal_tidak_menghalangi_penerima_lain(self, client):
        utama, tambahan = _user("SA"), _user("SA")
        project = _project("Submitted", utama.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _daftar([tambahan.id]), _daftar([utama, tambahan])])

        with _patch_status_response() as notify:
            notify.side_effect = [RuntimeError("boom"), None]
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        assert notify.await_count == 2  # penerima kedua tetap dicoba

    def test_penerima_pada_user_yang_tidak_ditemukan_dilewati(self, client):
        sa = _user("SA")
        project = _project("Submitted", sa.id)
        lead = _user("Lead_SA")
        _setup(lead, [_scalar(project), _daftar([]), _daftar([])])

        with _patch_status_response() as notify:
            resp = client.patch(
                f"/api/v1/projects/{project.id_project}/status",
                json={"new_status": "Won"},
            )

        assert resp.status_code == 200
        notify.assert_not_called()
