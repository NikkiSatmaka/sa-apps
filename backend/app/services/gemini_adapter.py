"""
Gemini Adapter — Implementasi LLMProviderInterface untuk Google Gemini API.

Adapter ini berkomunikasi langsung dengan Gemini REST API menggunakan httpx (async).
Mendukung:
- Text completion (generateContent)
- Multimodal document parsing (PDF/DOCX via inline_data)
- Text structuring (JSON mode via responseMimeType)
- Retry dengan exponential backoff (1s → 2s → 4s)
- Timeout 30 detik per request
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.llm_provider import LLMMetadata, LLMResponse, TokenUsage

logger = logging.getLogger(__name__)

# Mapping MIME type untuk dokumen yang didukung
SUPPORTED_MIME_TYPES = {
    "application/pdf": "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


class GeminiAdapter:
    """
    Adapter untuk Google Gemini API.

    Mengimplementasi LLMProviderInterface Protocol menggunakan httpx.AsyncClient
    untuk komunikasi langsung ke Gemini REST API (tanpa SDK).

    Fitur:
    - Retry exponential backoff: 1s → 2s → 4s (max 3 retries)
    - Timeout per request: sesuai LLM_TIMEOUT_SECONDS (default 30s)
    - Hot-reload: membaca config fresh dari settings saat instantiation
    - Error classification: auth_error, timeout, invalid_response
    """

    def __init__(self) -> None:
        """
        Inisialisasi adapter dengan config dari settings.

        Raises:
            ValueError: Jika GEMINI_API_KEY tidak dikonfigurasi.
        """
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY belum dikonfigurasi. "
                "Set environment variable GEMINI_API_KEY."
            )

        self._api_key = settings.GEMINI_API_KEY
        self._model_name = settings.LLM_MODEL_NAME
        self._api_endpoint = settings.LLM_API_ENDPOINT
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._max_retries = settings.LLM_MAX_RETRIES

        logger.info(
            f"GeminiAdapter diinisialisasi — model: {self._model_name}, "
            f"timeout: {self._timeout}s, max_retries: {self._max_retries}"
        )

    def _build_url(self) -> str:
        """Bangun URL endpoint Gemini generateContent."""
        base = self._api_endpoint.rstrip("/")
        return f"{base}/models/{self._model_name}:generateContent?key={self._api_key}"

    def _classify_error(self, status_code: int | None, error: Exception | None) -> str:
        """
        Klasifikasi jenis error berdasarkan status code atau exception.

        Returns:
            String error_type: "auth_error", "timeout", atau "invalid_response"
        """
        if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError)):
            return "timeout"
        if status_code in (401, 403):
            return "auth_error"
        return "invalid_response"

    async def _request_with_retry(self, payload: dict[str, Any]) -> LLMResponse:
        """
        Kirim request ke Gemini API dengan retry exponential backoff.

        Strategi retry:
        - Attempt 1: langsung kirim
        - Attempt 2: tunggu 1s, kirim
        - Attempt 3: tunggu 2s, kirim
        - Attempt 4: tunggu 4s, kirim (jika max_retries=3 berarti 4 total attempts)

        Sebenarnya: initial attempt + max_retries kali retry.
        Backoff intervals: 1s, 2s, 4s (2^0, 2^1, 2^2)

        Returns:
            LLMResponse dengan status success/error.
        """
        url = self._build_url()
        start_time = time.time()
        last_error_type = "unknown"
        last_error_message = ""

        # Total attempts = 1 (initial) + max_retries
        total_attempts = 1 + self._max_retries

        for attempt in range(total_attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout)
                ) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )

                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    data = response.json()
                    return self._parse_success_response(data, latency_ms)

                # Error response dari API
                last_error_type = self._classify_error(
                    response.status_code, None
                )
                last_error_message = (
                    f"Gemini API error {response.status_code}: "
                    f"{response.text[:500]}"
                )
                logger.warning(
                    f"Attempt {attempt + 1}/{total_attempts} gagal — "
                    f"status: {response.status_code}"
                )

            except httpx.TimeoutException as e:
                last_error_type = "timeout"
                last_error_message = (
                    f"Request timeout setelah {self._timeout}s: {str(e)}"
                )
                logger.warning(
                    f"Attempt {attempt + 1}/{total_attempts} timeout — {e}"
                )

            except Exception as e:
                last_error_type = self._classify_error(None, e)
                last_error_message = f"Request error: {str(e)}"
                logger.warning(
                    f"Attempt {attempt + 1}/{total_attempts} error — {e}"
                )

            # Jangan sleep setelah attempt terakhir
            if attempt < total_attempts - 1:
                # Exponential backoff: 2^0=1s, 2^1=2s, 2^2=4s
                backoff = 2**attempt
                logger.info(f"Retry dalam {backoff}s...")
                await asyncio.sleep(backoff)

        # Semua retry habis — return error response
        latency_ms = (time.time() - start_time) * 1000
        return LLMResponse(
            status="error",
            content=None,
            error_type=last_error_type,
            error_message=last_error_message,
            metadata=LLMMetadata(
                model=self._model_name,
                latency_ms=latency_ms,
                provider="gemini",
            ),
        )

    def _parse_success_response(
        self, data: dict[str, Any], latency_ms: float
    ) -> LLMResponse:
        """
        Parse response sukses dari Gemini API.

        Mengekstrak teks dari candidates[0].content.parts[0].text
        dan metadata token usage dari usageMetadata.
        """
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                return LLMResponse(
                    status="error",
                    content=None,
                    error_type="invalid_response",
                    error_message="Response tidak memiliki candidates.",
                    metadata=LLMMetadata(
                        model=self._model_name,
                        latency_ms=latency_ms,
                        provider="gemini",
                    ),
                )

            # Ambil teks dari candidate pertama
            parts = candidates[0].get("content", {}).get("parts", [])
            text_content = ""
            for part in parts:
                if "text" in part:
                    text_content += part["text"]

            # Parse token usage dari usageMetadata
            usage_meta = data.get("usageMetadata", {})
            token_usage = TokenUsage(
                prompt_tokens=usage_meta.get("promptTokenCount", 0),
                completion_tokens=usage_meta.get("candidatesTokenCount", 0),
                total_tokens=usage_meta.get("totalTokenCount", 0),
            )

            return LLMResponse(
                status="success",
                content=text_content,
                metadata=LLMMetadata(
                    model=self._model_name,
                    token_usage=token_usage,
                    latency_ms=latency_ms,
                    provider="gemini",
                    finish_reason=candidates[0].get("finishReason"),
                ),
            )

        except (KeyError, IndexError, TypeError) as e:
            return LLMResponse(
                status="error",
                content=None,
                error_type="invalid_response",
                error_message=f"Gagal parsing response Gemini: {str(e)}",
                metadata=LLMMetadata(
                    model=self._model_name,
                    latency_ms=latency_ms,
                    provider="gemini",
                ),
            )

    async def complete_text(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Text completion — kirim prompt dan terima response teks dari Gemini.

        Args:
            prompt: Teks prompt yang dikirim ke Gemini.
            **kwargs: Parameter opsional:
                - temperature (float): Kreativitas output (default 0.1)
                - max_output_tokens (int): Batas token output (default 8192)

        Returns:
            LLMResponse dengan content berupa string hasil completion.
        """
        temperature = kwargs.get("temperature", 0.1)
        max_output_tokens = kwargs.get("max_output_tokens", 8192)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        return await self._request_with_retry(payload)

    async def parse_document(
        self,
        file_content: bytes,
        mime_type: str,
        prompt: str,
        max_output_tokens: int = 8192,
    ) -> LLMResponse:
        """
        Multimodal document parsing — ekstrak informasi dari file PDF/DOCX.

        Mengirim file sebagai base64 inline data ke Gemini multimodal endpoint
        bersama dengan prompt instruksi.

        Args:
            file_content: Konten file dalam bytes.
            mime_type: MIME type file (PDF atau DOCX).
            prompt: Instruksi apa yang harus diekstrak dari dokumen.
            max_output_tokens: Batas token output (default 8192, perilaku lama).

        Returns:
            LLMResponse dengan content berupa data terstruktur hasil parsing.
        """
        # Validasi MIME type
        if mime_type not in SUPPORTED_MIME_TYPES:
            return LLMResponse(
                status="error",
                content=None,
                error_type="invalid_response",
                error_message=(
                    f"MIME type '{mime_type}' tidak didukung. "
                    f"Gunakan PDF atau DOCX."
                ),
                metadata=LLMMetadata(
                    model=self._model_name,
                    latency_ms=0.0,
                    provider="gemini",
                ),
            )

        # Encode file ke base64
        encoded_data = base64.b64encode(file_content).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded_data,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_output_tokens,
            },
        }

        return await self._request_with_retry(payload)

    async def structure_text(
        self, text: str, output_schema: dict[str, Any]
    ) -> LLMResponse:
        """
        Text structuring — ubah teks menjadi format JSON terstruktur.

        Menggunakan Gemini JSON mode (responseMimeType: application/json)
        untuk memastikan output dalam format JSON yang valid.

        Args:
            text: Teks input yang akan di-structure.
            output_schema: Schema JSON yang mendefinisikan format output.

        Returns:
            LLMResponse dengan content berupa dict sesuai output_schema.
        """
        # Buat prompt yang menyertakan schema sebagai instruksi
        schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)
        structured_prompt = (
            f"Ubah teks berikut menjadi format JSON sesuai schema yang diberikan.\n\n"
            f"Schema output yang diharapkan:\n```json\n{schema_str}\n```\n\n"
            f"Teks input:\n{text}\n\n"
            f"Kembalikan HANYA JSON yang valid sesuai schema di atas, tanpa penjelasan tambahan."
        )

        payload = {
            "contents": [{"parts": [{"text": structured_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }

        response = await self._request_with_retry(payload)

        # Jika sukses, coba parse content sebagai JSON
        if response.status == "success" and response.content:
            try:
                parsed = json.loads(response.content)
                response.content = parsed
            except json.JSONDecodeError:
                # Content bukan JSON valid — tetap return sebagai string
                logger.warning(
                    "Response structure_text bukan JSON valid, "
                    "mengembalikan raw text."
                )

        return response
