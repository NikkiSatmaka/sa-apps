"""
Unit test `AuthService` (tiket #55): OAuth Google (HTTP di-fake di boundary), validasi domain,
mapping peran, JWT access/refresh, dan provisioning user. Tanpa DB nyata.
"""

import json
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st
from jose import jwt

from app.core.config import settings
from app.schemas.auth import GoogleProfile
from app.services.auth_service import (
    AuthService,
    DomainNotAllowedError,
    OAuthError,
    TokenError,
)
from tests._auth_support import (
    SesiPalsu,
    buat_token,
    pasang_google,
    pasang_google_dengan,
    user_palsu,
)


@pytest.fixture
def svc() -> AuthService:
    """Instance segar (cache role_mapping singleton tidak ikut terpakai)."""
    return AuthService()


def _mapping(monkeypatch, nilai) -> None:
    monkeypatch.setattr(
        settings, "ROLE_MAPPING", nilai if isinstance(nilai, str) else json.dumps(nilai)
    )


def _domain(monkeypatch, nilai: str) -> None:
    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", nilai)


# --------------------------------------------------------------------------- initiate_oauth


class TestInitiateOauth:
    def test_url_mengarah_ke_google_dengan_parameter_wajib(self, svc, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id-uji-12345")
        monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/cb")

        url = svc.initiate_oauth()

        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
        q = parse_qs(parsed.query)
        assert q["client_id"] == ["client-id-uji-12345"]
        assert q["redirect_uri"] == ["http://localhost:8000/cb"]
        assert q["response_type"] == ["code"]
        assert "email" in q["scope"][0].split()
        assert "state" not in q

    def test_state_diteruskan(self, svc):
        q = parse_qs(urlparse(svc.initiate_oauth(state="/dashboard")).query)
        assert q["state"] == ["/dashboard"]

    def test_state_dengan_karakter_khusus_tidak_menyisipkan_parameter(self, svc):
        """Regresi: state berisi `&` tidak boleh menjadi parameter OAuth tambahan."""
        q = parse_qs(urlparse(svc.initiate_oauth(state="/x&redirect_uri=http://jahat")).query)
        assert q["state"] == ["/x&redirect_uri=http://jahat"]
        assert len(q["redirect_uri"]) == 1
        assert q["redirect_uri"][0] != "http://jahat"


# --------------------------------------------------------------------------- validate_domain


class TestValidateDomain:
    def test_whitelist_kosong_mengizinkan_semua(self, svc, monkeypatch):
        _domain(monkeypatch, "")
        assert svc.validate_domain("siapa@saja.com") is True

    def test_domain_dalam_whitelist_diizinkan_tanpa_peduli_huruf(self, svc, monkeypatch):
        _domain(monkeypatch, "Perusahaan.id, mitra.co.id")
        assert svc.validate_domain("Budi@PERUSAHAAN.ID") is True
        assert svc.validate_domain("sari@mitra.co.id") is True

    def test_domain_di_luar_whitelist_ditolak_dengan_nama_domain(self, svc, monkeypatch):
        _domain(monkeypatch, "perusahaan.id")
        with pytest.raises(DomainNotAllowedError) as exc:
            svc.validate_domain("x@gmail.com")
        assert "gmail.com" in exc.value.detail
        assert exc.value.error == "domain_not_allowed"

    def test_subdomain_tidak_dianggap_domain_yang_diizinkan(self, svc, monkeypatch):
        _domain(monkeypatch, "perusahaan.id")
        with pytest.raises(DomainNotAllowedError):
            svc.validate_domain("x@evil.perusahaan.id")
        with pytest.raises(DomainNotAllowedError):
            svc.validate_domain("x@perusahaan.id.evil.com")

    @given(local=st.from_regex(r"[a-z0-9._-]{1,12}", fullmatch=True))
    @hy_settings(max_examples=40, deadline=None)
    def test_property_domain_asing_selalu_ditolak(self, local):
        s = AuthService()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "ALLOWED_DOMAINS", "perusahaan.id")
            with pytest.raises(DomainNotAllowedError):
                s.validate_domain(f"{local}@asing.com")
            assert s.validate_domain(f"{local}@perusahaan.id") is True


# --------------------------------------------------------------------------- mapping peran


