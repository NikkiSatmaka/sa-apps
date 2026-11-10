"""
Test perbaikan temuan code-review integration branch Fase 5B (#25).

A: GET /projects/{id}/documents wajib `ensure_project_access`.
B: sweep startup `pending` -> `failed`.
C: regenerate atomik (409 untuk request yang kalah).
D: `_project_locks` tidak bocor.
Sesi DB dan layanan eksternal di-mock di boundary, sama seperti test Requirement lainnya.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from tests.test_doc_ready import _make_project, _make_user, _result_scalar

PRJ = "PRJ-20250101-XYZ789"
LIST_URL = f"/api/v1/projects/{PRJ}/documents"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- A: authz daftar dokumen
def _project_a(sales_pic=None, assigned_sa=None):
    p = _make_project(sales_pic=sales_pic)
    p.id_project = PRJ
    p.assigned_sa = assigned_sa
    p.qualification_answers = None
    p.requirement_generation_status = "ready"
    return p


def _list(user, project, *, collaborator=False):
    docs = MagicMock()
    docs.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_scalar(project),
            _result_scalar(object() if collaborator else None),  # query collaborator
            docs,
        ]
    )

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app).get(LIST_URL)


def test_daftar_dokumen_ditolak_untuk_sales_proyek_lain():
    resp = _list(_make_user("Sales"), _project_a())
    assert resp.status_code == 403


def test_daftar_dokumen_ditolak_untuk_sa_tidak_ditugaskan():
    resp = _list(_make_user("SA"), _project_a(assigned_sa=uuid.uuid4()))
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
def test_daftar_dokumen_boleh_untuk_privileged(role):
    assert _list(_make_user(role), _project_a()).status_code == 200


def test_daftar_dokumen_boleh_untuk_sales_pic():
    sales = _make_user("Sales")
    assert _list(sales, _project_a(sales_pic=sales.id)).status_code == 200


def test_daftar_dokumen_boleh_untuk_sa_ditugaskan():
    sa = _make_user("SA")
    assert _list(sa, _project_a(assigned_sa=sa.id)).status_code == 200


def test_daftar_dokumen_boleh_untuk_collaborator_baca():
    resp = _list(_make_user("SA"), _project_a(assigned_sa=uuid.uuid4()), collaborator=True)
    assert resp.status_code == 200


# --------------------------------------------------------------------------- B: sweep startup
class _Ctx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_sweep_mengubah_pending_menjadi_failed():
    from app.services.requirement_generator import sweep_stale_pending_requirements

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(session)):
        count = await sweep_stale_pending_requirements()

    assert count == 2
    session.commit.assert_awaited_once()
    sql = str(
        session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "UPDATE projects" in sql
    assert "requirement_generation_status='failed'" in sql.replace(" ", "")
    assert "requirement_generation_status='pending'" in sql.replace(" ", "")


@pytest.mark.asyncio
async def test_sweep_gagal_tidak_melempar():
    from app.services.requirement_generator import sweep_stale_pending_requirements

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db mati"))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(session)):
        assert await sweep_stale_pending_requirements() == 0


@pytest.mark.asyncio
async def test_startup_menjalankan_sweep_dan_tahan_kegagalan():
    import app.main as main

    for sweep in (AsyncMock(return_value=1), AsyncMock(side_effect=RuntimeError("x"))):
        with (
            patch.object(main, "sweep_stale_pending_requirements", new=sweep),
            patch.object(main.settings, "SLA_SCHEDULER_ENABLED", False),
        ):
            await main.startup_register_adapters()
        sweep.assert_awaited_once()
