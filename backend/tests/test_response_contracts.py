import pytest

from pydantic import ValidationError

from app.schemas.calendar import CalendarSyncErrorData, CalendarSyncResponse
from app.schemas.integration_operation import IntegrationOperationResponse
from app.schemas.project import ProjectListPageResponse
from app.schemas.response import ErrorResponse, SuccessResponse


def test_success_response_has_typed_success_discriminator_and_payload():
    response = SuccessResponse[dict[str, int]](
        status="success",
        data={"count": 3},
        message="Loaded",
    )

    assert response.model_dump() == {
        "status": "success",
        "data": {"count": 3},
        "message": "Loaded",
    }


def test_error_response_preserves_typed_error_data_in_standard_envelope():
    response = ErrorResponse[dict[str, dict[str, str]]](
        status="error",
        data={"integration_operation": {"status": "failed"}},
        message="Calendar session not found.",
    )


    assert response.model_dump() == {
        "status": "error",
        "data": {"integration_operation": {"status": "failed"}},
        "message": "Calendar session not found.",
    }



def test_project_list_success_contract_types_page_and_item_fields():
    response = SuccessResponse[ProjectListPageResponse](
        status="success",
        data={
            "items": [
                {
                    "id_project": "PRJ-1",
                    "project_name": "Project",
                    "customer_name": "Customer",
                    "status": "Assigned",
                    "qualification_state": "Qualified",
                    "dq_number": None,
                    "bant_score": 60,
                    "use_case_tags": [],
                    "estimasi_nilai": "100.00",
                    "target_submit": None,
                    "assigned_sa": None,
                    "created_by": None,
                    "product_pic": None,
                    "sales_pic": None,
                    "gdrive_folder_id": None,
                    "folder_provisioning_status": None,
                    "created_at": None,
                    "updated_at": None,
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 25,
            "total_pages": 1,
        },
        message="Ditemukan 1 proyek.",
    )

    assert response.data is not None
    assert response.data.items[0].id_project == "PRJ-1"


def test_operation_status_contract_keeps_attempt_history_and_actionable_failure():
    operation = IntegrationOperationResponse(
        id="1d3ec8f0-c224-4dae-ad31-bd11788dd38c",
        operation_type="calendar",
        action="sync_calendar",
        status="failed",
        attempts=[
            {
                "attempt": 1,
                "status": "failed",
                "started_at": "2026-11-16T09:00:00+00:00",
                "finished_at": "2026-11-16T09:00:01+00:00",
                "outcome": "Sync failed.",
                "actionable_error": "Reconnect Google Calendar.",
            }
        ],
        started_at="2026-11-16T09:00:00+00:00",
        finished_at="2026-11-16T09:00:01+00:00",
        outcome="Sync failed.",
        actionable_error="Reconnect Google Calendar.",
        retryable=False,
        context={"action": "sync_calendar"},
    )

    assert operation.attempts[0].actionable_error == "Reconnect Google Calendar."

def test_success_and_error_contracts_reject_the_other_discriminator():
    with pytest.raises(ValidationError):
        SuccessResponse[None](status="error", data=None, message="failed")

    with pytest.raises(ValidationError):
        ErrorResponse[None](status="success", data=None, message="ok")


def test_calendar_sync_contract_types_events_and_operation_failure_details():
    response = SuccessResponse[CalendarSyncResponse](
        data={
            "events": [],
            "total_events": 0,
            "integration_operation": None,
        },
        message="Synced",
    )
    failure = ErrorResponse[CalendarSyncErrorData](
        status="error",
        data={"integration_operation": None},
        message="Calendar session not found.",
    )

    assert response.data is not None and response.data.total_events == 0
    assert failure.data is not None and failure.data.integration_operation is None
