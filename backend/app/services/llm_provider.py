"""
LLM Provider Abstraction Layer.

Modul ini menyediakan interface standar untuk berkomunikasi dengan berbagai LLM provider
(Gemini, OpenAI, Anthropic, dll.) menggunakan Protocol pattern dan factory dengan registry.

Komponen utama:
- LLMResponse: Format response standar dari semua adapter
- LLMProviderInterface: Protocol yang harus diimplementasi setiap adapter
- LLMProviderFactory: Factory dengan registry pattern untuk mengelola adapter
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Standardized Response Format
# =============================================================================


class TokenUsage(BaseModel):
    """Detail penggunaan token dari LLM provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMMetadata(BaseModel):
    """Metadata yang menyertai setiap response dari LLM provider."""

    model: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    provider: str = ""
    # Alasan berhenti dari provider (mis. "STOP", "MAX_TOKENS"); None bila tidak dilaporkan.
    finish_reason: str | None = None


class LLMResponse(BaseModel):
    """
    Format response standar dari semua LLM adapter.

    Setiap adapter HARUS mengembalikan response dalam format ini,
    baik untuk operasi yang sukses maupun yang gagal.

    Attributes:
        status: "success" jika operasi berhasil, "error" jika gagal.
        content: Hasil teks terstruktur dari LLM, atau None jika error.
        error_type: Jenis kegagalan jika status "error" (timeout, auth_error, invalid_response, unknown).
        error_message: Pesan error detail jika status "error".
        metadata: Informasi tambahan (model, token usage, latency).
    """

    status: str = "success"  # "success" | "error"
    content: Any | None = None
    error_type: str | None = None  # "timeout" | "auth_error" | "invalid_response" | "unknown"
    error_message: str | None = None
    metadata: LLMMetadata = Field(default_factory=LLMMetadata)


# =============================================================================
# LLM Provider Interface (Protocol)
# =============================================================================


