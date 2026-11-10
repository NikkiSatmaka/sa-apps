"""
Unit test `RateLimiterMiddleware` (tiket #55) dengan waktu terkendali: modul `time` di
`app.core.rate_limiter` diganti jam palsu sehingga tidak ada sleep/waktu nyata.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from app.core.config import settings
from app.core.rate_limiter import RateLimiterMiddleware


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


class TestPengidentifikasi:
    def test_klien_berbeda_punya_kuota_terpisah(self, jam):
        c = _klien(1)
        a = {"X-Forwarded-For": "10.0.0.1"}
        b = {"X-Forwarded-For": "10.0.0.2"}
        assert c.get("/data", headers=a).status_code == 200
        assert c.get("/data", headers=a).status_code == 429
        assert c.get("/data", headers=b).status_code == 200

    def test_x_forwarded_for_memakai_alamat_pertama(self, jam):
        c = _klien(1)
        assert (
            c.get("/data", headers={"X-Forwarded-For": "10.0.0.1, 172.16.0.1"}).status_code == 200
        )
        assert (
            c.get("/data", headers={"X-Forwarded-For": "10.0.0.1, 172.99.0.9"}).status_code == 429
        )

    def test_tanpa_forwarded_memakai_ip_klien(self, jam):
        c = _klien(1)
        assert c.get("/data").status_code == 200
        assert c.get("/data").status_code == 429

    def test_pengidentifikasi_user_terautentikasi_lebih_utama_dari_ip(self):
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        req = SimpleNamespace(
            state=SimpleNamespace(user_id="u-1"),
            client=SimpleNamespace(host="1.2.3.4"),
            headers={},
        )
        assert mw._get_user_identifier(req) == "user:u-1"

    def test_tanpa_info_klien_dipetakan_ke_unknown(self):
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        req = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})
        assert mw._get_user_identifier(req) == "ip:unknown"

    def test_retry_after_nol_bila_tak_ada_riwayat(self):
        mw = RateLimiterMiddleware(app=None, max_requests=1)
        assert mw._calculate_retry_after("ip:x", 1000.0) == 0


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
