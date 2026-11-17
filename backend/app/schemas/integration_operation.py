from typing import Any, Literal

from pydantic import BaseModel


class IntegrationOperationAttemptResponse(BaseModel):
    attempt: int
    status: Literal["pending", "succeeded", "failed"]
    started_at: str
    finished_at: str | None = None
    outcome: str | None = None
    actionable_error: str | None = None


class ManualEmailRepairRequest(BaseModel):
    recipient_checked_not_received: Literal[True]
    manually_delivered_outside_app: Literal[True]


class IntegrationOperationResponse(BaseModel):
    id: str
    operation_type: str
    action: str
    status: Literal["pending", "succeeded", "failed"]
    attempts: list[IntegrationOperationAttemptResponse]
    started_at: str | None
    finished_at: str | None
    outcome: str | None
    actionable_error: str | None
    retryable: bool
    project_id: str | None = None
    context: dict[str, Any]
