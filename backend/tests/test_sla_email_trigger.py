"""
Test email sebagai trigger untuk reminder H+3 dan eskalasi H+5 SLA (Fase 2A.5).

Spec §4.C: email di semua flow. In-app log tetap ditulis SLATimer dalam transaksinya;
email dipicu lewat notification_service.dispatch_email_for_user. Semua I/O di-mock.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notification_service import (
    NotificationEventType,
    NotificationService,
)
from app.services.sla_timer import SLATimer

# --- dispatch_email_for_user -------------------------------------------------


def _session_returning(user):
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session = AsyncMock()
    session.execute.return_value = result
    return AsyncMock(
        __aenter__=AsyncMock(return_value=session),
        __aexit__=AsyncMock(return_value=False),
    )


class TestDispatchEmailForUser:
    @pytest.mark.asyncio
    async def test_noop_tanpa_gmail(self):
        service = NotificationService()
        service._send_email_with_retry = AsyncMock()
        with (
            patch.object(service, "_is_gmail_configured", return_value=False),
            patch("app.services.notification_service.AsyncSessionLocal") as session_cls,
        ):
            await service.dispatch_email_for_user(
                NotificationEventType.SLA_REMINDER, uuid.uuid4(), "PRJ-1", {"a": 1}
            )
        session_cls.assert_not_called()
        service._send_email_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_kirim_email_bila_gmail_aktif(self):
        service = NotificationService()
        service._send_email_with_retry = AsyncMock()
        user = MagicMock(id=uuid.uuid4(), email="sales@company.com")
        with (
            patch.object(service, "_is_gmail_configured", return_value=True),
            patch(
                "app.services.notification_service.AsyncSessionLocal",
                return_value=_session_returning(user),
            ),
        ):
            await service.dispatch_email_for_user(
                NotificationEventType.SLA_ESCALATION, user.id, "PRJ-1", {"m": "x"}
            )
            await asyncio.gather(*service._background_tasks)

        service._send_email_with_retry.assert_awaited_once()
        event = service._send_email_with_retry.call_args[0][0]
        assert event.event_type == NotificationEventType.SLA_ESCALATION
        assert event.recipient_email == "sales@company.com"
        assert event.reference_id == "PRJ-1"
        assert event.metadata == {"m": "x"}

    @pytest.mark.asyncio
    async def test_user_tidak_ada_dilewati(self):
        service = NotificationService()
        service._send_email_with_retry = AsyncMock()
        with (
            patch.object(service, "_is_gmail_configured", return_value=True),
            patch(
                "app.services.notification_service.AsyncSessionLocal",
                return_value=_session_returning(None),
            ),
        ):
            await service.dispatch_email_for_user(
                NotificationEventType.SLA_REMINDER, uuid.uuid4(), "PRJ-1", None
            )
        service._send_email_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_tidak_raise(self):
        service = NotificationService()
        with (
            patch.object(service, "_is_gmail_configured", return_value=True),
            patch(
                "app.services.notification_service.AsyncSessionLocal",
                side_effect=RuntimeError("db down"),
            ),
        ):
            await service.dispatch_email_for_user(
                NotificationEventType.SLA_REMINDER, uuid.uuid4(), "PRJ-1", None
            )  # tidak boleh raise


# --- SLATimer memicu email ---------------------------------------------------


def _project():
    p = MagicMock()
    p.id_project = "PRJ-001"
    p.project_name = "Test Project"
    p.customer_name = "Customer A"
    p.sales_pic = uuid.uuid4()
    return p


class TestSLATimerEmail:
    @pytest.mark.asyncio
    async def test_reminder_memicu_email_ke_sales(self):
        project = _project()
        db = AsyncMock()
        db.add = MagicMock()
        with patch(
            "app.services.sla_timer.notification_service.dispatch_email_for_user",
            new_callable=AsyncMock,
        ) as dispatch:
            await SLATimer()._send_sla_reminder(project=project, days_elapsed=3, db=db)

        db.add.assert_called_once()  # in-app log tetap ditulis
        dispatch.assert_awaited_once()
        args = dispatch.call_args[0]
        assert args[0] == NotificationEventType.SLA_REMINDER
        assert args[1] == project.sales_pic
        assert args[2] == "PRJ-001"
        assert "belum diinput" in args[3]["message"]

    @pytest.mark.asyncio
    async def test_eskalasi_memicu_email_ke_manager_dan_sales(self):
        project = _project()
        managers = [MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())]
        result = MagicMock()
        result.scalars.return_value.all.return_value = managers
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.return_value = result

        with patch(
            "app.services.sla_timer.notification_service.dispatch_email_for_user",
            new_callable=AsyncMock,
        ) as dispatch:
            await SLATimer()._send_sla_escalation(project=project, days_elapsed=5, db=db)

        assert db.add.call_count == 3  # 2 manager + 1 sales (in-app)
        recipients = [c[0][1] for c in dispatch.call_args_list]
        assert recipients == [managers[0].id, managers[1].id, project.sales_pic]
        assert all(c[0][0] == NotificationEventType.SLA_ESCALATION for c in dispatch.call_args_list)
