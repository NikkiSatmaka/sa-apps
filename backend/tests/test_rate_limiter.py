"""
Unit test `RateLimiterMiddleware` (tiket #55) dengan waktu terkendali: modul `time` di
`app.core.rate_limiter` diganti jam palsu sehingga tidak ada sleep/waktu nyata.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from app.core.config import Settings, settings
from app.core.rate_limiter import RateLimiterMiddleware
from tests._auth_support import buat_token


class JamPalsu:
    def __init__(self, awal: float = 1000.0):
        self.sekarang = awal

    def time(self) -> float:
        return self.sekarang

    def maju(self, detik: float) -> None:
        self.sekarang += detik


@pytest.fixture
def jam(monkeypatch) -> JamPalsu:
    j = JamPalsu()
    monkeypatch.setattr("app.core.rate_limiter.time", j)
    return j


def _klien(max_requests: int | None = 3) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimiterMiddleware, max_requests=max_requests)

    @app.get("/data")
    async def data():
        return {"ok": True}

    for jalur in ("/health", "/docs", "/redoc", "/openapi.json"):
        app.add_api_route(jalur, data, methods=["GET"], include_in_schema=False)
    return TestClient(app)


class TestBatas:
    def test_request_sampai_batas_lolos_lalu_429(self, jam):
        c = _klien(3)
        assert [c.get("/data").status_code for _ in range(3)] == [200, 200, 200]

        resp = c.get("/data")

        assert resp.status_code == 429
        body = resp.json()
        assert body["status"] == "error"
        assert body["data"] is None
        assert "Maksimal 3 request per menit" in body["message"]

    def test_request_yang_ditolak_tidak_menambah_hitungan(self, jam):
        """Spam saat terblokir tidak memperpanjang blokir: jendela tetap menggeser."""
        c = _klien(2)
        c.get("/data")
        c.get("/data")
        for _ in range(5):
            jam.maju(1)
            assert c.get("/data").status_code == 429
        jam.maju(60)  # 65 detik sejak request pertama
        assert c.get("/data").status_code == 200

    def test_default_batas_dari_settings(self, jam, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 2)
        c = _klien(None)
        assert [c.get("/data").status_code for _ in range(3)] == [200, 200, 429]


class TestJendelaDanReset:
    def test_reset_setelah_jendela_60_detik(self, jam):
        c = _klien(2)
        c.get("/data")
        c.get("/data")
        assert c.get("/data").status_code == 429

        jam.maju(60.5)

        assert c.get("/data").status_code == 200

    def test_masih_terblokir_tepat_sebelum_jendela_habis(self, jam):
        c = _klien(1)
        c.get("/data")
        jam.maju(59)
        assert c.get("/data").status_code == 429

    def test_sliding_window_hanya_membebaskan_request_tertua(self, jam):
        c = _klien(2)
        c.get("/data")  # t=0
        jam.maju(30)
        c.get("/data")  # t=30
        assert c.get("/data").status_code == 429
        jam.maju(31)  # t=61: request t=0 keluar jendela, t=30 masih di dalam
        assert c.get("/data").status_code == 200
        assert c.get("/data").status_code == 429


class TestHeaderRetryAfter:
    def test_retry_after_dihitung_dari_request_tertua(self, jam):
        c = _klien(3)
        c.get("/data")  # t=1000
        jam.maju(10)
        c.get("/data")
        jam.maju(10)
        c.get("/data")
        jam.maju(10)  # t=1030

        resp = c.get("/data")

        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "31"  # 1000 + 60 - 1030 = 30, +1 pembulatan

    def test_retry_after_minimal_1_detik(self, jam):
        c = _klien(1)
        c.get("/data")
        jam.maju(59.99)
        assert int(c.get("/data").headers["Retry-After"]) >= 1

    def test_menunggu_sesuai_retry_after_membuka_blokir(self, jam):
        c = _klien(2)
        c.get("/data")
        jam.maju(5)
        c.get("/data")
        jam.maju(7)
        resp = c.get("/data")
        jam.maju(int(resp.headers["Retry-After"]))
        assert c.get("/data").status_code == 200

    def test_response_sukses_tidak_membawa_retry_after(self, jam):
        assert "Retry-After" not in _klien(3).get("/data").headers

    @given(
        jeda=st.lists(st.floats(min_value=0, max_value=5), min_size=1, max_size=4),
        batas=st.integers(min_value=1, max_value=4),
    )
    @hy_settings(max_examples=40, deadline=None)
    def test_property_retry_after_dalam_rentang_1_sampai_61_dan_membuka_blokir(self, jeda, batas):
        with pytest.MonkeyPatch.context() as mp:
            j = JamPalsu()
            mp.setattr("app.core.rate_limiter.time", j)
            c = _klien(batas)
            diterima = 0
            for d in jeda * batas:  # pastikan kuota habis
                j.maju(d)
                if c.get("/data").status_code == 200:
                    diterima += 1
            j.maju(0.001)
            resp = c.get("/data")
            if resp.status_code == 429:
                tunggu = int(resp.headers["Retry-After"])
                assert 1 <= tunggu <= 61
                j.maju(tunggu)
                assert c.get("/data").status_code == 200


def _jwt(sub="u-1", **kw) -> dict[str, str]:
    return {"Authorization": f"Bearer {buat_token(sub, **kw)}"}


def _klien_ip(max_requests: int = 1, peer: str = "198.51.100.7") -> TestClient:
    """Klien dengan alamat peer socket terkendali (bukan 'testclient')."""
    app = FastAPI()
    app.add_middleware(RateLimiterMiddleware, max_requests=max_requests)

    @app.get("/data")
    async def data():
        return {"ok": True}

    return TestClient(app, client=(peer, 50000))


def _hops(monkeypatch, n: int) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", n)


def _id(headers: dict[str, str], peer: str = "198.51.100.7") -> str:
    mw = RateLimiterMiddleware(app=None, max_requests=1)
    req = SimpleNamespace(
        state=SimpleNamespace(), client=SimpleNamespace(host=peer), headers=headers
    )
    return mw._get_user_identifier(req)


class TestConfigHop:
    def test_default_trusted_proxy_hops_nol(self):
        assert Settings(_env_file=None).TRUSTED_PROXY_HOPS == 0

    def test_dibaca_dari_environment(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
        assert Settings(_env_file=None).TRUSTED_PROXY_HOPS == 2

    def test_negatif_ditolak(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "-1")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


class TestPengidentifikasi:
    """Anonim: IP klien. XFF hanya dibaca bila TRUSTED_PROXY_HOPS > 0 (entri ke-N dari KANAN)."""

    def test_tanpa_forwarded_memakai_ip_klien(self, jam):
        c = _klien(1)
        assert c.get("/data").status_code == 200
        assert c.get("/data").status_code == 429

    def test_tanpa_info_klien_dipetakan_ke_unknown(self):
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        req = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})
        assert mw._get_user_identifier(req) == "ip:unknown"

    def test_retry_after_nol_bila_tak_ada_riwayat(self):
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        assert mw._calculate_retry_after("ip:x", 1000.0) == 0

    def test_hop_nol_mengabaikan_xff_sepenuhnya(self, jam, monkeypatch):
        """Ganti perilaku lama (entri pertama XFF dipercaya): kini XFF diabaikan saat N=0,
        sehingga klien tak bisa ganti identifier dengan memalsukan header."""
        _hops(monkeypatch, 0)
        c = _klien_ip(1)
        assert c.get("/data", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
        assert c.get("/data", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429

    def test_hop_nol_identifier_adalah_peer(self, monkeypatch):
        _hops(monkeypatch, 0)
        assert _id({"X-Forwarded-For": "10.0.0.1"}) == "ip:198.51.100.7"

    def test_hop_satu_memakai_entri_terakhir(self, monkeypatch):
        _hops(monkeypatch, 1)
        assert _id({"X-Forwarded-For": "6.6.6.6, 203.0.113.5"}) == "ip:203.0.113.5"

    def test_hop_dua_memakai_entri_kedua_dari_kanan(self, monkeypatch):
        _hops(monkeypatch, 2)
        xff = "6.6.6.6, 203.0.113.5, 172.68.0.1"
        assert _id({"X-Forwarded-For": xff}) == "ip:203.0.113.5"

    def test_memalsukan_entri_kiri_tidak_mengubah_identifier(self, monkeypatch):
        _hops(monkeypatch, 2)
        asli = _id({"X-Forwarded-For": "6.6.6.6, 203.0.113.5, 172.68.0.1"})
        palsu = _id({"X-Forwarded-For": "9.9.9.9, 8.8.8.8, 203.0.113.5, 172.68.0.1"})
        assert asli == palsu == "ip:203.0.113.5"

    def test_pemalsuan_entri_kiri_tidak_menghindari_429(self, jam, monkeypatch):
        _hops(monkeypatch, 1)
        c = _klien_ip(1)
        assert (
            c.get("/data", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.5"}).status_code == 200
        )
        resp = c.get("/data", headers={"X-Forwarded-For": "2.2.2.2, 203.0.113.5"})
        assert resp.status_code == 429

    def test_klien_dari_ip_berbeda_kuota_terpisah(self, jam, monkeypatch):
        _hops(monkeypatch, 1)
        c = _klien_ip(1)
        assert c.get("/data", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
        assert c.get("/data", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 429
        assert c.get("/data", headers={"X-Forwarded-For": "203.0.113.6"}).status_code == 200

    @pytest.mark.parametrize(
        "xff",
        ["", "   ", "6.6.6.6", ",", "bukan-ip, tidak-valid", "bukan-ip, 172.68.0.1"],
        ids=["kosong", "spasi", "lebih-pendek", "koma", "tidak-valid", "entri-N-tidak-valid"],
    )
    def test_rantai_pendek_kosong_atau_tidak_valid_jatuh_ke_peer(self, monkeypatch, xff):
        _hops(monkeypatch, 2)
        assert _id({"X-Forwarded-For": xff}) == "ip:198.51.100.7"

    def test_tanpa_header_xff_jatuh_ke_peer(self, monkeypatch):
        _hops(monkeypatch, 2)
        assert _id({}) == "ip:198.51.100.7"

    def test_ipv6_valid_diterima(self, monkeypatch):
        _hops(monkeypatch, 1)
        assert _id({"X-Forwarded-For": "6.6.6.6, 2001:db8::1"}) == "ip:2001:db8::1"

    def test_entri_dengan_spasi_dirapikan(self, monkeypatch):
        _hops(monkeypatch, 1)
        assert _id({"X-Forwarded-For": "6.6.6.6 ,   203.0.113.5  "}) == "ip:203.0.113.5"

    def test_xff_tidak_valid_di_request_nyata_tidak_error(self, jam, monkeypatch):
        _hops(monkeypatch, 3)
        c = _klien_ip(5)
        assert c.get("/data", headers={"X-Forwarded-For": "\x00??, ;;"}).status_code == 200


class TestKuotaPerPengguna:
    def test_identifier_dari_token_access_valid(self):
        assert _id(_jwt("u-1")) == "user:u-1"

    def test_token_menang_atas_ip_dan_xff(self, monkeypatch):
        _hops(monkeypatch, 1)
        h = {**_jwt("u-1"), "X-Forwarded-For": "203.0.113.5"}
        assert _id(h) == "user:u-1"

    def test_request_state_tidak_dipakai(self):
        """user_id di request.state terisi SETELAH middleware; tidak boleh jadi sumber identifier."""
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        req = SimpleNamespace(
            state=SimpleNamespace(user_id="u-palsu"),
            client=SimpleNamespace(host="1.2.3.4"),
            headers={},
        )
        assert mw._get_user_identifier(req) == "ip:1.2.3.4"

    def test_dua_pengguna_satu_ip_tidak_saling_memblokir(self, jam):
        c = _klien_ip(2)
        a, b = _jwt("user-a"), _jwt("user-b")
        assert [c.get("/data", headers=a).status_code for _ in range(2)] == [200, 200]
        assert c.get("/data", headers=a).status_code == 429
        assert c.get("/data", headers=b).status_code == 200

    def test_pengguna_sama_dari_ip_berbeda_berbagi_kuota(self, jam, monkeypatch):
        _hops(monkeypatch, 1)
        c = _klien_ip(1)
        h = _jwt("user-a")
        assert c.get("/data", headers={**h, "X-Forwarded-For": "1.1.1.1"}).status_code == 200
        assert c.get("/data", headers={**h, "X-Forwarded-For": "2.2.2.2"}).status_code == 429

    def test_kuota_anonim_terpisah_dari_kuota_pengguna(self, jam):
        c = _klien_ip(1)
        assert c.get("/data", headers=_jwt("user-a")).status_code == 200
        assert c.get("/data").status_code == 200

    @pytest.mark.parametrize(
        "headers",
        [
            {"Authorization": "Bearer bukan.jwt.valid"},
            {"Authorization": "Bearer "},
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer"},
        ],
        ids=["sampah", "kosong", "skema-lain", "tanpa-token"],
    )
    def test_token_tidak_valid_jatuh_ke_ip(self, headers):
        assert _id(headers) == "ip:198.51.100.7"

    def test_token_tanda_tangan_salah_jatuh_ke_ip(self):
        assert _id(_jwt("u-1", secret="x" * 40)) == "ip:198.51.100.7"

    def test_token_kedaluwarsa_jatuh_ke_ip(self):
        assert _id(_jwt("u-1", berlaku=timedelta(hours=-1))) == "ip:198.51.100.7"

    def test_refresh_token_tidak_dihitung_sebagai_pengguna(self):
        assert _id(_jwt("u-1", tipe="refresh")) == "ip:198.51.100.7"

    def test_token_tanpa_subject_jatuh_ke_ip(self):
        assert _id(_jwt(None)) == "ip:198.51.100.7"

    def test_token_palsu_tidak_memberi_kuota_baru(self, jam):
        """Token sampah berganti-ganti tidak membuka bucket baru: tetap kuota IP."""
        c = _klien_ip(1)
        assert c.get("/data", headers={"Authorization": "Bearer a.b.c"}).status_code == 200
        assert c.get("/data", headers={"Authorization": "Bearer d.e.f"}).status_code == 429


class TestJalurDikecualikan:
    @pytest.mark.parametrize("jalur", ["/health", "/docs", "/redoc", "/openapi.json"])
    def test_tidak_dibatasi(self, jam, jalur):
        c = _klien(1)
        assert [c.get(jalur).status_code for _ in range(5)] == [200] * 5

    def test_jalur_dikecualikan_tidak_memakan_kuota(self, jam):
        c = _klien(1)
        for _ in range(3):
            c.get("/health")
        assert c.get("/data").status_code == 200
