"""
Test tiket 5B-1 (#33) pada API dokumen: Requirement hanya dibuat sistem, daftar dokumen
menangani `gdrive_link` kosong + konten butir, dan Requirement `Reviewed` tidak memicu
`doc_ready` / pembukaan folder Solutions. DB dan layanan eksternal di-mock.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.document import Document
from app.services.scoring_engine import ScoringEngine
from tests.test_doc_ready import _make_project, _make_user, _result_scalar

PRJ = "PRJ-20250101-XYZ789"
KONTEN = [
    {"id": "a1b2c3d4", "kategori": "Fungsional", "butir": "Migrasi 40 server"},
    {"id": "e5f6a7b8", "kategori": "Asumsi", "butir": "Jaringan sudah tersedia"},
]


def _requirement(status="Draft"):
    now = datetime.now(timezone.utc)
    return Document(
        id_doc="DOC-20250101-REQ001",
        id_project=PRJ,
        doc_type="Requirement",
        status=status,
        gdrive_link=None,
        folder_type="Inventory",
        notes=None,
        created_by=None,
        updated_by=None,
        content=KONTEN,
        is_overridden=False,
        source_hash="a" * 64,
        generated_at=now,
        source_truncated=True,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _setup(user, results):
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return session


def test_post_dokumen_menolak_requirement_karena_hanya_dibuat_sistem():
    session = _setup(_make_user("SA"), [_result_scalar(_make_project())])
    resp = TestClient(app).post(
        f"/api/v1/projects/{PRJ}/documents",
        json={"doc_type": "Requirement", "gdrive_link": "https://x.y/z", "folder_type": "Inventory"},
    )
    assert resp.status_code == 422
    session.add.assert_not_called()


def test_post_dokumen_lain_tetap_wajib_link():
    _setup(_make_user("SA"), [_result_scalar(_make_project())])
    resp = TestClient(app).post(
        f"/api/v1/projects/{PRJ}/documents",
        json={"doc_type": "PropTek", "gdrive_link": "", "folder_type": "Solutions"},
    )
    assert resp.status_code == 422


def test_daftar_dokumen_mengembalikan_requirement_dengan_link_kosong_dan_butir():
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_requirement()]
    sa = _make_user("SA")
    project = _make_project()
    project.assigned_sa = sa.id  # akses proyek wajib (ensure_project_access)
    _setup(sa, [_result_scalar(project), result])  # BACA terbuka: tanpa query collaborator
    resp = TestClient(app).get(f"/api/v1/projects/{PRJ}/documents")
    assert resp.status_code == 200
    [doc] = resp.json()["data"]["documents"]
    assert doc["doc_type"] == "Requirement"
    assert doc["gdrive_link"] is None
    assert doc["created_by"] is None
    assert doc["content"] == KONTEN
    assert doc["is_overridden"] is False
    assert doc["source_truncated"] is True
    assert doc["source_hash"] == "a" * 64


# Cek akses KELOLA (tiket #90) menambah satu query proyek di luar urutan `execute()` tetap di
# bawah; dinetralkan di sini, matriks aksesnya diuji di Postgres nyata
# (`tests/integration/test_akses_k3_dokumen_dq.py`).
@pytest.fixture
def lewati_cek_akses_dokumen():
    with patch("app.api.documents._periksa_akses_kelola_dokumen", new_callable=AsyncMock):
        yield


@pytest.mark.usefixtures("lewati_cek_akses_dokumen")
@pytest.mark.parametrize("dq", ["DQ-12345", None])
def test_requirement_reviewed_tidak_memicu_doc_ready_maupun_unlock_solutions(dq):
    sales_id = uuid.uuid4()
    project = _make_project(dq_number=dq, sales_pic=sales_id)
    sales = _make_user("Sales", sales_id)
    session = _setup(
        _make_user("SA"),
        [_result_scalar(_requirement()), _result_scalar(project), _result_scalar(sales)],
    )
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    with patch(
        "app.api.documents.notification_service.send_notification", new_callable=AsyncMock
    ) as notify, patch(
        "app.api.documents.folder_provisioner.unlock_solutions_folder", new_callable=AsyncMock
    ) as unlock:
        resp = TestClient(app).patch(
            "/api/v1/documents/DOC-20250101-REQ001/status", json={"new_status": "Reviewed"}
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "Reviewed"
    notify.assert_not_called()
    unlock.assert_not_called()


@pytest.mark.asyncio
async def test_rag_tidak_merekomendasikan_dokumen_tanpa_link():
    proyek = MagicMock(
        id_project="PRJ-001", project_name="P", customer_name="C", status="Won",
        use_case_tags=["etl"],
    )
    ada = MagicMock(id_doc="D1", id_project="PRJ-001", doc_type="PropTek",
                    gdrive_link="https://drive/x", status="Final")
    tanpa_link = MagicMock(id_doc="D2", id_project="PRJ-001", doc_type="Requirement",
                           gdrive_link=None, status="Draft")
    r1, r2 = MagicMock(), MagicMock()
    r1.scalars.return_value.all.return_value = [proyek]
    r2.scalars.return_value.all.return_value = [ada, tanpa_link]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[r1, r2])
    hasil = await ScoringEngine().search_similar_projects(["etl"], "PRJ-NEW", db)
    assert [d.id_doc for d in hasil[0].documents] == ["D1"]


def test_model_document_mendeklarasikan_check_dan_unique_index_requirement():
    constraints = {c.name: str(c.sqltext) for c in Document.__table__.constraints if hasattr(c, "sqltext")}
    assert constraints["chk_documents_gdrive_link_required"] == (
        "gdrive_link IS NOT NULL OR doc_type = 'Requirement'"
    )
    assert constraints["chk_documents_created_by_required"] == (
        "created_by IS NOT NULL OR doc_type = 'Requirement'"
    )
    indeks = {i.name: i for i in Document.__table__.indexes}
    assert indeks["uq_documents_requirement_per_project"].unique is True
    assert Document.__table__.c.gdrive_link.nullable is True
