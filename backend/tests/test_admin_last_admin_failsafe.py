"""
Unit tests untuk failsafe admin terakhir pada endpoint PATCH /admin/users/{user_id}/admin
(#114, ADR 0012; sebelumnya failsafe di /role saat Admin masih role).

Invarian: sistem harus selalu punya minimal satu user dengan `is_admin`.
- Mencabut `is_admin` satu-satunya admin ditolak (409 Conflict).
- Mencabut `is_admin` ketika masih ada admin lain diperbolehkan.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app


def _user(nama: str, *, is_admin: bool) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = f"{nama}@company.com"
    user.name = nama
    user.role = "SA"
    user.is_admin = is_admin
    return user


@pytest.fixture
def admin_env():
    """Setup current_user admin + mock DB session, dengan override dependency."""
    current_admin = _user("Admin Utama", is_admin=True)
    target_admin = _user("Target Admin", is_admin=True)

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=target_admin)
    mock_session.execute = AsyncMock(return_value=execute_result)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_admin

    yield current_admin, target_admin, mock_session

    app.dependency_overrides.clear()


def test_cabut_admin_terakhir_ditolak(admin_env):
    """Mencabut `is_admin` admin satu-satunya ditolak dengan 409 Conflict."""
    _, target_admin, mock_session = admin_env
    mock_session.scalar = AsyncMock(return_value=1)  # hanya 1 admin di sistem

    response = TestClient(app).patch(
        f"/api/v1/admin/users/{target_admin.id}/admin", json={"is_admin": False}
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Admin terakhir" in response.json()["message"]
    mock_session.commit.assert_not_awaited()


def test_cabut_admin_dengan_admin_lain_diperbolehkan(admin_env):
    """Mencabut `is_admin` ketika masih ada admin lain diperbolehkan."""
    _, target_admin, mock_session = admin_env
    mock_session.scalar = AsyncMock(return_value=2)  # ada lebih dari 1 admin

    response = TestClient(app).patch(
        f"/api/v1/admin/users/{target_admin.id}/admin", json={"is_admin": False}
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["is_admin"] is False
    assert body["data"]["old_is_admin"] is True
    mock_session.commit.assert_awaited()
