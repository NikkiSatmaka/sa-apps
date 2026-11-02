"""
Tests untuk Subtask API (FEAT-002) di seam HTTP.

Memvalidasi perilaku teramati lewat API:
- Lifecycle: create (Lead_SA) -> list -> update status -> assign/reassign -> delete.
- Auto-seed: assign proyek ke SA menanam 4 subtask template; re-assign idempoten (tetap 4).
- Authz: tanpa token -> 401; SA bukan owner mengubah subtask -> 403.
- Link activity log (ADR 0008): create log dengan id_subtask memajukan subtask
  open -> in_progress; idempoten pada in_progress/done; tidak pernah ke done
  maupun mundur; id_subtask lintas-proyek ditolak (422).

Test terisolasi: tidak butuh Postgres live. Memakai fake in-memory AsyncSession
yang menyimpan subtasks/projects/activity logs sehingga create->list->update->delete
dan idempotensi seed teramati lewat API. Query dirutekan berdasarkan entitas
yang di-select, bukan bergantung pada urutan kolom internal.
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
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.subtask import Subtask
from app.models.user import User

PROJECT_ID = "PRJ-20250101-ABC123"


# =============================================================================
# Helpers & fixtures
# =============================================================================


def _make_user(role: str = "SA", user_id: uuid.UUID | None = None, name: str | None = None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = f"{role.lower()}@company.com"
    user.name = name or f"Test {role}"
    user.role = role
    return user


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


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=value)
    return result


def _scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(values))
    result.scalars = MagicMock(return_value=scalars)
    return result


class _FakeSession:
    """
    Fake AsyncSession in-memory yang mengenali entitas yang di-query lewat
    kolom/entity description dari statement SQLAlchemy.

    Menyimpan Project, User, Subtask, dan ActivityLog di memori sehingga
    create -> list -> update -> delete dan seeding idempoten teramati via API.
    """

    def __init__(self):
        self.projects: dict[str, Project] = {}
        self.users: dict[uuid.UUID, User] = {}
        self.subtasks: dict[str, Subtask] = {}
        self.activity_logs: dict[str, ActivityLog] = {}

    # --- seeding langsung (bukan lewat API) ---
    def add_project(self, project):
        self.projects[project.id_project] = project

    def add_user(self, user):
        self.users[user.id] = user

    # --- introspeksi statement ---
    @staticmethod
    def _entity_name(stmt) -> str:
        """Nama entitas utama yang di-select dari statement."""
        try:
            desc = stmt.column_descriptions
            if desc:
                entity = desc[0].get("entity")
                if entity is not None:
                    return entity.__name__
                # count(): type bisa berupa fungsi; cek select_from
        except Exception:
            pass
        # Fallback: lihat froms
        try:
            froms = stmt.get_final_froms()
            if froms:
                name = getattr(froms[0], "name", "")
                return {
                    "projects": "Project",
                    "users": "User",
                    "subtasks": "Subtask",
                    "activity_logs": "ActivityLog",
                }.get(name, "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _is_count(stmt) -> bool:
        try:
            desc = stmt.column_descriptions
            if desc and desc[0].get("name") == "count":
                return True
            text = str(stmt).lower()
            return "count(" in text
        except Exception:
            return False

    @staticmethod
    def _criteria_values(stmt) -> list:
        """Ambil nilai literal dari WHERE clause (parameter bind)."""
        try:
            params = stmt.compile().params
            return list(params.values())
        except Exception:
            return []

    async def execute(self, stmt):
        entity = self._entity_name(stmt)
        values = self._criteria_values(stmt)

        if entity == "Subtask":
            if self._is_count(stmt):
                # count subtask untuk suatu project_id
                pid = next((v for v in values if isinstance(v, str)), None)
                n = sum(1 for s in self.subtasks.values() if s.id_project == pid)
                return _scalar_result(n)
            # select Subtask: by PK id_subtask ATAU list by id_project
            id_values = [v for v in values if isinstance(v, str)]
            # PK lookup
            for v in id_values:
                if v in self.subtasks:
                    return _scalar_result(self.subtasks[v])
            # list by project
            if id_values:
                pid = id_values[0]
                matched = [s for s in self.subtasks.values() if s.id_project == pid]
                matched.sort(key=lambda s: s.created_at)
                return _scalars_result(matched)
            return _scalar_result(None)

        if entity == "Project":
            pid = next((v for v in values if isinstance(v, str)), None)
            return _scalar_result(self.projects.get(pid))

        if entity == "User":
            uid = next((v for v in values if isinstance(v, uuid.UUID)), None)
            if uid is None:
                # coba parse string uuid
                for v in values:
                    try:
                        uid = uuid.UUID(str(v))
                        break
                    except (ValueError, AttributeError, TypeError):
                        continue
            return _scalar_result(self.users.get(uid))

        if entity == "ActivityLog":
            return _scalar_result(None)

        return _scalar_result(None)

    def add(self, obj):
        if isinstance(obj, Subtask):
            self._ensure_subtask_defaults(obj)
            self.subtasks[obj.id_subtask] = obj
        elif isinstance(obj, ActivityLog):
            self.activity_logs[obj.id_log] = obj

    @staticmethod
    def _ensure_subtask_defaults(obj: Subtask):
        now = datetime.now(timezone.utc)
        if getattr(obj, "status", None) is None:
            obj.status = "open"
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        if not hasattr(obj, "assigned_sa"):
            obj.assigned_sa = None

    async def delete(self, obj):
        if isinstance(obj, Subtask):
            self.subtasks.pop(obj.id_subtask, None)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


def _make_project(sales_pic=None, assigned_sa=None, status_value="Pending Assignment"):
    project = MagicMock(spec=Project)
    project.id_project = PROJECT_ID
    project.project_name = "Proyek Uji"
    project.customer_name = "Customer A"
    project.status = status_value
    project.bant_score = 80
    project.use_case_tags = ["etl"]
    project.sales_pic = sales_pic or uuid.uuid4()
    project.assigned_sa = assigned_sa
    project.assigned_at = None
    project.target_submit = date(2026, 12, 31)
    project.gdrive_folder_id = None
    return project


# =============================================================================
# (a) Lifecycle: create -> list -> update -> assign/reassign -> delete
# =============================================================================


class TestSubtaskLifecycle:
    def test_full_lifecycle_via_api(self):
        session = _FakeSession()
        lead = _make_user(role="Lead_SA")
        sa_one = _make_user(role="SA", name="SA Satu")
        sa_two = _make_user(role="SA", name="SA Dua")
        session.add_project(_make_project())
        session.add_user(lead)
        session.add_user(sa_one)
        session.add_user(sa_two)

        _override_db(session)
        _override_current_user(lead)
        client = TestClient(app)

        # create
        resp = client.post(
            f"/api/v1/projects/{PROJECT_ID}/subtasks",
            json={"title": "Requirement"},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        created = resp.json()["data"]
        sub_id = created["id_subtask"]
        assert created["status"] == "open"
        assert created["title"] == "Requirement"

        # list memuat item
        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/subtasks")
        assert resp.status_code == status.HTTP_200_OK
        items = resp.json()["data"]["items"]
        assert any(s["id_subtask"] == sub_id for s in items)

        # update status open -> in_progress -> done
        for new_status in ("in_progress", "done"):
            resp = client.patch(
                f"/api/v1/projects/subtasks/{sub_id}/status",
                json={"status": new_status},
            )
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["data"]["status"] == new_status

        # status terlihat di list
        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/subtasks")
        listed = next(s for s in resp.json()["data"]["items"] if s["id_subtask"] == sub_id)
        assert listed["status"] == "done"

        # assign ke sa_one
        resp = client.patch(
            f"/api/v1/projects/subtasks/{sub_id}/assign",
            json={"assigned_sa": str(sa_one.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["data"]["assigned_sa"] == str(sa_one.id)

        # reassign ke sa_two (assigned_sa berubah)
        resp = client.patch(
            f"/api/v1/projects/subtasks/{sub_id}/assign",
            json={"assigned_sa": str(sa_two.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["data"]["assigned_sa"] == str(sa_two.id)

        # delete -> hilang dari list
        resp = client.delete(f"/api/v1/projects/subtasks/{sub_id}")
        assert resp.status_code == status.HTTP_200_OK
        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/subtasks")
        assert all(s["id_subtask"] != sub_id for s in resp.json()["data"]["items"])


# =============================================================================
# (b) Auto-seed saat assignment, idempoten pada re-assign
# =============================================================================


class TestAutoSeedOnAssignment:
    @patch("app.api.assignment.sla_timer")
    def test_assign_seeds_four_then_reassign_idempotent(self, mock_sla_timer):
        from unittest.mock import AsyncMock

        mock_sla_timer.start_timer = AsyncMock(return_value=MagicMock())

        session = _FakeSession()
        lead = _make_user(role="Lead_SA")
        sa_one = _make_user(role="SA", name="SA Satu")
        sa_two = _make_user(role="SA", name="SA Dua")
        session.add_project(_make_project(status_value="Pending Assignment"))
        session.add_user(lead)
        session.add_user(sa_one)
        session.add_user(sa_two)

        _override_db(session)
        _override_current_user(lead)
        client = TestClient(app)

        # assign -> seed 4 template
        resp = client.post(
            f"/api/v1/projects/{PROJECT_ID}/assign",
            json={"sa_id": str(sa_one.id)},
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/subtasks")
        items = resp.json()["data"]["items"]
        titles = sorted(s["title"] for s in items)
        assert titles == sorted(["Requirement", "BoQ", "PropTek", "HLD"])
        assert len(items) == 4

        # keempat subtask hasil seeding ditugaskan ke SA proyek (bukan None)
        assert all(s["assigned_sa"] == str(sa_one.id) for s in items)

        # re-assign -> tetap 4 (idempoten)
        resp = client.post(
            f"/api/v1/projects/{PROJECT_ID}/reassign",
            json={"sa_id": str(sa_two.id)},
        )
        assert resp.status_code == status.HTTP_200_OK

        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/subtasks")
        assert len(resp.json()["data"]["items"]) == 4


# =============================================================================
# (c) Authz: 401 tanpa token, 403 SA non-owner
# =============================================================================


class TestSubtaskAuthz:
    def test_create_unauthenticated_401(self):
        session = _FakeSession()
        session.add_project(_make_project())
        _override_db(session)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/projects/{PROJECT_ID}/subtasks",
            json={"title": "Requirement"},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_status_unauthenticated_401(self):
        session = _FakeSession()
        _override_db(session)
        client = TestClient(app)
        resp = client.patch(
            "/api/v1/projects/subtasks/SUB-20250101-AAAAAA/status",
            json={"status": "done"},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_owner_sa_cannot_update_status_403(self):
        session = _FakeSession()
        owner = _make_user(role="SA", name="Owner")
        other = _make_user(role="SA", name="Lain")
        session.add_project(_make_project(assigned_sa=owner.id))
        session.add_user(owner)
        session.add_user(other)

        subtask = Subtask(
            id_subtask="SUB-20250101-OWNED1",
            id_project=PROJECT_ID,
            title="Requirement",
            status="open",
        )
        subtask.assigned_sa = owner.id
        subtask.created_at = datetime.now(timezone.utc)
        subtask.updated_at = datetime.now(timezone.utc)
        session.subtasks[subtask.id_subtask] = subtask

        _override_db(session)
        _override_current_user(other)  # SA bukan owner
        client = TestClient(app)

        resp = client.patch(
            f"/api/v1/projects/subtasks/{subtask.id_subtask}/status",
            json={"status": "done"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# (d) Link activity log id_subtask memajukan subtask open -> in_progress
#     (ADR 0008): aktivitas pertama memulai subtask, idempoten setelahnya,
#     tidak pernah ke done maupun mundur, dan menolak subtask lintas-proyek.
# =============================================================================


def _make_subtask(
    id_subtask: str,
    id_project: str = PROJECT_ID,
    status_value: str = "open",
    assigned_sa=None,
) -> Subtask:
    subtask = Subtask(
        id_subtask=id_subtask,
        id_project=id_project,
        title="Requirement",
        status=status_value,
    )
    subtask.assigned_sa = assigned_sa
    subtask.created_at = datetime.now(timezone.utc)
    subtask.updated_at = datetime.now(timezone.utc)
    return subtask


def _post_activity_log(client, id_subtask: str, id_project: str = PROJECT_ID):
    return client.post(
        "/api/v1/activity-logs",
        json={
            "work_type": "Project",
            "id_project": id_project,
            "project_phase": "Pre-Implementation",
            "subtask_category": "Assessment",
            "id_subtask": id_subtask,
            "duration_hours": 1.0,
            "raw_notes": "Diskusi requirement awal.",
        },
    )


class TestActivityLogSubtaskLink:
    @patch(
        "app.services.activity_logger.ActivityLogger.polish_notes",
        new_callable=AsyncMock,
    )
    def test_first_activity_advances_open_subtask_to_in_progress(self, mock_polish):
        mock_polish.return_value = None  # hindari LLM; entry needs_repolish

        session = _FakeSession()
        sa = _make_user(role="SA")
        session.add_project(_make_project(assigned_sa=sa.id, status_value="Assigned"))
        session.add_user(sa)

        subtask = _make_subtask("SUB-20250101-LINK01", status_value="open", assigned_sa=sa.id)
        session.subtasks[subtask.id_subtask] = subtask

        _override_db(session)
        _override_current_user(sa)
        client = TestClient(app)

        resp = _post_activity_log(client, subtask.id_subtask)
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["data"]["id_subtask"] == subtask.id_subtask

        # Aktivitas pertama memulai subtask: open -> in_progress (ADR 0008).
        assert session.subtasks[subtask.id_subtask].status == "in_progress"

    @patch(
        "app.services.activity_logger.ActivityLogger.polish_notes",
        new_callable=AsyncMock,
    )
    def test_activity_on_in_progress_subtask_leaves_status_unchanged(self, mock_polish):
        mock_polish.return_value = None

        session = _FakeSession()
        sa = _make_user(role="SA")
        session.add_project(_make_project(assigned_sa=sa.id, status_value="Assigned"))
        session.add_user(sa)

        subtask = _make_subtask(
            "SUB-20250101-LINK02", status_value="in_progress", assigned_sa=sa.id
        )
        session.subtasks[subtask.id_subtask] = subtask

        _override_db(session)
        _override_current_user(sa)
        client = TestClient(app)

        resp = _post_activity_log(client, subtask.id_subtask)
        assert resp.status_code == status.HTTP_201_CREATED

        # Idempoten: sudah in_progress -> tidak berubah.
        assert session.subtasks[subtask.id_subtask].status == "in_progress"

    @patch(
        "app.services.activity_logger.ActivityLogger.polish_notes",
        new_callable=AsyncMock,
    )
    def test_activity_never_advances_subtask_to_done_and_never_moves_back(self, mock_polish):
        mock_polish.return_value = None

        session = _FakeSession()
        sa = _make_user(role="SA")
        session.add_project(_make_project(assigned_sa=sa.id, status_value="Assigned"))
        session.add_user(sa)

        subtask = _make_subtask("SUB-20250101-LINK03", status_value="done", assigned_sa=sa.id)
        session.subtasks[subtask.id_subtask] = subtask

        _override_db(session)
        _override_current_user(sa)
        client = TestClient(app)

        resp = _post_activity_log(client, subtask.id_subtask)
        assert resp.status_code == status.HTTP_201_CREATED

        # Aktivitas tidak pernah menutup (done tetap) maupun memundurkan status.
        assert session.subtasks[subtask.id_subtask].status == "done"

    @patch(
        "app.services.activity_logger.ActivityLogger.polish_notes",
        new_callable=AsyncMock,
    )
    def test_id_subtask_from_other_project_is_rejected(self, mock_polish):
        mock_polish.return_value = None

        session = _FakeSession()
        sa = _make_user(role="SA")
        session.add_project(_make_project(assigned_sa=sa.id, status_value="Assigned"))
        session.add_user(sa)

        # Subtask milik proyek LAIN daripada id_project pada log.
        subtask = _make_subtask(
            "SUB-20250101-OTHER1",
            id_project="PRJ-20250101-OTHER9",
            status_value="open",
            assigned_sa=sa.id,
        )
        session.subtasks[subtask.id_subtask] = subtask

        _override_db(session)
        _override_current_user(sa)
        client = TestClient(app)

        resp = _post_activity_log(client, subtask.id_subtask, id_project=PROJECT_ID)
        # id_subtask lintas-proyek ditolak -> ValueError dipetakan ke 422.
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Status subtask proyek lain tidak tersentuh.
        assert session.subtasks[subtask.id_subtask].status == "open"
