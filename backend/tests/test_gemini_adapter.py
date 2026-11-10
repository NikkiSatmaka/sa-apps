"""
Unit tests untuk GeminiAdapter.

Menggunakan httpx MockTransport untuk mensimulasi response dari Gemini API
tanpa melakukan panggilan jaringan nyata.
"""

import asyncio
import base64
import json
from unittest.mock import patch

import httpx
import pytest

from app.services.gemini_adapter import GeminiAdapter
from app.services.llm_provider import LLMResponse


# =============================================================================
# Fixtures & Helpers
# =============================================================================


def mock_gemini_response(text: str = "Hello world", status_code: int = 200) -> dict:
    """Buat mock response body yang valid dari Gemini API."""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": text}],
                    "role": "model",
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        },
    }


@pytest.fixture
def mock_settings():
    """Patch settings untuk testing tanpa perlu .env file."""
    with patch("app.services.gemini_adapter.settings") as mock:
        mock.GEMINI_API_KEY = "test-api-key-123"
        mock.LLM_MODEL_NAME = "gemini-1.5-flash"
        mock.LLM_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1"
        mock.LLM_TIMEOUT_SECONDS = 30
        mock.LLM_MAX_RETRIES = 3
        yield mock


# =============================================================================
# Test: Inisialisasi
# =============================================================================


class TestGeminiAdapterInit:
    """Test inisialisasi GeminiAdapter."""

    def test_init_sukses_dengan_api_key(self, mock_settings):
        """Adapter berhasil diinisialisasi jika API key tersedia."""
        adapter = GeminiAdapter()
        assert adapter._api_key == "test-api-key-123"
        assert adapter._model_name == "gemini-1.5-flash"
        assert adapter._timeout == 30
        assert adapter._max_retries == 3

    def test_init_gagal_tanpa_api_key(self, mock_settings):
        """Adapter raise ValueError jika API key kosong."""
        mock_settings.GEMINI_API_KEY = ""
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiAdapter()

    def test_build_url_format_benar(self, mock_settings):
        """URL endpoint dibangun dengan format yang benar."""
        adapter = GeminiAdapter()
        url = adapter._build_url()
        assert "models/gemini-1.5-flash:generateContent" in url
        assert "key=test-api-key-123" in url


# =============================================================================
# Test: complete_text
# =============================================================================


class TestCompleteText:
    """Test method complete_text."""

    @pytest.mark.asyncio
    async def test_complete_text_sukses(self, mock_settings):
        """complete_text mengembalikan LLMResponse sukses untuk response valid."""
        adapter = GeminiAdapter()
        response_body = mock_gemini_response("Ini adalah jawaban.")

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=response_body)

            result = await adapter.complete_text("Halo, apa kabar?")

        assert result.status == "success"
        assert result.content == "Ini adalah jawaban."
        assert result.metadata.model == "gemini-1.5-flash"
        assert result.metadata.provider == "gemini"
        assert result.metadata.token_usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_complete_text_error_401(self, mock_settings):
        """complete_text mengembalikan auth_error untuk status 401."""
        adapter = GeminiAdapter()
        # Override max_retries ke 0 agar tidak retry
        adapter._max_retries = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(
                401, json={"error": {"message": "Invalid API key"}}
            )

            result = await adapter.complete_text("test")

        assert result.status == "error"
        assert result.error_type == "auth_error"

    @pytest.mark.asyncio
    async def test_complete_text_timeout(self, mock_settings):
        """complete_text mengembalikan timeout error saat request timeout."""
        adapter = GeminiAdapter()
        adapter._max_retries = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.side_effect = httpx.TimeoutException("timeout")

            result = await adapter.complete_text("test")

        assert result.status == "error"
        assert result.error_type == "timeout"

    @pytest.mark.asyncio
    async def test_complete_text_empty_candidates(self, mock_settings):
        """complete_text mengembalikan error jika response tanpa candidates."""
        adapter = GeminiAdapter()

        empty_response = {"candidates": [], "usageMetadata": {}}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=empty_response)

            result = await adapter.complete_text("test")

        assert result.status == "error"
        assert result.error_type == "invalid_response"


# =============================================================================
# Test: parse_document
# =============================================================================


