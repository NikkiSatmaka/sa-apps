"""
Test perilaku GeminiAdapter lewat `httpx.MockTransport` (tanpa jaringan nyata).

Melengkapi `test_gemini_adapter.py`: yang ditegaskan adalah apa yang tampak dari luar —
jumlah request yang sampai ke "server", jeda backoff, respons akhir, dan klasifikasi error —
bukan detail internal. `asyncio.sleep` di-patch dan dicatat; tidak ada waktu nyata.
"""

import json
from unittest.mock import patch

import httpx
import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.services.gemini_adapter import GeminiAdapter

_AsyncClientAsli = httpx.AsyncClient


class Server:
    """Server Gemini palsu: antrean respons/exception, merekam request yang masuk."""

    def __init__(self, *antrean):
        self.antrean = list(antrean)
        self.request: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.request.append(request)
        item = self.antrean.pop(0) if len(self.antrean) > 1 else self.antrean[0]
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, idx: int = 0) -> dict:
        return json.loads(self.request[idx].content)


def sukses(teks="ok", finish_reason=None, **extra):
    cand = {"content": {"parts": [{"text": teks}]}}
    if finish_reason:
        cand["finishReason"] = finish_reason
    return httpx.Response(
        200,
        json={
            "candidates": [cand],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 4,
                "totalTokenCount": 7,
            },
            **extra,
        },
    )


@pytest.fixture
def jeda():
    """Catat durasi setiap `asyncio.sleep` backoff tanpa menunggu."""
    durasi: list[float] = []

    async def _sleep(detik):
        durasi.append(detik)

    with patch("app.services.gemini_adapter.asyncio.sleep", _sleep):
        yield durasi


@pytest.fixture
def pasang(monkeypatch):
    """Kembalikan fungsi yang membuat adapter dengan `Server` di belakangnya."""
    from app.services import gemini_adapter

    monkeypatch.setattr(gemini_adapter.settings, "GEMINI_API_KEY", "kunci-uji")
    monkeypatch.setattr(gemini_adapter.settings, "LLM_MAX_RETRIES", 3)

    def _buat(*antrean, max_retries: int = 3) -> tuple[GeminiAdapter, Server]:
        server = Server(*antrean)
        monkeypatch.setattr(gemini_adapter.settings, "LLM_MAX_RETRIES", max_retries)

        def _client(*args, **kwargs):
            return _AsyncClientAsli(*args, transport=httpx.MockTransport(server.handler), **kwargs)

        monkeypatch.setattr(gemini_adapter.httpx, "AsyncClient", _client)
        return GeminiAdapter(), server

    return _buat


# --------------------------------------------------------------------------- sukses
async def test_sukses_satu_request_tanpa_jeda_dan_menyertakan_metadata(pasang, jeda):
    adapter, server = pasang(sukses("halo", finish_reason="STOP"))

    r = await adapter.complete_text("prompt")

    assert (r.status, r.content) == ("success", "halo")
    assert len(server.request) == 1 and jeda == []
    assert r.metadata.finish_reason == "STOP"
    assert r.metadata.token_usage.total_tokens == 7
    assert r.metadata.provider == "gemini" and r.metadata.latency_ms >= 0
    assert "generateContent" in str(server.request[0].url)


async def test_beberapa_part_teks_digabung_dan_part_non_teks_dilewati(pasang, jeda):
    resp = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": "A"}, {"inlineData": {}}, {"text": "B"}]}}
            ]
        },
    )
    adapter, _ = pasang(resp)

    r = await adapter.complete_text("x")

    assert r.status == "success" and r.content == "AB"
    assert r.metadata.token_usage.total_tokens == 0


async def test_parameter_generasi_dikirim_dan_default_diterapkan(pasang, jeda):
    adapter, server = pasang(sukses())

    await adapter.complete_text("p", temperature=0.7, max_output_tokens=123)
    await adapter.complete_text("p")

    assert server.body(0)["generationConfig"] == {"temperature": 0.7, "maxOutputTokens": 123}
    assert server.body(1)["generationConfig"] == {"temperature": 0.1, "maxOutputTokens": 8192}


# --------------------------------------------------------------------------- respons terpotong
async def test_respons_terpotong_tetap_sukses_dengan_finish_reason_max_tokens(pasang, jeda):
    adapter, _ = pasang(sukses('{"items": [', finish_reason="MAX_TOKENS"))

    r = await adapter.complete_text("p")

    # Adapter tidak menolak keluaran terpotong: callerlah yang memutuskan (lihat extractor).
    assert r.status == "success"
    assert r.content == '{"items": ['
    assert r.metadata.finish_reason == "MAX_TOKENS"


