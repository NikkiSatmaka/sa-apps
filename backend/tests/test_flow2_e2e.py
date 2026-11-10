"""
Integration test end-to-end Flow 2 (Dokumen, DQ Number & Gating) — Fase 2A / T5.

Tiket ini mengikat perilaku gabungan T2 (start timer), T3 (scheduler /
`process_sla_actions`) dan T4 (`doc_ready` + akses Solutions) sebagai SATU alur,
bukan sebagai potongan terisolasi seperti test unit masing-masing. Spec Flow 2
punya dua cabang:

- **Cabang ">5 hari" (DQ belum diinput):** assign → SLA timer start → di H+3
  reminder ke Sales, di H+5 eskalasi ke manager + auto-lock folder Solutions.
  Setelah lock, saat Sales menginput DQ → timer stop + auto-unlock.
- **Cabang "<5 hari" (dokumen Reviewed):** DQ sudah terisi, dokumen Solutions
  berpindah ke `Reviewed` → `doc_ready` ter-emit ke Sales + akses Drive Solutions
  dibuka; Sales melihat dokumen via `GET /projects/{id}/documents/solutions`.

Waktu disimulasikan dengan **backdate `started_at`** pada row `SLATracking`
(service seam) — bukan `sleep` nyata — sehingga `process_sla_actions()` melihat
proyek seolah sudah berjalan H+3 / H+5. Side-effect eksternal (Google Drive,
notifikasi) di-mock; yang diikat adalah urutan transisi dan trigger, bukan
integrasi GDrive nyata.

Tidak membutuhkan Postgres live: `SLATimer` asli dijalankan di atas fake
AsyncSession in-memory yang mensimulasikan tabel `sla_tracking` + lookup
`Project`/`User`, dan cabang "<5 hari" dijalankan lewat TestClient dengan DB
session di-override.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.sla_tracking import SLATracking
from app.services.notification_service import NotificationEventType
from app.services.sla_timer import (
    SLA_RED_THRESHOLD,
    SLA_YELLOW_THRESHOLD,
    SLAStatus,
    SLATimer,
)

PROJECT_ID = "PRJ-20260101-FLOW02"


# =============================================================================
# Helpers
# =============================================================================


def _make_user(role: str, user_id: uuid.UUID | None = None, email: str | None = None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = role
    user.email = email or f"{role.lower()}@company.com"
    user.name = f"Test {role}"
    return user


def _make_project(
    *,
    sales_pic: uuid.UUID,
    gdrive_solutions_folder_id: str | None = "gdrive_solutions_123",
    dq_number: str | None = None,
):
    project = MagicMock()
    project.id_project = PROJECT_ID
    project.project_name = "Proyek Flow 2"
    project.customer_name = "PT Customer Flow"
    project.sales_pic = sales_pic
    # Master folder selalu ada saat Solutions ada (proxy "sudah ter-provision").
    project.gdrive_folder_id = "gdrive_master_123" if gdrive_solutions_folder_id else None
    project.gdrive_solutions_folder_id = gdrive_solutions_folder_id
    project.dq_number = dq_number
    return project


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_all_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


class _FakeFlow2Session:
    """
    Fake AsyncSession yang menjalankan `SLATimer` asli end-to-end.

    Menyimpan satu row `SLATracking` di memori (untuk start/stop/idempotency
    nyata) dan mengembalikan `Project`/`User` lookup sesuai urutan query yang
    dilakukan service. Query SLATracking dikenali lewat `SLATracking` di dalam
    row-store; query Project/User dilayani dari daftar jawaban terurut.

    `process_sla_actions()` memakai `AsyncSessionLocal()` sebagai context
    manager, jadi instance ini juga berperan sebagai async context manager yang
    mengembalikan dirinya sendiri.
    """

    def __init__(self, project, managers, sales_user):
        self._project = project
        self._managers = managers
        self._sales_user = sales_user
        self.sla_rows: dict[str, SLATracking] = {}
        self._pending: list = []
        self.added: list = []

    # --- async context manager (dipakai process_sla_actions) ---
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    # --- query routing ---
    async def execute(self, statement):
        entity = self._entity_of(statement)
        name = getattr(entity, "__name__", "")

        if name == "SLATracking":
            # Query bisa berupa list (stopped_at IS NULL) atau by project_id.
            if self._is_list_query(statement):
                active = [r for r in self.sla_rows.values() if r.stopped_at is None]
                return _scalars_all_result(active)
            return _scalar_result(next(iter(self.sla_rows.values()), None))

        if name == "Project":
            return _scalar_result(self._project)

        if name == "User":
            if self._is_list_query(statement):
                return _scalars_all_result(self._managers)
            return _scalar_result(self._sales_user)

        return _scalar_result(None)

    @staticmethod
    def _entity_of(statement):
        # SQLAlchemy 2.0 Select: ambil entity kolom pertama.
        try:
            return statement.column_descriptions[0]["entity"]
        except Exception:
            return None

    @staticmethod
    def _is_list_query(statement):
        # Query by project_id / id memakai WHERE pada kolom unik → single.
        # Query manager (role IN ...) dan active SLA (stopped_at IS NULL) → list.
        text = str(statement).lower()
        return "in (" in text or "is null" in text

    def add(self, obj):
        self._pending.append(obj)
        self.added.append(obj)

    async def commit(self):
        for obj in self._pending:
            if isinstance(obj, SLATracking):
                self.sla_rows[obj.project_id] = obj
        self._pending.clear()

    async def refresh(self, _obj):
        return None

    async def close(self):
        return None

    # --- test helper ---
    def added_of_event(self, event_type: str) -> list:
        return [o for o in self.added if getattr(o, "event_type", None) == event_type]


# =============================================================================
# Cabang ">5 hari": reminder H+3 → eskalasi H+5 + auto-lock → stop+unlock saat DQ
# =============================================================================


class TestCabangLebih5Hari:
    """
    Urutan penuh cabang DQ belum diinput: start → H+3 reminder → H+5 eskalasi +
    lock → DQ input → stop + unlock.
    """

    def _backdate_started_at(self, session, days: int):
        """Geser started_at mundur `days` hari (service seam simulasi waktu)."""
        row = session.sla_rows[PROJECT_ID]
        row.started_at = datetime.now(timezone.utc) - timedelta(days=days)
        row.current_status = SLAStatus.GREEN.value

    @pytest.mark.asyncio
    async def test_alur_penuh_reminder_eskalasi_lock_unlock(self):
        timer = SLATimer()
        sales = _make_user("Sales", email="sales@company.com")
        manager = _make_user("Lead_SA", email="lead@company.com")
        project = _make_project(sales_pic=sales.id)
        session = _FakeFlow2Session(project=project, managers=[manager], sales_user=sales)

        # --- T2: assign memulai SLA timer di H+0 ---
        assigned_at = datetime.now(timezone.utc)
        await timer.start_timer(project_id=PROJECT_ID, assigned_at=assigned_at, db=session)
        assert PROJECT_ID in session.sla_rows
        assert session.sla_rows[PROJECT_ID].current_status == SLAStatus.GREEN.value

        # --- H+3: process → reminder ke Sales, status yellow, belum lock ---
        self._backdate_started_at(session, SLA_YELLOW_THRESHOLD)
        with patch("app.services.sla_timer.AsyncSessionLocal", return_value=session):
            stats_h3 = await timer.process_sla_actions()

        assert stats_h3["reminders_sent"] == 1
        assert stats_h3["escalations_sent"] == 0
        assert stats_h3["locks_performed"] == 0
        reminders = session.added_of_event("sla_reminder")
        assert len(reminders) == 1
        assert reminders[0].recipient_user_id == sales.id
        row = session.sla_rows[PROJECT_ID]
        assert row.current_status == SLAStatus.YELLOW.value
        assert row.is_locked is False

        # --- H+5: process → eskalasi ke manager + auto-lock folder Solutions ---
        self._backdate_started_at(session, SLA_RED_THRESHOLD)
        with (
            patch("app.services.sla_timer.AsyncSessionLocal", return_value=session),
            patch(
                "app.services.sla_timer.folder_provisioner.lock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_lock,
        ):
            stats_h5 = await timer.process_sla_actions()

        assert stats_h5["escalations_sent"] == 1
        assert stats_h5["locks_performed"] == 1
        # Eskalasi ke manager (Lead_SA/Admin) + notifikasi lock ke Sales.
        escalations = session.added_of_event("sla_escalation")
        recipients = {n.recipient_user_id for n in escalations}
        assert manager.id in recipients
        assert sales.id in recipients
        # Lock folder Solutions dipanggil dengan folder + email Sales yang benar.
        mock_lock.assert_awaited_once_with(
            solutions_folder_id=project.gdrive_solutions_folder_id,
            sales_email=sales.email,
        )
        row = session.sla_rows[PROJECT_ID]
        assert row.current_status == SLAStatus.RED.value
        assert row.is_locked is True

        # --- DQ diinput setelah lock → stop timer + auto-unlock ---
        with patch(
            "app.services.sla_timer.folder_provisioner.unlock_solutions_folder",
            new_callable=AsyncMock,
        ) as mock_unlock:
            stopped = await timer.stop_timer(project_id=PROJECT_ID, db=session)

        mock_unlock.assert_awaited_once_with(
            solutions_folder_id=project.gdrive_solutions_folder_id,
            sales_email=sales.email,
        )
        assert stopped.stopped_at is not None
        assert stopped.is_locked is False
        assert stopped.unlocked_at is not None

        # --- process ulang setelah stop tidak melakukan aksi lagi ---
        with patch("app.services.sla_timer.AsyncSessionLocal", return_value=session):
            stats_after_stop = await timer.process_sla_actions()
        assert stats_after_stop["total_checked"] == 0

    @pytest.mark.asyncio
    async def test_h5_tanpa_gdrive_folder_skip_lock_graceful(self):
        """
        Auto-lock di-skip graceful bila `gdrive_folder_id` kosong (catatan
        lintas-spec T3): eskalasi tetap terkirim, tapi tidak ada lock.
        """
        timer = SLATimer()
        sales = _make_user("Sales")
        manager = _make_user("Lead_SA")
        project = _make_project(sales_pic=sales.id, gdrive_solutions_folder_id=None)
        session = _FakeFlow2Session(project=project, managers=[manager], sales_user=sales)

        await timer.start_timer(
            project_id=PROJECT_ID,
            assigned_at=datetime.now(timezone.utc),
            db=session,
        )
        self._backdate_started_at(session, SLA_RED_THRESHOLD)

        with (
            patch("app.services.sla_timer.AsyncSessionLocal", return_value=session),
            patch(
                "app.services.sla_timer.folder_provisioner.lock_solutions_folder",
                new_callable=AsyncMock,
            ) as mock_lock,
        ):
            stats = await timer.process_sla_actions()

        # Eskalasi tetap dikirim, tapi lock tidak dilakukan (folder kosong).
        assert stats["escalations_sent"] == 1
        assert stats["locks_performed"] == 0
        mock_lock.assert_not_awaited()
        assert session.sla_rows[PROJECT_ID].is_locked is False


# =============================================================================
# Cabang "<5 hari": dokumen Reviewed → doc_ready + akses Solutions via API
# =============================================================================


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


def _make_document(status: str = "Draft"):
    doc = MagicMock()
    doc.id_doc = "DOC-20260101-SOL001"
    doc.id_project = PROJECT_ID
    doc.doc_type = "PropTek"
    doc.status = status
    doc.folder_type = "Solutions"
    doc.gdrive_link = "https://drive.google.com/solutions-doc"
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


class TestCabangKurang5Hari:
    """
    DQ sudah terisi: dokumen Solutions → Reviewed memicu doc_ready + buka akses,
    lalu Sales bisa melihat dokumen via API gating.
    """

    def test_reviewed_emit_doc_ready_lalu_sales_lihat_dokumen(self):
        sales = _make_user("Sales", email="sales@company.com")
        sa = _make_user("SA")
        document = _make_document(status="Draft")
        project = _make_project(sales_pic=sales.id, dq_number="DQ-99887")

        client = TestClient(app)

        # --- 1. SA menandai dokumen Reviewed → doc_ready + buka akses Solutions ---
        review_session = AsyncMock()
        # execute: 1) lookup dokumen, 2) lookup project (handle_doc_ready),
        # 3) lookup sales user (handle_doc_ready).
        review_session.execute.side_effect = [
            _scalar_result(document),
            _scalar_result(project),
            _scalar_result(sales),
        ]
        review_session.commit = AsyncMock()
        review_session.refresh = AsyncMock()

        _override_current_user(sa)
        _override_db(review_session)

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
            review_resp = client.patch(
                f"/api/v1/documents/{document.id_doc}/status",
                json={"new_status": "Reviewed"},
            )

        assert review_resp.status_code == 200
        assert review_resp.json()["data"]["status"] == "Reviewed"
        # doc_ready ter-emit ke Sales (sales_pic).
        mock_notify.assert_awaited_once()
        event = mock_notify.call_args[0][0]
        assert event.event_type == NotificationEventType.DOC_READY
        assert event.recipient_user_id == sales.id
        # Akses Drive Solutions dibuka untuk Sales.
        mock_unlock.assert_awaited_once_with(
            solutions_folder_id=project.gdrive_solutions_folder_id,
            sales_email=sales.email,
        )

        # --- 2. Sales mengakses dokumen Solutions via API (DQ ada → terlihat) ---
        document.status = "Reviewed"
        list_session = AsyncMock()
        # execute: 1) lookup project, 2) query dokumen Solutions.
        list_session.execute.side_effect = [
            _scalar_result(project),
            _scalars_all_result([document]),
        ]
        _override_current_user(sales)
        _override_db(list_session)

        list_resp = client.get(f"/api/v1/projects/{PROJECT_ID}/documents/solutions")

        assert list_resp.status_code == 200
        body = list_resp.json()["data"]
        assert body["total"] == 1
        assert body["dq_number"] == "DQ-99887"
        assert body["documents"][0]["id_doc"] == document.id_doc
        assert body["documents"][0]["status"] == "Reviewed"

    def test_sales_tanpa_dq_tidak_bisa_akses_solutions(self):
        """Gating: tanpa DQ Number, Sales tidak melihat dokumen Solutions."""
        sales = _make_user("Sales")
        project = _make_project(sales_pic=sales.id, dq_number=None)

        session = AsyncMock()
        session.execute.side_effect = [_scalar_result(project)]
        _override_current_user(sales)
        _override_db(session)

        client = TestClient(app)
        resp = client.get(f"/api/v1/projects/{PROJECT_ID}/documents/solutions")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] == 0
        assert body["documents"] == []
        assert body["dq_required"] is True
