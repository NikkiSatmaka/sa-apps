"""
API endpoints untuk assignment SA ke proyek oleh Lead_SA.
Menangani penugasan SA, daftar proyek pending, dan ketersediaan SA.
"""

import logging
import random
import re
import string
import uuid
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orang import tentukan_lead_sa
from app.core import status as status_konst
from app.core.database import get_db
from app.core.dependencies import (
    PERAN_DAPAT_DITUGASKAN,
    PeranUser,
    TingkatAkses,
    adalah_privileged,
    ensure_project_access,
    get_current_user,
)
from app.models.integration_operation import IntegrationOperation
from app.models.document import Document
from app.models.notification_log import NotificationLog
from app.models.project import Project
from app.models.customer import Customer
from app.models.project_assignment import ProjectAssignment
from app.models.subtask import Subtask
from app.models.user import User
from app.models.sla_tracking import SLATracking
from app.schemas.assignment import (
    AssignmentResponse,
    AssignRequest,
    ProjectBrief,
    SAAvailability,
)
from app.schemas.integration_operation import (
    IntegrationOperationResponse,
    ManualEmailRepairRequest,
)
from app.schemas.response import ErrorResponse, SuccessResponse, success_response
from app.services.folder_provisioner import (
    FolderProvisioningError,
    folder_provisioner,
)
from app.services.integration_operations import (
    begin_retry,
    retry_side_effect,
    run_side_effect,
    serialize_operation,
)
from app.services.sla_timer import sla_timer
from app.services.workload import hitung_project_aktif_per_sa

logger = logging.getLogger(__name__)

# Status tempat SA utama boleh diganti (ADR 0014): sudah ditugaskan atau menunggu penugasan.
STATUS_BOLEH_GANTI_SA = (
    status_konst.AWAITING_ASSIGNMENT,
    status_konst.ASSIGNED,
    status_konst.IN_PROGRESS,
    status_konst.SUBMITTED,
)

router = APIRouter(tags=["Assignment"])

# Checklist default yang di-seed otomatis saat proyek di-assign ke SA.
DEFAULT_SUBTASK_TEMPLATE = ["Requirement", "BoQ", "PropTek", "HLD"]


def _generate_subtask_id() -> str:
    """Generate ID subtask unik dengan format SUB-{YYYYMMDD}-{random 6 chars}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"SUB-{date_part}-{random_part}"


async def _seed_default_subtasks(db: AsyncSession, project_id: str, assigned_sa: uuid.UUID) -> None:
    """
    Seed checklist subtask default untuk proyek bila belum ada subtask apa pun.

    Subtask hasil seeding langsung ditugaskan ke SA proyek (`assigned_sa`), sehingga
    begitu SA membuka proyek, to-do list miliknya sudah terisi tanpa Lead SA perlu
    mendistribusikan tiap item. Lead SA tetap bisa memindah sebagian ke SA lain lewat
    endpoint assign subtask.

    Idempoten: jika proyek sudah punya minimal satu subtask (mis. re-assign),
    seeding dilewati sehingga tidak terjadi duplikasi.
    """
    count_result = await db.execute(
        select(func.count()).select_from(Subtask).where(Subtask.id_project == project_id)
    )
    existing = count_result.scalar() or 0
    if existing > 0:
        return

    for title in DEFAULT_SUBTASK_TEMPLATE:
        db.add(
            Subtask(
                id_subtask=_generate_subtask_id(),
                id_project=project_id,
                title=title,
                status="open",
                assigned_sa=assigned_sa,
            )
        )


def _generate_notification_id() -> str:
    """Generate ID notifikasi unik dengan format NOTIF-{timestamp}-{random}."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"NOTIF-{ts}-{random_part}"


def _require_lead_sa(current_user: User) -> None:
    """Validasi bahwa user saat ini Lead_SA atau admin (`is_admin`)."""
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat melakukan operasi ini.",
        )


async def _reserve_project_folder(db: AsyncSession, project: Project) -> None:
    """Persist the Customer Drive identity and a unique number before project-folder creation."""
    if project.customer_id is None:
        raise FolderProvisioningError(
            f"Project '{project.id_project}' has no Customer identity. Link it to a Customer "
            "before provisioning its Drive folder."
        )

    customer_result = await db.execute(
        select(Customer)
        .where(Customer.id == project.customer_id)
        .with_for_update()
    )
    customer = customer_result.scalar_one_or_none()
    if customer is None:
        raise FolderProvisioningError(
            f"Customer identity for project '{project.id_project}' no longer exists."
        )
    # A concurrent attempt for the same project may have committed while this task waited.
    await db.refresh(
        project,
        attribute_names=["customer_id", "gdrive_folder_id", "gdrive_folder_number"],
    )
    project.customer = customer

    # Existing Drive associations are legacy paths: retain them without renaming or moving.
    if project.gdrive_folder_id is not None:
        return

    customer_folder_id = await folder_provisioner.ensure_customer_folder(
        customer.name, customer.gdrive_folder_id
    )
    customer.gdrive_folder_id = customer_folder_id

    if project.gdrive_folder_number is None:
        existing_children = await folder_provisioner.list_folder_children(customer_folder_id)
        highest_drive_number = max(
            (
                int(match.group(1))
                for child in existing_children
                if (match := re.match(r"^(\d+)-", child.get("name", "")))
            ),
            default=0,
        )
        highest_reserved_number = await db.scalar(
            select(func.max(Project.gdrive_folder_number)).where(
                Project.customer_id == customer.id
            )
        )
        project.gdrive_folder_number = max(
            highest_drive_number, highest_reserved_number or 0
        ) + 1

    # Commit while holding the Customer row lock so overlapping assignments see this reservation.
    await db.commit()