class TestParseDocument:
    """Test method parse_document."""

    @pytest.mark.asyncio
    async def test_parse_document_pdf_sukses(self, mock_settings):
        """parse_document berhasil untuk file PDF."""
        adapter = GeminiAdapter()
        response_body = mock_gemini_response("Extracted: Budget 1M, Timeline Q2 2025")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=response_body)

            result = await adapter.parse_document(
                file_content=b"fake-pdf-content",
                mime_type="application/pdf",
                prompt="Ekstrak informasi BANT dari dokumen ini.",
            )

        assert result.status == "success"
        assert "Budget" in result.content

    @pytest.mark.asyncio
    async def test_parse_document_docx_sukses(self, mock_settings):
        """parse_document berhasil untuk file DOCX."""
        adapter = GeminiAdapter()
        response_body = mock_gemini_response("Dokumen berisi proposal teknis.")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=response_body)

            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            result = await adapter.parse_document(
                file_content=b"fake-docx-content",
                mime_type=mime,
                prompt="Ringkaskan dokumen ini.",
            )

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_parse_document_mime_type_tidak_didukung(self, mock_settings):
        """parse_document menolak MIME type yang tidak didukung."""
        adapter = GeminiAdapter()

        result = await adapter.parse_document(
            file_content=b"content",
            mime_type="image/png",
            prompt="test",
        )

        assert result.status == "error"
        assert result.error_type == "invalid_response"
        assert "tidak didukung" in result.error_message

    @pytest.mark.asyncio
    async def test_parse_document_payload_berisi_inline_data(self, mock_settings):
        """parse_document mengirim file sebagai base64 inline_data."""
        adapter = GeminiAdapter()
        file_bytes = b"test-pdf-content"
        expected_b64 = base64.b64encode(file_bytes).decode("utf-8")
        captured_payload = {}

        async def capture_post(url, json=None, headers=None):
            captured_payload.update(json)
            return httpx.Response(200, json=mock_gemini_response("ok"))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.side_effect = capture_post

            await adapter.parse_document(
                file_content=file_bytes,
                mime_type="application/pdf",
                prompt="Analisis dokumen.",
            )

        parts = captured_payload["contents"][0]["parts"]
        assert parts[0]["text"] == "Analisis dokumen."
        assert parts[1]["inline_data"]["mime_type"] == "application/pdf"
        assert parts[1]["inline_data"]["data"] == expected_b64


class TestParseDocumentBatasOutput:
    """Batas output parse_document: default tidak berubah, bisa dinaikkan, finishReason dibaca."""

    async def _kirim(self, adapter, body=None, **kwargs):
        captured = {}

        async def capture_post(url, json=None, headers=None):
            captured.update(json)
            return httpx.Response(200, json=body or mock_gemini_response("ok"))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.side_effect = capture_post
            result = await adapter.parse_document(
                file_content=b"x", mime_type="application/pdf", prompt="p", **kwargs
            )
        return captured, result

    @pytest.mark.asyncio
    async def test_default_tetap_8192(self, mock_settings):
        payload, _ = await self._kirim(GeminiAdapter())
        assert payload["generationConfig"]["maxOutputTokens"] == 8192

    @pytest.mark.asyncio
    async def test_batas_output_bisa_dinaikkan(self, mock_settings):
        payload, _ = await self._kirim(GeminiAdapter(), max_output_tokens=32768)
        assert payload["generationConfig"]["maxOutputTokens"] == 32768

    @pytest.mark.asyncio
    async def test_finish_reason_dibawa_ke_metadata(self, mock_settings):
        body = mock_gemini_response("terpotong")
        body["candidates"][0]["finishReason"] = "MAX_TOKENS"
        _, result = await self._kirim(GeminiAdapter(), body=body)
        assert result.metadata.finish_reason == "MAX_TOKENS"

    @pytest.mark.asyncio
    async def test_finish_reason_kosong_bila_tidak_ada(self, mock_settings):
        _, result = await self._kirim(GeminiAdapter())
        assert result.metadata.finish_reason is None


# =============================================================================
# Test: structure_text
# =============================================================================