# --------------------------------------------------------------------------- retry
async def test_retry_berhasil_pada_percobaan_ketiga_dengan_backoff_1_lalu_2_detik(pasang, jeda):
    adapter, server = pasang(
        httpx.Response(500, text="x"), httpx.Response(503, text="y"), sukses("akhirnya")
    )

    r = await adapter.complete_text("p")

    assert r.status == "success" and r.content == "akhirnya"
    assert len(server.request) == 3
    assert jeda == [1, 2]


async def test_kegagalan_akhir_memakai_1_ditambah_max_retries_percobaan_dan_backoff_eksponensial(
    pasang, jeda
):
    adapter, server = pasang(httpx.Response(500, text="rusak parah"))

    r = await adapter.complete_text("p")

    assert len(server.request) == 4  # 1 awal + 3 retry
    assert jeda == [1, 2, 4]  # tidak ada jeda setelah percobaan terakhir
    assert r.status == "error" and r.content is None
    assert r.error_type == "invalid_response"
    assert "500" in r.error_message and "rusak parah" in r.error_message
    assert r.metadata.provider == "gemini"


async def test_max_retries_nol_hanya_satu_percobaan_tanpa_jeda(pasang, jeda):
    adapter, server = pasang(httpx.Response(500, text="x"), max_retries=0)

    r = await adapter.complete_text("p")

    assert r.status == "error" and len(server.request) == 1 and jeda == []


async def test_pesan_error_dipotong_500_karakter(pasang, jeda):
    adapter, _ = pasang(httpx.Response(500, text="Z" * 5000), max_retries=0)

    r = await adapter.complete_text("p")

    assert r.error_message.count("Z") == 500


# --------------------------------------------------------------------------- klasifikasi error
@pytest.mark.parametrize("kode", [401, 403])
async def test_status_401_dan_403_adalah_auth_error(pasang, jeda, kode):
    adapter, _ = pasang(httpx.Response(kode, json={"error": "x"}), max_retries=0)
    assert (await adapter.complete_text("p")).error_type == "auth_error"


@pytest.mark.parametrize("kode", [400, 404, 429, 500, 503])
async def test_status_lain_adalah_invalid_response(pasang, jeda, kode):
    adapter, _ = pasang(httpx.Response(kode, text="x"), max_retries=0)
    assert (await adapter.complete_text("p")).error_type == "invalid_response"


async def test_timeout_httpx_diklasifikasi_timeout_dan_di_retry(pasang, jeda):
    adapter, server = pasang(httpx.ReadTimeout("lambat"))

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "timeout"
    assert "timeout" in r.error_message.lower()
    assert len(server.request) == 4


async def test_timeout_lalu_pulih_mengembalikan_sukses(pasang, jeda):
    adapter, _ = pasang(httpx.ConnectTimeout("t"), sukses("pulih"))

    r = await adapter.complete_text("p")

    assert (r.status, r.content) == ("success", "pulih")


async def test_asyncio_timeout_diklasifikasi_timeout(pasang, jeda):
    adapter, _ = pasang(TimeoutError("habis"), max_retries=0)

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "timeout"
    assert "Request error" in r.error_message


async def test_error_jaringan_lain_invalid_response_dan_di_retry(pasang, jeda):
    adapter, server = pasang(httpx.ConnectError("putus"))

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "invalid_response"
    assert "putus" in r.error_message
    assert len(server.request) == 4


async def test_body_200_bukan_json_diperlakukan_error_dan_di_retry(pasang, jeda):
    adapter, server = pasang(httpx.Response(200, text="<html>bukan json</html>"))

    r = await adapter.complete_text("p")

    assert r.status == "error"
    assert len(server.request) == 4


# --------------------------------------------------------------------------- respons 200 abnormal
async def test_200_tanpa_candidates_adalah_error_invalid_response_tanpa_retry(pasang, jeda):
    adapter, server = pasang(httpx.Response(200, json={"candidates": []}))

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "invalid_response"
    assert "candidates" in r.error_message
    assert len(server.request) == 1 and jeda == []


async def test_200_dengan_part_bertipe_salah_adalah_error_parsing_tanpa_retry(pasang, jeda):
    adapter, server = pasang(
        httpx.Response(200, json={"candidates": [{"content": {"parts": [5]}}]})
    )

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "invalid_response"
    assert "parsing" in r.error_message.lower()
    assert len(server.request) == 1