async def _trigger_folder_provisioner(
    project_id: str,
    sa_email: str,
    lead_sa_email: str,
    sales_email: str,
) -> None:
    """
    Background task: trigger Folder_Provisioner setelah assignment.
    Membuat folder proyek di Google Drive secara async lalu mem-persist
    id folder (master + Solutions) dan status provisioning ke proyek.

    Membuka session baru via AsyncSessionLocal() karena request session sudah
    ditutup saat background task berjalan (pola projects.py::_trigger_scoring_engine).

    Alur status (ADR 0005):
    - set folder_provisioning_status='pending' sebelum memanggil provisioner;
    - sukses  -> persist gdrive_folder_id + gdrive_solutions_folder_id,
                 status='provisioned';
    - gagal (FolderProvisioningError setelah retry internal) -> status='failed'.

    Side-effect ini graceful: error tidak di-re-raise keluar dari task.

    Args:
        project_id: ID proyek yang baru di-assign.
        sa_email: Email SA yang ditugaskan.
        lead_sa_email: Email Lead_SA yang melakukan assignment.
        sales_email: Email Sales PIC proyek.
    """
    from app.core.database import AsyncSessionLocal

    logger.info(
        f"[FolderProvisioner] Trigger provisioning untuk proyek {project_id} "
        f"(SA: {sa_email}, Lead: {lead_sa_email})"
    )
    try:
        async with AsyncSessionLocal() as db:
            # Muat proyek dari session baru
            project_result = await db.execute(
                select(Project).where(Project.id_project == project_id)
            )
            project = project_result.scalar_one_or_none()

            if project is None:
                logger.error(
                    f"[FolderProvisioner] Proyek {project_id} tidak ditemukan, skip provisioning."
                )
                return

            started_at = datetime.now(timezone.utc)
            operation = dict(project.folder_provisioning_operation or {})
            attempts = list(operation.get("attempts", []))
            attempt = {
                "attempt": len(attempts) + 1,
                "status": "pending",
                "started_at": started_at.isoformat(),
                "finished_at": None,
                "outcome": None,
                "actionable_error": None,
            }
            attempts.append(attempt)
            operation.update(
                {
                    "status": "pending",
                    "attempts": attempts,
                    "started_at": started_at.isoformat(),
                    "finished_at": None,
                    "outcome": None,
                    "actionable_error": None,
                }
            )
            project.folder_provisioning_status = "pending"
            project.folder_provisioning_operation = operation
            await db.commit()

            try:
                await _reserve_project_folder(db, project)

                async def persist_master_folder_id(folder_id: str) -> None:
                    if project.gdrive_folder_id not in (None, folder_id):
                        raise FolderProvisioningError(
                            "A different Drive project folder is already associated with this project."
                        )
                    project.gdrive_folder_id = folder_id
                    await db.commit()

                result = await folder_provisioner.provision_project_folder(
                    project,
                    sa_email,
                    lead_sa_email,
                    sales_email,
                    persist_master_folder_id=persist_master_folder_id,
                )
            except Exception as e:  # noqa: BLE001 - kegagalan Drive harus persisten dan non-blocking
                finished_at = datetime.now(timezone.utc).isoformat()
                attempt.update(
                    {
                        "status": "failed",
                        "finished_at": finished_at,
                        "outcome": "Drive provisioning failed",
                        "actionable_error": (
                            (
                                f"{e} "
                                if isinstance(e, FolderProvisioningError)
                                else ""
                            )
                            + "Review the project’s Drive folders and permissions, then use "
                            "the authorized manual provision action."
                        ),
                    }
                )
                operation.update(
                    {
                        "status": "failed",
                        "attempts": attempts,
                        "finished_at": finished_at,
                        "outcome": "Drive provisioning failed",
                        "actionable_error": attempt["actionable_error"],
                    }
                )
                project.folder_provisioning_status = "failed"
                project.folder_provisioning_operation = operation
                await db.commit()
                logger.error(
                    f"[FolderProvisioner] Gagal provision folder proyek "
                    f"{project_id} setelah retry: {e}"
                )
                return

            finished_at = datetime.now(timezone.utc).isoformat()
            attempt.update(
                {
                    "status": "succeeded",
                    "finished_at": finished_at,
                    "outcome": "Project Drive folders provisioned",
                }
            )
            operation.update(
                {
                    "status": "succeeded",
                    "attempts": attempts,
                    "finished_at": finished_at,
                    "outcome": "Project Drive folders provisioned",
                    "actionable_error": None,
                }
            )
            # Sukses — persist kedua id folder + status provisioned
            project.gdrive_folder_id = result.master
            project.gdrive_solutions_folder_id = result.solutions
            project.folder_provisioning_status = "provisioned"
            project.folder_provisioning_operation = operation
            await db.commit()

            logger.info(
                f"[FolderProvisioner] Folder proyek {project_id} berhasil "
                f"di-provision (master={result.master}, solutions={result.solutions})."
            )
    except Exception as e:  # noqa: BLE001 - background task tidak boleh meledak keluar
        logger.error(
            f"[FolderProvisioner] Error tidak terduga saat provisioning proyek {project_id}: {e}"
        )


