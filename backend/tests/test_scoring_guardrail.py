"""
Integration test wiring guardrail ke BANT scoring (``scoring_engine``).

Memverifikasi (Req 8.1, 8.4, 8.5):
- ``check_document_size`` dipanggil sebelum ``provider.parse_document``.
- ``validate_llm_json`` dipakai pada response LLM.
- Output invalid setelah retry → Intake + qualification_state "Manual Review".

Provider di-mock mengikuti pola test_gemini_adapter.py (unittest.mock), tanpa
panggilan jaringan. Tidak menyentuh DB untuk jalur yang diuji.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm_provider import LLMResponse
from app.services.scoring_engine import ScoringEngine
from app.utils.guardrails import check_document_size as real_check_document_size

VALID_BANT_JSON = json.dumps(
    {
        "budget": {"score": 20, "evidence": "ada"},
        "authority": {"score": 15, "evidence": "ada"},
        "need": {"score": 25, "evidence": "ada"},
        "timeline": {"score": 10, "evidence": "ada"},
        "use_case_tags": ["cloud", "security"],
    }
)


def _success_response(content):
    return LLMResponse(status="success", content=content)


@pytest.mark.asyncio
async def test_check_document_size_dipanggil_sebelum_parse_document():
    """Req 8.1: guardrail dokumen jalan sebelum konten dikirim ke LLM."""
    engine = ScoringEngine()
    provider = AsyncMock()
    provider.parse_document.return_value = _success_response(VALID_BANT_JSON)

    with patch(
        "app.services.scoring_engine.check_document_size",
        wraps=real_check_document_size,
    ) as spy_guard:
        result = await engine._extract_bant_with_retry(
            provider, b"konten-pdf", "application/pdf", "dok.pdf", "PRJ-1", db=None
        )

    spy_guard.assert_called_once()
    # safe_value guardrail yang dikirim ke parse_document (bukan konten mentah).
    assert provider.parse_document.await_count == 1
    kwargs = provider.parse_document.await_args.kwargs
    assert kwargs["file_content"] == b"konten-pdf"
    assert result["budget"]["score"] == 20


@pytest.mark.asyncio
async def test_validate_llm_json_dipakai_pada_response():
    """Req 8.4: response yang valid di-parse via validate_llm_json → dict BANT."""
    engine = ScoringEngine()
    provider = AsyncMock()
    provider.parse_document.return_value = _success_response(VALID_BANT_JSON)

    result = await engine._extract_bant_with_retry(
        provider, b"x", "application/pdf", "dok.pdf", "PRJ-1", db=None
    )

    assert result is not None
    # Clamp defense-in-depth lewat BANTExtractionResult.
    assert 0 <= result["budget"]["score"] <= 25
    assert result["use_case_tags"] == ["cloud", "security"]


@pytest.mark.asyncio
async def test_output_invalid_setelah_retry_mengembalikan_none():
    """Req 8.5: output invalid di semua attempt → None (dipakai Manual Review)."""
    engine = ScoringEngine()
    provider = AsyncMock()
    provider.parse_document.return_value = _success_response("bukan json {{{")

    with patch("app.services.scoring_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine._extract_bant_with_retry(
            provider, b"x", "application/pdf", "dok.pdf", "PRJ-1", db=None
        )

    assert result is None
    # Retry tetap dipertahankan: parse_document dipanggil MAX_SCORING_RETRIES kali.
    assert provider.parse_document.await_count == 3
