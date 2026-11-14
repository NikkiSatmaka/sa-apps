"""
Unit tests untuk RAG Template Recommendation (Task 12.1).

Memvalidasi:
- search_similar_projects: pencarian proyek Won berdasarkan use_case_tags
- Endpoint GET /api/v1/projects/{id}/recommendations
- Edge cases: belum ada Won, proyek belum punya tags
"""

import pytest
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.scoring import RecommendedDocumentInfo, SimilarProjectResult
from app.services.scoring_engine import ScoringEngine


class FakeProject:
    """Mock proyek untuk testing tanpa database."""

    def __init__(self, id_project, project_name, customer_name, status, use_case_tags):
        self.id_project = id_project
        self.project_name = project_name
        self.customer_name = customer_name
        self.status = status
        self.use_case_tags = use_case_tags


class FakeDocument:
    """Mock dokumen untuk testing tanpa database."""

    def __init__(self, id_doc, id_project, doc_type, gdrive_link, status):
        self.id_doc = id_doc
        self.id_project = id_project
        self.doc_type = doc_type
        self.gdrive_link = gdrive_link
        self.status = status


class FakeScalarsResult:
    """Mock scalars().all() result."""

    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeExecuteResult:
    """Mock db.execute() result."""

    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalarsResult(self._items)


@pytest.fixture
def engine():
    """Instance ScoringEngine untuk testing."""
    return ScoringEngine()


@pytest.fixture
def closed_win_projects():
    """Proyek-proyek Won sebagai referensi."""
    return [
        FakeProject(
            id_project="PRJ-001",
            project_name="Migrasi Data Warehouse",
            customer_name="PT ABC",
            status="Won",
            use_case_tags=["data-warehouse", "etl", "redshift"],
        ),
        FakeProject(
            id_project="PRJ-002",
            project_name="Cloud Native App",
            customer_name="PT XYZ",
            status="Won",
            use_case_tags=["kubernetes", "microservices", "ci-cd"],
        ),
        FakeProject(
            id_project="PRJ-003",
            project_name="Big Data Analytics",
            customer_name="PT DEF",
            status="Won",
            use_case_tags=["data-warehouse", "spark", "etl", "datalake"],
        ),
        FakeProject(
            id_project="PRJ-004",
            project_name="ML Platform",
            customer_name="PT GHI",
            status="Won",
            use_case_tags=["machine-learning", "data-warehouse", "etl"],
        ),
        FakeProject(
            id_project="PRJ-005",
            project_name="IoT Dashboard",
            customer_name="PT JKL",
            status="Won",
            use_case_tags=["iot", "dashboard", "realtime"],
        ),
        FakeProject(
            id_project="PRJ-006",
            project_name="Data Lake Implementation",
            customer_name="PT MNO",
            status="Won",
            use_case_tags=["datalake", "data-warehouse", "governance"],
        ),
    ]


