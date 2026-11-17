"""
Integrasi assignment, reassign, seeding subtask, timer SLA, dan provisioning folder terhadap
Postgres nyata dengan Drive palsu (tiket B5 #58, spec #49).

Alur utama `assign → timer SLA → provisioning` diuji lewat endpoint nyata. Background task
provisioning ditangkap lalu `_trigger_folder_provisioner` ASLI dijalankan setelah request selesai
(harness satu koneksi: sesi request yang masih terbuka me-rollback hasil task; pola
`test_fake_boundary_contoh.py`).
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import Customer, Document, IntegrationOperation, Subtask
from app.services.folder_provisioner import folder_provisioner
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_log, bangun_subtask
from tests.integration.support_assignment import (
    ASSIGN,
    REASSIGN,
    REPROVISION,
    ambil_proyek,
    ambil_sla,
    bangun_dunia,
    daftar_notif,
    daftar_subtask,
    jalankan_provisioning,
    rekam_background,
)

JUDUL_DEFAULT = ["Requirement", "BoQ", "PropTek", "HLD"]


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


RETRY_OPERATION = "/api/v1/projects/{}/integration-operations/{}/retry"


async def test_retry_sla_operation_rejects_missing_tracker(dunia, api):
    project = await dunia.buat_proyek(
        status="Assigned",
        gdrive_solutions_folder_id="solutions-folder",
    )
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="sla",
        action="solutions_lock",
        status="failed",
        retryable=True,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    persisted_operation = (
        await dunia.db.execute(
            select(IntegrationOperation)
            .where(IntegrationOperation.id == operation.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert response.status_code == 409
    assert response.json()["message"] == "The project's SLA tracker is no longer available."
    assert (persisted_operation.status, persisted_operation.attempts) == ("failed", [])


async def test_retry_sla_lock_rejects_stale_dq_state(dunia, api):
    project = await dunia.buat_proyek(
        status="Assigned",
        dq_number="DQ-TEST",
        gdrive_solutions_folder_id="solutions-folder",
    )
    await sla_timer.start_timer(project.id_project, datetime.now(timezone.utc), dunia.db)
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="sla",
        action="solutions_lock",
        status="failed",
        retryable=True,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    persisted_operation = (
        await dunia.db.execute(
            select(IntegrationOperation)
            .where(IntegrationOperation.id == operation.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert response.status_code == 409
    assert response.json()["message"] == (
        "The DQ state changed; the recorded SLA permission action is no longer current."
    )
    assert (persisted_operation.status, persisted_operation.attempts) == ("failed", [])


async def test_retry_sla_lock_rejects_missing_solutions_folder(dunia, api):
    project = await dunia.buat_proyek(status="Assigned")
    await sla_timer.start_timer(project.id_project, datetime.now(timezone.utc), dunia.db)
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="sla",
        action="solutions_lock",
        status="failed",
        retryable=True,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    persisted_operation = (
        await dunia.db.execute(
            select(IntegrationOperation)
            .where(IntegrationOperation.id == operation.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert response.status_code == 409
    assert response.json()["message"] == (
        "The project no longer has the required Solutions folder and Sales PIC."
    )
    assert (persisted_operation.status, persisted_operation.attempts) == ("failed", [])


async def test_retry_document_review_unlock_rejects_missing_document(dunia, api):
    project = await dunia.buat_proyek(
        status="Assigned",
        dq_number="DQ-TEST",
        gdrive_solutions_folder_id="solutions-folder",
    )
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="drive_permission",
        action="document_review_unlock",
        status="failed",
        retryable=True,
        context={
            "document_id": "DOC-MISSING",
            "folder_id": "solutions-folder",
            "sales_email": dunia.sales.email,
        },
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    persisted_operation = (
        await dunia.db.execute(
            select(IntegrationOperation)
            .where(IntegrationOperation.id == operation.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert response.status_code == 409
    assert response.json()["message"] == (
        "The project or reviewed document state changed; this Drive action is no longer current."
    )
    assert (persisted_operation.status, persisted_operation.attempts) == ("failed", [])


async def test_retry_document_review_unlock_restores_sales_and_product_access(
    dunia, api, fake_drive
):
    project = await dunia.buat_proyek(
        status="Assigned",
        dq_number="DQ-TEST",
        gdrive_solutions_folder_id="solutions-folder",
        product_pic=dunia.produk.id,
    )
    document = Document(
        id_doc="DOC-REVIEWED-RETRY",
        id_project=project.id_project,
        doc_type="BOQ",
        status="Reviewed",
        gdrive_link="https://drive.google.com/file/d/retry",
        folder_type="Solutions",
        created_by=dunia.sa.id,
    )
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="drive_permission",
        action="document_review_unlock",
        status="failed",
        retryable=True,
        context={
            "document_id": document.id_doc,
            "folder_id": "solutions-folder",
            "sales_email": dunia.sales.email,
        },
    )
    dunia.db.add_all([document, operation])
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    await dunia.db.refresh(operation)
    assert operation.status == "succeeded"
    assert fake_drive.peran("solutions-folder", dunia.sales.email) == "reader"
    assert fake_drive.peran("solutions-folder", dunia.produk.email) == "reader"
    [call] = fake_drive.panggilan_operasi("unlock_solutions_folder")
    assert call.argumen["product_email"] == dunia.produk.email


async def test_retry_sla_unlock_restores_product_access(dunia, api, fake_drive):
    project = await dunia.buat_proyek(
        status="Assigned",
        dq_number="DQ-TEST",
        gdrive_solutions_folder_id="solutions-folder",
        product_pic=dunia.produk.id,
    )
    await sla_timer.start_timer(project.id_project, datetime.now(timezone.utc), dunia.db)
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="sla",
        action="solutions_unlock",
        status="failed",
        retryable=True,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    await dunia.db.refresh(operation)
    assert operation.status == "succeeded"
    assert fake_drive.peran("solutions-folder", dunia.sales.email) == "reader"
    assert fake_drive.peran("solutions-folder", dunia.produk.email) == "reader"
    [call] = fake_drive.panggilan_operasi("unlock_solutions_folder")
    assert call.argumen["product_email"] == dunia.produk.email


async def test_retry_integration_operation_requires_existing_project(dunia, api):
    response = await api.client.post(
        RETRY_OPERATION.format("PRJ-MISSING", uuid.uuid4()),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Project not found."


async def test_retry_integration_operation_requires_existing_operation(dunia, api):
    project = await dunia.buat_proyek()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, uuid.uuid4()),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Integration operation not found."


async def test_retry_integration_operation_rejects_pending_operation(dunia, api):
    project = await dunia.buat_proyek()
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="drive_permission",
        action="reassign_sa_access",
        status="pending",
        retryable=True,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 409
    assert response.json()["message"] == "This operation cannot be retried safely."
    assert operation.status == "pending"

REPAIR_OPERATION = "/api/v1/projects/{}/integration-operations/{}/repair"


@pytest.mark.parametrize("role", ["lead", "admin"])
async def test_manual_email_repair_records_confirmation_without_replay(
    dunia, api, monkeypatch, role
):
    project = await dunia.buat_proyek()
    original_attempts = [
        {
            "attempt": 1,
            "status": "failed",
            "started_at": "2026-11-17T10:00:00+00:00",
            "finished_at": "2026-11-17T10:00:01+00:00",
            "outcome": "send_assignment_email failed.",
            "actionable_error": "Check the recipient and manually send the notification.",
        }
    ]
    operation = IntegrationOperation(
        project_id=project.id_project,
        actor_user_id=dunia.sa.id,
        operation_type="email_delivery",
        action="send_assignment_email",
        status="failed",
        attempts=original_attempts,
        outcome=original_attempts[0]["outcome"],
        actionable_error=original_attempts[0]["actionable_error"],
        retryable=False,
        context={"event_type": "assignment"},
    )
    dunia.db.add(operation)
    await dunia.db.flush()
    provider_called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("manual repair must not contact the provider")

    monkeypatch.setattr(
        "app.services.notification_service.notification_service.send_email",
        fail_if_called,
    )
    response = await api.client.post(
        REPAIR_OPERATION.format(project.id_project, operation.id),
        json={
            "recipient_checked_not_received": True,
            "manually_delivered_outside_app": True,
        },
        headers=dunia.h[role],
    )

    assert response.status_code == 200, response.text
    repaired = response.json()["data"]
    audit = repaired["context"]["manual_repair"]
    assert audit["actor_user_id"] == str(getattr(dunia, role).id)
    assert audit["repaired_at"]
    assert audit["recipient_checked_not_received"] is True
    assert audit["manually_delivered_outside_app"] is True
    assert repaired["status"] == "failed"
    assert repaired["outcome"] == original_attempts[0]["outcome"]
    assert repaired["actionable_error"] == original_attempts[0]["actionable_error"]
    assert repaired["attempts"] == original_attempts
    assert repaired["retryable"] is False
    assert provider_called is False
    await dunia.db.refresh(operation)
    assert operation.context["manual_repair"] == audit
    assert operation.status == "failed"
    assert operation.attempts == original_attempts


@pytest.mark.parametrize("role", ["sa", "sales"])
async def test_manual_email_repair_requires_privileged_user(dunia, api, role):
    project = await dunia.buat_proyek()
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="email_delivery",
        action="send_assignment_email",
        status="failed",
        attempts=[],
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        REPAIR_OPERATION.format(project.id_project, operation.id),
        json={
            "recipient_checked_not_received": True,
            "manually_delivered_outside_app": True,
        },
        headers=dunia.h[role],
    )

    assert response.status_code == 403
    assert operation.context.get("manual_repair") is None


@pytest.mark.parametrize(
    ("operation_type", "operation_status", "context", "payload", "expected_status"),
    [
        (
            "email_delivery",
            "pending",
            {},
            {
                "recipient_checked_not_received": True,
                "manually_delivered_outside_app": True,
            },
            409,
        ),
        (
            "email_delivery",
            "succeeded",
            {},
            {
                "recipient_checked_not_received": True,
                "manually_delivered_outside_app": True,
            },
            409,
        ),
        (
            "drive_permission",
            "failed",
            {},
            {
                "recipient_checked_not_received": True,
                "manually_delivered_outside_app": True,
            },
            409,
        ),
        (
            "email_delivery",
            "failed",
            {"manual_repair": {"actor_user_id": "prior"}},
            {
                "recipient_checked_not_received": True,
                "manually_delivered_outside_app": True,
            },
            409,
        ),
        ("email_delivery", "failed", {}, {"recipient_checked_not_received": True}, 422),
        (
            "email_delivery",
            "failed",
            {},
            {"recipient_checked_not_received": False, "manually_delivered_outside_app": True},
            422,
        ),
    ],
)
async def test_manual_email_repair_rejects_invalid_state_or_confirmation(
    dunia, api, operation_type, operation_status, context, payload, expected_status
):
    project = await dunia.buat_proyek()
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type=operation_type,
        action="send_assignment_email",
        status=operation_status,
        attempts=[],
        context=context,
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        REPAIR_OPERATION.format(project.id_project, operation.id),
        json=payload,
        headers=dunia.h["lead"],
    )

    assert response.status_code == expected_status
    assert operation.context == context


async def test_manual_email_repair_cannot_target_operation_from_another_project(dunia, api):
    requested_project = await dunia.buat_proyek()
    operation_project = await dunia.buat_proyek()
    operation = IntegrationOperation(
        project_id=operation_project.id_project,
        operation_type="email_delivery",
        action="send_assignment_email",
        status="failed",
        attempts=[],
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        REPAIR_OPERATION.format(requested_project.id_project, operation.id),
        json={
            "recipient_checked_not_received": True,
            "manually_delivered_outside_app": True,
        },
        headers=dunia.h["lead"],
    )

    assert response.status_code == 404
    assert operation.context.get("manual_repair") is None

async def test_retry_reassignment_rejects_changed_assignment(dunia, api):
    project = await dunia.buat_proyek(
        status="Assigned",
        assigned_sa=dunia.sa.id,
        gdrive_folder_id="drive-folder-current",
    )
    operation = IntegrationOperation(
        project_id=project.id_project,
        operation_type="drive_permission",
        action="reassign_sa_access",
        status="failed",
        retryable=True,
        context={
            "master_folder_id": "drive-folder-current",
            "old_sa_email": "old-sa@example.com",
            "new_sa_email": "different-sa@example.com",
        },
    )
    dunia.db.add(operation)
    await dunia.db.flush()

    response = await api.client.post(
        RETRY_OPERATION.format(project.id_project, operation.id),
        headers=dunia.h["lead"],
    )

    assert response.status_code == 409
    assert response.json()["message"] == (
        "The project assignment changed; reconcile permissions from the current assignment."
    )
    assert operation.status == "failed"


# ----------------------------------------------------------------------------- assign: alur penuh


async def test_assign_memulai_timer_seed_subtask_notifikasi_lalu_provisioning_sukses(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek(project_name="Core Banking", customer_name="PT Bank")
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(
        ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["assigned_sa_name"] == dunia.sa.name
    assert data["notification_sent"] is True and data["folder_provisioning_triggered"] is True
    assert data["project"]["status"] == "Assigned"
    assert data["project"]["folder_provisioning_status"] == "pending"

    # Status & penugasan tersimpan.
    p = await ambil_proyek(dunia.db, pid)
    assert (p.status, p.assigned_sa, p.folder_provisioning_status) == (
        "Assigned",
        dunia.sa.id,
        "pending",
    )
    assert p.assigned_at is not None
    # Timer SLA aktif sejak H+0, memakai waktu assignment.
    sla = await ambil_sla(dunia.db, pid)
    assert (sla.current_status, sla.days_elapsed, sla.is_locked) == ("green", 0, False)
    assert sla.started_at == p.assigned_at and sla.stopped_at is None
    # Checklist default ditugaskan ke SA proyek.
    subtask = await daftar_subtask(dunia.db, pid)
    assert sorted(s.title for s in subtask) == sorted(JUDUL_DEFAULT)
    assert {(s.status, s.assigned_sa) for s in subtask} == {("open", dunia.sa.id)}
    # Notifikasi in-app untuk SA.
    notif = await daftar_notif(dunia.db, pid, "assignment")
    assert [n.recipient_user_id for n in notif] == [dunia.sa.id]
    assert notif[0].notification_metadata["project_name"] == "Core Banking"
    assert notif[0].notification_metadata["assigned_by"] == dunia.lead.name
    # Provisioning dijadwalkan dengan email SA, Lead_SA, dan Sales yang benar.
    assert tugas == [(pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)]

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    customer = await dunia.db.get(Customer, p.customer_id)
    assert p.folder_provisioning_status == "provisioned"
    assert p.gdrive_folder_number == 1
    assert customer.gdrive_folder_id is not None
    assert fake_drive.folder[customer.gdrive_folder_id] == {
        "name": "PT Bank",
        "parent": fake_drive.parent_id,
    }
    assert fake_drive.folder[p.gdrive_folder_id] == {
        "name": "01-Core Banking",
        "parent": customer.gdrive_folder_id,
    }
    assert fake_drive.folder[p.gdrive_solutions_folder_id]["name"] == "Solutions"
    assert fake_drive.folder[p.gdrive_solutions_folder_id]["parent"] == p.gdrive_folder_id
    assert fake_drive.peran(p.gdrive_folder_id, dunia.sa.email) == "writer"
    assert fake_drive.peran(p.gdrive_folder_id, dunia.lead.email) == "writer"
    # Sales tidak punya akses ke Solutions (menunggu DQ Number).
    assert fake_drive.peran(p.gdrive_solutions_folder_id, dunia.sales.email) is None


async def test_assign_provisioning_gagal_status_failed_lalu_provision_ulang_berhasil(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)
    fake_drive.fail_next("provision_project_folder")
    await api.client.post(
        ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    customer = await dunia.db.get(Customer, p.customer_id)
    assert p.folder_provisioning_status == "failed"
    assert p.gdrive_folder_id is None
    assert p.gdrive_folder_number == 1
    assert customer.gdrive_folder_id is not None
    assert [
        folder for folder in fake_drive.folder.values()
        if folder["parent"] == customer.gdrive_folder_id
    ] == []
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.sa.id)
    assert (await ambil_sla(dunia.db, pid)) is not None
    assert len(await daftar_subtask(dunia.db, pid)) == 4

    detail = await api.client.get(f"/api/v1/projects/{pid}", headers=dunia.h["lead"])
    assert detail.status_code == 200, detail.text
    operation = detail.json()["data"]["folder_provisioning_operation"]
    assert operation["status"] == "failed"
    assert len(operation["attempts"]) == 1
    attempt = operation["attempts"][0]
    assert attempt["attempt"] == 1
    assert attempt["status"] == "failed"
    assert attempt["started_at"] is not None and attempt["finished_at"] is not None
    assert attempt["outcome"] == operation["outcome"] == "Drive provisioning failed"
    assert attempt["actionable_error"] == operation["actionable_error"]
    assert "manual provision" in operation["actionable_error"]
    assert operation["started_at"] is not None
    assert operation["finished_at"] is not None
    assert operation["outcome"] == "Drive provisioning failed"
    assert operation["actionable_error"]

    # Provision ulang (Lead_SA): menandai pending lalu menjadwalkan task yang sama.
    resp = await api.client.post(REPROVISION.format(pid), headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["folder_provisioning_status"] == "pending"
    assert tugas[1] == (pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)
    await jalankan_provisioning(dunia.db, tugas[1])
    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "provisioned" and p.gdrive_folder_id is not None
    detail = await api.client.get(f"/api/v1/projects/{pid}", headers=dunia.h["lead"])
    operation = detail.json()["data"]["folder_provisioning_operation"]
    assert operation["status"] == "succeeded"
    assert len(operation["attempts"]) == 2
    assert [entry["status"] for entry in operation["attempts"]] == ["failed", "succeeded"]
    assert all(entry["started_at"] and entry["finished_at"] for entry in operation["attempts"])
    assert operation["outcome"] == "Project Drive folders provisioned"
    assert operation["actionable_error"] is None

    # Guard idempotensi (ADR 0006): sudah ada folder → 409 dan Drive tidak disentuh lagi.
    panggilan_sebelum = len(fake_drive.panggilan)
    lagi = await api.client.post(REPROVISION.format(pid), headers=dunia.h["admin"])
    assert lagi.status_code == 409
    assert len(fake_drive.panggilan) == panggilan_sebelum
    assert len(tugas) == 2


async def test_project_number_uses_highest_numbered_folder_and_leaves_legacy_flat_folder(
    dunia, api, fake_drive, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Migration", customer_name="PT Bank")
    customer = await dunia.db.get(Customer, project.customer_id)
    customer_folder_id = fake_drive.seed_folder("PT Bank", fake_drive.parent_id)
    customer.gdrive_folder_id = customer_folder_id
    legacy_folder_id = fake_drive.seed_folder("PT Bank - Legacy", fake_drive.parent_id)
    fake_drive.seed_folder("01-Old", customer_folder_id)
    fake_drive.seed_folder("104-Old", customer_folder_id)
    await dunia.db.commit()

    tasks = rekam_background(monkeypatch)
    response = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert response.status_code == 200, response.text
    await jalankan_provisioning(dunia.db, tasks[0])

    persisted = await ambil_proyek(dunia.db, project.id_project)
    assert persisted.gdrive_folder_number == 105
    assert fake_drive.folder[persisted.gdrive_folder_id] == {
        "name": "105-Migration",
        "parent": customer_folder_id,
    }
    assert fake_drive.folder[legacy_folder_id] == {
        "name": "PT Bank - Legacy",
        "parent": fake_drive.parent_id,
    }


async def test_partial_provisioning_retry_reuses_reserved_number_and_master_folder(
    dunia, api, fake_drive, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Migration", customer_name="PT Bank")
    tasks = rekam_background(monkeypatch)
    response = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert response.status_code == 200, response.text

    fake_drive.fail_next("create_inventory_subfolder")
    await jalankan_provisioning(dunia.db, tasks[0])

    failed = await ambil_proyek(dunia.db, project.id_project)
    assert failed.folder_provisioning_status == "failed"
    assert failed.gdrive_folder_number == 1
    assert failed.gdrive_folder_id is not None
    master_id = failed.gdrive_folder_id
    customer = await dunia.db.get(Customer, failed.customer_id)
    assert fake_drive.folder[master_id] == {
        "name": "01-Migration",
        "parent": customer.gdrive_folder_id,
    }

    response = await api.client.post(
        REPROVISION.format(project.id_project), headers=dunia.h["lead"]
    )
    assert response.status_code == 200, response.text
    await jalankan_provisioning(dunia.db, tasks[1])

    retried = await ambil_proyek(dunia.db, project.id_project)
    assert retried.folder_provisioning_status == "provisioned"
    assert (retried.gdrive_folder_number, retried.gdrive_folder_id) == (1, master_id)
    assert sum(
        folder["parent"] == customer.gdrive_folder_id for folder in fake_drive.folder.values()
    ) == 1
    subfolders = {
        folder["name"]
        for folder in fake_drive.folder.values()
        if folder["parent"] == master_id
    }
    assert subfolders == {"Inventory", "Diagram", "Solutions"}


async def test_concurrent_assignments_for_one_customer_reserve_distinct_numbers(
    dunia, api, fake_drive, monkeypatch
):
    projects = [
        await dunia.buat_proyek(project_name=name, customer_name="PT Bank")
        for name in ("Migration", "Modernization")
    ]
    tasks = rekam_background(monkeypatch)
    for project in projects:
        response = await api.client.post(
            ASSIGN.format(project.id_project),
            json={"sa_id": str(dunia.sa.id)},
            headers=dunia.h["lead"],
        )
        assert response.status_code == 200, response.text

    await asyncio.gather(
        *(jalankan_provisioning(dunia.db, task) for task in tasks)
    )

    persisted = [await ambil_proyek(dunia.db, project.id_project) for project in projects]
    assert {project.gdrive_folder_number for project in persisted} == {1, 2}
    customer = await dunia.db.get(Customer, persisted[0].customer_id)
    assert persisted[0].customer_id == persisted[1].customer_id
    assert customer.gdrive_folder_id is not None
    assert {
        fake_drive.folder[project.gdrive_folder_id]["parent"] for project in persisted
    } == {customer.gdrive_folder_id}
    assert {
        fake_drive.folder[project.gdrive_folder_id]["name"] for project in persisted
    } == {"01-Migration", "02-Modernization"}
    assert sum(
        folder["name"] == "PT Bank" and folder["parent"] == fake_drive.parent_id
        for folder in fake_drive.folder.values()
    ) == 1


async def test_unassociated_project_folder_name_collision_fails_closed(
    dunia, api, fake_drive, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Proyek", customer_name="Cust")
    customer = await dunia.db.get(Customer, project.customer_id)
    customer.gdrive_folder_id = fake_drive.seed_folder("Cust", fake_drive.parent_id)
    project.gdrive_folder_number = 1
    collision_id = fake_drive.seed_folder("01-Proyek", customer.gdrive_folder_id)
    await dunia.db.commit()
    tasks = rekam_background(monkeypatch)

    response = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert response.status_code == 200, response.text
    await jalankan_provisioning(dunia.db, tasks[0])

    persisted = await ambil_proyek(dunia.db, project.id_project)
    assert persisted.folder_provisioning_status == "failed"
    assert persisted.gdrive_folder_number == 1
    assert persisted.gdrive_folder_id is None
    assert fake_drive.folder[collision_id] == {
        "name": "01-Proyek",
        "parent": customer.gdrive_folder_id,
    }
    detail = await api.client.get(
        f"/api/v1/projects/{project.id_project}", headers=dunia.h["lead"]
    )
    error = detail.json()["data"]["folder_provisioning_operation"]["actionable_error"]
    assert "collision" in error.lower() or "already exists" in error.lower()


async def test_duplicate_customer_folders_fail_with_actionable_operation_error(
    dunia, api, fake_drive, monkeypatch
):
    project = await dunia.buat_proyek(project_name="Migration", customer_name="Cust")
    fake_drive.seed_folder("Cust", fake_drive.parent_id)
    fake_drive.seed_folder("Cust", fake_drive.parent_id)
    tasks = rekam_background(monkeypatch)

    response = await api.client.post(
        ASSIGN.format(project.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )
    assert response.status_code == 200, response.text
    await jalankan_provisioning(dunia.db, tasks[0])

    persisted = await ambil_proyek(dunia.db, project.id_project)
    customer = await dunia.db.get(Customer, persisted.customer_id)
    assert persisted.folder_provisioning_status == "failed"
    assert persisted.gdrive_folder_number is None
    assert customer.gdrive_folder_id is None
    detail = await api.client.get(
        f"/api/v1/projects/{project.id_project}", headers=dunia.h["lead"]
    )
    error = detail.json()["data"]["folder_provisioning_operation"]["actionable_error"]
    assert "multiple" in error.lower() or "duplicate" in error.lower()


async def test_provisioning_error_tak_terduga_dipersisten_dan_tetap_non_blocking(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)
    await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    async def _meledak(*a, **k):
        raise RuntimeError("Drive tidak terduga")

    monkeypatch.setattr(folder_provisioner, "provision_project_folder", _meledak)

    await jalankan_provisioning(dunia.db, tugas[0])  # tidak boleh raise

    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "failed" and p.gdrive_folder_id is None
    detail = await api.client.get(
        f"/api/v1/projects/{proyek.id_project}", headers=dunia.h["lead"]
    )
    operation = detail.json()["data"]["folder_provisioning_operation"]
    assert operation["status"] == "failed"
    assert operation["attempts"][0]["finished_at"] is not None
    assert operation["actionable_error"]


async def test_provisioning_proyek_hilang_dilewati_tanpa_menyentuh_drive(dunia, fake_drive):
    await jalankan_provisioning(
        dunia.db, ("PRJ-TIDAK-ADA", dunia.sa.email, dunia.lead.email, dunia.sales.email)
    )

    assert fake_drive.panggilan == []


# ----------------------------------------------------------------------------- assign: validasi


async def test_assign_dua_kali_ditolak_tanpa_menggandakan_subtask_atau_timer(
    dunia, api, monkeypatch
):
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    rekam_background(monkeypatch)
    url = ASSIGN.format(pid)
    await api.client.post(url, json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"])

    kedua = await api.client.post(url, json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"])

    assert kedua.status_code == 400 and "Assigned" in kedua.json()["message"]
    p = await ambil_proyek(dunia.db, pid)
    assert p.assigned_sa == dunia.sa.id
    assert len(await daftar_subtask(dunia.db, pid)) == 4
    assert len(await daftar_notif(dunia.db, pid, "assignment")) == 1


@pytest.mark.parametrize("status", ["Intake", "Submitted", "Won", "Lost"])
async def test_assign_hanya_untuk_pending_assignment(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 400
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == (status, None)
    assert await ambil_sla(dunia.db, proyek.id_project) is None


async def test_assign_proyek_tidak_ada_404_dan_sa_tidak_ada_404(dunia, api):
    proyek = await dunia.buat_proyek()
    import uuid

    tanpa_proyek = await api.client.post(
        ASSIGN.format("PRJ-TIDAK-ADA"), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    tanpa_sa = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(uuid.uuid4())},
        headers=dunia.h["lead"],
    )

    assert tanpa_proyek.status_code == 404 and tanpa_sa.status_code == 404
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Awaiting Assignment"


async def test_assign_lead_sa_diizinkan_sebagai_assigned_sa(dunia, api):
    """ADR 0012: SA dan Lead_SA sama-sama bisa ditugaskan sebagai `assigned_sa`."""
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.lead.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.lead.id)
    assert {s.assigned_sa for s in await daftar_subtask(dunia.db, proyek.id_project)} == {
        dunia.lead.id
    }


async def test_assign_sa_pemilik_flag_admin_diizinkan(dunia, api):
    """Admin menempel pada role fungsional (ADR 0012): admin berrole SA bisa ditugaskan."""
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.admin.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.admin.id)


@pytest.mark.parametrize("target", ["sales_lain", "produk"])
async def test_assign_target_bukan_sa_ditolak(dunia, api, target):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(getattr(dunia, target).id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Awaiting Assignment", None)
    assert await daftar_subtask(dunia.db, proyek.id_project) == []


async def test_assign_body_tanpa_sa_id_422(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(ASSIGN.format(proyek.id_project), json={}, headers=dunia.h["lead"])

    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("peran", "diizinkan"),
    [("lead", True), ("admin", True), ("sa", False), ("sales", False)],
)
async def test_assign_hak_akses_per_peran(dunia, api, monkeypatch, peran, diizinkan):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    # Admin non-Lead_SA wajib memilih Lead SA (#135); peran lain tidak terpengaruh.
    body = {"sa_id": str(dunia.sa.id)}
    if peran == "admin":
        body["lead_sa_id"] = str(dunia.lead.id)
    resp = await api.client.post(ASSIGN.format(proyek.id_project), json=body, headers=dunia.h[peran])

    p = await ambil_proyek(dunia.db, proyek.id_project)
    if diizinkan:
        assert resp.status_code == 200, resp.text
        assert p.status == "Assigned"
    else:
        assert resp.status_code == 403
        assert (p.status, p.assigned_sa) == ("Awaiting Assignment", None)
        assert await ambil_sla(dunia.db, proyek.id_project) is None


async def test_assign_tanpa_login_ditolak(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)})

    assert resp.status_code in (401, 403)


async def test_assign_tetap_berhasil_walau_timer_gagal_dimulai(dunia, api, monkeypatch):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    async def _gagal(*a, **k):
        raise RuntimeError("timer rusak")

    monkeypatch.setattr(sla_timer, "start_timer", _gagal)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Assigned"
    assert await ambil_sla(dunia.db, proyek.id_project) is None


# ----------------------------------------------------------------------------- seeding idempoten


async def test_assign_tidak_seed_bila_proyek_sudah_punya_subtask(dunia, api, monkeypatch):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)
    dunia.db.add(bangun_subtask(proyek.id_project, title="Sudah Ada"))
    await dunia.db.commit()

    await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert [s.title for s in await daftar_subtask(dunia.db, proyek.id_project)] == ["Sudah Ada"]


async def test_seed_subtask_dua_kali_tetap_satu_set_dengan_id_unik(dunia):
    from app.api.assignment import _seed_default_subtasks

    proyek = await dunia.buat_proyek()
    pid = proyek.id_project

    await _seed_default_subtasks(dunia.db, pid, dunia.sa.id)
    await dunia.db.commit()
    await _seed_default_subtasks(dunia.db, pid, dunia.sa2.id)
    await dunia.db.commit()

    subtask = await daftar_subtask(dunia.db, pid)
    assert sorted(s.title for s in subtask) == sorted(JUDUL_DEFAULT)
    assert len({s.id_subtask for s in subtask}) == 4
    assert {s.assigned_sa for s in subtask} == {dunia.sa.id}  # set kedua tidak menimpa


# ----------------------------------------------------------------------------- reassign


async def _assign(api, dunia, monkeypatch, **proyek_opsi):
    proyek = await dunia.buat_proyek(**proyek_opsi)
    rekam_background(monkeypatch)
    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    assert resp.status_code == 200, resp.text
    return proyek.id_project


async def test_reassign_mengganti_sa_menotifikasi_sa_baru_tanpa_duplikasi_timer_atau_subtask(
    dunia, api, monkeypatch
):
    pid = await _assign(api, dunia, monkeypatch)
    sla_awal = await ambil_sla(dunia.db, pid)
    started_at = sla_awal.started_at

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["assigned_sa"] == str(dunia.sa2.id)
    assert (data["assigned_sa_email"], data["status"]) == (dunia.sa2.email, "Assigned")
    p = await ambil_proyek(dunia.db, pid)
    assert p.assigned_sa == dunia.sa2.id
    notif = {n.recipient_user_id: n for n in await daftar_notif(dunia.db, pid, "assignment")}
    assert set(notif) == {dunia.sa.id, dunia.sa2.id}
    assert notif[dunia.sa2.id].notification_metadata["previous_sa_id"] == str(dunia.sa.id)
    assert len(await daftar_subtask(dunia.db, pid)) == 4  # seeding idempoten
    jumlah_sla = await dunia.db.scalar(
        select(func.count()).select_from(type(sla_awal)).where(type(sla_awal).project_id == pid)
    )
    assert jumlah_sla == 1
    assert (await ambil_sla(dunia.db, pid)).started_at == started_at


@pytest.mark.parametrize("status", ["Submitted", "Assigned"])
async def test_reassign_diizinkan_pada_assigned_dan_ready(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id, assigned_at=None)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == (status, dunia.sa2.id)


async def test_reassign_pada_pending_assignment_menjadikan_assigned_dan_seed_subtask(
    dunia, api, monkeypatch
):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.sa.id)
    assert len(await daftar_subtask(dunia.db, proyek.id_project)) == 4


async def test_reassign_dari_pending_assignment_memulai_timer_sla_dan_provisioning_folder(
    dunia, api, fake_drive, monkeypatch
):
    """#77: reassign dari Awaiting Assignment setara assign: tracker SLA + folder Drive dibuat."""
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)
    assert await ambil_sla(dunia.db, pid) is None

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, pid)
    sla = await ambil_sla(dunia.db, pid)
    assert sla is not None and sla.started_at == p.assigned_at
    assert (sla.current_status, sla.is_locked, sla.stopped_at) == ("green", False, None)
    assert p.folder_provisioning_status == "pending"
    assert tugas == [(pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)]

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "provisioned"
    assert fake_drive.peran(p.gdrive_folder_id, dunia.sa.email) == "writer"


