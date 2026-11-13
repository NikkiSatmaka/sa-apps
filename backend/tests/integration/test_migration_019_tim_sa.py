"""
Migration 019 (issue #119, ADR 0014): tabel `project_assignments` (SA tambahan per project).

Memakai database sementara per test (`database_kosong_url`) karena mengubah versi skema.
Role (`SA`/`Lead_SA`) ditegakkan di lapisan API (CHECK tidak bisa merujuk `users.role`);
buktinya ada di `test_tim_sa_api.py`.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _sql, _versi


def _user(url: str, role: str, nama: str) -> str:
    user_id = str(uuid.uuid4())
    _sql(
        url,
        "INSERT INTO users (id, email, name, role, google_id) "
        "VALUES (:id, :email, :name, :role, :google_id)",
        {
            "id": user_id,
            "email": f"{nama}@mig.test",
            "name": nama,
            "role": role,
            "google_id": f"g-{nama}",
        },
    )
    return user_id


def _proyek(url: str, id_project: str, orang: str) -> None:
    _sql(
        url,
        "INSERT INTO projects (id_project, project_name, customer_name, created_by, "
        "product_pic, target_submit, status) VALUES (:id, 'P', 'C', :o, :o, :t, 'Assigned')",
        {"id": id_project, "o": orang, "t": date(2030, 1, 1)},
    )


def _tambah(url: str, id_project: str, user_id: str, added_by: str) -> None:
    _sql(
        url,
        "INSERT INTO project_assignments (id, id_project, user_id, added_by) "
        "VALUES (:id, :p, :u, :a)",
        {"id": str(uuid.uuid4()), "p": id_project, "u": user_id, "a": added_by},
    )


def _siapkan(url: str):
    jalankan_alembic(url, "upgrade", "head")
    lead = _user(url, "Lead_SA", "lead")
    sa = _user(url, "SA", "sa")
    _proyek(url, "PRJ-1", lead)
    return lead, sa


def test_head_adalah_019_dan_tabel_ada(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == _head() == "019"
    kolom = {
        r[0]
        for r in _sql(
            url,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'project_assignments'",
        )
    }
    assert kolom == {"id", "id_project", "user_id", "added_by", "created_at"}


def test_upgrade_dari_018_membuat_tabel_kosong_tanpa_mengubah_data(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "018")
    lead = _user(url, "Lead_SA", "lead")
    _proyek(url, "PRJ-LAMA", lead)

    jalankan_alembic(url, "upgrade", "head")

    assert _sql(url, "SELECT count(*) FROM project_assignments")[0][0] == 0
    assert _sql(url, "SELECT count(*) FROM projects")[0][0] == 1


def test_unik_per_project_dan_user(database_kosong_url):
    url = database_kosong_url
    lead, sa = _siapkan(url)
    _tambah(url, "PRJ-1", sa, lead)

    with pytest.raises(DBAPIError, match="uq_project_assignment"):
        _tambah(url, "PRJ-1", sa, lead)


def test_user_yang_sama_boleh_di_project_berbeda(database_kosong_url):
    url = database_kosong_url
    lead, sa = _siapkan(url)
    _proyek(url, "PRJ-2", lead)

    _tambah(url, "PRJ-1", sa, lead)
    _tambah(url, "PRJ-2", sa, lead)

    assert _sql(url, "SELECT count(*) FROM project_assignments")[0][0] == 2


@pytest.mark.parametrize("kolom", ["id_project", "user_id", "added_by"])
def test_kolom_wajib_dan_berfk(database_kosong_url, kolom):
    url = database_kosong_url
    lead, sa = _siapkan(url)
    nilai = {"id_project": "PRJ-1", "user_id": sa, "added_by": lead}

    nilai[kolom] = None  # NOT NULL
    with pytest.raises(DBAPIError, match=kolom):
        _sql(
            url,
            "INSERT INTO project_assignments (id, id_project, user_id, added_by) "
            "VALUES (:id, :id_project, :user_id, :added_by)",
            {"id": str(uuid.uuid4()), **nilai},
        )

    nilai[kolom] = "PRJ-TIDAK-ADA" if kolom == "id_project" else str(uuid.uuid4())  # FK
    with pytest.raises(DBAPIError, match="fk_project_assignments"):
        _sql(
            url,
            "INSERT INTO project_assignments (id, id_project, user_id, added_by) "
            "VALUES (:id, :id_project, :user_id, :added_by)",
            {"id": str(uuid.uuid4()), **nilai},
        )


def test_hapus_project_dan_user_menghapus_penugasan_tetapi_added_by_menahan(database_kosong_url):
    url = database_kosong_url
    _, sa = _siapkan(url)
    penambah = _user(url, "Lead_SA", "penambah")  # tidak dirujuk tabel lain
    _tambah(url, "PRJ-1", sa, penambah)

    with pytest.raises(DBAPIError, match="fk_project_assignments_added_by"):
        _sql(url, "DELETE FROM users WHERE id = :u", {"u": penambah})

    _sql(url, "DELETE FROM users WHERE id = :u", {"u": sa})
    assert _sql(url, "SELECT count(*) FROM project_assignments")[0][0] == 0


def test_downgrade_ke_018_membuang_tabel_lalu_naik_lagi(database_kosong_url):
    url = database_kosong_url
    lead, sa = _siapkan(url)
    _tambah(url, "PRJ-1", sa, lead)

    jalankan_alembic(url, "downgrade", "018")

    assert _versi(url) == "018"
    assert _sql(url, "SELECT to_regclass('public.project_assignments')")[0][0] is None
    jalankan_alembic(url, "upgrade", "head")
    assert _sql(url, "SELECT count(*) FROM project_assignments")[0][0] == 0
