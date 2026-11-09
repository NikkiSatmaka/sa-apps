"""
Test soft delete proyek.

1. Listener global `_filter_soft_deleted` menambahkan `deleted_at IS NULL`
   ke SELECT ORM atas Project (termasuk select kolom/agregat), dan bisa
   dimatikan via execution option INCLUDE_DELETED.
2. Endpoint DELETE /projects/{id} melakukan soft delete (bukan hard delete),
   menghentikan SLA timer aktif, dan tetap menegakkan otorisasi role.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.main import app
from app.models.document import Document
from app.models.project import INCLUDE_DELETED, Project, _filter_soft_deleted


# =============================================================================
# Listener filter soft delete
# =============================================================================


def _run_filter(stmt) -> str:
    """Jalankan listener pada state palsu lalu kembalikan SQL hasil compile."""
    state = SimpleNamespace(
        statement=stmt,
        is_select=True,
        is_column_load=False,
        is_relationship_load=False,
        execution_options=stmt.get_execution_options(),
    )
    _filter_soft_deleted(state)
    return str(state.statement.compile(dialect=postgresql.dialect()))


class TestSoftDeleteFilter:
    def test_select_entity_disaring(self):
        sql = _run_filter(select(Project).where(Project.id_project == "PRJ-1"))
        assert "projects.deleted_at IS NULL" in sql

    def test_select_kolom_agregat_disaring(self):
        """Count per status (dashboard) juga tidak boleh menghitung proyek terhapus."""
        stmt = select(Project.status, func.count(Project.id_project)).group_by(
            Project.status
        )
        assert "projects.deleted_at IS NULL" in _run_filter(stmt)

    def test_include_deleted_menonaktifkan_filter(self):
        stmt = select(Project).execution_options(**{INCLUDE_DELETED: True})
        assert "deleted_at IS NULL" not in _run_filter(stmt)

    def test_query_tabel_lain_tidak_disaring(self):
        """Dokumen/activity log tidak ikut disaring — data tetap utuh."""
        sql = _run_filter(select(Document))
        assert "deleted_at" not in sql


# =============================================================================
# Endpoint DELETE /projects/{id}
# =============================================================================


def _user(role: str):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = f"{role.lower()}@company.com"
    user.role = role
    return user


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


@pytest.fixture
def call_delete():
    """Panggil DELETE dengan user & session mock; kembalikan (response, session)."""
    import app.core.database as database_module
    import app.core.dependencies as dependencies_module

    def _call(user, project):
        session = AsyncMock()
        session.delete = AsyncMock()
        # 1) lookup Project, 2) UPDATE sla_tracking
        session.execute = AsyncMock(side_effect=[_scalar_result(project), MagicMock()])

        async def override_get_db():
            yield session

        app.dependency_overrides[database_module.get_db] = override_get_db
        app.dependency_overrides[dependencies_module.get_current_user] = lambda: user
        try:
            response = TestClient(app).delete("/api/v1/projects/PRJ-20250101-ABC123")
        finally:
            app.dependency_overrides.clear()
        return response, session

    return _call


class TestDeleteProjectEndpoint:
    @pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
    def test_soft_delete_bukan_hard_delete(self, call_delete, role):
        user = _user(role)
        project = Project(id_project="PRJ-20250101-ABC123")

        response, session = call_delete(user, project)

        assert response.status_code == status.HTTP_200_OK
        assert project.deleted_at is not None
        assert project.deleted_by == user.id
        session.delete.assert_not_called()
        session.commit.assert_awaited_once()

    def test_sla_timer_aktif_dihentikan(self, call_delete):
        response, session = call_delete(
            _user("Admin"), Project(id_project="PRJ-20250101-ABC123")
        )

        assert response.status_code == status.HTTP_200_OK
        update_stmt = session.execute.await_args_list[1].args[0]
        sql = str(update_stmt.compile(dialect=postgresql.dialect()))
        assert sql.startswith("UPDATE sla_tracking SET stopped_at")
        assert "sla_tracking.stopped_at IS NULL" in sql

    @pytest.mark.parametrize("role", ["Sales", "SA"])
    def test_role_lain_ditolak(self, call_delete, role):
        project = Project(id_project="PRJ-20250101-ABC123")

        response, session = call_delete(_user(role), project)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert project.deleted_at is None
        session.commit.assert_not_awaited()

    def test_proyek_tidak_ada_atau_sudah_dihapus_404(self, call_delete):
        """Proyek terhapus tersaring dari lookup → diperlakukan sebagai 404."""
        response, session = call_delete(_user("Admin"), None)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        session.commit.assert_not_awaited()