async def test_reassign_dari_pending_tetap_berhasil_walau_timer_gagal_dimulai(
    dunia, api, monkeypatch
):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    async def _gagal(*a, **k):
        raise RuntimeError("timer rusak")

    monkeypatch.setattr(sla_timer, "start_timer", _gagal)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Assigned"
    assert await ambil_sla(dunia.db, proyek.id_project) is None


async def _assign_dan_provision(api, dunia, fake_drive, monkeypatch):
    """Proyek Assigned ke `dunia.sa` dengan folder Drive sungguh-sungguh dibuat (fake)."""
    proyek = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)
    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    assert resp.status_code == 200, resp.text
    await jalankan_provisioning(dunia.db, tugas[0])
    return (await ambil_proyek(dunia.db, proyek.id_project)).gdrive_folder_id, proyek.id_project


async def test_reassign_memindahkan_akses_drive_sa_baru_diberi_sa_lama_dicabut(
    dunia, api, fake_drive, monkeypatch
):
    """#77: SA baru mendapat Editor di folder master, SA lama dicabut; Lead_SA tetap."""
    master, pid = await _assign_dan_provision(api, dunia, fake_drive, monkeypatch)
    assert fake_drive.peran(master, dunia.sa.email) == "writer"

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert fake_drive.peran(master, dunia.sa2.email) == "writer"
    assert fake_drive.peran(master, dunia.sa.email) is None
    assert fake_drive.peran(master, dunia.lead.email) == "writer"
    [panggilan] = fake_drive.panggilan_operasi("reassign_sa_access")
    assert panggilan.argumen == {
        "master_folder_id": master,
        "old_sa_email": dunia.sa.email,
        "new_sa_email": dunia.sa2.email,
    }


