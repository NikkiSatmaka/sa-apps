"""
`Assigned` → `In Progress` otomatis (issue #122, ADR 0013, spec §2.0), terhadap Postgres nyata.

Pemicu: activity log Project pertama (lewat `POST /activity-logs` atau `POST /calendar/map`) atau
subtask yang menjadi `in_progress` pertama. Perpindahan hanya terjadi dari `Assigned`, tercatat di
audit log, dan terjadi sekali saja.
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project
from tests.integration.helpers_t60 import API, bearer, buat_proyek, buat_user
from tests.integration.model_helpers import bangun_subtask

LOGS = f"{API}/activity-logs"
CAL = f"{API}/calendar"


def _badan_log(id_project: str, **o) -> dict:
    dasar = {
        "id_project": id_project,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1.5",
        "raw_notes": "diskusi arsitektur",
    }
    dasar.update(o)
    return dasar


async def _siap(db, status="Assigned", **o):
    sales = await buat_user(db, "Sales")
    sa = await buat_user(db, "SA")
    proyek = await buat_proyek(db, sales, assigned_sa=sa, status=status, **o)
    return sa, proyek


async def _status(db, id_project: str) -> str:
    q = select(Project.status).where(Project.id_project == id_project)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one()


async def _audit_status(db, id_project: str) -> list[AuditLog]:
    q = select(AuditLog).where(
        AuditLog.entity_id == id_project, AuditLog.action == "status_change"
    )
    return list((await db.execute(q)).scalars().all())


async def test_log_pertama_memindahkan_assigned_ke_in_progress_dan_diaudit(
    api, db_session, fake_llm
):
    sa, proyek = await _siap(db_session)

    resp = await api.client.post(LOGS, json=_badan_log(proyek.id_project), headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert await _status(db_session, proyek.id_project) == "In Progress"
    audit = await _audit_status(db_session, proyek.id_project)
    assert len(audit) == 1
    assert audit[0].old_value == {"status": "Assigned"}
    assert audit[0].new_value["status"] == "In Progress"
    assert audit[0].performed_by == sa.id


async def test_log_kedua_tidak_mengulang_perpindahan(api, db_session, fake_llm):
    sa, proyek = await _siap(db_session)

    for _ in range(2):
        resp = await api.client.post(LOGS, json=_badan_log(proyek.id_project), headers=bearer(sa))
        assert resp.status_code == 201, resp.text

    assert await _status(db_session, proyek.id_project) == "In Progress"
    assert len(await _audit_status(db_session, proyek.id_project)) == 1


async def test_log_setelah_submitted_tidak_menarik_status_kembali(api, db_session, fake_llm):
    sa, proyek = await _siap(db_session, status="Submitted")

    resp = await api.client.post(LOGS, json=_badan_log(proyek.id_project), headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert await _status(db_session, proyek.id_project) == "Submitted"
    assert await _audit_status(db_session, proyek.id_project) == []


async def test_log_saat_on_hold_tidak_mengubah_status(api, db_session, fake_llm):
    sa, proyek = await _siap(db_session, status="On Hold", previous_status="Assigned")

    resp = await api.client.post(LOGS, json=_badan_log(proyek.id_project), headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert await _status(db_session, proyek.id_project) == "On Hold"


async def test_log_non_project_tidak_mengubah_status_proyek(api, db_session, fake_llm):
    sa, proyek = await _siap(db_session)
    badan = {
        "work_type": "Non-Project",
        "subtask_category": "Internal Meeting",
        "duration_hours": "1",
        "raw_notes": "rapat internal",
    }

    resp = await api.client.post(LOGS, json=badan, headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert await _status(db_session, proyek.id_project) == "Assigned"


async def test_pemetaan_kalender_pertama_memindahkan_ke_in_progress(api, db_session):
    sa, proyek = await _siap(db_session)
    badan = {
        "gcal_event_id": "evt-122",
        "work_type": "Project",
        "project_id": proyek.id_project,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Diskusi kebutuhan",
    }

    resp = await api.client.post(f"{CAL}/map", json=badan, headers=bearer(sa))

    assert resp.status_code == 201, resp.text
    assert await _status(db_session, proyek.id_project) == "In Progress"
    assert len(await _audit_status(db_session, proyek.id_project)) == 1


async def test_subtask_in_progress_pertama_memindahkan_ke_in_progress(api, db_session):
    sa, proyek = await _siap(db_session)
    st = bangun_subtask(proyek.id_project, assigned_sa=sa.id)
    db_session.add(st)
    await db_session.commit()

    resp = await api.client.patch(
        f"{API}/projects/subtasks/{st.id_subtask}/status",
        json={"status": "in_progress"},
        headers=bearer(sa),
    )

    assert resp.status_code == 200, resp.text
    assert await _status(db_session, proyek.id_project) == "In Progress"
    assert len(await _audit_status(db_session, proyek.id_project)) == 1


@pytest.mark.parametrize("status_subtask", ["open", "done"])
async def test_subtask_selain_in_progress_tidak_memicu(api, db_session, status_subtask):
    sa, proyek = await _siap(db_session)
    st = bangun_subtask(proyek.id_project, assigned_sa=sa.id, status="in_progress")
    db_session.add(st)
    await db_session.commit()

    resp = await api.client.patch(
        f"{API}/projects/subtasks/{st.id_subtask}/status",
        json={"status": status_subtask},
        headers=bearer(sa),
    )

    assert resp.status_code == 200, resp.text
    assert await _status(db_session, proyek.id_project) == "Assigned"