async def test_200_dengan_candidate_bukan_objek_tetap_error_terkendali_bukan_crash(pasang, jeda):
    # Perilaku nyata: AttributeError tidak tertangkap parser respons sehingga jatuh ke
    # penanganan umum (error `invalid_response`, ikut di-retry). Yang dijaga: tidak melempar.
    adapter, server = pasang(httpx.Response(200, json={"candidates": ["bukan-dict"]}))

    r = await adapter.complete_text("p")

    assert r.status == "error" and r.error_type == "invalid_response"
    assert len(server.request) == 4


async def test_200_tanpa_parts_menghasilkan_sukses_dengan_teks_kosong(pasang, jeda):
    adapter, _ = pasang(httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]}))

    r = await adapter.complete_text("p")

    assert r.status == "success" and r.content == ""
    assert r.metadata.finish_reason == "SAFETY"


# --------------------------------------------------------------------------- parse_document
async def test_parse_document_mime_tak_didukung_ditolak_tanpa_request(pasang, jeda):
    adapter, server = pasang(sukses())

    r = await adapter.parse_document(b"x", "image/png", "ekstrak")

    assert r.status == "error" and r.error_type == "invalid_response"
    assert "image/png" in r.error_message
    assert server.request == []


async def test_parse_document_mengirim_batas_output_dan_file_base64(pasang, jeda):
    adapter, server = pasang(sukses("teks", finish_reason="MAX_TOKENS"))

    r = await adapter.parse_document(b"%PDF", "application/pdf", "ekstrak", max_output_tokens=32768)

    assert r.metadata.finish_reason == "MAX_TOKENS"
    body = server.body()
    assert body["generationConfig"]["maxOutputTokens"] == 32768
    inline = body["contents"][0]["parts"][1]["inline_data"]
    assert inline == {"mime_type": "application/pdf", "data": "JVBERg=="}


# --------------------------------------------------------------------------- structure_text
async def test_structure_text_json_valid_diparse_menjadi_objek(pasang, jeda):
    adapter, server = pasang(sukses('{"a": 1}'))

    r = await adapter.structure_text("teks", {"type": "object"})

    assert r.status == "success" and r.content == {"a": 1}
    assert server.body()["generationConfig"]["responseMimeType"] == "application/json"


async def test_structure_text_bukan_json_dikembalikan_sebagai_string_mentah(pasang, jeda):
    adapter, _ = pasang(sukses("bukan json"))

    r = await adapter.structure_text("teks", {})

    # Perilaku nyata adapter: TIDAK error `invalid_response`; caller wajib memvalidasi.
    assert r.status == "success" and r.content == "bukan json"


async def test_structure_text_error_dikembalikan_apa_adanya(pasang, jeda):
    adapter, _ = pasang(httpx.Response(401, text="x"), max_retries=0)

    r = await adapter.structure_text("teks", {})

    assert r.status == "error" and r.error_type == "auth_error"


async def test_structure_text_konten_kosong_tidak_diparse(pasang, jeda):
    adapter, _ = pasang(httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]}))

    r = await adapter.structure_text("teks", {})

    assert r.status == "success" and r.content == ""


# --------------------------------------------------------------------------- property
@hyp_settings(max_examples=40, deadline=None)
@given(st.integers(min_value=0, max_value=6))
async def test_property_percobaan_dan_jeda_mengikuti_max_retries(n):
    """Untuk N retry: N+1 request, jeda 2^0..2^(N-1), tidak ada jeda terakhir."""
    server = Server(httpx.Response(500, text="x"))
    durasi: list[float] = []

    async def _sleep(d):
        durasi.append(d)

    from app.services import gemini_adapter

    def _client(*a, **k):
        return _AsyncClientAsli(*a, transport=httpx.MockTransport(server.handler), **k)

    with (
        patch.object(gemini_adapter.settings, "GEMINI_API_KEY", "k"),
        patch.object(gemini_adapter.settings, "LLM_MAX_RETRIES", n),
        patch.object(gemini_adapter.httpx, "AsyncClient", _client),
        patch("app.services.gemini_adapter.asyncio.sleep", _sleep),
    ):
        r = await GeminiAdapter().complete_text("p")

    assert r.status == "error"
    assert len(server.request) == n + 1
    assert durasi == [2**i for i in range(n)]