async def test_reassign_tetap_berhasil_walau_drive_gagal(dunia, api, fake_drive, monkeypatch):
    master, pid = await _assign_dan_provision(api, dunia, fake_drive, monkeypatch)
    fake_drive.fail_always("reassign_sa_access")

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, pid)).assigned_sa == dunia.sa2.id
    # Drive gagal: akses lama belum dicabut (dapat dirapikan dengan provision ulang / manual).
    assert fake_drive.peran(master, dunia.sa.email) == "writer"


async def test_reassign_tanpa_folder_tidak_menyentuh_drive(dunia, api, fake_drive):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert fake_drive.panggilan_operasi("reassign_sa_access") == []
    assert fake_drive.panggilan_operasi("provision_project_folder") == []


async def test_reassign_sla_melanjutkan_hitungan_dan_subtask_tidak_dipindahkan(
    dunia, api, monkeypatch
):
    """#77: timer SLA TIDAK direset (started_at tetap) dan subtask SA lama tetap miliknya."""
    pid = await _assign(api, dunia, monkeypatch)
    sla_awal = await ambil_sla(dunia.db, pid)

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, pid)
    sla = await ambil_sla(dunia.db, pid)
    assert sla.id == sla_awal.id and sla.started_at == sla_awal.started_at
    assert sla.started_at < p.assigned_at  # assigned_at mencatat SA saat ini, bukan awal SLA
    assert (sla.stopped_at, sla.is_locked) == (None, False)
    assert {s.assigned_sa for s in await daftar_subtask(dunia.db, pid)} == {dunia.sa.id}


