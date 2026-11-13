"""
Unit test `core/dependencies` (tiket #55): `get_current_user`, `require_role`, dan
`ensure_project_access` dengan sesi DB palsu. Matriks authz terhadap Postgres nyata ada di
`tests/integration/test_auth_core.py`.
"""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import (
    TingkatAkses,
    ensure_project_access,
    get_current_user,
    require_role,
)
from app.core.exceptions import register_exception_handlers
from tests._auth_support import SesiPalsu, buat_token, user_palsu


def _app(db: SesiPalsu) -> TestClient:
    """Aplikasi mini yang memakai dependency produksi apa adanya."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/saya")
    async def saya(request: Request, user=Depends(get_current_user)):
        return {"id": str(user.id), "state_user_id": request.state.user_id}

    @app.get("/lead", dependencies=[Depends(require_role("Lead_SA"))])
    async def lead():
        return {"ok": True}

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestGetCurrentUser:
    def test_token_valid_mengembalikan_user_dan_mengisi_state(self):
        user = user_palsu("SA")
        resp = _app(SesiPalsu(user)).get("/saya", headers=_bearer(buat_token(user.id)))
        assert resp.status_code == 200
        assert resp.json() == {"id": str(user.id), "state_user_id": str(user.id)}

    def test_tanpa_token_401_dengan_header_www_authenticate(self):
        resp = _app(SesiPalsu(None)).get("/saya")
        assert resp.status_code == 401
        assert resp.headers["WWW-Authenticate"] == "Bearer"
        assert resp.json()["status"] == "error"
        assert "Token tidak ditemukan" in resp.json()["message"]

    def test_skema_selain_bearer_dianggap_tanpa_token(self):
        resp = _app(SesiPalsu(None)).get("/saya", headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401

    def test_token_kedaluwarsa_pesan_expired(self):
        token = buat_token(uuid.uuid4(), berlaku=timedelta(seconds=-10))
        resp = _app(SesiPalsu(user_palsu())).get("/saya", headers=_bearer(token))
        assert resp.status_code == 401
        assert "expired" in resp.json()["message"]
        assert resp.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("bukan-jwt", id="sampah"),
            pytest.param(lambda: buat_token(uuid.uuid4(), secret="y" * 40), id="secret-salah"),
        ],
    )
    def test_token_rusak_401(self, token):
        token = token() if callable(token) else token
        resp = _app(SesiPalsu(user_palsu())).get("/saya", headers=_bearer(token))
        assert resp.status_code == 401
        assert resp.json()["message"] == "Token tidak valid."

    def test_token_tanpa_subject_401(self):
        resp = _app(SesiPalsu(user_palsu())).get("/saya", headers=_bearer(buat_token(None)))
        assert resp.status_code == 401
        assert "subject" in resp.json()["message"]

    def test_user_sudah_dihapus_401(self):
        resp = _app(SesiPalsu(None)).get("/saya", headers=_bearer(buat_token(uuid.uuid4())))
        assert resp.status_code == 401
        assert resp.json()["message"] == "User tidak ditemukan."

    def test_refresh_token_tidak_diterima_sebagai_access_token(self):
        """Regresi: refresh token (TTL 7 hari) tidak boleh dipakai sebagai kredensial API."""
        user = user_palsu()
        resp = _app(SesiPalsu(user)).get(
            "/saya", headers=_bearer(buat_token(user.id, tipe="refresh"))
        )
        assert resp.status_code == 401

    def test_pesan_error_tidak_memuat_token(self):
        token = buat_token(uuid.uuid4(), secret="z" * 40)
        resp = _app(SesiPalsu(None)).get("/saya", headers=_bearer(token))
        assert token not in resp.text


class TestRequireRole:
    def test_peran_diizinkan(self):
        role = "Lead_SA"
        user = user_palsu(role)
        resp = _app(SesiPalsu(user)).get("/lead", headers=_bearer(buat_token(user.id)))
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["Sales", "Product", "SA"])
    def test_peran_lain_403(self, role):
        user = user_palsu(role)
        resp = _app(SesiPalsu(user)).get("/lead", headers=_bearer(buat_token(user.id)))
        assert resp.status_code == 403
        assert "tidak memiliki akses" in resp.json()["message"]

    def test_tanpa_token_401_bukan_403(self):
        assert _app(SesiPalsu(None)).get("/lead").status_code == 401


# --------------------------------------------------------------------------- ensure_project_access


def _proyek(sales_pic=None, assigned_sa=None) -> SimpleNamespace:
    return SimpleNamespace(
        id_project="PRJ-1", sales_pic=sales_pic or uuid.uuid4(), assigned_sa=assigned_sa
    )


class TestEnsureProjectAccess:
    @pytest.mark.parametrize(("role", "is_admin"), [("Lead_SA", False), ("SA", True)])
    async def test_peran_privileged_selalu_boleh(self, role, is_admin):
        user = user_palsu(role, is_admin=is_admin)
        await ensure_project_access(SesiPalsu(None), _proyek(), user)

    async def test_sales_pic_boleh(self):
        user = user_palsu("Sales")
        await ensure_project_access(SesiPalsu(None), _proyek(sales_pic=user.id), user)

    async def test_sa_ditugaskan_boleh(self):
        user = user_palsu("SA")
        await ensure_project_access(SesiPalsu(None), _proyek(assigned_sa=user.id), user)

    @pytest.mark.parametrize("role_kolab", ["viewer", "contributor"])
    async def test_collaborator_boleh(self, role_kolab):
        user = user_palsu("SA")
        kolab = SimpleNamespace(user_id=user.id, role=role_kolab)
        await ensure_project_access(SesiPalsu(kolab), _proyek(), user)

    @pytest.mark.parametrize("role", ["Sales", "SA"])
    async def test_pihak_luar_boleh_membaca_tetapi_tulis_403(self, role):
        """Keputusan 2026-11-10: baca terbuka untuk semua; tulis tetap dibatasi."""
        user = user_palsu(role)
        assert await ensure_project_access(SesiPalsu(None), _proyek(), user) is None
        with pytest.raises(HTTPException) as exc:
            await ensure_project_access(SesiPalsu(None), _proyek(), user, TingkatAkses.TULIS)
        assert exc.value.status_code == 403
        assert exc.value.detail == "Anda tidak memiliki akses ke proyek ini."

    async def test_proyek_belum_ada_sa_tidak_memberi_akses_tulis_ke_user_acak(self):
        """assigned_sa=None tidak boleh cocok dengan user mana pun."""
        with pytest.raises(HTTPException):
            await ensure_project_access(
                SesiPalsu(None), _proyek(assigned_sa=None), user_palsu("SA"), TingkatAkses.TULIS
            )