@pytest.fixture
def sample_documents():
    """Dokumen-dokumen dari proyek Won."""
    return [
        FakeDocument(
            id_doc="DOC-001",
            id_project="PRJ-001",
            doc_type="PropTek",
            gdrive_link="https://drive.google.com/doc1",
            status="Final",
        ),
        FakeDocument(
            id_doc="DOC-002",
            id_project="PRJ-001",
            doc_type="BOQ",
            gdrive_link="https://drive.google.com/doc2",
            status="Final",
        ),
        FakeDocument(
            id_doc="DOC-003",
            id_project="PRJ-003",
            doc_type="HLD",
            gdrive_link="https://drive.google.com/doc3",
            status="Reviewed",
        ),
    ]


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_tags(engine):
    """Jika use_case_tags kosong, harus return list kosong."""
    db = AsyncMock()
    result = await engine.search_similar_projects(
        use_case_tags=[],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )
    assert result == []
    # db.execute tidak boleh dipanggil jika tags kosong
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_closed_win(engine):
    """Jika tidak ada proyek Won, harus return list kosong."""
    db = AsyncMock()
    # Simulasi: query proyek Won return kosong
    db.execute.return_value = FakeExecuteResult([])

    result = await engine.search_similar_projects(
        use_case_tags=["data-warehouse", "etl"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )
    assert result == []


@pytest.mark.asyncio
async def test_search_filters_by_matching_tags(engine, closed_win_projects, sample_documents):
    """Hanya proyek dengan minimal 1 tag cocok yang dikembalikan."""
    db = AsyncMock()

    # First call: query proyek Won
    # Second call: query dokumen
    db.execute.side_effect = [
        FakeExecuteResult(closed_win_projects),
        FakeExecuteResult(sample_documents),
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["data-warehouse", "etl"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    # PRJ-001 punya "data-warehouse" dan "etl" (2 match)
    # PRJ-003 punya "data-warehouse" dan "etl" (2 match)
    # PRJ-004 punya "data-warehouse" dan "etl" (2 match)
    # PRJ-006 punya "data-warehouse" (1 match)
    # PRJ-002 punya 0 match (tidak masuk)
    # PRJ-005 punya 0 match (tidak masuk)
    assert len(result) == 4

    # Verifikasi tidak ada proyek tanpa tag cocok
    project_ids = [r.id_project for r in result]
    assert "PRJ-002" not in project_ids
    assert "PRJ-005" not in project_ids


@pytest.mark.asyncio
async def test_search_orders_by_matching_count_descending(
    engine, closed_win_projects, sample_documents
):
    """Hasil diurutkan descending berdasarkan jumlah tag cocok."""
    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(closed_win_projects),
        FakeExecuteResult(sample_documents),
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["data-warehouse", "etl"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    # Verifikasi urutan: yang lebih banyak match di atas
    for i in range(len(result) - 1):
        assert result[i].matching_tags >= result[i + 1].matching_tags


@pytest.mark.asyncio
async def test_search_max_5_results(engine):
    """Hasil dibatasi maksimal 5 proyek."""
    # Buat 7 proyek Won yang semuanya punya tag cocok
    many_projects = [
        FakeProject(
            id_project=f"PRJ-{i:03d}",
            project_name=f"Project {i}",
            customer_name=f"Customer {i}",
            status="Won",
            use_case_tags=["common-tag"],
        )
        for i in range(7)
    ]

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(many_projects),
        FakeExecuteResult([]),  # Tidak ada dokumen
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["common-tag"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )
    assert len(result) <= 5


@pytest.mark.asyncio
async def test_search_case_insensitive_matching(engine):
    """Tag matching harus case-insensitive."""
    projects = [
        FakeProject(
            id_project="PRJ-001",
            project_name="Test Project",
            customer_name="Test Customer",
            status="Won",
            use_case_tags=["Data-Warehouse", "ETL"],
        ),
    ]

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(projects),
        FakeExecuteResult([]),
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["data-warehouse", "etl"],  # lowercase
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    assert len(result) == 1
    assert result[0].matching_tags == 2


@pytest.mark.asyncio
async def test_search_excludes_current_project(engine):
    """Proyek saat ini harus dikecualikan dari hasil."""
    projects = [
        FakeProject(
            id_project="PRJ-CURRENT",
            project_name="Current Project",
            customer_name="Customer",
            status="Won",
            use_case_tags=["tag-a"],
        ),
        FakeProject(
            id_project="PRJ-OTHER",
            project_name="Other Project",
            customer_name="Customer B",
            status="Won",
            use_case_tags=["tag-a"],
        ),
    ]

    db = AsyncMock()
    # exclude_project_id ditangani oleh query WHERE, jadi kita simulasi
    # bahwa DB hanya return proyek yang bukan PRJ-CURRENT
    db.execute.side_effect = [
        FakeExecuteResult([projects[1]]),  # DB sudah filter exclude
        FakeExecuteResult([]),
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["tag-a"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    project_ids = [r.id_project for r in result]
    assert "PRJ-CURRENT" not in project_ids


@pytest.mark.asyncio
async def test_search_includes_document_info(engine):
    """Hasil harus menyertakan info dokumen dari proyek Won."""
    projects = [
        FakeProject(
            id_project="PRJ-001",
            project_name="Data Project",
            customer_name="PT ABC",
            status="Won",
            use_case_tags=["analytics"],
        ),
    ]
    documents = [
        FakeDocument(
            id_doc="DOC-001",
            id_project="PRJ-001",
            doc_type="PropTek",
            gdrive_link="https://drive.google.com/proptek",
            status="Final",
        ),
        FakeDocument(
            id_doc="DOC-002",
            id_project="PRJ-001",
            doc_type="HLD",
            gdrive_link="https://drive.google.com/hld",
            status="Reviewed",
        ),
    ]

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(projects),
        FakeExecuteResult(documents),
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["analytics"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    assert len(result) == 1
    assert len(result[0].documents) == 2
    assert result[0].documents[0].doc_type == "PropTek"
    assert result[0].documents[0].gdrive_link == "https://drive.google.com/proptek"
    assert result[0].documents[1].doc_type == "HLD"


@pytest.mark.asyncio
async def test_search_no_documents_returns_empty_list(engine):
    """Proyek tanpa dokumen harus punya documents = [] (bukan error)."""
    projects = [
        FakeProject(
            id_project="PRJ-001",
            project_name="Empty Project",
            customer_name="PT ABC",
            status="Won",
            use_case_tags=["tag-x"],
        ),
    ]

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(projects),
        FakeExecuteResult([]),  # Tidak ada dokumen
    ]

    result = await engine.search_similar_projects(
        use_case_tags=["tag-x"],
        exclude_project_id="PRJ-CURRENT",
        db=db,
    )

    assert len(result) == 1
    assert result[0].documents == []
