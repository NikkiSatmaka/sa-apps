"""
Fake LLM: adapter palsu yang didaftarkan ke `llm_factory` (tanpa mengubah kode produksi).

Respons diprogram per jenis panggilan (`complete_text`, `parse_document`, `structure_text`).
Semua panggilan direkam. Panggilan yang belum diprogram gagal keras (AssertionError) agar test
tidak diam-diam memakai respons tebakan.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.llm_provider import LLMMetadata, LLMResponse, TokenUsage, llm_factory

JENIS_PANGGILAN = ("complete_text", "parse_document", "structure_text")
TIPE_ERROR = ("timeout", "auth_error", "invalid_response", "unknown")


def _metadata(finish_reason: str | None = "STOP") -> LLMMetadata:
    return LLMMetadata(
        model="fake-model",
        token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        latency_ms=0.0,
        provider="fake",
        finish_reason=finish_reason,
    )


def respons_sukses(content: Any, *, finish_reason: str | None = "STOP") -> LLMResponse:
    """Respons sukses; `content` string (complete_text) atau dict/list (structure_text)."""
    return LLMResponse(status="success", content=content, metadata=_metadata(finish_reason))


def respons_terpotong(content: Any = "") -> LLMResponse:
    """Sukses tetapi terpotong: `finish_reason="MAX_TOKENS"` (keluaran tidak lengkap)."""
    return respons_sukses(content, finish_reason="MAX_TOKENS")


def respons_error(tipe: str = "unknown", pesan: str | None = None) -> LLMResponse:
    """Error ala adapter nyata: `status="error"`, `content=None`, `error_type` terisi."""
    assert tipe in TIPE_ERROR, f"tipe error tidak dikenal: {tipe!r} (pilih {TIPE_ERROR})"
    return LLMResponse(
        status="error",
        content=None,
        error_type=tipe,
        error_message=pesan or f"fake LLM error: {tipe}",
        metadata=_metadata(None),
    )


def respons_malformed(jenis: str) -> LLMResponse:
    """
    Keluaran malformed seperti yang akan dihasilkan Gemini nyata.

    - `structure_text`: adapter nyata mem-parse JSON sendiri dan mengembalikan error
      `invalid_response` bila gagal.
    - `complete_text`/`parse_document`: adapter nyata mengembalikan sukses dengan teks mentah, jadi
      caller yang harus menolak JSON rusak.
    """
    if jenis == "structure_text":
        return respons_error("invalid_response", "Response LLM bukan JSON yang valid.")
    return respons_sukses('{"field": "tidak ditutup", ')


@dataclass
class PanggilanLLM:
    jenis: str
    argumen: dict[str, Any]


@dataclass
class FakeLLM:
    """Pengendali fake LLM. Gunakan lewat fixture `fake_llm`."""

    panggilan: list[PanggilanLLM] = field(default_factory=list)
    _antrean: dict[str, deque] = field(
        default_factory=lambda: {j: deque() for j in JENIS_PANGGILAN}
    )
    _tetap: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ pemrograman
    def program(self, jenis: str, *respons: LLMResponse | Exception, tetap: bool = False) -> None:
        """
        Antrekan respons untuk `jenis` (dipakai berurutan, satu per panggilan).

        `Exception` di antrean akan di-raise oleh adapter (meniru adapter yang meledak).
        `tetap=True`: respons TERAKHIR dipakai terus setelah antrean habis.
        """
        assert jenis in JENIS_PANGGILAN, f"jenis tidak dikenal: {jenis!r}"
        assert respons, "minimal satu respons"
        self._antrean[jenis].extend(respons)
        if tetap:
            self._tetap[jenis] = respons[-1]

    def sukses(self, jenis: str, content: Any, *, tetap: bool = False) -> None:
        self.program(jenis, respons_sukses(content), tetap=tetap)

    def malformed(self, jenis: str, *, tetap: bool = False) -> None:
        self.program(jenis, respons_malformed(jenis), tetap=tetap)

    def error(
        self, jenis: str, tipe: str = "unknown", pesan: str | None = None, *, tetap: bool = False
    ) -> None:
        self.program(jenis, respons_error(tipe, pesan), tetap=tetap)

    def terpotong(self, jenis: str, content: Any = "", *, tetap: bool = False) -> None:
        self.program(jenis, respons_terpotong(content), tetap=tetap)

    # ------------------------------------------------------------------ perekaman
    def jumlah(self, jenis: str | None = None) -> int:
        return len(self.panggilan_jenis(jenis))

    def panggilan_jenis(self, jenis: str | None = None) -> list[PanggilanLLM]:
        if jenis is None:
            return list(self.panggilan)
        return [p for p in self.panggilan if p.jenis == jenis]

    # ------------------------------------------------------------------ internal
    def _layani(self, jenis: str, **argumen: Any) -> LLMResponse:
        self.panggilan.append(PanggilanLLM(jenis=jenis, argumen=argumen))
        antrean = self._antrean[jenis]
        if antrean:
            item = antrean.popleft()
        elif jenis in self._tetap:
            item = self._tetap[jenis]
        else:
            raise AssertionError(
                f"Panggilan LLM {jenis!r} tidak terprogram. Panggil fake_llm.sukses/error/... dulu."
            )
        if isinstance(item, Exception):
            raise item
        return item

    def buat_kelas_adapter(self) -> type:
        """Kelas adapter (memenuhi `LLMProviderInterface`) yang melayani lewat fake ini."""
        fake = self

        class AdapterFake:
            async def complete_text(self, prompt: str, **kwargs: Any) -> LLMResponse:
                return fake._layani("complete_text", prompt=prompt, **kwargs)

            async def parse_document(
                self,
                file_content: bytes,
                mime_type: str,
                prompt: str,
                max_output_tokens: int = 8192,
            ) -> LLMResponse:
                return fake._layani(
                    "parse_document",
                    file_content=file_content,
                    mime_type=mime_type,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                )

            async def structure_text(self, text: str, output_schema: dict[str, Any]) -> LLMResponse:
                return fake._layani("structure_text", text=text, output_schema=output_schema)

        return AdapterFake

    def pasang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Daftarkan adapter "fake" dan jadikan provider aktif. Semua state factory (registry,
        cache provider, snapshot config) dipulihkan otomatis oleh `monkeypatch`.
        """
        from app.core.config import settings

        # Salinan registry: pendaftaran "fake" tidak bocor ke test lain.
        monkeypatch.setattr(llm_factory, "_adapters", dict(llm_factory._adapters))
        llm_factory.register_adapter("fake", self.buat_kelas_adapter())
        monkeypatch.setattr(settings, "LLM_PROVIDER", "fake")
        for atribut in ("_current_provider", "_current_config_snapshot", "_last_good_config"):
            monkeypatch.setattr(llm_factory, atribut, None)