class TestDetermineRole:
    def test_default_sa_tanpa_mapping(self, svc, monkeypatch):
        _mapping(monkeypatch, {})
        assert svc._determine_role("a@b.com") == "SA"

    def test_exact_match_tidak_peduli_huruf(self, svc, monkeypatch):
        _mapping(monkeypatch, {"Boss@Perusahaan.id": "Admin"})
        assert svc._determine_role("boss@perusahaan.ID") == "Admin"

    def test_wildcard_domain(self, svc, monkeypatch):
        _mapping(monkeypatch, {"*@sales.id": "Sales"})
        assert svc._determine_role("budi@sales.id") == "Sales"
        assert svc._determine_role("budi@lain.id") == "SA"

    def test_exact_lebih_prioritas_daripada_wildcard(self, svc, monkeypatch):
        _mapping(monkeypatch, {"*@perusahaan.id": "Sales", "lead@perusahaan.id": "Lead_SA"})
        assert svc._determine_role("lead@perusahaan.id") == "Lead_SA"
        assert svc._determine_role("staf@perusahaan.id") == "Sales"

    @pytest.mark.parametrize("mentah", ["bukan json", "", "[1, 2]", '"teks"', "null"])
    def test_mapping_rusak_atau_bukan_objek_jatuh_ke_default(self, svc, monkeypatch, mentah):
        """Regresi: JSON valid tapi bukan objek tidak boleh membuat login meledak (500)."""
        _mapping(monkeypatch, mentah)
        assert svc._determine_role("a@b.com") == "SA"

    def test_mapping_di_cache_per_instance(self, svc, monkeypatch):
        _mapping(monkeypatch, {"a@b.com": "Admin"})
        assert svc._determine_role("a@b.com") == "Admin"
        _mapping(monkeypatch, {})  # perubahan setelah dibaca tidak terbaca ulang
        assert svc._determine_role("a@b.com") == "Admin"

    @given(
        local=st.from_regex(r"[a-z]{1,8}", fullmatch=True),
        domain=st.from_regex(r"[a-z]{2,8}\.(com|id)", fullmatch=True),
        peran=st.sampled_from(["Sales", "SA", "Lead_SA", "Admin"]),
    )
    @hy_settings(max_examples=40, deadline=None)
    def test_property_hasil_selalu_peran_mapping_atau_default(self, local, domain, peran):
        s = AuthService()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "ROLE_MAPPING", json.dumps({f"*@{domain}": peran}))
            assert s._determine_role(f"{local}@{domain}") == peran
            assert s._determine_role(f"{local}@tidak-ada.org") == "SA"


# --------------------------------------------------------------------------- JWT