async def _pindahkan_akses_drive_sa(
    project_id: str,
    master_folder_id: str,
    sa_lama_email: Optional[str],
    sa_baru_email: str,
    actor_user_id: Optional[uuid.UUID] = None,
) -> None:
    """Persist and perform the safe, idempotent Drive SA permission reassign."""
    await run_side_effect(
        project_id=project_id,
        operation_type="drive_permission",
        action="reassign_sa_access",
        perform=lambda: folder_provisioner.reassign_sa_access(
            master_folder_id, sa_lama_email, sa_baru_email
        ),
        outcome="Drive editor access matches the assigned SA.",
        actionable_failure=(
            "The SA reassignment is saved, but Drive permissions may be stale. "
            "Retry this idempotent permission update after restoring Drive access."
        ),
        actor_user_id=actor_user_id,
        context={
            "master_folder_id": master_folder_id,
            "old_sa_email": sa_lama_email,
            "new_sa_email": sa_baru_email,
        },
        retryable=True,
    )


@router.post(
    "/projects/{project_id}/integration-operations/{operation_id}/retry",
    summary="Retry an idempotent integration operation",
    response_model=SuccessResponse[IntegrationOperationResponse],
    responses={
        401: {"model": ErrorResponse[None]},
        403: {"model": ErrorResponse[None]},
        404: {"model": ErrorResponse[None]},
        409: {"model": ErrorResponse[None]},
        422: {"model": ErrorResponse[list[dict[str, str]]]},
    },
)
async def retry_integration_operation(
    project_id: str,
    operation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry persisted Drive permission operations with a safe desired state."""
    _require_lead_sa(current_user)
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    await ensure_project_access(db, project, current_user, TingkatAkses.BACA)

    result = await db.execute(
        select(IntegrationOperation).where(
            IntegrationOperation.id == operation_id,
            IntegrationOperation.project_id == project_id,
        )
    )
    operation = result.scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Integration operation not found.")
    if operation.status != "failed" or not operation.retryable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This operation cannot be retried safely.",
        )
    context = operation.context or {}
    if operation.operation_type == "drive_permission" and operation.action == "reassign_sa_access":
        sa_result = await db.execute(select(User).where(User.id == project.assigned_sa))
        assigned_sa = sa_result.scalar_one_or_none()
        if (
            project.gdrive_folder_id != context.get("master_folder_id")
            or assigned_sa is None
            or assigned_sa.email.lower() != str(context.get("new_sa_email", "")).lower()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The project assignment changed; reconcile permissions from the current assignment.",
            )

        async def perform() -> None:
            await folder_provisioner.reassign_sa_access(
                project.gdrive_folder_id,
                context.get("old_sa_email"),
                assigned_sa.email,
            )

        outcome = "Drive editor access matches the assigned SA."
        actionable_failure = (
            "The SA reassignment is saved, but Drive permissions may be stale. "
            "Restore Drive access and retry this idempotent permission update."
        )
    elif (
        operation.operation_type == "drive_permission"
        and operation.action == "document_review_unlock"
    ):
        document_result = await db.execute(
            select(Document).where(
                Document.id_doc == context.get("document_id"),
                Document.id_project == project_id,
            )
        )
        document = document_result.scalar_one_or_none()
        sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
        sales_user = sales_result.scalar_one_or_none()
        if (
            document is None
            or document.status != "Reviewed"
            or project.dq_number is None
            or project.gdrive_solutions_folder_id != context.get("folder_id")
            or sales_user is None
            or sales_user.email.lower() != str(context.get("sales_email", "")).lower()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The project or reviewed document state changed; this Drive action is no longer current.",
            )

        async def perform() -> None:
            await folder_provisioner.unlock_solutions_folder(
                project.gdrive_solutions_folder_id,
                sales_user.email,
            )

        outcome = "Sales viewer access to the Solutions folder is restored."
        actionable_failure = (
            "The document review is saved, but Sales access may remain locked. "
            "Restore Drive access and retry this idempotent unlock."
        )
    elif operation.operation_type == "sla" and operation.action in {
        "solutions_lock",
        "solutions_unlock",
    }:
        desired_locked = operation.action == "solutions_lock"
        sla_result = await db.execute(
            select(SLATracking).where(SLATracking.project_id == project_id)
        )
        sla_tracking = sla_result.scalar_one_or_none()
        if sla_tracking is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The project's SLA tracker is no longer available.",
            )
        if (project.dq_number is None) != desired_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The DQ state changed; the recorded SLA permission action is no longer current.",
            )
        if not project.gdrive_solutions_folder_id or not project.sales_pic:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The project no longer has the required Solutions folder and Sales PIC.",
            )
        sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
        sales_user = sales_result.scalar_one_or_none()
        if sales_user is None:
            raise HTTPException(status_code=409, detail="The project's Sales PIC is unavailable.")
        if desired_locked:
            perform = lambda: folder_provisioner.lock_solutions_folder(
                project.gdrive_solutions_folder_id, sales_user.email
            )
            outcome = "Sales access to the Solutions folder is locked."
            actionable_failure = (
                "The SLA lock is still unresolved. Restore Drive access and retry this idempotent lock."
            )
        else:
            perform = lambda: folder_provisioner.unlock_solutions_folder(
                project.gdrive_solutions_folder_id, sales_user.email
            )
            outcome = "Sales viewer access to the Solutions folder is restored."
            actionable_failure = (
                "The DQ number is saved but Solutions access may remain locked. "
                "Restore Drive access and retry this idempotent unlock."
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This operation has no safe manual retry path.",
        )

    await begin_retry(db, operation)
    await retry_side_effect(
        operation.id,
        perform=perform,
        outcome=outcome,
        actionable_failure=actionable_failure,
    )
    await db.refresh(operation)
    if operation.status == "succeeded" and operation.operation_type == "sla":
        now = datetime.now(timezone.utc)
        was_locked = sla_tracking.is_locked
        old_locked_at = sla_tracking.locked_at
        if desired_locked:
            sla_tracking.is_locked = True
            sla_tracking.locked_at = now
            action = "lock"
            new_value = {
                "is_locked": True,
                "locked_at": now.isoformat(),
                "reason": "SLA Drive permission retry",
            }
        else:
            sla_tracking.is_locked = False
            sla_tracking.unlocked_at = now
            action = "unlock"
            new_value = {
                "is_locked": False,
                "unlocked_at": now.isoformat(),
                "delay_days": sla_tracking.days_elapsed,
            }
        await sla_timer._create_audit_log(
            entity_type="folder",
            entity_id=project_id,
            action=action,
            old_value={
                "is_locked": was_locked,
                "locked_at": old_locked_at.isoformat() if old_locked_at else None,
            },
            new_value=new_value,
            db=db,
        )
        await db.commit()
    elif operation.status == "succeeded" and operation.action == "document_review_unlock":
        sla_result = await db.execute(
            select(SLATracking).where(SLATracking.project_id == project_id)
        )
        sla_tracking = sla_result.scalar_one_or_none()
        if sla_tracking is not None and sla_tracking.is_locked:
            now = datetime.now(timezone.utc)
            old_locked_at = sla_tracking.locked_at
            sla_tracking.is_locked = False
            sla_tracking.unlocked_at = now
            await sla_timer._create_audit_log(
                entity_type="folder",
                entity_id=project_id,
                action="unlock",
                old_value={
                    "is_locked": True,
                    "locked_at": old_locked_at.isoformat() if old_locked_at else None,
                },
                new_value={
                    "is_locked": False,
                    "unlocked_at": now.isoformat(),
                    "delay_days": sla_tracking.days_elapsed,
                },
                db=db,
            )
            await db.commit()
    return success_response(
        data=serialize_operation(operation),
        message="Integration operation retry recorded.",
    )


@router.post(
    "/projects/{project_id}/integration-operations/{operation_id}/repair",
    summary="Record operator-confirmed manual email recovery",
    response_model=SuccessResponse[IntegrationOperationResponse],
    responses={
        401: {"model": ErrorResponse[None]},
        403: {"model": ErrorResponse[None]},
        404: {"model": ErrorResponse[None]},
        409: {"model": ErrorResponse[None]},
        422: {"model": ErrorResponse[list[dict[str, str]]]},
    },
)
async def record_manual_email_repair(
    project_id: str,
    operation_id: uuid.UUID,
    confirmation: ManualEmailRepairRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record human-confirmed recovery without contacting the email provider."""
    _require_lead_sa(current_user)
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    await ensure_project_access(db, project, current_user, TingkatAkses.BACA)

    result = await db.execute(
        select(IntegrationOperation)
        .where(
            IntegrationOperation.id == operation_id,
            IntegrationOperation.project_id == project_id,
        )
        .with_for_update()
    )
    operation = result.scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Integration operation not found.")
    if (
        operation.operation_type != "email_delivery"
        or operation.status != "failed"
        or "manual_repair" in (operation.context or {})
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an unrepaired failed email operation can be recorded as manually resolved.",
        )

    context = dict(operation.context or {})
    context["manual_repair"] = {
        "actor_user_id": str(current_user.id),
        "repaired_at": datetime.now(timezone.utc).isoformat(),
        "recipient_checked_not_received": confirmation.recipient_checked_not_received,
        "manually_delivered_outside_app": confirmation.manually_delivered_outside_app,
    }
    operation.context = context
    await db.commit()
    await db.refresh(operation)
    return success_response(
        data=serialize_operation(operation),
        message="Operator-confirmed manual email recovery recorded; provider delivery was not confirmed.",
    )


@router.get(
    "/projects/pending-assignment",
    summary="Daftar proyek yang menunggu assignment",
    description=(
        "Menampilkan proyek-proyek berstatus 'Awaiting Assignment' "
        "yang siap ditugaskan ke SA. Hanya untuk Lead_SA."
    ),
)
async def get_pending_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar proyek yang berstatus 'Awaiting Assignment'.
    Hanya Lead_SA yang bisa mengakses endpoint ini.
    """
    _require_lead_sa(current_user)

    # Query proyek dengan status "Awaiting Assignment"
    result = await db.execute(
        select(Project)
        .where(Project.status == status_konst.AWAITING_ASSIGNMENT)
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    # Format response
    projects_data = [
        ProjectBrief(
            id_project=p.id_project,
            project_name=p.project_name,
            customer_name=p.customer_name,
            status=p.status,
            bant_score=p.bant_score,
            use_case_tags=p.use_case_tags,
            assigned_sa=p.assigned_sa,
            assigned_at=p.assigned_at,
            target_submit=p.target_submit,
            gdrive_folder_id=p.gdrive_folder_id,
            folder_provisioning_status=p.folder_provisioning_status,
        ).model_dump(mode="json")
        for p in projects
    ]

    return success_response(
        data=projects_data,
        message=f"Ditemukan {len(projects_data)} proyek menunggu assignment.",
    )


@router.get(
    "/sa/available",
    summary="Daftar SA yang tersedia dengan workload",
    description=(
        "Menampilkan semua SA yang terdaftar di sistem beserta jumlah proyek aktif "
        "masing-masing (definisi sama dengan `/workload/beban`: bukan soft-deleted, status bukan "
        "Closed/Lost/On Hold, SA utama + SA tambahan). Hanya untuk Lead_SA."
    ),
)
async def get_available_sa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar SA beserta jumlah proyek aktif (definisi workload, lihat `hitung_project_aktif_per_sa`).
    Hanya Lead_SA yang bisa mengakses endpoint ini.
    """
    _require_lead_sa(current_user)

    # Query semua kandidat SA: user berrole SA atau Lead_SA (ADR 0012)
    sa_result = await db.execute(select(User).where(User.role.in_(PERAN_DAPAT_DITUGASKAN)).order_by(User.name))
    sa_users = sa_result.scalars().all()

    # Definisi "project aktif" sama dengan `/workload/beban` (satu sumber di services/workload).
    active_counts = await hitung_project_aktif_per_sa(db)

    # Format response
    sa_data = [
        SAAvailability(
            id=sa.id,
            name=sa.name,
            email=sa.email,
            role=str(sa.role),
            active_project_count=active_counts.get(sa.id, 0),
        ).model_dump(mode="json")
        for sa in sa_users
    ]

    return success_response(
        data=sa_data,
        message=f"Ditemukan {len(sa_data)} SA tersedia.",
    )



@router.post(
    "/projects/{project_id}/assign",
    summary="Assign SA ke proyek",
    description=(
        "Menugaskan SA ke proyek yang berstatus 'Awaiting Assignment'. "
        "Update status menjadi 'Assigned', kirim notifikasi ke SA, "
        "dan trigger folder provisioning. Hanya untuk Lead_SA."
    ),
)
async def assign_sa_to_project(
    project_id: str,
    body: AssignRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Assign SA ke proyek tertentu.

    Flow:
    1. Validasi role Lead_SA
    2. Validasi proyek ada dan berstatus "Awaiting Assignment"
    3. Validasi SA ada dan role-nya "SA"
    4. Update proyek: status="Assigned", assigned_sa, assigned_at
    5. Insert notifikasi ke SA yang ditugaskan
    6. Trigger Folder_Provisioner async
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada dan berstatus "Awaiting Assignment" ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    if project.status != status_konst.AWAITING_ASSIGNMENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Proyek tidak bisa di-assign karena statusnya '{project.status}'. "
                f"Hanya proyek berstatus 'Awaiting Assignment' yang bisa di-assign."
            ),
        )

    # === 2. Validasi SA ada dan role-nya SA ===
    sa_result = await db.execute(select(User).where(User.id == body.sa_id))
    sa_user = sa_result.scalar_one_or_none()

    if sa_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SA dengan ID '{body.sa_id}' tidak ditemukan.",
        )

    if sa_user.role not in PERAN_DAPAT_DITUGASKAN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"User '{sa_user.name}' memiliki role '{sa_user.role}', "
                f"bukan 'SA' atau 'Lead_SA'. Hanya user dengan role SA atau Lead_SA "
                f"yang bisa ditugaskan."
            ),
        )

    # === 2a. Tentukan Lead_SA proyek (wajib sejak Assigned; ADR 0014) ===
    lead_sa_id = await tentukan_lead_sa(db, body.lead_sa_id, current_user)

    # === 2b. Lookup email Sales (requester) untuk provisioning folder ===
    sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
    sales_user = sales_result.scalar_one_or_none()
    sales_email = sales_user.email if sales_user else None

    # === 3. Update proyek ===
    now = datetime.now(timezone.utc)
    project.status = status_konst.ASSIGNED
    project.assigned_sa = body.sa_id
    project.lead_sa = lead_sa_id
    project.assigned_at = now
    project.updated_at = now
    # Tandai provisioning akan berjalan (background task men-set 'provisioned'/'failed')
    project.folder_provisioning_status = "pending"

    # === 4. Insert notifikasi ke SA ===
    notification = NotificationLog(
        id=_generate_notification_id(),
        event_type="assignment",
        recipient_user_id=body.sa_id,
        channel="in-app",
        status="sent",
        reference_id=project_id,
        notification_metadata={
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "bant_score": project.bant_score,
            "use_case_tags": project.use_case_tags or [],
            "assigned_by": current_user.name,
        },
        created_at=now,
    )
    db.add(notification)

    # === Auto-seed checklist subtask default (idempoten) ===
    # Subtask default langsung ditugaskan ke SA proyek yang baru di-assign.
    await _seed_default_subtasks(db, project_id, project.assigned_sa)

    # Commit perubahan
    await db.commit()
    await db.refresh(project)

    logger.info(f"Proyek {project_id} di-assign ke SA {sa_user.email} oleh {current_user.email}")

    # === 5. Start SLA timer (Flow 2 DQ Number) ===
    # Buat row SLATracking agar GET /projects/{id}/sla-status aktif sejak H+0.
    # Service start_timer idempoten: skip bila tracker sudah ada (mis. re-assign),
    # jadi tidak akan membuat duplikat atau error pada assignment ulang.
    try:
        await sla_timer.start_timer(
            project_id=project_id,
            assigned_at=project.assigned_at,
            db=db,
        )
    except Exception as e:
        logger.warning(f"Gagal memulai SLA timer untuk proyek {project_id}: {e}")

    # === 6. Trigger Folder_Provisioner async ===
    # Hanya dijadwalkan bila email Sales ditemukan (provisioner butuh email Sales
    # untuk permission Viewer pada Inventory). folder_scheduled mencerminkan apakah
    # task benar-benar dijadwalkan (bukan hardcode True).
    folder_scheduled = False
    if sales_email is not None:
        background_tasks.add_task(
            _trigger_folder_provisioner,
            project_id,
            sa_user.email,
            current_user.email,
            sales_email,
        )
        folder_scheduled = True
    else:
        logger.warning(
            f"Email Sales (sales_pic={project.sales_pic}) tidak ditemukan untuk "
            f"proyek {project_id}; folder provisioning tidak dijadwalkan."
        )

    # === 7. Build response ===
    response_data = AssignmentResponse(
        project=ProjectBrief(
            id_project=project.id_project,
            project_name=project.project_name,
            customer_name=project.customer_name,
            status=project.status,
            bant_score=project.bant_score,
            use_case_tags=project.use_case_tags,
            assigned_sa=project.assigned_sa,
            assigned_at=project.assigned_at,
            target_submit=project.target_submit,
            gdrive_folder_id=project.gdrive_folder_id,
            folder_provisioning_status=project.folder_provisioning_status,
        ),
        assigned_sa_name=sa_user.name,
        notification_sent=True,
        folder_provisioning_triggered=folder_scheduled,
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message=f"Proyek '{project.project_name}' berhasil ditugaskan ke {sa_user.name}.",
    )


