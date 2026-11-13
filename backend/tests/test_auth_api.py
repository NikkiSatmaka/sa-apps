"""
Unit test endpoint `/api/v1/auth/*` (tiket #55) lewat `TestClient(app)` dengan sesi DB palsu
dan Google di-fake pada boundary HTTP. Jalur Postgres nyata: `tests/integration/test_auth_core.py`.
"""

import hashlib
import logging
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from tests._auth_support import SesiPalsu, buat_token, pasang_google, user_palsu

P = "/api/v1/auth"


@pytest.fixture
def klien():
    """`klien(db)` → TestClient dengan `get_db` diganti sesi palsu; dibersihkan setelah test."""

    def _buat(db: SesiPalsu | None = None, **kw) -> TestClient:
        async def _db():
            yield db or SesiPalsu(None)

        app.dependency_overrides[get_db] = _db
        return TestClient(app, follow_redirects=False, **kw)

    yield _buat
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _bersihkan_domain(monkeypatch):
    """Default test: tanpa pembatasan domain / mapping (tiap test mengatur sendiri)."""
    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "")
    monkeypatch.setattr(settings, "ROLE_MAPPING", "{}")
    monkeypatch.setattr("app.services.auth_service.auth_service._role_mapping", None)


def _log_aplikasi(caplog) -> str:
    """Log dari kode `app.*` saja (log klien test sendiri mencatat URL request-nya)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- /config


class TestAuthConfig:
    def test_demo_mati_oauth_belum_dikonfigurasi(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", False)
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
        assert klien().get(f"{P}/config").json() == {"demo_mode": False, "oauth_configured": False}

    def test_demo_aktif_di_development(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        assert klien().get(f"{P}/config").json()["demo_mode"] is True

    def test_demo_dilaporkan_mati_di_produksi_meski_flag_true(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        assert klien().get(f"{P}/config").json()["demo_mode"] is False

    @pytest.mark.parametrize(
        ("cid", "secret", "diharapkan"),
        [
            ("client-id-panjang-123", "rahasia", True),
            ("client-id-panjang-123", "", False),
            ("", "rahasia", False),
            ("pendek", "rahasia", False),  # placeholder pendek tidak dianggap terkonfigurasi
        ],
    )
    def test_oauth_configured(self, klien, monkeypatch, cid, secret, diharapkan):
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", cid)
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", secret)
        assert klien().get(f"{P}/config").json()["oauth_configured"] is diharapkan

    def test_tidak_butuh_autentikasi(self, klien):
        assert klien().get(f"{P}/config").status_code == 200


# --------------------------------------------------------------------------- demo login


class TestDemoLogin:
    def test_demo_nonaktif_403(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", False)
        resp = klien().post(f"{P}/demo-login", json={"role": "Admin"})
        assert resp.status_code == 403
        assert "Demo mode tidak aktif" in resp.json()["message"]

    @pytest.mark.parametrize("role", ["Sales", "Product", "SA", "Lead_SA", "Admin"])
    def test_produksi_memblok_demo_untuk_semua_peran(self, klien, monkeypatch, role):
        """Hard block: ENVIRONMENT=production menolak demo login meski DEMO_MODE=true."""
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        db = SesiPalsu(None)
        resp = klien(db).post(f"{P}/demo-login", json={"role": role})
        assert resp.status_code == 403
        assert "tokens" not in resp.text
        assert db.ditambahkan == []  # tidak ada user demo yang dibuat

    @pytest.mark.parametrize("env", ["development", "staging"])
    def test_demo_aktif_di_non_produksi(self, klien, monkeypatch, env):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", env)
        assert klien().post(f"{P}/demo-login", json={"role": "SA"}).status_code == 200

    @pytest.mark.parametrize(
        ("persona", "email", "role", "is_admin"),
        [
            ("Sales", "demo-sales@portal-sa.local", "Sales", False),
            ("Product", "demo-product@portal-sa.local", "Product", False),
            ("SA", "demo-sa@portal-sa.local", "SA", False),
            ("Lead_SA", "demo-lead@portal-sa.local", "Lead_SA", False),
            # Persona "Admin" = SA dengan flag admin (admin selalu menempel pada satu role).
            ("Admin", "demo-admin@portal-sa.local", "SA", True),
        ],
    )
    def test_user_demo_baru_dibuat_dengan_id_deterministik_dan_token_valid(
        self, klien, monkeypatch, persona, email, role, is_admin
    ):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        db = SesiPalsu(None)

        resp = klien(db).post(f"{P}/demo-login", json={"role": persona})

        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["email"] == email
        assert body["user"]["role"] == role
        assert body["user"]["is_admin"] is is_admin
        assert body["user"]["id"] == str(uuid.UUID(hashlib.md5(email.encode()).hexdigest()))
        assert len(db.ditambahkan) == 1 and db.jumlah_commit == 1
        assert body["tokens"]["token_type"] == "bearer"
        # token benar-benar bisa dipakai di endpoint terproteksi
        from app.services.auth_service import auth_service

        klaim = auth_service.verify_access_token(body["tokens"]["access_token"])
        assert (klaim["role"], klaim["is_admin"]) == (role, is_admin)

    def test_user_demo_existing_tidak_dibuat_ulang(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        ada = user_palsu("SA", is_admin=True, email="demo-admin@portal-sa.local")
        db = SesiPalsu(ada)
        resp = klien(db).post(f"{P}/demo-login", json={"role": "Admin"})
        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == str(ada.id)
        assert db.ditambahkan == [] and db.jumlah_commit == 0

    def test_peran_tidak_dikenal_422(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "DEMO_MODE", True)
        assert klien().post(f"{P}/demo-login", json={"role": "Root"}).status_code == 422


# --------------------------------------------------------------------------- login & callback


class TestLoginRedirect:
    def test_redirect_ke_google_tanpa_token_apa_pun(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id-panjang-123")
        resp = klien().get(f"{P}/login", params={"redirect_url": "/dashboard"})
        assert resp.status_code in (302, 307)
        loc = urlparse(resp.headers["location"])
        assert loc.netloc == "accounts.google.com"
        q = parse_qs(loc.query)
        assert q["state"] == ["/dashboard"]
        assert q["client_id"] == ["client-id-panjang-123"]
        assert "access_token" not in loc.query and "token" not in q


class TestCallback:
    def test_consent_dibatalkan_400(self, klien):
        resp = klien().get(f"{P}/callback", params={"error": "access_denied"})
        assert resp.status_code == 400
        assert "access_denied" in resp.json()["message"]

    def test_tanpa_code_400(self, klien):
        resp = klien().get(f"{P}/callback")
        assert resp.status_code == 400
        assert "Authorization code" in resp.json()["message"]

    def test_sukses_membuat_user_dan_token_ada_di_body_bukan_url(self, klien, monkeypatch):
        diterima = pasang_google(monkeypatch)
        db = SesiPalsu(None)

        resp = klien(db).get(f"{P}/callback", params={"code": "kode-ok", "state": "/dashboard"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["email"] == "budi@perusahaan.id"
        assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]
        assert "location" not in resp.headers
        assert len(db.ditambahkan) == 1
        assert len(diterima) == 2  # tukar kode + ambil profil

    def test_peran_user_baru_mengikuti_role_mapping(self, klien, monkeypatch):
        pasang_google(monkeypatch)
        monkeypatch.setattr(settings, "ROLE_MAPPING", '{"*@perusahaan.id": "Sales"}')
        resp = klien().get(f"{P}/callback", params={"code": "k"})
        assert resp.json()["user"]["role"] == "Sales"

    def test_domain_ditolak_403_dan_tanpa_user(self, klien, monkeypatch):
        pasang_google(monkeypatch, profil={"id": "g", "email": "x@gmail.com", "name": "X"})
        monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "perusahaan.id")
        db = SesiPalsu(None)
        resp = klien(db).get(f"{P}/callback", params={"code": "k"})
        assert resp.status_code == 403
        assert "gmail.com" in resp.json()["message"]
        assert db.ditambahkan == []

    def test_kode_tidak_valid_502(self, klien, monkeypatch):
        pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
        resp = klien().get(f"{P}/callback", params={"code": "basi"})
        assert resp.status_code == 502
        assert "Gagal mendapatkan token dari Google" in resp.json()["message"]

    def test_error_service_umum_400(self, klien, monkeypatch):
        """Error AuthService selain domain/OAuth dipetakan ke 400 dengan detail-nya."""
        from unittest.mock import AsyncMock

        from app.services.auth_service import AuthServiceError, auth_service

        monkeypatch.setattr(
            auth_service,
            "handle_callback",
            AsyncMock(side_effect=AuthServiceError("lain", "Gagal tak terduga di service.")),
        )
        resp = klien().get(f"{P}/callback", params={"code": "k"})
        assert resp.status_code == 400
        assert resp.json()["message"] == "Gagal tak terduga di service."

    def test_profil_gagal_502(self, klien, monkeypatch):
        pasang_google(monkeypatch, profil_status=500)
        assert klien().get(f"{P}/callback", params={"code": "k"}).status_code == 502


class TestCallbackCalendar:
    def _state(self, url: str) -> str:
        return f"calendar_auth|{url}"

    def test_sukses_redirect_ke_frontend_dengan_token_di_fragment(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
        pasang_google(monkeypatch, token_body={"access_token": "tok-kalender"})
        db = SesiPalsu(None)

        resp = klien(db).get(
            f"{P}/callback",
            params={
                "code": "k",
                "state": self._state("http://localhost:3000/activity-logs/calendar"),
            },
        )

        assert resp.status_code in (302, 307)
        loc = resp.headers["location"]
        assert loc == "http://localhost:3000/activity-logs/calendar#gcal_token=tok-kalender"
        # fragment tidak dikirim ke server: tidak ada token di query string
        assert urlparse(loc).query == ""
        assert db.ditambahkan == []  # flow kalender tidak membuat/login user

    def test_gagal_tukar_kode_redirect_dengan_penanda_error(self, klien, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
        pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
        resp = klien().get(
            f"{P}/callback",
            params={"code": "basi", "state": self._state("http://localhost:3000/x")},
        )
        assert resp.status_code in (302, 307)
        assert (
            resp.headers["location"] == "http://localhost:3000/x#gcal_error=token_exchange_failed"
        )

    @pytest.mark.parametrize(
        "url_jahat",
        [
            "https://jahat.example/tangkap",
            "http://localhost:3000.jahat.example/x",
            "//jahat.example/x",
            "http://localhost:3000@jahat.example/x",
            "javascript:alert(1)",
        ],
    )
    def test_return_url_di_luar_frontend_ditolak_tanpa_menukar_kode(
        self, klien, monkeypatch, url_jahat
    ):
        """Regresi keamanan: token Google tidak boleh dikirim ke origin selain FRONTEND_URL."""
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
        diterima = pasang_google(monkeypatch, token_body={"access_token": "tok-rahasia"})

        resp = klien().get(f"{P}/callback", params={"code": "k", "state": self._state(url_jahat)})

        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert "tok-rahasia" not in resp.text
        assert diterima == []  # kode OAuth tidak ditukar sama sekali


# --------------------------------------------------------------------------- refresh / logout / me


class TestRefresh:
    def test_refresh_valid_memberi_pasangan_baru(self, klien):
        user = user_palsu("Lead_SA")
        resp = klien(SesiPalsu(user)).post(
            f"{P}/refresh", json={"refresh_token": buat_token(user.id, tipe="refresh")}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {"access_token", "refresh_token", "token_type", "expires_in"}
        from app.services.auth_service import auth_service

        assert auth_service.verify_access_token(body["access_token"])["role"] == "Lead_SA"

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param(lambda u: "sampah", id="sampah"),
            pytest.param(
                lambda u: buat_token(u, tipe="refresh", berlaku=timedelta(seconds=-1)),
                id="kedaluwarsa",
            ),
            pytest.param(lambda u: buat_token(u, tipe="access"), id="access-bukan-refresh"),
        ],
    )
    def test_refresh_tidak_valid_401(self, klien, token):
        user = user_palsu()
        resp = klien(SesiPalsu(user)).post(f"{P}/refresh", json={"refresh_token": token(user.id)})
        assert resp.status_code == 401

    def test_user_tidak_ada_401(self, klien):
        resp = klien(SesiPalsu(None)).post(
            f"{P}/refresh", json={"refresh_token": buat_token(uuid.uuid4(), tipe="refresh")}
        )
        assert resp.status_code == 401

    def test_body_tanpa_refresh_token_422(self, klien):
        assert klien().post(f"{P}/refresh", json={}).status_code == 422


class TestLogout:
    def test_logout_dengan_token_valid(self, klien):
        resp = klien().post(f"{P}/logout", headers=_auth(buat_token(uuid.uuid4())))
        assert resp.status_code == 200
        assert resp.json() == {"message": "Logout berhasil."}

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Token abc"}, {"Authorization": "bearer abc"}],
        ids=["tanpa-header", "skema-salah", "huruf-kecil"],
    )
    def test_header_tidak_valid_401(self, klien, headers):
        assert klien().post(f"{P}/logout", headers=headers).status_code == 401

    def test_token_rusak_401(self, klien):
        assert klien().post(f"{P}/logout", headers=_auth("rusak")).status_code == 401


class TestMe:
    def test_mengembalikan_user_login(self, klien):
        user = user_palsu("SA", is_admin=True)
        resp = klien(SesiPalsu(user)).get(f"{P}/me", headers=_auth(buat_token(user.id)))
        assert resp.status_code == 200
        assert resp.json()["id"] == str(user.id)
        assert resp.json()["role"] == "SA"
        assert resp.json()["is_admin"] is True

    def test_tanpa_token_401(self, klien):
        assert klien().get(f"{P}/me").status_code == 401

    def test_token_kedaluwarsa_401(self, klien):
        token = buat_token(uuid.uuid4(), berlaku=timedelta(seconds=-5))
        assert (
            klien(SesiPalsu(user_palsu())).get(f"{P}/me", headers=_auth(token)).status_code == 401
        )

    def test_refresh_token_tidak_bisa_dipakai(self, klien):
        user = user_palsu()
        token = buat_token(user.id, tipe="refresh")
        assert klien(SesiPalsu(user)).get(f"{P}/me", headers=_auth(token)).status_code == 401

    def test_user_terhapus_401(self, klien):
        assert (
            klien(SesiPalsu(None))
            .get(f"{P}/me", headers=_auth(buat_token(uuid.uuid4())))
            .status_code
            == 401
        )


# --------------------------------------------------------------------------- token tidak bocor


class TestTokenTidakBocor:
    def test_login_flow_tidak_menaruh_token_di_url_atau_log(self, klien, monkeypatch, caplog):
        pasang_google(monkeypatch, token_body={"access_token": "tok-google-rahasia"})
        caplog.set_level(logging.DEBUG)

        resp = klien(SesiPalsu(None)).get(f"{P}/callback", params={"code": "kode-rahasia"})

        tokens = resp.json()["tokens"]
        assert "location" not in resp.headers
        assert str(resp.url).count(tokens["access_token"]) == 0
        log = _log_aplikasi(caplog)
        for rahasia in (
            tokens["access_token"],
            tokens["refresh_token"],
            "tok-google-rahasia",
            settings.JWT_SECRET_KEY,
        ):
            assert rahasia not in log

    def test_kegagalan_tukar_kode_kalender_tidak_mencatat_token_di_log(
        self, klien, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
        pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
        caplog.set_level(logging.DEBUG)
        klien().get(
            f"{P}/callback",
            params={"code": "kode-rahasia", "state": "calendar_auth|http://localhost:3000/x"},
        )
        log = _log_aplikasi(caplog)
        assert "Calendar OAuth token exchange failed" in log  # jalur log benar-benar dieksekusi
        assert "kode-rahasia" not in log
        assert settings.JWT_SECRET_KEY not in log

    def test_respons_error_tidak_memantulkan_token(self, klien):
        token = buat_token(uuid.uuid4(), secret="q" * 40)
        for resp in (
            klien().get(f"{P}/me", headers=_auth(token)),
            klien().post(f"{P}/logout", headers=_auth(token)),
        ):
            assert resp.status_code == 401
            assert token not in resp.text
            assert token not in str(resp.headers)

    def test_refresh_gagal_tidak_memantulkan_token(self, klien):
        resp = klien().post(f"{P}/refresh", json={"refresh_token": "refresh-rusak-123"})
        assert resp.status_code == 401
        assert "refresh-rusak-123" not in resp.text