class TestTokenPair:
    def test_klaim_access_dan_refresh(self, svc):
        user = user_palsu("Lead_SA")
        pair = svc._create_token_pair(user)

        akses = jwt.decode(pair.access_token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        refresh = jwt.decode(pair.refresh_token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        assert akses["sub"] == str(user.id)
        assert akses["email"] == user.email
        assert akses["role"] == "Lead_SA"
        assert akses["type"] == "access"
        assert refresh["sub"] == str(user.id)
        assert refresh["type"] == "refresh"
        assert "role" not in refresh and "email" not in refresh
        assert akses["exp"] - akses["iat"] == settings.JWT_EXPIRE_HOURS * 3600
        assert refresh["exp"] - refresh["iat"] == settings.JWT_REFRESH_EXPIRE_HOURS * 3600
        assert pair.expires_in == settings.JWT_EXPIRE_HOURS * 3600
        assert pair.token_type == "bearer"

    @given(uid=st.uuids())
    @hy_settings(max_examples=30, deadline=None)
    def test_property_token_access_roundtrip(self, uid):
        s = AuthService()
        pair = s._create_token_pair(user_palsu("SA", id=uid))
        assert s.verify_access_token(pair.access_token)["sub"] == str(uid)


class TestVerifyAccessToken:
    def test_valid(self, svc):
        uid = uuid.uuid4()
        assert svc.verify_access_token(buat_token(uid))["sub"] == str(uid)

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param(
                lambda: buat_token(uuid.uuid4(), berlaku=timedelta(seconds=-5)), id="kedaluwarsa"
            ),
            pytest.param(lambda: buat_token(uuid.uuid4(), secret="x" * 40), id="secret-salah"),
            pytest.param(lambda: "bukan.jwt.sama-sekali", id="sampah"),
            pytest.param(lambda: "", id="kosong"),
            pytest.param(
                lambda: buat_token(uuid.uuid4(), tipe="refresh"), id="refresh-bukan-access"
            ),
            pytest.param(lambda: buat_token(uuid.uuid4(), tipe=None), id="tanpa-type"),
        ],
    )
    def test_ditolak(self, svc, token):
        with pytest.raises(TokenError):
            svc.verify_access_token(token())

    def test_algoritma_none_ditolak(self, svc):
        """Token tak bertanda tangan (alg=none) tidak boleh diterima."""
        import base64

        def b64(d: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        kepala = b64({"alg": "none", "typ": "JWT"})
        isi = b64({"sub": str(uuid.uuid4()), "type": "access"})
        palsu = f"{kepala}.{isi}."
        with pytest.raises(TokenError):
            svc.verify_access_token(palsu)


class TestRefreshToken:
    async def test_refresh_valid_menghasilkan_pasangan_baru(self, svc):
        user = user_palsu("Admin")
        db = SesiPalsu(user)

        pair = await svc.refresh_token(buat_token(user.id, tipe="refresh"), db)

        akses = svc.verify_access_token(pair.access_token)
        assert akses["sub"] == str(user.id)
        assert akses["role"] == "Admin"

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param(lambda u: buat_token(u, tipe="access"), id="access-bukan-refresh"),
            pytest.param(
                lambda u: buat_token(u, tipe="refresh", berlaku=timedelta(seconds=-1)),
                id="kedaluwarsa",
            ),
            pytest.param(lambda u: "sampah", id="sampah"),
            pytest.param(lambda u: buat_token(None, tipe="refresh"), id="tanpa-sub"),
        ],
    )
    async def test_refresh_tidak_valid_ditolak(self, svc, token):
        user = user_palsu()
        with pytest.raises(TokenError):
            await svc.refresh_token(token(user.id), SesiPalsu(user))

    async def test_user_sudah_tidak_ada_ditolak(self, svc):
        with pytest.raises(TokenError, match="User tidak ditemukan"):
            await svc.refresh_token(buat_token(uuid.uuid4(), tipe="refresh"), SesiPalsu(None))


class TestRevokeDanCurrentUser:
    def test_revoke_token_valid(self, svc):
        assert svc.revoke_session(buat_token(uuid.uuid4())) is True

    def test_revoke_token_rusak(self, svc):
        with pytest.raises(TokenError):
            svc.revoke_session("rusak")

    async def test_get_current_user_ditemukan(self, svc):
        user = user_palsu()
        assert await svc.get_current_user(buat_token(user.id), SesiPalsu(user)) is user

    async def test_get_current_user_tak_ada_di_db(self, svc):
        with pytest.raises(TokenError, match="User tidak ditemukan"):
            await svc.get_current_user(buat_token(uuid.uuid4()), SesiPalsu(None))

    async def test_get_current_user_token_refresh_ditolak(self, svc):
        with pytest.raises(TokenError):
            await svc.get_current_user(buat_token(uuid.uuid4(), tipe="refresh"), SesiPalsu(None))


# --------------------------------------------------------------------------- Google (HTTP fake)


