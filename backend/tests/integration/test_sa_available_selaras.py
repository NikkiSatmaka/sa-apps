"""
Integrasi `GET /sa/available`: `active_project_count` harus sama dengan `project_aktif` di
`/workload/beban` (keputusan pemilik produk, rujukan PR #153, #142/#143).

Definisi tunggal (`app.services.workload`): tidak soft-deleted, status bukan Closed, Lost, On Hold,
SA utama + SA tambahan (`ProjectAssignments`) dihitung sekali per SA.
"""

from datetime import UTC, datetime

import pytest

from app.models.project_assignment import ProjectAssignment
from tests.integration.conftest import patch_session_factory
from tests.integration.support_assignment import bangun_dunia

TERSEDIA = "/api/v1/sa/available"
BEBAN = "/api/v1/workload/beban"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _tersedia(api, dunia) -> dict[str, int]:
    resp = await api.client.get(TERSEDIA, headers=dunia.h["lead"])
    assert resp.status_code == 200, resp.text
    return {u["email"]: u["active_project_count"] for u in resp.json()["data"]}


async def _beban(api, dunia) -> dict[str, int]:
    resp = await api.client.get(BEBAN, headers=dunia.h["lead"])
    assert resp.status_code == 200, resp.text
    return {i["email"]: i["project_aktif"] for i in resp.json()["data"]["items"]}


async def _tambahan(dunia, id_project: str, user):
    dunia.db.add(ProjectAssignment(id_project=id_project, user_id=user.id, added_by=dunia.lead.id))
    await dunia.db.commit()


@pytest.mark.parametrize("status", ["Won", "Handed Over"])
async def test_won_dan_handed_over_dihitung_aktif(dunia, api, status):
    await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)

    assert (await _tersedia(api, dunia))[dunia.sa.email] == 1


@pytest.mark.parametrize("status", ["On Hold", "Closed", "Lost"])
async def test_on_hold_closed_lost_tidak_dihitung(dunia, api, status):
    await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)

    assert (await _tersedia(api, dunia))[dunia.sa.email] == 0


async def test_soft_deleted_tidak_dihitung(dunia, api):
    await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa.id,
        deleted_at=datetime.now(UTC),
        deleted_by=dunia.lead.id,
    )

    assert (await _tersedia(api, dunia))[dunia.sa.email] == 0


async def test_sa_tambahan_dihitung(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    await _tambahan(dunia, p.id_project, dunia.sa2)

    hitung = await _tersedia(api, dunia)

    assert hitung[dunia.sa.email] == 1
    assert hitung[dunia.sa2.email] == 1


async def test_sa_utama_sekaligus_tambahan_tidak_dobel(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    await _tambahan(dunia, p.id_project, dunia.sa)

    assert (await _tersedia(api, dunia))[dunia.sa.email] == 1


async def test_paritas_dengan_workload_beban(dunia, api):
    a = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(status="Won", assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(status="Handed Over", assigned_sa=dunia.sa2.id)
    await dunia.buat_proyek(status="On Hold", assigned_sa=dunia.sa2.id)
    await dunia.buat_proyek(status="Closed", assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(status="Lost", assigned_sa=dunia.lead.id)
    await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa2.id,
        deleted_at=datetime.now(UTC),
        deleted_by=dunia.lead.id,
    )
    b = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa2.id)
    await _tambahan(dunia, a.id_project, dunia.lead)
    await _tambahan(dunia, b.id_project, dunia.sa)
    await _tambahan(dunia, b.id_project, dunia.sa2)

    tersedia = await _tersedia(api, dunia)

    assert tersedia == await _beban(api, dunia)
    assert tersedia[dunia.sa.email] == 3
    assert tersedia[dunia.sa2.email] == 2
    assert tersedia[dunia.lead.email] == 1
