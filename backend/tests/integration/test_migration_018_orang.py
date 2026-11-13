"""
Migration 018 (issue #117, ADR 0014): `created_by`, `product_pic` (wajib), `sales_pic` opsional,
`lead_sa` (opsional) pada `projects`.

Memakai database sementara per test (`database_kosong_url`) karena mengubah versi skema.
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


def _proyek_lama(url: str, sales: str, id_project: str = "PRJ-MIG-1") -> str:
    """Proyek skema 017 (hanya `sales_pic`)."""
    _sql(
        url,
        "INSERT INTO projects (id_project, project_name, customer_name, sales_pic, "
        "target_submit, status) VALUES (:id, 'P', 'C', :sales, :target, 'New')",
        {"id": id_project, "sales": sales, "target": date(2030, 1, 1)},
    )
    return id_project


def _proyek_baru(url: str, id_project: str, *, created_by: str, product_pic: str, sales_pic=None):
    _sql(
        url,
        "INSERT INTO projects (id_project, project_name, customer_name, created_by, "
        "product_pic, sales_pic, target_submit, status) "
        "VALUES (:id, 'P', 'C', :cb, :pp, :sp, :target, 'New')",
        {
            "id": id_project,
            "cb": created_by,
            "pp": product_pic,
            "sp": sales_pic,
            "target": date(2030, 1, 1),
        },
    )


def _kolom(url: str, id_project: str, kolom: str):
    return _sql(
        url, f"SELECT {kolom} FROM projects WHERE id_project = :id", {"id": id_project}
    )[0][0]


def test_upgrade_mengisi_created_by_dan_product_pic_dari_sales_pic_lama(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "017")
    sales = _user(url, "Sales", "sales-lama")
    pid = _proyek_lama(url, sales)

    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == _head()
    assert str(_kolom(url, pid, "created_by")) == sales
    assert str(_kolom(url, pid, "product_pic")) == sales
    assert str(_kolom(url, pid, "sales_pic")) == sales
    assert _kolom(url, pid, "lead_sa") is None


def test_head_product_pic_wajib_tetapi_sales_pic_dan_lead_sa_boleh_kosong(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    produk = _user(url, "Product", "produk")

    _proyek_baru(url, "PRJ-TANPA-SALES", created_by=produk, product_pic=produk)

    assert _kolom(url, "PRJ-TANPA-SALES", "sales_pic") is None
    assert _kolom(url, "PRJ-TANPA-SALES", "lead_sa") is None
    with pytest.raises(DBAPIError, match="product_pic"):
        _sql(
            url,
            "INSERT INTO projects (id_project, project_name, customer_name, created_by, "
            "target_submit, status) VALUES ('PRJ-X', 'P', 'C', :cb, :target, 'New')",
            {"cb": produk, "target": date(2030, 1, 1)},
        )


def test_head_created_by_wajib(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    produk = _user(url, "Product", "produk")

    with pytest.raises(DBAPIError, match="created_by"):
        _sql(
            url,
            "INSERT INTO projects (id_project, project_name, customer_name, product_pic, "
            "target_submit, status) VALUES ('PRJ-Y', 'P', 'C', :pp, :target, 'New')",
            {"pp": produk, "target": date(2030, 1, 1)},
        )


@pytest.mark.parametrize("kolom", ["created_by", "product_pic", "sales_pic", "lead_sa"])
def test_head_kolom_orang_berfk_ke_users(database_kosong_url, kolom):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    produk = _user(url, "Product", "produk")
    nilai = {"created_by": produk, "product_pic": produk, kolom: str(uuid.uuid4())}

    with pytest.raises(DBAPIError, match=f"fk_projects_{kolom}"):
        _sql(
            url,
            f"INSERT INTO projects (id_project, project_name, customer_name, "
            f"{', '.join(nilai)}, target_submit, status) "
            f"VALUES ('PRJ-FK', 'P', 'C', {', '.join(f':{k}' for k in nilai)}, :target, 'New')",
            {**nilai, "target": date(2030, 1, 1)},
        )


def test_downgrade_mengisi_sales_pic_kosong_dari_product_pic_lalu_naik_lagi(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    produk = _user(url, "Product", "produk")
    sales = _user(url, "Sales", "sales")
    _proyek_baru(url, "PRJ-A", created_by=produk, product_pic=produk)  # tanpa Sales
    _proyek_baru(url, "PRJ-B", created_by=sales, product_pic=produk, sales_pic=sales)

    jalankan_alembic(url, "downgrade", "017")

    assert _versi(url) == "017"
    assert str(_kolom(url, "PRJ-A", "sales_pic")) == produk  # lossy: Sales kosong → Product
    assert str(_kolom(url, "PRJ-B", "sales_pic")) == sales
    assert _sql(
        url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'projects' "
        "AND column_name IN ('created_by', 'product_pic', 'lead_sa')",
    ) == []
    with pytest.raises(DBAPIError, match="sales_pic"):  # NOT NULL kembali
        _sql(
            url,
            "INSERT INTO projects (id_project, project_name, customer_name, target_submit, "
            "status) VALUES ('PRJ-Z', 'P', 'C', :target, 'New')",
            {"target": date(2030, 1, 1)},
        )

    jalankan_alembic(url, "upgrade", "head")
    assert str(_kolom(url, "PRJ-A", "product_pic")) == produk
    assert str(_kolom(url, "PRJ-A", "created_by")) == produk
