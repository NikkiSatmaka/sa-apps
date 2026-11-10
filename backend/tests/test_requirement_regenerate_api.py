"""
Test seam tiket 5B-2 (#34): generate ulang manual Requirement, status gagal + coba lagi.

Lewat HTTP API (TestClient); sesi DB dan provider LLM di-mock di boundary. Endpoint:
POST /api/v1/projects/{id}/requirement/regenerate.
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.document import Document
from app.services.llm_provider import LLMResponse
from tests.test_requirement_generate_api import ITEMS, _bg_session, _Ctx, llm_ok, _source
from tests.test_projects_questionnaire_api import _result

PRJ = "PRJ-20250101-XYZ789"
URL = f"/api/v1/projects/{PRJ}/requirement/regenerate"
LIST_URL = f"/api/v1/projects/{PRJ}/documents"


def _user(role, uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.role = role
    u.name = role
    return u


def _project(status="ready", assigned_sa=None):
    p = MagicMock()
    p.id_project = PRJ
    p.status = "Pending Assignment"
    p.assigned_sa = assigned_sa
    p.sales_pic = uuid.uuid4()
    p.qualification_answers = {"masalah_bisnis": "Data center lama sering down"}
    p.requirement_generation_status = status
    return p


def _existing(overridden=True):
    now = datetime.now(timezone.utc)
    return Document(
        id_doc="DOC-20250101-REQ001",
        id_project=PRJ,
        doc_type="Requirement",
        status="Draft",
        gdrive_link=None,
        folder_type="Inventory",
        created_by=None,
        content=[{"id": "old00001", "kategori": "Asumsi", "butir": "butir lama"}],
        is_overridden=overridden,
        source_hash="0" * 64,
        generated_at=now,
        source_truncated=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _call(user, project, llm=None, existing=None, sources=None):
    """POST regenerate; background dijalankan. Return (resp, project, bg, provider)."""
    req_session = AsyncMock()
    req_session.add = MagicMock()
    req_session.execute = AsyncMock(return_value=_result(one=project))

    async def _db():
        yield req_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user

    provider = MagicMock()
    provider.complete_text = AsyncMock(
        side_effect=llm if isinstance(llm, list) else None,
        return_value=None if isinstance(llm, list) else (llm or llm_ok()),
    )
    bg = _bg_session(lambda: project, sources, existing)
    patches = [
        patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)),
        patch("app.services.requirement_generator.llm_factory.get_provider", return_value=provider),
        patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()),
    ]
    for p in patches:
        p.start()
    try:
        resp = TestClient(app).post(URL)
    finally:
        for p in reversed(patches):
            p.stop()
    return resp, project, bg, provider


# --------------------------------------------------------------------------- peran
@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
def test_lead_sa_dan_admin_boleh_generate_ulang(role):
    resp, project, bg, provider = _call(_user(role), _project(), existing=_existing())
    assert resp.status_code == 202
    provider.complete_text.assert_awaited()
    assert project.requirement_generation_status == "ready"


def test_sa_yang_ditugaskan_boleh_generate_ulang():
    sa = _user("SA")
    resp, project, _, provider = _call(sa, _project(assigned_sa=sa.id), existing=_existing())
    assert resp.status_code == 202
    provider.complete_text.assert_awaited()


@pytest.mark.parametrize("role", ["Sales", "Viewer"])
def test_peran_lain_ditolak_403_tanpa_memanggil_llm(role):
    resp, project, _, provider = _call(_user(role), _project())
    assert resp.status_code == 403
    provider.complete_text.assert_not_called()
    assert project.requirement_generation_status == "ready"


def test_sa_tidak_ditugaskan_ditolak_403():
    resp, _, _, provider = _call(_user("SA"), _project(assigned_sa=uuid.uuid4()))
    assert resp.status_code == 403
    provider.complete_text.assert_not_called()


def test_proyek_tidak_ada_404():
    resp, *_ = _call(_user("Admin"), None)
    assert resp.status_code == 404


def test_proyek_belum_lolos_gate_ditolak_409():
    resp, _, _, provider = _call(_user("Admin"), _project(status=None))
    assert resp.status_code == 409
    provider.complete_text.assert_not_called()


def test_generate_sedang_berjalan_ditolak_409():
    resp, _, _, provider = _call(_user("Admin"), _project(status="pending"))
    assert resp.status_code == 409
    provider.complete_text.assert_not_called()


# --------------------------------------------------------------------------- hasil
def test_generate_ulang_menimpa_konten_dan_menghapus_override():
    existing = _existing(overridden=True)
    items = [{"kategori": "Teknis", "butir": "Kubernetes managed"}]
    resp, project, bg, _ = _call(_user("Admin"), _project(), llm=llm_ok(items), existing=existing)
    assert resp.status_code == 202
    assert [(i["kategori"], i["butir"]) for i in existing.content] == [("Teknis", "Kubernetes managed")]
    assert existing.is_overridden is False
    assert existing.source_hash != "0" * 64
    assert bg.of_type(Document) == []  # menimpa baris, bukan menambah baris baru
    assert project.requirement_generation_status == "ready"


def test_generate_ulang_memperbarui_penanda_terpotong():
    existing = _existing()
    _call(
        _user("Admin"),
        _project(),
        existing=existing,
        sources=[_source(truncated=True)],
    )
    assert existing.source_truncated is True


# --------------------------------------------------------------------------- gagal & coba lagi
def test_generate_ulang_gagal_menandai_failed_dan_konten_lama_utuh():
    existing = _existing()
    gagal = LLMResponse(status="error", error_type="timeout", error_message="x")
    resp, project, _, _ = _call(_user("Admin"), _project(), llm=gagal, existing=existing)
    assert resp.status_code == 202  # penerimaan; hasil akhir lewat status
    assert project.requirement_generation_status == "failed"
    assert existing.content[0]["butir"] == "butir lama"
    assert existing.is_overridden is True  # tidak terhapus bila gagal


def test_coba_lagi_setelah_gagal_berhasil_saat_llm_pulih():
    # Proyek gagal tanpa baris Requirement → coba lagi lewat endpoint yang sama.
    project = _project(status="failed")
    resp, project, bg, _ = _call(_user("Lead_SA"), project, llm=llm_ok())
    assert resp.status_code == 202
    assert project.requirement_generation_status == "ready"
    [doc] = bg.of_type(Document)
    assert [(i["kategori"], i["butir"]) for i in doc.content] == [
        (i["kategori"], i["butir"]) for i in ITEMS
    ]


# --------------------------------------------------------------------------- daftar dokumen
def _list(user, project, docs):
    session = AsyncMock()
    r_docs = MagicMock()
    r_docs.scalars.return_value.all.return_value = docs
    # project, cek collaborator (ensure_project_access), daftar dokumen
    session.execute = AsyncMock(side_effect=[_result(one=project), _result(one=None), r_docs])

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app).get(LIST_URL)


def test_daftar_dokumen_memuat_status_generate_dan_hak_generate_ulang():
    sa = _user("SA")
    data = _list(sa, _project(status="failed", assigned_sa=sa.id), []).json()["data"]
    assert data["requirement_generation_status"] == "failed"
    assert data["can_regenerate_requirement"] is True


def test_daftar_dokumen_sales_tidak_boleh_generate_ulang():
    sales = _user("Sales")
    project = _project(status="ready")
    project.sales_pic = sales.id  # Sales PIC boleh membaca, tetapi tidak boleh generate ulang
    data = _list(sales, project, []).json()["data"]
    assert data["can_regenerate_requirement"] is False
