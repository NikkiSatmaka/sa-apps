"""Consumer-visible persistence for best-effort integration operations."""

import asyncio

import pytest

from app.services.notification_service import notification_service
from tests.integration.conftest import patch_session_factory

from tests.integration.support_assignment import (
    ASSIGN,
    REASSIGN,
    bangun_dunia,
    jalankan_provisioning,
    rekam_background,
)


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def test_drive_permission_failure_is_visible_without_rolling_back_reassignment(
    dunia, api, fake_drive, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Core Banking", customer_name="PT Bank")
    background = rekam_background(monkeypatch)

    assigned = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert assigned.status_code == 200, assigned.text
    await jalankan_provisioning(dunia.db, background[0])

    fake_drive.fail_next("reassign_sa_access", pesan="Google Drive is temporarily unavailable")
    reassigned = await api.client.post(
        REASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )
    assert reassigned.status_code == 200, reassigned.text

    detail = await api.client.get(f"/api/v1/projects/{project.id_project}", headers=dunia.h["lead"])
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["assigned_sa"]["id"] == str(dunia.sa2.id)

    operation = next(
        item
        for item in data["integration_operations"]
        if item["operation_type"] == "drive_permission"
        and item["action"] == "reassign_sa_access"
    )
    assert operation["status"] == "failed"
    assert operation["attempts"][-1]["status"] == "failed"
    assert operation["started_at"]
    assert operation["finished_at"]
    assert operation["outcome"]
    assert "Google Drive" in operation["actionable_error"]
    assert operation["retryable"] is True

    retry_url = (
        f"/api/v1/projects/{project.id_project}/integration-operations/{operation['id']}/retry"
    )
    denied_retry = await api.client.post(retry_url, headers=dunia.h["sales_lain"])
    assert denied_retry.status_code == 403

    retried = await api.client.post(retry_url, headers=dunia.h["lead"])
    assert retried.status_code == 200, retried.text
    retry_operation = retried.json()["data"]
    assert retry_operation["status"] == "succeeded"
    assert len(retry_operation["attempts"]) == 2
    assert [item["status"] for item in retry_operation["attempts"]] == [
        "failed",
        "succeeded",
    ]


async def test_calendar_sync_failure_is_persisted_and_reported(
    dunia, api, db_session, fake_calendar
):
    from app.api.auth import CALENDAR_SESSION_COOKIE
    from app.models.integration_operation import IntegrationOperation
    from app.services.auth_service import auth_service
    from sqlalchemy import select

    session_cookie = await auth_service.create_calendar_session(
        db_session,
        user_id=dunia.sa.id,
        access_token="calendar-test-token",
    )
    await db_session.commit()
    api.client.cookies.set(CALENDAR_SESSION_COOKIE, session_cookie)
    fake_calendar.fail_next("api", "Google Calendar is unavailable")

    response = await api.client.post(
        "/api/v1/calendar/sync",
        headers=dunia.h["sa"],
    )

    assert response.status_code == 502
    operation = response.json()["data"]["integration_operation"]
    assert operation["operation_type"] == "calendar"
    assert operation["action"] == "sync_calendar"
    assert operation["status"] == "failed"
    assert operation["attempts"][-1]["status"] == "failed"
    assert operation["started_at"] and operation["finished_at"]
    assert operation["outcome"]
    assert "reconnect" in operation["actionable_error"].lower()
    persisted = await db_session.scalar(
        select(IntegrationOperation).where(IntegrationOperation.id == operation["id"])
    )
    assert persisted is not None


async def test_calendar_mapping_operation_is_visible_with_project_work(
    dunia, api, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Calendar project")
    background = rekam_background(monkeypatch)
    assigned = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert assigned.status_code == 200, assigned.text
    assert background

    mapped = await api.client.post(
        "/api/v1/calendar/map",
        json={
            "gcal_event_id": "evt-visible-outcome",
            "work_type": "Project",
            "project_id": project.id_project,
            "project_phase": "Pre-Implementation",
            "subtask_category": "Customer Meeting",
            "event_title": "Customer workshop",
        },
        headers=dunia.h["sa"],
    )
    assert mapped.status_code == 201, mapped.text
    assert mapped.json()["data"]["integration_operation"]["status"] == "succeeded"

    detail = await api.client.get(
        f"/api/v1/projects/{project.id_project}",
        headers=dunia.h["sa"],
    )
    assert detail.status_code == 200, detail.text
    operation = next(
        item
        for item in detail.json()["data"]["integration_operations"]
        if item["action"] == "map_event_to_project"
    )
    assert operation["status"] == "succeeded"
    assert operation["attempts"][-1]["status"] == "succeeded"
    assert operation["outcome"]


async def test_assignment_email_failure_is_visible_without_blocking_assignment(
    dunia, api, fake_gmail, monkeypatch
):
    fake_gmail.fail_next()
    fake_gmail.tahan_email()
    project = await dunia.buat_proyek(project_name="Email outcome")
    rekam_background(monkeypatch)

    assigned = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert assigned.status_code == 200, assigned.text
    fake_gmail.lepaskan_email()
    await fake_gmail.tunggu_percobaan(1)
    await asyncio.gather(*notification_service._background_tasks)

    detail = await api.client.get(
        f"/api/v1/projects/{project.id_project}",
        headers=dunia.h["lead"],
    )
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["assigned_sa"]["id"] == str(dunia.sa.id)
    operation = next(
        item
        for item in data["integration_operations"]
        if item["operation_type"] == "email_delivery"
        and item["action"] == "send_assignment_email"
    )
    assert operation["status"] == "failed"
    assert len(operation["attempts"]) == 1
    assert operation["attempts"][0]["status"] == "failed"
    assert operation["retryable"] is False
    assert operation["actionable_error"]


async def test_sla_lock_failure_is_visible_and_safe_retry_updates_sla_state(
    dunia, api, db_session, fake_drive, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.sla_tracking import SLATracking

    project = await dunia.buat_proyek(project_name="SLA lock outcome")
    background = rekam_background(monkeypatch)
    assigned = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert assigned.status_code == 200, assigned.text
    await jalankan_provisioning(dunia.db, background[0])

    sla = await db_session.scalar(
        select(SLATracking).where(SLATracking.project_id == project.id_project)
    )
    assert sla is not None
    sla.started_at = datetime.now(timezone.utc) - timedelta(days=5)
    sla.escalated_at = datetime.now(timezone.utc)
    await db_session.commit()

    fake_drive.fail_next("lock_solutions_folder", pesan="Drive lock unavailable")
    processed = await api.client.post("/api/v1/sla/process", headers=dunia.h["lead"])
    assert processed.status_code == 200, processed.text

    detail = await api.client.get(
        f"/api/v1/projects/{project.id_project}",
        headers=dunia.h["lead"],
    )
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["status"] == "Assigned"
    operation = next(
        item
        for item in data["integration_operations"]
        if item["operation_type"] == "sla" and item["action"] == "solutions_lock"
    )
    assert operation["status"] == "failed"
    assert operation["attempts"][-1]["status"] == "failed"
    assert operation["retryable"] is True
    assert "Drive lock unavailable" in operation["actionable_error"]
    assert sla.is_locked is False

    retried = await api.client.post(
        f"/api/v1/projects/{project.id_project}/integration-operations/{operation['id']}/retry",
        headers=dunia.h["lead"],
    )
    assert retried.status_code == 200, retried.text
    retry_operation = retried.json()["data"]
    assert retry_operation["status"] == "succeeded"
    assert [attempt["status"] for attempt in retry_operation["attempts"]] == [
        "failed",
        "succeeded",
    ]
    await db_session.refresh(sla)
    assert sla.is_locked is True
    assert sla.locked_at is not None