@pytest.mark.parametrize(
    "status", ["Won", "Handed Over", "Lost", "Intake"]
)
async def test_reassign_status_tidak_valid_ditolak(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == dunia.sa.id


async def test_reassign_ke_lead_sa_diizinkan(dunia, api):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.lead.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == dunia.lead.id


async def test_reassign_proyek_tidak_ada_sa_tidak_ada_dan_target_bukan_sa(dunia, api):
    import uuid

    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    url = REASSIGN.format(proyek.id_project)

    tanpa_proyek = await api.client.post(
        REASSIGN.format("PRJ-TIDAK-ADA"), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )
    tanpa_sa = await api.client.post(
        url, json={"sa_id": str(uuid.uuid4())}, headers=dunia.h["lead"]
    )
    bukan_sa = await api.client.post(
        url, json={"sa_id": str(dunia.sales_lain.id)}, headers=dunia.h["lead"]
    )
    produk = await api.client.post(
        url, json={"sa_id": str(dunia.produk.id)}, headers=dunia.h["lead"]
    )

    assert (tanpa_proyek.status_code, tanpa_sa.status_code, bukan_sa.status_code) == (404, 404, 400)
    assert produk.status_code == 400
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == dunia.sa.id
    assert await daftar_notif(dunia.db, proyek.id_project, "assignment") == []


@pytest.mark.parametrize(
    ("peran", "diizinkan"),
    [("lead", True), ("admin", True), ("sa", False), ("sales", False)],
)
async def test_reassign_hak_akses_per_peran(dunia, api, peran, diizinkan):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h[peran],
    )

    expected = dunia.sa2.id if diizinkan else dunia.sa.id
    assert resp.status_code == (200 if diizinkan else 403)
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == expected


