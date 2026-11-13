"""
Migration 017 (issue #114, ADR 0012): role `Product` + flag `is_admin`, role `Admin` dihapus.

Memakai database sementara per test (`database_kosong_url`) karena mengubah versi skema.
"""

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _sql, _versi


def _user(url: str, role: str, nama: str, **kolom_ekstra: str) -> str:
    user_id = str(uuid.uuid4())
    kolom = ["id", "email", "name", "role", "google_id", *kolom_ekstra]
    nilai = [":id", ":email", ":name", ":role", ":google_id", *(f":{k}" for k in kolom_ekstra)]
    _sql(
        url,
        f"INSERT INTO users ({', '.join(kolom)}) VALUES ({', '.join(nilai)})",
        {
            "id": user_id,
            "email": f"{nama}@mig.test",
            "name": nama,
            "role": role,
            "google_id": f"g-{nama}",
            **kolom_ekstra,
        },
    )
    return user_id


def _baca(url: str, user_id: str, kolom: str):
    return _sql(url, f"SELECT {kolom} FROM users WHERE id = :id", {"id": user_id})[0][0]


def test_upgrade_memetakan_admin_lama_ke_lead_sa_dengan_is_admin(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "016")
    admin = _user(url, "Admin", "admin-lama")
    sales = _user(url, "Sales", "sales-lama")
    sa = _user(url, "SA", "sa-lama")

    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == _head()
    assert (_baca(url, admin, "role"), _baca(url, admin, "is_admin")) == ("Lead_SA", True)
    assert (_baca(url, sales, "role"), _baca(url, sales, "is_admin")) == ("Sales", False)
    assert (_baca(url, sa, "role"), _baca(url, sa, "is_admin")) == ("SA", False)


def test_head_menerima_product_dan_menolak_admin_sebagai_role(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    produk = _user(url, "Product", "produk")
    assert _baca(url, produk, "role") == "Product"
    assert _baca(url, produk, "is_admin") is False  # bawaan: bukan admin

    with pytest.raises(DBAPIError, match="chk_users_role"):
        _user(url, "Admin", "admin-baru")


def test_is_admin_tidak_boleh_null(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    user_id = _user(url, "SA", "sa-null")

    with pytest.raises(DBAPIError, match="is_admin"):
        _sql(url, "UPDATE users SET is_admin = NULL WHERE id = :id", {"id": user_id})


def test_downgrade_mengembalikan_admin_dan_memetakan_product_ke_sales_lalu_naik_lagi(
    database_kosong_url,
):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    admin = _user(url, "SA", "sa-admin")
    _sql(url, "UPDATE users SET is_admin = true WHERE id = :id", {"id": admin})
    produk = _user(url, "Product", "produk")
    lead = _user(url, "Lead_SA", "lead")

    jalankan_alembic(url, "downgrade", "016")

    assert _versi(url) == "016"
    assert _baca(url, admin, "role") == "Admin"
    assert _baca(url, produk, "role") == "Sales"  # role Product belum ada di skema lama
    assert _baca(url, lead, "role") == "Lead_SA"
    assert _sql(
        url,
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'is_admin'",
    ) == []

    jalankan_alembic(url, "upgrade", "head")
    assert (_baca(url, admin, "role"), _baca(url, admin, "is_admin")) == ("Lead_SA", True)