class TestBoundaryGoogle:
    async def test_exchange_code_mengirim_kode_dan_kredensial(self, svc, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid-uji-1234567")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "rahasia-uji")
        monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://x/cb")
        diterima = pasang_google(monkeypatch, token_body={"access_token": "tok-g"})

        hasil = await svc._exchange_code("kode-123")

        assert hasil == {"access_token": "tok-g"}
        form = parse_qs(diterima[0].content.decode())
        assert form["code"] == ["kode-123"]
        assert form["grant_type"] == ["authorization_code"]
        assert form["client_id"] == ["cid-uji-1234567"]
        assert form["redirect_uri"] == ["http://x/cb"]

    async def test_exchange_code_ditolak_google(self, svc, monkeypatch):
        pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
        with pytest.raises(OAuthError) as exc:
            await svc._exchange_code("kode-basi")
        assert "invalid_grant" in exc.value.detail

    async def test_profil_dipetakan_dan_memakai_bearer(self, svc, monkeypatch):
        diterima = pasang_google(
            monkeypatch,
            profil={"id": "g-9", "email": "s@x.id", "name": "Sari", "picture": "http://p/1.png"},
        )
        profil = await svc._get_google_profile("tok-g")
        assert profil == GoogleProfile(
            google_id="g-9", email="s@x.id", name="Sari", avatar_url="http://p/1.png"
        )
        assert diterima[0].headers["Authorization"] == "Bearer tok-g"

    async def test_profil_tanpa_nama_memakai_email(self, svc, monkeypatch):
        pasang_google(monkeypatch, profil={"id": "g-1", "email": "tanpa@nama.id"})
        profil = await svc._get_google_profile("t")
        assert profil.name == "tanpa@nama.id"
        assert profil.avatar_url is None

    async def test_profil_ditolak_google(self, svc, monkeypatch):
        pasang_google(monkeypatch, profil_status=401)
        with pytest.raises(OAuthError, match="profil"):
            await svc._get_google_profile("t")


# --------------------------------------------------------------------------- handle_callback


class TestHandleCallback:
    async def test_user_baru_dibuat_dengan_peran_dari_mapping(self, svc, monkeypatch):
        _domain(monkeypatch, "")
        _mapping(monkeypatch, {"budi@perusahaan.id": "Lead_SA"})
        pasang_google(monkeypatch)
        db = SesiPalsu(None)  # belum ada user dengan google_id itu

        user, tokens = await svc.handle_callback("kode", db)

        assert db.ditambahkan == [user]
        assert db.jumlah_commit == 1
        assert (user.email, user.role, user.google_id) == ("budi@perusahaan.id", "Lead_SA", "g-123")
        assert user.avatar_url == "http://a/b.png"
        akses = svc.verify_access_token(tokens.access_token)
        assert akses["sub"] == str(user.id)
        assert akses["role"] == "Lead_SA"

    async def test_user_baru_tanpa_mapping_menjadi_sa(self, svc, monkeypatch):
        _domain(monkeypatch, "")
        _mapping(monkeypatch, {})
        pasang_google(monkeypatch)
        user, _ = await svc.handle_callback("kode", SesiPalsu(None))
        assert user.role == "SA"

    async def test_user_existing_diperbarui_tanpa_mengubah_peran(self, svc, monkeypatch):
        """Login ulang memperbarui profil, tetapi peran (mungkin diubah Admin) dipertahankan."""
        _domain(monkeypatch, "")
        _mapping(monkeypatch, {"budi@perusahaan.id": "Admin"})
        pasang_google(
            monkeypatch,
            profil={"id": "g-123", "email": "budi@perusahaan.id", "name": "Budi Baru"},
        )
        lama = user_palsu("Sales", google_id="g-123", name="Budi Lama", email="lama@perusahaan.id")
        db = SesiPalsu(lama)

        user, _ = await svc.handle_callback("kode", db)

        assert user is lama
        assert db.ditambahkan == []
        assert (user.name, user.email, user.role) == ("Budi Baru", "budi@perusahaan.id", "Sales")
        assert db.jumlah_commit == 1

    async def test_domain_ditolak_tidak_membuat_user(self, svc, monkeypatch):
        _domain(monkeypatch, "perusahaan.id")
        pasang_google(monkeypatch, profil={"id": "g-1", "email": "x@gmail.com", "name": "X"})
        db = SesiPalsu(None)

        with pytest.raises(DomainNotAllowedError):
            await svc.handle_callback("kode", db)

        assert db.ditambahkan == []
        assert db.jumlah_commit == 0

    async def test_kode_tidak_valid_menghasilkan_oauth_error(self, svc, monkeypatch):
        pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
        db = SesiPalsu(None)
        with pytest.raises(OAuthError):
            await svc.handle_callback("salah", db)
        assert db.ditambahkan == []

    async def test_google_mati_di_transport_merambat_sebagai_error(self, svc, monkeypatch):
        import httpx

        def handler(request):
            raise httpx.ConnectError("jaringan putus", request=request)

        pasang_google_dengan(monkeypatch, handler)
        with pytest.raises(httpx.ConnectError):
            await svc.handle_callback("kode", SesiPalsu(None))