# ----------------------------------------------------------------------------- re-provision


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_reprovision_hanya_lead_sa_dan_admin(dunia, api, monkeypatch, peran):
    proyek = await dunia.buat_proyek(
        status="Assigned", assigned_sa=dunia.sa.id, folder_provisioning_status="failed"
    )
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h[peran])

    assert resp.status_code == 403 and tugas == []
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "failed"


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_reprovision_oleh_lead_sa_atau_admin_menjadwalkan_dengan_email_pemanggil(
    dunia, api, monkeypatch, peran
):
    proyek = await dunia.buat_proyek(
        status="Assigned", assigned_sa=dunia.sa.id, folder_provisioning_status="failed"
    )
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    pemanggil = getattr(dunia, peran)
    assert tugas == [(proyek.id_project, dunia.sa.email, pemanggil.email, dunia.sales.email)]
    assert (await ambil_proyek(dunia.db, proyek.id_project)).folder_provisioning_status == "pending"


async def test_reprovision_proyek_belum_di_assign_400_dan_tidak_ada_404(dunia, api, monkeypatch):
    belum = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)

    tanpa_sa = await api.client.post(REPROVISION.format(belum.id_project), headers=dunia.h["lead"])
    tidak_ada = await api.client.post(REPROVISION.format("PRJ-TIDAK-ADA"), headers=dunia.h["lead"])

    assert (tanpa_sa.status_code, tidak_ada.status_code) == (400, 404)
    assert tugas == []
    assert (await ambil_proyek(dunia.db, belum.id_project)).folder_provisioning_status is None


