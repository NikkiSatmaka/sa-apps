"""
Integrasi API Admin (daftar user, ubah role, flag `is_admin`) terhadap Postgres nyata
(tiket #60, spec #49; diperbarui #114/ADR 0012).

Mencakup hak akses admin (flag `is_admin`), validasi role/ID, failsafe admin terakhir, dan efek
perubahan pada request berikutnya (role dan flag dibaca dari DB tiap request, bukan dari token).
Pasangan unit: `tests/test_admin_last_admin_failsafe.py`.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import User
from tests.integration.helpers_t60 import API, bearer, buat_user

ADMIN = f"{API}/admin"


@pytest.mark.parametrize("peran", ["Sales", "Product", "SA", "Lead_SA"])
async def test_bukan_admin_ditolak_403_di_semua_endpoint(api, db_session, peran):
    pelaku = await buat_user(db_session, peran)
    target = await buat_user(db_session, "SA")
    h = bearer(pelaku)

    daftar = await api.client.get(f"{ADMIN}/users", headers=h)
    ubah = await api.client.patch(
        f"{ADMIN}/users/{target.id}/role", json={"role": "Lead_SA"}, headers=h
    )
    jadikan_admin = await api.client.patch(
        f"{ADMIN}/users/{target.id}/admin", json={"is_admin": True}, headers=h
    )

    assert daftar.status_code == ubah.status_code == jadikan_admin.status_code == 403
    await db_session.refresh(target)
    assert (target.role, target.is_admin) == ("SA", False)


async def test_tanpa_token_401(api):
    assert (await api.client.get(f"{ADMIN}/users")).status_code == 401
    resp = await api.client.patch(f"{ADMIN}/users/{uuid.uuid4()}/role", json={"role": "SA"})
    assert resp.status_code == 401
    resp = await api.client.patch(f"{ADMIN}/users/{uuid.uuid4()}/admin", json={"is_admin": True})
    assert resp.status_code == 401


async def test_daftar_user_urut_nama_berisi_field_publik(api, db_session):
    admin = await buat_user(db_session, "Admin", name="Zeta Admin")
    await buat_user(db_session, "SA", name="Alfa SA", email="alfa@portal-sa.local")
    await buat_user(db_session, "Sales", name="Beta Sales", email="beta@portal-sa.local")

    resp = await api.client.get(f"{ADMIN}/users", headers=bearer(admin))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [u["name"] for u in data] == ["Alfa SA", "Beta Sales", "Zeta Admin"]
    assert data[0] == {
        "id": data[0]["id"],
        "name": "Alfa SA",
        "email": "alfa@portal-sa.local",
        "role": "SA",
        "is_admin": False,
    }
    assert data[2]["is_admin"] is True
    assert "3 users" in resp.json()["message"]


@pytest.mark.parametrize("role_baru", ["Sales", "Product", "SA", "Lead_SA"])
async def test_ubah_role_ke_semua_role_valid_tersimpan(api, db_session, role_baru):
    admin = await buat_user(db_session, "Admin")
    target = await buat_user(db_session, "SA", name="Target")

    resp = await api.client.patch(
        f"{ADMIN}/users/{target.id}/role", json={"role": role_baru}, headers=bearer(admin)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["role"], data["old_role"], data["id"]) == (role_baru, "SA", str(target.id))
    stored = (await db_session.execute(select(User.role).where(User.id == target.id))).scalar_one()
    assert stored == role_baru


async def test_flag_admin_berlaku_pada_request_berikutnya_tanpa_login_ulang(api, db_session):
    admin = await buat_user(db_session, "Admin")
    target = await buat_user(db_session, "SA")
    h_target = bearer(target)
    assert (await api.client.get(f"{ADMIN}/users", headers=h_target)).status_code == 403

    resp = await api.client.patch(
        f"{ADMIN}/users/{target.id}/admin", json={"is_admin": True}, headers=bearer(admin)
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["is_admin"], data["old_is_admin"], data["role"]) == (True, False, "SA")
    assert (await api.client.get(f"{ADMIN}/users", headers=h_target)).status_code == 200


@pytest.mark.parametrize("role_invalid", ["Admin", "admin", "Manager", "", "SA "])
async def test_ubah_role_invalid_400_dan_tidak_berubah(api, db_session, role_invalid):
    admin = await buat_user(db_session, "Admin")
    target = await buat_user(db_session, "SA")

    resp = await api.client.patch(
        f"{ADMIN}/users/{target.id}/role", json={"role": role_invalid}, headers=bearer(admin)
    )

    assert resp.status_code == 400
    await db_session.refresh(target)
    assert target.role == "SA"


async def test_ubah_role_id_bukan_uuid_400_dan_user_tidak_ada_404_dan_body_kosong_422(
    api, db_session
):
    admin = await buat_user(db_session, "Admin")
    h = bearer(admin)

    bukan_uuid = await api.client.patch(
        f"{ADMIN}/users/bukan-uuid/role", json={"role": "SA"}, headers=h
    )
    tak_ada = await api.client.patch(
        f"{ADMIN}/users/{uuid.uuid4()}/role", json={"role": "SA"}, headers=h
    )
    kosong = await api.client.patch(f"{ADMIN}/users/{uuid.uuid4()}/role", json={}, headers=h)

    assert bukan_uuid.status_code == 400
    assert tak_ada.status_code == 404
    assert kosong.status_code == 422


async def test_admin_terakhir_tidak_bisa_dicabut_sendiri_409(api, db_session):
    """DB uji bersih per test: satu-satunya admin tidak boleh mencabut flag dirinya."""
    admin = await buat_user(db_session, "Admin")

    resp = await api.client.patch(
        f"{ADMIN}/users/{admin.id}/admin", json={"is_admin": False}, headers=bearer(admin)
    )

    assert resp.status_code == 409
    assert "Admin terakhir" in resp.json()["message"]
    await db_session.refresh(admin)
    assert admin.is_admin is True


async def test_cabut_admin_diizinkan_bila_masih_ada_admin_lain(api, db_session):
    admin1 = await buat_user(db_session, "Admin")
    admin2 = await buat_user(db_session, "Admin")

    resp = await api.client.patch(
        f"{ADMIN}/users/{admin2.id}/admin", json={"is_admin": False}, headers=bearer(admin1)
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(admin2)
    assert admin2.is_admin is False
    # Kini admin1 adalah admin terakhir: pencabutan berikutnya ditolak.
    lagi = await api.client.patch(
        f"{ADMIN}/users/{admin1.id}/admin", json={"is_admin": False}, headers=bearer(admin1)
    )
    assert lagi.status_code == 409


async def test_set_is_admin_true_ke_admin_bukan_pencabutan_selalu_boleh(api, db_session):
    admin = await buat_user(db_session, "Admin")

    resp = await api.client.patch(
        f"{ADMIN}/users/{admin.id}/admin", json={"is_admin": True}, headers=bearer(admin)
    )

    assert resp.status_code == 200


async def test_ubah_role_tidak_menghilangkan_flag_admin(api, db_session):
    """Admin selalu menempel pada satu role fungsional; mengubah role tidak mencabut admin."""
    admin = await buat_user(db_session, "Admin")

    resp = await api.client.patch(
        f"{ADMIN}/users/{admin.id}/role", json={"role": "Lead_SA"}, headers=bearer(admin)
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(admin)
    assert (admin.role, admin.is_admin) == ("Lead_SA", True)


async def test_admin_id_bukan_uuid_400_user_tidak_ada_404_body_salah_422(api, db_session):
    admin = await buat_user(db_session, "Admin")
    h = bearer(admin)

    bukan_uuid = await api.client.patch(
        f"{ADMIN}/users/bukan-uuid/admin", json={"is_admin": True}, headers=h
    )
    tak_ada = await api.client.patch(
        f"{ADMIN}/users/{uuid.uuid4()}/admin", json={"is_admin": True}, headers=h
    )
    kosong = await api.client.patch(f"{ADMIN}/users/{uuid.uuid4()}/admin", json={}, headers=h)

    assert (bukan_uuid.status_code, tak_ada.status_code, kosong.status_code) == (400, 404, 422)