@runtime_checkable
class LLMProviderInterface(Protocol):
    """
    Protocol interface untuk semua LLM adapter.

    Setiap adapter (Gemini, OpenAI, Anthropic, dll.) HARUS mengimplementasi
    ketiga method async berikut. Menggunakan typing.Protocol agar bersifat
    structural subtyping — tidak perlu inheritance eksplisit.
    """

    async def complete_text(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Text completion — mengirim prompt dan menerima response teks.

        Args:
            prompt: Teks prompt yang akan dikirim ke LLM.
            **kwargs: Parameter tambahan spesifik provider (temperature, max_tokens, dll.)

        Returns:
            LLMResponse dengan content berupa string hasil completion.
        """
        ...

    async def parse_document(
        self,
        file_content: bytes,
        mime_type: str,
        prompt: str,
        max_output_tokens: int = 8192,
    ) -> LLMResponse:
        """
        Multimodal document parsing — mengekstrak informasi dari file.

        Args:
            max_output_tokens: Batas token output (default 8192; dinaikkan untuk ekstraksi teks).
            file_content: Konten file dalam bentuk bytes.
            mime_type: MIME type file (e.g., "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document").
            prompt: Instruksi untuk LLM tentang apa yang harus diekstrak.

        Returns:
            LLMResponse dengan content berupa data terstruktur hasil parsing.
        """
        ...

    async def structure_text(
        self, text: str, output_schema: dict[str, Any]
    ) -> LLMResponse:
        """
        Text structuring — mengubah teks menjadi format terstruktur.

        Args:
            text: Teks input yang akan di-structure.
            output_schema: Schema JSON yang mendefinisikan format output yang diharapkan.

        Returns:
            LLMResponse dengan content berupa dict sesuai output_schema.
        """
        ...


# =============================================================================
# LLM Provider Factory (Registry Pattern)
# =============================================================================


class LLMProviderFactory:
    """
    Factory dengan registry pattern untuk mengelola LLM adapter.

    Mendukung:
    - Registrasi adapter baru tanpa modifikasi kode existing (Open-Closed Principle)
    - Hot-reload config tanpa restart aplikasi (maks 30 detik switch)
    - Fallback ke config terakhir yang valid jika config baru gagal

    Contoh penggunaan:
        factory = LLMProviderFactory()
        factory.register_adapter("gemini", GeminiAdapter)
        provider = factory.get_provider()
        response = await provider.complete_text("Hello!")
    """

    def __init__(self) -> None:
        """Inisialisasi factory dengan registry kosong."""
        self._adapters: dict[str, type[LLMProviderInterface]] = {}
        self._current_provider: LLMProviderInterface | None = None
        self._last_good_config: dict[str, Any] | None = None
        self._current_config_snapshot: dict[str, Any] | None = None

    def register_adapter(
        self, name: str, adapter_class: type[LLMProviderInterface]
    ) -> None:
        """
        Daftarkan adapter baru ke registry.

        Args:
            name: Nama unik adapter (e.g., "gemini", "openai", "anthropic").
            adapter_class: Class adapter yang mengimplementasi LLMProviderInterface.

        Raises:
            ValueError: Jika name kosong atau adapter_class None.
        """
        if not name:
            raise ValueError("Nama adapter tidak boleh kosong.")
        if adapter_class is None:
            raise ValueError("Adapter class tidak boleh None.")

        self._adapters[name.lower()] = adapter_class
        logger.info(f"Adapter '{name}' berhasil didaftarkan ke registry.")

    def get_provider(self) -> LLMProviderInterface:
        """
        Ambil provider aktif berdasarkan konfigurasi environment.

        Membaca setting LLM_PROVIDER dari config dan mengembalikan instance adapter
        yang sesuai. Jika config berubah sejak terakhir kali dipanggil, instance baru
        akan dibuat (mendukung hot-reload).

        Returns:
            Instance LLMProviderInterface yang aktif.

        Raises:
            ValueError: Jika provider yang dikonfigurasi belum terdaftar di registry.
            RuntimeError: Jika tidak ada adapter yang terdaftar.
        """
        from app.core.config import settings

        if not self._adapters:
            raise RuntimeError(
                "Tidak ada adapter yang terdaftar. "
                "Panggil register_adapter() terlebih dahulu."
            )

        # Ambil snapshot config saat ini
        current_config = {
            "provider": settings.LLM_PROVIDER.lower(),
            "model_name": settings.LLM_MODEL_NAME,
            "api_endpoint": settings.LLM_API_ENDPOINT,
            "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
            "max_retries": settings.LLM_MAX_RETRIES,
        }

        # Cek apakah config berubah — jika ya, buat instance baru (hot-reload)
        if (
            self._current_provider is not None
            and self._current_config_snapshot == current_config
        ):
            return self._current_provider

        provider_name = current_config["provider"]

        if provider_name not in self._adapters:
            available = ", ".join(self._adapters.keys())
            raise ValueError(
                f"Provider '{provider_name}' belum terdaftar. "
                f"Adapter tersedia: [{available}]"
            )

        try:
            # Buat instance adapter baru
            adapter_class = self._adapters[provider_name]
            self._current_provider = adapter_class()  # type: ignore[call-arg]
            self._current_config_snapshot = current_config
            self._last_good_config = current_config
            logger.info(
                f"Provider '{provider_name}' (model: {current_config['model_name']}) "
                f"berhasil diinisialisasi."
            )
        except Exception as e:
            logger.error(
                f"Gagal membuat instance provider '{provider_name}': {e}"
            )
            # Fallback ke config terakhir yang valid
            if self._last_good_config and self._current_provider:
                logger.warning(
                    f"Fallback ke config terakhir yang valid: "
                    f"{self._last_good_config['provider']}"
                )
                return self._current_provider
            raise RuntimeError(
                f"Gagal inisialisasi provider '{provider_name}' "
                f"dan tidak ada fallback config yang tersedia."
            ) from e

        return self._current_provider

    async def reload_config(self) -> None:
        """
        Hot-reload konfigurasi LLM tanpa restart aplikasi.

        Method ini mereset current provider sehingga panggilan get_provider()
        berikutnya akan membaca ulang config dan membuat instance baru.
        Proses switch dijamin selesai dalam maks 30 detik.

        Jika config baru gagal, akan fallback ke config terakhir yang valid.
        """
        start_time = time.time()

        logger.info("Memulai hot-reload konfigurasi LLM...")

        # Reset current provider agar get_provider() membuat instance baru
        old_provider = self._current_provider
        old_config = self._current_config_snapshot
        self._current_provider = None
        self._current_config_snapshot = None

        try:
            # Coba inisialisasi provider baru dengan config terbaru
            self.get_provider()

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Hot-reload berhasil dalam {elapsed_ms:.0f}ms. "
                f"Provider aktif: {self._current_config_snapshot}"
            )
        except Exception as e:
            logger.error(f"Hot-reload gagal: {e}. Mengembalikan provider sebelumnya.")
            # Rollback ke provider lama
            self._current_provider = old_provider
            self._current_config_snapshot = old_config

            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > 30_000:
                logger.critical(
                    f"Hot-reload melebihi batas 30 detik ({elapsed_ms:.0f}ms)!"
                )

    @property
    def registered_adapters(self) -> list[str]:
        """Daftar nama adapter yang sudah terdaftar di registry."""
        return list(self._adapters.keys())

    @property
    def active_provider_name(self) -> str | None:
        """Nama provider yang sedang aktif, atau None jika belum diinisialisasi."""
        if self._current_config_snapshot:
            return self._current_config_snapshot.get("provider")
        return None


# =============================================================================
# Singleton Factory Instance
# =============================================================================

# Instance global factory — digunakan oleh seluruh aplikasi
llm_factory = LLMProviderFactory()
