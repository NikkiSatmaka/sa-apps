"""
Test tiket 5B-4 (#36): override Requirement per butir lewat API.

Seam: endpoint `/projects/{id}/requirement/items` (POST/PUT/DELETE) dengan TestClient.
DB di-mock. Butir hasil edit menyetel `is_overridden`, `source_hash` tidak berubah.
"""

import copy
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from tests.test_doc_ready import _make_project, _make_user, _result_scalar
from tests.test_requirement_documents_api import KONTEN, PRJ, _requirement

BASE = f"/api/v1/projects/{PRJ}/requirement/items"
HASH = "a" * 64


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _setup(user, project, doc, collaborator=False):
    """Urutan execute: project, requirement doc."""
    project.assigned_sa = getattr(project, "assigned_sa", None)
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=[_result_scalar(project), _result_scalar(doc)])
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return session


def _project(assigned_sa=None):
    p = _make_project()
    p.id_project = PRJ
    p.assigned_sa = assigned_sa
    p.collaborators = []
    return p


def _doc(status="Draft"):
    d = _requirement(status)
    d.content = copy.deepcopy(KONTEN)
    d.source_hash = HASH
    return d


def _sa_ditugaskan():
    user = _make_user("SA")
    return user, _project(assigned_sa=user.id)


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
def test_lead_sa_dan_admin_menambah_butir_dan_menyetel_override(role):
    doc = _doc()
    session = _setup(_make_user(role), _project(), doc)
    resp = TestClient(app).post(BASE, json={"kategori": "Teknis", "butir": "  Perlu HA  "})
    assert resp.status_code == 201
    assert len(doc.content) == 3
    baru = doc.content[-1]
    assert baru["kategori"] == "Teknis" and baru["butir"] == "Perlu HA"
    assert len(baru["id"]) == 8 and int(baru["id"], 16) >= 0
    assert doc.is_overridden is True
    assert doc.source_hash == HASH
    session.commit.assert_awaited()
    assert resp.json()["data"]["is_overridden"] is True


def test_sa_ditugaskan_mengubah_butir():
    user, project = _sa_ditugaskan()
    doc = _doc()
    _setup(user, project, doc)
    resp = TestClient(app).put(
        f"{BASE}/a1b2c3d4", json={"kategori": "Kepatuhan", "butir": "Wajib ISO 27001"}
    )
    assert resp.status_code == 200
    item = next(i for i in doc.content if i["id"] == "a1b2c3d4")
    assert item == {"id": "a1b2c3d4", "kategori": "Kepatuhan", "butir": "Wajib ISO 27001"}
    assert doc.is_overridden is True
    assert doc.source_hash == HASH


def test_sa_ditugaskan_menghapus_butir():
    user, project = _sa_ditugaskan()
    doc = _doc()
    _setup(user, project, doc)
    resp = TestClient(app).delete(f"{BASE}/e5f6a7b8")
    assert resp.status_code == 200
    assert [i["id"] for i in doc.content] == ["a1b2c3d4"]
    assert doc.is_overridden is True


def test_hapus_butir_terakhir_diizinkan():
    user, project = _sa_ditugaskan()
    doc = _doc()
    doc.content = [KONTEN[0]]
    _setup(user, project, doc)
    resp = TestClient(app).delete(f"{BASE}/a1b2c3d4")
    assert resp.status_code == 200
    assert doc.content == []


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_sales_ditolak_403_dan_tidak_mengubah(method):
    sales = _make_user("Sales")
    project = _project()
    project.sales_pic = sales.id
    doc = _doc()
    session = _setup(sales, project, doc)
    url = BASE if method == "post" else f"{BASE}/a1b2c3d4"
    kwargs = {} if method == "delete" else {"json": {"kategori": "Teknis", "butir": "x"}}
    resp = getattr(TestClient(app), method)(url, **kwargs)
    assert resp.status_code == 403
    assert doc.content == KONTEN
    assert doc.is_overridden is False
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_sa_tidak_ditugaskan_ditolak(method):
    doc = _doc()
    session = _setup(_make_user("SA"), _project(assigned_sa=uuid.uuid4()), doc)
    url = BASE if method == "post" else f"{BASE}/a1b2c3d4"
    kwargs = {} if method == "delete" else {"json": {"kategori": "Teknis", "butir": "x"}}
    resp = getattr(TestClient(app), method)(url, **kwargs)
    assert resp.status_code == 403
    assert doc.is_overridden is False
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"kategori": "Bebas", "butir": "x"},
        {"kategori": "Teknis", "butir": ""},
        {"kategori": "Teknis", "butir": "   "},
        {"kategori": "Teknis", "butir": "x" * 1001},
        {"butir": "tanpa kategori"},
    ],
)
def test_butir_tidak_valid_ditolak_422(payload):
    user, project = _sa_ditugaskan()
    doc = _doc()
    session = _setup(user, project, doc)
    for method, url in (("post", BASE), ("put", f"{BASE}/a1b2c3d4")):
        resp = getattr(TestClient(app), method)(url, json=payload)
        assert resp.status_code == 422
    assert doc.content == KONTEN
    assert doc.is_overridden is False


def test_butir_tidak_ditemukan_404():
    user, project = _sa_ditugaskan()
    _setup(user, project, _doc())
    resp = TestClient(app).put(f"{BASE}/zzzzzzzz", json={"kategori": "Teknis", "butir": "x"})
    assert resp.status_code == 404


def test_requirement_belum_ada_404():
    user, project = _sa_ditugaskan()
    _setup(user, project, None)
    resp = TestClient(app).post(BASE, json={"kategori": "Teknis", "butir": "x"})
    assert resp.status_code == 404


def test_requirement_final_tidak_dapat_diedit_409():
    user, project = _sa_ditugaskan()
    doc = _doc(status="Final")
    _setup(user, project, doc)
    resp = TestClient(app).post(BASE, json={"kategori": "Teknis", "butir": "x"})
    assert resp.status_code == 409
    assert doc.is_overridden is False


def test_status_dokumen_tidak_berubah_oleh_edit():
    user, project = _sa_ditugaskan()
    doc = _doc(status="Reviewed")
    _setup(user, project, doc)
    resp = TestClient(app).post(BASE, json={"kategori": "Asumsi", "butir": "x"})
    assert resp.status_code == 201
    assert doc.status == "Reviewed"