@router.post(
    "/projects/{project_id}/reassign",
    summary="Reassign SA ke proyek",
    description=(
        "Mengubah SA yang ditugaskan pada proyek yang sudah berstatus 'Assigned', 'In Progress', atau 'Submitted'. "
        "Hanya Lead_SA dan Admin yang dapat melakukan reassignment."
    ),
)
async def reassign_sa_to_project(
    project_id: str,
    body: AssignRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reassign SA ke proyek yang sudah memiliki SA sebelumnya.

    Flow:
    1. Validasi role Lead_SA atau Admin
    2. Validasi proyek ada dan berstatus 'Assigned', 'In Progress', 'Submitted', atau 'Awaiting Assignment'
    3. Validasi SA baru ada dan role-nya 'SA'
    4. Update proyek: assigned_sa ke SA baru
    5. Insert notifikasi ke SA baru
    6. Drive: SA baru diberi akses Editor, SA lama dicabut (bila folder sudah ada)
    7. Dari 'Awaiting Assignment': mulai timer SLA + provisioning folder (setara assign)

    Timer SLA yang sudah berjalan TIDAK direset (keputusan 2026-11-10) dan subtask tidak
    dipindahkan dari SA lama.
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    if project.status not in STATUS_BOLEH_GANTI_SA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Proyek tidak bisa di-reassign karena statusnya '{project.status}'. "
                f"Hanya proyek berstatus 'Assigned', 'In Progress', 'Submitted', "
                f"atau 'Awaiting Assignment' "
                f"yang bisa di-reassign."
            ),
        )

    # === 2. Validasi SA baru ada dan role-nya SA ===
    sa_result = await db.execute(select(User).where(User.id == body.sa_id))
    sa_user = sa_result.scalar_one_or_none()

    if sa_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SA dengan ID '{body.sa_id}' tidak ditemukan.",
        )

    if sa_user.role not in PERAN_DAPAT_DITUGASKAN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"User '{sa_user.name}' memiliki role '{sa_user.role}', "
                f"bukan 'SA' atau 'Lead_SA'. Hanya user dengan role SA atau Lead_SA "
                f"yang bisa ditugaskan."
            ),
        )

    # `lead_sa` wajib sejak Assigned (ADR 0014): isi bila kosong; yang sudah ada tidak ditimpa
    # (penggantian lewat PATCH /projects/{id}/people). Admin non-Lead_SA wajib memilih pada alur
    # assign awal (dari Awaiting Assignment); pada proyek lama yang sudah Assigned/Submitted tanpa
    # lead_sa, reassign tetap diizinkan dan admin tidak diam-diam menjadi lead_sa.
    if project.lead_sa is None and (
        body.lead_sa_id is not None
        or project.status == status_konst.AWAITING_ASSIGNMENT
        or current_user.role == PeranUser.LEAD_SA
    ):
        project.lead_sa = await tentukan_lead_sa(db, body.lead_sa_id, current_user)

    # === 3. Update proyek ===
    now = datetime.now(timezone.utc)
    old_sa_id = project.assigned_sa
    dari_pending = project.status == status_konst.AWAITING_ASSIGNMENT
    project.assigned_sa = body.sa_id
    project.assigned_at = now
    project.updated_at = now
    # SA utama tidak diulang di SA tambahan (ADR 0014): bila SA baru sebelumnya SA tambahan,
    # ia naik menjadi utama dan keluar dari `project_assignments`.
    await db.execute(
        delete(ProjectAssignment).where(
            ProjectAssignment.id_project == project_id, ProjectAssignment.user_id == body.sa_id
        )
    )

    # Email SA lama (untuk mencabut akses Drive). FK `projects.assigned_sa` menjamin user ada.
    sa_lama_email: Optional[str] = None
    if old_sa_id is not None and old_sa_id != body.sa_id:
        sa_lama_email = (
            await db.execute(select(User.email).where(User.id == old_sa_id))
        ).scalar_one()

    # Jika status masih Awaiting Assignment, ubah ke Assigned (setara assign: tandai provisioning)
    sales_email: Optional[str] = None
    if dari_pending:
        project.status = status_konst.ASSIGNED
        # `sales_pic` opsional (ADR 0014): tanpa Sales, email kosong (sama seperti assign).
        if project.sales_pic is not None:
            sales_email = (
                await db.execute(select(User.email).where(User.id == project.sales_pic))
            ).scalar_one_or_none()
        project.folder_provisioning_status = "pending"

    # === 4. Insert notifikasi ke SA baru ===
    notification = NotificationLog(
        id=_generate_notification_id(),
        event_type="assignment",
        recipient_user_id=body.sa_id,
        channel="in-app",
        status="sent",
        reference_id=project_id,
        notification_metadata={
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "assigned_by": current_user.name,
            "previous_sa_id": str(old_sa_id) if old_sa_id else None,
        },
        created_at=now,
    )
    db.add(notification)

    # === Auto-seed checklist subtask default (idempoten) ===
    # Subtask default langsung ditugaskan ke SA proyek. Pada re-assign yang sudah
    # punya subtask, seeding di-skip (idempoten) sehingga tidak menduplikasi.
    await _seed_default_subtasks(db, project_id, project.assigned_sa)

    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Proyek {project_id} di-reassign ke SA {sa_user.email} "
        f"oleh {current_user.email} (sebelumnya: {old_sa_id})"
    )

    # === 5. Dari Awaiting Assignment: timer SLA + provisioning folder (setara assign) ===
    if dari_pending:
        try:
            await sla_timer.start_timer(
                project_id=project_id, assigned_at=project.assigned_at, db=db
            )
        except Exception as e:
            logger.warning(f"Gagal memulai SLA timer untuk proyek {project_id}: {e}")
        if sales_email is not None:
            background_tasks.add_task(
                _trigger_folder_provisioner,
                project_id,
                sa_user.email,
                current_user.email,
                sales_email,
            )
        else:  # tanpa Sales (ADR 0014); penerima akses Drive mengikuti orang di tiket #120
            logger.warning(
                f"Proyek {project_id} tanpa Sales PIC; folder provisioning tidak dijadwalkan."
            )
    elif project.gdrive_folder_id:
        # Folder sudah ada: pindahkan akses Editor dari SA lama ke SA baru.
        background_tasks.add_task(
            _pindahkan_akses_drive_sa,
            project_id,
            project.gdrive_folder_id,
            sa_lama_email,
            sa_user.email,
            current_user.id,
        )

    # === 6. Build response ===
    return success_response(
        data={
            "id_project": project.id_project,
            "project_name": project.project_name,
            "assigned_sa": str(project.assigned_sa),
            "assigned_sa_name": sa_user.name,
            "assigned_sa_email": sa_user.email,
            "status": project.status,
        },
        message=f"SA proyek '{project.project_name}' berhasil diubah ke {sa_user.name}.",
    )


