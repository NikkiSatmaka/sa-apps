"""
Migration 022 (issue #124): subtask kaya. Kolom `description` (Text), `due_date` (Date), dan
`estimate_hours` (Numeric, CHECK >= 0), semuanya opsional.

Memakai database sementara per test (`database_kosong_url`). Yang diuji: upgrade mempertahankan
subtask lama (kolom baru NULL), downgrade membuang kolom dan constraint, upgrade ulang, dan
constraint pada head.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _revisi_lama_ke_baru, _sql, _versi
from tests.integration.test_migration_020_status import _proyek, _user

REVISI_BARU = "022"
REVISI_LAMA = "021"
KOLOM_BARU = {"description", "due_date", "estimate_hours"}
SEKARANG = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _kolom(url: str) -> set[str]:
    baris = _sql(
        url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'subtasks'",
    )
    return {b[0] for b in baris}


def _constraint(url: str) -> set[str]:
    baris = _sql(
        url,
        "SELECT conname FROM pg_constraint WHERE conrelid = 'subtasks'::regclass",
    )
    return {b[0] for b in baris}


def _subtask(url: str, id_project: str, id_subtask: str = "ST-1", **kolom) -> None:
    nilai = {
        "id_subtask": id_subtask,
        "id_project": id_project,
        "title": f"Judul {id_subtask}",
        "status": "open",
        "created_at": SEKARANG,
        "updated_at": SEKARANG,
        **kolom,
    }
    nama = list(nilai)
    _sql(
        url,
        f"INSERT INTO subtasks ({', '.join(nama)}) VALUES ({', '.join(f':{n}' for n in nama)})",
        nilai,
    )


def _siapkan_head(url: str, id_project: str = "PRJ-ST") -> str:
    jalankan_alembic(url, "upgrade", "head")
    _proyek(url, _user(url), id_project, "Assigned")
    return id_project


def test_revisi_022_ada_di_rantai_dan_head_mengikutinya(database_kosong_url):
    # Bukan lagi head sejak migration 023 (#125); head dijaga test migration 023 dan test_migration.
    jalankan_alembic(database_kosong_url, "upgrade", "head")

    urutan = _revisi_lama_ke_baru()
    assert urutan[urutan.index(REVISI_BARU) - 1] == REVISI_LAMA
    assert _versi(database_kosong_url) == _head() == urutan[-1]


def test_upgrade_mempertahankan_subtask_lama_dengan_kolom_baru_null(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    _proyek(url, _user(url), "PRJ-LAMA", "Assigned")
    _subtask(url, "PRJ-LAMA", "ST-LAMA")

    jalankan_alembic(url, "upgrade", "head")

    assert _sql(
        url,
        "SELECT title, description, due_date, estimate_hours FROM subtasks "
        "WHERE id_subtask = 'ST-LAMA'",
    ) == [("Judul ST-LAMA", None, None, None)]


def test_downgrade_membuang_kolom_dan_constraint(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    assert KOLOM_BARU <= _kolom(url)
    assert "chk_subtasks_estimate_hours" in _constraint(url)

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _versi(url) == REVISI_LAMA
    assert not KOLOM_BARU & _kolom(url)
    assert "chk_subtasks_estimate_hours" not in _constraint(url)


def test_downgrade_mempertahankan_baris_subtask(database_kosong_url):
    url = database_kosong_url
    proyek = _siapkan_head(url)
    _subtask(url, proyek, description="d", due_date=date(2030, 2, 1), estimate_hours=3)

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _sql(url, "SELECT title FROM subtasks") == [("Judul ST-1",)]


def test_upgrade_ulang_setelah_downgrade(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == _head()
    assert KOLOM_BARU <= _kolom(url)


def test_head_menyimpan_ketiga_field_apa_adanya(database_kosong_url):
    url = database_kosong_url
    proyek = _siapkan_head(url)

    _subtask(
        url,
        proyek,
        description="Susun HLD",
        due_date=date(2030, 3, 15),
        estimate_hours=Decimal("12.50"),
    )

    assert _sql(url, "SELECT description, due_date, estimate_hours FROM subtasks") == [
        ("Susun HLD", date(2030, 3, 15), Decimal("12.50"))
    ]


def test_head_ketiga_field_boleh_kosong(database_kosong_url):
    url = database_kosong_url
    proyek = _siapkan_head(url)

    _subtask(url, proyek)

    assert _sql(url, "SELECT description, due_date, estimate_hours FROM subtasks") == [
        (None, None, None)
    ]


@pytest.mark.parametrize("jam", [0, Decimal("0.25"), 40])
def test_head_estimate_hours_nol_atau_positif_diterima(database_kosong_url, jam):
    url = database_kosong_url
    proyek = _siapkan_head(url)

    _subtask(url, proyek, estimate_hours=jam)

    assert _sql(url, "SELECT estimate_hours FROM subtasks")[0][0] == Decimal(str(jam))


@pytest.mark.parametrize("jam", [-1, Decimal("-0.01")])
def test_head_estimate_hours_negatif_ditolak(database_kosong_url, jam):
    url = database_kosong_url
    proyek = _siapkan_head(url)

    with pytest.raises(DBAPIError, match="chk_subtasks_estimate_hours"):
        _subtask(url, proyek, estimate_hours=jam)
