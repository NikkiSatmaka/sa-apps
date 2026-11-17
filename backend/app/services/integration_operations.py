"""Persist side-effect attempts without coupling them to project transactions."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IntegrationOperation

logger = logging.getLogger(__name__)


async def begin_operation(
    *,
    project_id: Optional[str],
    operation_type: str,
    action: str,
    actor_user_id: Optional[uuid.UUID] = None,
    context: Optional[dict] = None,
    retryable: bool = False,
) -> Optional[uuid.UUID]:
    """Commit a pending attempt before invoking its external provider."""
    now = datetime.now(UTC)
    operation_id = uuid.uuid4()
    attempt = {
        "attempt": 1,
        "status": "pending",
        "started_at": now.isoformat(),
        "finished_at": None,
        "outcome": None,
        "actionable_error": None,
    }
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            db.add(
                IntegrationOperation(
                    id=operation_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    operation_type=operation_type,
                    action=action,
                    status="pending",
                    attempts=[attempt],
                    context=context or {},
                    retryable=retryable,
                    started_at=now,
                )
            )
            await db.commit()
        return operation_id
    except Exception:
        logger.exception("Could not persist pending integration operation %s", action)
        return None


async def finish_operation(
    operation_id: Optional[uuid.UUID],
    *,
    succeeded: bool,
    outcome: str,
    actionable_error: Optional[str] = None,
) -> None:
    """Persist the provider outcome; logging failure never replaces project work."""
    if operation_id is None:
        return

    now = datetime.now(UTC)
    status = "succeeded" if succeeded else "failed"
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            operation = await db.get(IntegrationOperation, operation_id)
            if operation is None:
                return
            attempts = list(operation.attempts or [])
            if attempts:
                last_attempt = dict(attempts[-1])
                last_attempt.update(
                    status=status,
                    finished_at=now.isoformat(),
                    outcome=outcome,
                    actionable_error=actionable_error,
                )
                attempts[-1] = last_attempt
            operation.attempts = attempts
            operation.status = status
            operation.finished_at = now
            operation.outcome = outcome
            operation.actionable_error = actionable_error
            await db.commit()
    except Exception:
        logger.exception("Could not persist integration operation outcome %s", operation_id)


async def run_side_effect(
    *,
    project_id: Optional[str],
    operation_type: str,
    action: str,
    perform: Callable[[], Awaitable[None]],
    outcome: str,
    actionable_failure: str,
    actor_user_id: Optional[uuid.UUID] = None,
    context: Optional[dict] = None,
    retryable: bool = False,
) -> bool:
    """Run one best-effort provider action and persist its observable result."""
    operation_id = await begin_operation(
        project_id=project_id,
        operation_type=operation_type,
        action=action,
        actor_user_id=actor_user_id,
        context=context,
        retryable=retryable,
    )
    try:
        await perform()
    except Exception as error:  # noqa: BLE001 - integration failures never block core work
        detail = str(error).strip()
        actionable_error = actionable_failure
        if detail:
            actionable_error = f"{actionable_failure} Provider error: {detail[:1000]}"
        await finish_operation(
            operation_id,
            succeeded=False,
            outcome=f"{action} failed.",
            actionable_error=actionable_error,
        )
        logger.warning("Integration operation %s failed: %s", action, error)
        return False

    await finish_operation(operation_id, succeeded=True, outcome=outcome)
    return True


async def list_project_operations(db: AsyncSession, project_id: str) -> list[dict]:
    """Serialize persisted operations for a project, newest first."""
    result = await db.execute(
        select(IntegrationOperation)
        .where(IntegrationOperation.project_id == project_id)
        .order_by(IntegrationOperation.started_at.desc(), IntegrationOperation.id.desc())
    )
    return [serialize_operation(operation) for operation in result.scalars().all()]


def serialize_operation(operation: IntegrationOperation) -> dict:
    return {
        "id": str(operation.id),
        "operation_type": operation.operation_type,
        "action": operation.action,
        "status": operation.status,
        "attempts": operation.attempts or [],
        "started_at": operation.started_at.isoformat() if operation.started_at else None,
        "finished_at": operation.finished_at.isoformat() if operation.finished_at else None,
        "outcome": operation.outcome,
        "actionable_error": operation.actionable_error,
        "retryable": operation.retryable,
        "context": operation.context or {},
    }


async def begin_retry(db: AsyncSession, operation: IntegrationOperation) -> None:
    """Append a manual attempt to a previously failed, explicitly safe operation."""
    now = datetime.now(UTC)
    attempts = list(operation.attempts or [])
    attempts.append(
        {
            "attempt": len(attempts) + 1,
            "status": "pending",
            "started_at": now.isoformat(),
            "finished_at": None,
            "outcome": None,
            "actionable_error": None,
        }
    )
    operation.attempts = attempts
    operation.status = "pending"
    operation.started_at = now
    operation.finished_at = None
    operation.outcome = None
    operation.actionable_error = None
    await db.commit()


async def retry_side_effect(
    operation_id: uuid.UUID,
    *,
    perform: Callable[[], Awaitable[None]],
    outcome: str,
    actionable_failure: str,
) -> bool:
    try:
        await perform()
    except Exception as error:  # noqa: BLE001 - recovery remains non-blocking
        detail = str(error).strip()
        message = actionable_failure
        if detail:
            message = f"{actionable_failure} Provider error: {detail[:1000]}"
        await finish_operation(
            operation_id,
            succeeded=False,
            outcome="Manual retry failed.",
            actionable_error=message,
        )
        return False
    await finish_operation(operation_id, succeeded=True, outcome=outcome)
    return True