async def test_drive_palsu_gagal_permanen_provisioning_failed_tanpa_folder_yatim_di_db(
    dunia, api, fake_drive, monkeypatch
):
    fake_drive.fail_always("provision_project_folder")
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    tugas = rekam_background(monkeypatch)

    for _ in range(2):  # dua percobaan provision ulang, keduanya gagal
        resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h["lead"])
        assert resp.status_code == 200, resp.text
        await jalankan_provisioning(dunia.db, tugas[-1])

    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "failed" and p.gdrive_folder_id is None
    assert len(fake_drive.panggilan_operasi("provision_project_folder")) == 2
    assert all(
        not call.berhasil
        for call in fake_drive.panggilan_operasi("provision_project_folder")
    )


@pytest.mark.parametrize(
    ("path", "expected_data"),
    [
        ("/api/v1/sa/utilization?year=2025", {"year": 2025}),
        ("/api/v1/utilization/projects", []),
        ("/api/v1/utilization/summary?year=2025", {"year": 2025}),
    ],
)
async def test_endpoint_utilisasi_mendukung_kontrak_dasarnya(dunia, api, path, expected_data):
    response = await api.client.get(path, headers=dunia.h["lead"])

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    if path.startswith("/api/v1/sa/utilization"):
        assert data["year"] == expected_data["year"]
        assert {row["sa_id"] for row in data["monthly_data"]} == {
            str(dunia.sa.id),
            str(dunia.sa2.id),
            str(dunia.lead.id),
            str(dunia.admin.id),
        }
        assert data["summary"]["sa_count"] == 4
    elif path.endswith("/projects"):
        assert data == expected_data
    else:
        assert data["year"] == expected_data["year"]
        assert data["work_type"]["totals"] == {"Project": 0.0, "Non-Project": 0.0}