class TestStructureText:
    """Test method structure_text."""

    @pytest.mark.asyncio
    async def test_structure_text_sukses_json(self, mock_settings):
        """structure_text mengembalikan parsed JSON jika response valid."""
        adapter = GeminiAdapter()
        json_content = json.dumps({"name": "Test", "score": 85})
        response_body = mock_gemini_response(json_content)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=response_body)

            result = await adapter.structure_text(
                text="Proyek ABC, skor 85 dari 100",
                output_schema={"name": "string", "score": "integer"},
            )

        assert result.status == "success"
        assert isinstance(result.content, dict)
        assert result.content["name"] == "Test"
        assert result.content["score"] == 85

    @pytest.mark.asyncio
    async def test_structure_text_non_json_response(self, mock_settings):
        """structure_text mengembalikan raw text jika response bukan JSON."""
        adapter = GeminiAdapter()
        response_body = mock_gemini_response("ini bukan json yang valid {{{")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(200, json=response_body)

            result = await adapter.structure_text(
                text="input text",
                output_schema={"key": "value"},
            )

        # Tetap sukses tapi content tetap string (bukan dict)
        assert result.status == "success"
        assert isinstance(result.content, str)

    @pytest.mark.asyncio
    async def test_structure_text_payload_berisi_response_mime_type(self, mock_settings):
        """structure_text mengirim responseMimeType application/json."""
        adapter = GeminiAdapter()
        captured_payload = {}

        async def capture_post(url, json=None, headers=None):
            captured_payload.update(json)
            return httpx.Response(
                200, json=mock_gemini_response('{"result": "ok"}')
            )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.side_effect = capture_post

            await adapter.structure_text(
                text="some text",
                output_schema={"result": "string"},
            )

        gen_config = captured_payload["generationConfig"]
        assert gen_config["responseMimeType"] == "application/json"


# =============================================================================
# Test: Retry & Error Handling
# =============================================================================


class TestRetryAndErrorHandling:
    """Test retry mechanism dan error classification."""

    @pytest.mark.asyncio
    async def test_retry_berhasil_setelah_gagal_pertama(self, mock_settings):
        """Request berhasil di attempt kedua setelah gagal pertama."""
        adapter = GeminiAdapter()
        call_count = 0

        async def flaky_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, json={"error": "server error"})
            return httpx.Response(200, json=mock_gemini_response("berhasil!"))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.side_effect = flaky_post

            # Patch sleep agar test tidak lambat
            with patch("asyncio.sleep", return_value=None):
                result = await adapter.complete_text("test")

        assert result.status == "success"
        assert result.content == "berhasil!"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_semua_retry_habis(self, mock_settings):
        """Semua retry gagal mengembalikan error response."""
        adapter = GeminiAdapter()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(
                500, json={"error": "persistent error"}
            )

            with patch("asyncio.sleep", return_value=None):
                result = await adapter.complete_text("test")

        assert result.status == "error"
        assert result.error_type == "invalid_response"
        assert result.metadata.provider == "gemini"

    @pytest.mark.asyncio
    async def test_error_403_diklasifikasi_auth_error(self, mock_settings):
        """Status 403 diklasifikasi sebagai auth_error."""
        adapter = GeminiAdapter()
        adapter._max_retries = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(
                403, json={"error": "forbidden"}
            )

            result = await adapter.complete_text("test")

        assert result.error_type == "auth_error"

    @pytest.mark.asyncio
    async def test_metadata_latency_dihitung(self, mock_settings):
        """Latency tercatat di metadata response."""
        adapter = GeminiAdapter()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__aenter__.return_value
            mock_client.post.return_value = httpx.Response(
                200, json=mock_gemini_response("ok")
            )

            result = await adapter.complete_text("test")

        assert result.metadata.latency_ms >= 0


# =============================================================================
# Test: Protocol Compliance
# =============================================================================


class TestProtocolCompliance:
    """Verifikasi bahwa GeminiAdapter memenuhi LLMProviderInterface."""

    def test_implements_protocol(self, mock_settings):
        """GeminiAdapter memenuhi LLMProviderInterface Protocol."""
        from app.services.llm_provider import LLMProviderInterface

        adapter = GeminiAdapter()
        assert isinstance(adapter, LLMProviderInterface)

    def test_has_complete_text_method(self, mock_settings):
        """Adapter memiliki method complete_text."""
        adapter = GeminiAdapter()
        assert hasattr(adapter, "complete_text")
        assert asyncio.iscoroutinefunction(adapter.complete_text)

    def test_has_parse_document_method(self, mock_settings):
        """Adapter memiliki method parse_document."""
        adapter = GeminiAdapter()
        assert hasattr(adapter, "parse_document")
        assert asyncio.iscoroutinefunction(adapter.parse_document)

    def test_has_structure_text_method(self, mock_settings):
        """Adapter memiliki method structure_text."""
        adapter = GeminiAdapter()
        assert hasattr(adapter, "structure_text")
        assert asyncio.iscoroutinefunction(adapter.structure_text)