@router.post(
    "/projects/{project_id}/provision-folder",
    summary="Provision ulang folder proyek",
    description=(
        "Men-trigger ulang provisioning folder Google Drive untuk proyek yang belum berhasil "
        "diprovision; kegagalan parsial dengan nomor tersimpan dilanjutkan pada folder yang sama. "
        "Mengembalikan 409 setelah sukses. Hanya untuk Lead_SA atau Admin."
    ),
)
async def provision_folder(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-provision folder proyek (ADR 0006: idempotency guard sederhana).

    Flow:
    1. Validasi role Lead_SA/Admin.
    2. Validasi proyek ada (404).
    3. Reject an associated folder unless a failed attempt has a persisted number to resume.
    4. Set folder_provisioning_status='pending' (commit), then schedule the same provisioner
       with the assigned SA, requesting Lead SA, and Sales PIC emails.

    Memakai jalur persist yang sama dengan assignment (background task mem-persist
    gdrive_folder_id + gdrive_solutions_folder_id + status).
    """
    _require_lead_sa(current_user)

    # === 1. Validasi proyek ada ===
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # === 2. Idempotency guard: allow failed partial work only when its number is reserved ===
    resumable_partial_folder = (
        project.gdrive_folder_number is not None
        and project.folder_provisioning_status == "failed"
    )
    if project.gdrive_folder_id is not None and not resumable_partial_folder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Folder proyek '{project_id}' sudah ter-provision "
                f"(gdrive_folder_id='{project.gdrive_folder_id}'). "
                "Re-provision hanya untuk proyek yang belum berhasil diprovision."
            ),
        )

    # === 3. Lookup email SA assigned & Sales (requester) ===
    sa_email = None
    if project.assigned_sa is not None:
        sa_result = await db.execute(select(User).where(User.id == project.assigned_sa))
        sa_user = sa_result.scalar_one_or_none()
        sa_email = sa_user.email if sa_user else None

    sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
    sales_user = sales_result.scalar_one_or_none()
    sales_email = sales_user.email if sales_user else None

    if sa_email is None or sales_email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provisioning tidak bisa dijadwalkan: email SA assigned dan/atau "
                "Sales PIC tidak ditemukan. Pastikan proyek sudah di-assign ke SA."
            ),
        )

    # === 4. Tandai pending lalu jadwalkan provisioning ===
    project.folder_provisioning_status = "pending"
    await db.commit()

    background_tasks.add_task(
        _trigger_folder_provisioner,
        project_id,
        sa_email,
        current_user.email,
        sales_email,
    )

    logger.info(
        f"Re-provision folder dijadwalkan untuk proyek {project_id} oleh {current_user.email}."
    )

    return success_response(
        data={
            "id_project": project.id_project,
            "folder_provisioning_status": project.folder_provisioning_status,
            "folder_provisioning_triggered": True,
        },
        message=f"Provisioning folder untuk proyek '{project.project_name}' telah dijadwalkan.",
    )