async def test_endpoint_utilisasi_mengagregasi_jam_activity_log(dunia, api):
    project = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    dunia.db.add_all(
        [
            bangun_log(
                dunia.sa.id,
                project.id_project,
                duration_hours=3.5,
                created_at=datetime(2025, 2, 5, tzinfo=timezone.utc),
            ),
            bangun_log(
                dunia.sa2.id,
                None,
                work_type="Non-Project",
                project_phase=None,
                duration_hours=2.25,
                created_at=datetime(2025, 2, 6, tzinfo=timezone.utc),
            ),
        ]
    )
    await dunia.db.commit()

    per_sa = await api.client.get(
        "/api/v1/sa/utilization?year=2025", headers=dunia.h["lead"]
    )
    per_project = await api.client.get("/api/v1/utilization/projects", headers=dunia.h["lead"])
    summary = await api.client.get(
        "/api/v1/utilization/summary?year=2025", headers=dunia.h["lead"]
    )

    assert per_sa.status_code == per_project.status_code == summary.status_code == 200
    row_sa = next(
        row for row in per_sa.json()["data"]["monthly_data"] if row["sa_id"] == str(dunia.sa.id)
    )
    assert row_sa["months"]["2"] == 3.5
    assert per_project.json()["data"][0]["id_project"] == project.id_project
    assert per_project.json()["data"][0]["total_hours"] == 3.5
    assert summary.json()["data"]["work_type"]["totals"] == {
        "Project": 3.5,
        "Non-Project": 2.25,
    }
    assert summary.json()["data"]["project_phase"]["total"] == 3.5


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sa/utilization?year=2025",
        "/api/v1/utilization/projects",
        "/api/v1/utilization/summary?year=2025",
    ],
)
async def test_endpoint_utilisasi_tetap_dibatasi_ke_lead_sa(dunia, api, path):
    response = await api.client.get(path, headers=dunia.h["sa"])

    assert response.status_code == 403



async def test_subtask_default_dapat_dibaca_dan_dikerjakan_sa_pemilik_setelah_assign(
    dunia, api, monkeypatch
):
    pid = await _assign(api, dunia, monkeypatch)

    daftar = await api.client.get(f"/api/v1/projects/{pid}/subtasks", headers=dunia.h["sa"])

    assert daftar.status_code == 200, daftar.text
    isi = daftar.json()["data"]
    assert isi["total"] == 4
    assert {i["assigned_sa_name"] for i in isi["items"]} == {dunia.sa.name}
    # Subtask tersimpan benar di tabel.
    jumlah = await dunia.db.scalar(
        select(func.count()).select_from(Subtask).where(Subtask.id_project == pid)
    )
    assert jumlah == 4
