"""
Guardrail_Module — lapisan keamanan terpusat untuk semua pemanggilan LLM (Gemini).

Module ini bersifat pure-function: tidak ada import model SQLAlchemy, session DB,
maupun client HTTP. Satu-satunya side-effect adalah logging via
``logging.getLogger(__name__)``. Dengan begitu seluruh fungsi dapat diuji dengan
input acak tanpa fixture DB/HTTP (lihat Requirements 1.1 dan 1.5).

Komponen utama:
- ``sanitize_text_input`` — Input_Guardrail teks (size clamp, PII detection,
  injection neutralize, delimiter wrap) untuk note polishing & project summary.
- ``check_document_size`` — Input_Guardrail dokumen (byte clamp) untuk BANT scoring.
- ``detect_pii`` — PII_Detector Indonesia-centric (flag-and-log saja).
- ``validate_llm_json`` — Output_Validator terhadap Pydantic contract.
- ``is_nonempty_summary`` — validasi ringan untuk ringkasan prosa (project summary).
- ``strip_code_fence`` — helper pembersih markdown code-fence, dipakai bersama
  oleh ``scoring_engine`` dan ``validate_llm_json``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Literal, Optional, TypeVar, get_args

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Delimiter konstanta untuk Delimiter_Wrap (Requirement 5.2). Konten user dibungkus
# penanda eksplisit ini agar LLM memperlakukannya sebagai data, bukan instruksi.
USER_CONTENT_START = "<<<USER_CONTENT_START>>>"
USER_CONTENT_END = "<<<USER_CONTENT_END>>>"

# Penanda yang disisipkan ke tengah frasa injeksi agar pola instruksi utuh tidak
# lagi muncul sebagai substring utuh, tanpa membuang informasi konten user.
_INJECTION_MARKER = "[user-content]"


class PiiType(str, Enum):
    """Tipe PII Indonesia-centric yang dipindai oleh PII_Detector (MVP)."""

    EMAIL = "email"
    PHONE_ID = "phone_id"  # nomor telepon Indonesia
    NIK = "nik"  # NIK/KTP (16 digit)
    NPWP = "npwp"  # NPWP
    CREDIT_CARD = "credit_card"


@dataclass(frozen=True)
class PiiFlag:
    """
    Penanda hasil deteksi PII.

    Hanya menyimpan ``type`` dan ``count`` kemunculan — nilai mentah PII TIDAK
    pernah disimpan di sini maupun di log (Requirement 4.3).
    """

    type: PiiType
    count: int


@dataclass
class GuardrailResult(Generic[T]):
    """
    Return terpadu untuk semua fungsi Input_Guardrail.

    Baik guardrail teks (``safe_value: str``) maupun dokumen
    (``safe_value: bytes``) mengembalikan struktur yang sama, agar Call_Site
    menangani hasil secara seragam. Fungsi tidak pernah melempar exception untuk
    input oversized/injection/PII; ``safe_value`` selalu terisi sehingga
    pemanggilan LLM tetap dapat dilanjutkan.
    """

    safe_value: T  # teks/bytes yang aman diteruskan ke LLM
    truncated: bool = False  # True bila size/byte clamp terjadi
    pii_flags: list[PiiFlag] = field(default_factory=list)
    injection_hits: int = 0  # jumlah pola injeksi yang dinetralkan
    original_size: int = 0  # char (teks) atau byte (dokumen) sebelum clamp
    final_size: int = 0  # ukuran setelah clamp


# =============================================================================
# PII_Detector — regex Indonesia-centric
# =============================================================================

# Pola regex Indonesia-centric (MVP). Urutan dipertahankan sesuai design.md.
_PII_PATTERNS: list[tuple[PiiType, re.Pattern[str]]] = [
    (PiiType.EMAIL, re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    (PiiType.PHONE_ID, re.compile(r"(?:\+62|62|0)8[1-9]\d{6,11}")),
    (PiiType.NIK, re.compile(r"\b\d{16}\b")),
    (PiiType.NPWP, re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\.?\d{1}-?\d{3}\.?\d{3}\b")),
    (PiiType.CREDIT_CARD, re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]


def detect_pii(text: str) -> list[PiiFlag]:
    """
    Deteksi PII Indonesia-centric berbasis regex. Flag-and-log saja.

    Mengembalikan daftar ``PiiFlag`` berisi ``type`` + ``count`` tanpa menyimpan
    nilai mentah. Dinonaktifkan bila ``settings.GUARDRAIL_PII_DETECTION_ENABLED ==
    False`` (mengembalikan list kosong tanpa scan) — Requirement 4.
    """
    if not settings.GUARDRAIL_PII_DETECTION_ENABLED:
        return []

    flags: list[PiiFlag] = []
    for pii_type, pattern in _PII_PATTERNS:
        count = len(pattern.findall(text))
        if count > 0:
            flags.append(PiiFlag(type=pii_type, count=count))

    if flags:
        # Log aman: hanya tipe + count, tidak pernah nilai mentah (Requirement 4.3).
        summary = ", ".join(f"{flag.type.value}={flag.count}" for flag in flags)
        logger.warning("PII terdeteksi: %s", summary)

    return flags


# =============================================================================
# Prompt_Injection_Mitigator
# =============================================================================

# Pola prompt-injection yang dinetralkan (case-insensitive, multiline).
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+the\s+(above|system)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"^\s*system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*assistant\s*:", re.IGNORECASE | re.MULTILINE),
]


def _neutralize_injection(text: str) -> tuple[str, int]:
    """
    Netralkan pola injeksi; kembalikan ``(teks_ternetralkan, jumlah_hit)``.

    Menyisipkan penanda ``[user-content]`` di dalam frasa instruksi sehingga pola
    tidak lagi terbaca sebagai perintah utuh oleh LLM, tanpa membuang kata-kata
    konten user (Requirement 5.1, 5.3).
    """
    hits = 0
    result = text
    for pattern in _INJECTION_PATTERNS:

        def _replace(match: re.Match[str]) -> str:
            nonlocal hits
            hits += 1
            matched = match.group(0)
            # Sisipkan marker setelah karakter pertama agar frasa pola pecah
            # (mis. "ignore ..." -> "i[user-content]gnore ...").
            return matched[0] + _INJECTION_MARKER + matched[1:]

        result = pattern.sub(_replace, result)

    return result, hits


def _wrap_with_delimiter(text: str) -> str:
    """Bungkus konten user dengan penanda batas awal/akhir yang eksplisit."""
    return f"{USER_CONTENT_START}\n{text}\n{USER_CONTENT_END}"


# =============================================================================
# Input_Guardrail — teks & dokumen
# =============================================================================


def sanitize_text_input(
    text: str,
    *,
    filename: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> GuardrailResult[str]:
    """
    Pipeline Input_Guardrail untuk input teks (note polishing & project summary).

    Urutan orkestrasi:
      1. Size clamp ke ``max_chars`` bila diberikan, selain itu ke
         ``settings.LLM_MAX_INPUT_CHARS`` (Requirement 2).
      2. PII detection bila ``GUARDRAIL_PII_DETECTION_ENABLED`` (Requirement 4) —
         flag-and-log, tanpa redaction.
      3. Injection neutralize (Requirement 5.1).
      4. Delimiter wrap (Requirement 5.2).

    ``safe_value`` selalu dikembalikan; fungsi tidak melempar untuk input bermasalah.
    ``original_size``/``final_size`` dihitung pada dimensi char size-clamp (sebelum
    neutralize/wrap), konsisten dengan Property 1.
    """
    original_size = len(text)
    if max_chars is None:
        max_chars = settings.LLM_MAX_INPUT_CHARS
    max_chars = max(0, max_chars)

    # 1. Size clamp (Requirement 2.1, 2.2, 2.4)
    truncated = original_size > max_chars
    clamped = text[:max_chars] if truncated else text
    final_size = len(clamped)
    if truncated:
        logger.warning(
            "Input teks terpotong: panjang asli %d karakter, dipotong ke %d karakter.",
            original_size,
            final_size,
        )

    # 2. PII detection (flag-and-log, tanpa redaction) — scan pada teks size-clamp
    pii_flags = detect_pii(clamped)

    # 3. Injection neutralize (Requirement 5.1, 5.3)
    neutralized, injection_hits = _neutralize_injection(clamped)
    if injection_hits > 0:
        logger.warning(
            "Pola prompt-injection dinetralkan: %d pola.",
            injection_hits,
        )

    # 4. Delimiter wrap (Requirement 5.2)
    safe_value = _wrap_with_delimiter(neutralized)

    return GuardrailResult(
        safe_value=safe_value,
        truncated=truncated,
        pii_flags=pii_flags,
        injection_hits=injection_hits,
        original_size=original_size,
        final_size=final_size,
    )


def check_document_size(content: bytes, mime_type: str, filename: str) -> GuardrailResult[bytes]:
    """
    Byte clamp untuk dokumen multimodal (BANT scoring sebelum ``parse_document``).

    Jika ``len(content) > settings.LLM_MAX_DOCUMENT_BYTES``, potong ke batas byte,
    set ``truncated=True``, dan tulis ``logger.warning`` berisi ukuran asli,
    ukuran terpotong, dan ``filename``. Jika ≤ batas, konten diteruskan apa adanya
    (Requirement 3).
    """
    original_size = len(content)
    max_bytes = settings.LLM_MAX_DOCUMENT_BYTES

    truncated = original_size > max_bytes
    clamped = content[:max_bytes] if truncated else content
    final_size = len(clamped)
    if truncated:
        logger.warning(
            "Dokumen '%s' terpotong: ukuran asli %d byte, dipotong ke %d byte.",
            filename,
            original_size,
            final_size,
        )

    return GuardrailResult(
        safe_value=clamped,
        truncated=truncated,
        original_size=original_size,
        final_size=final_size,
    )


# =============================================================================
# Output_Validator & Pydantic contracts
# =============================================================================


def strip_code_fence(text: str) -> str:
    """
    Bersihkan markdown code-fence (```` ```json ```` / ``` ``` ```) dari teks.

    Dipakai bersama oleh ``scoring_engine._parse_llm_response`` dan
    ``validate_llm_json`` agar perilaku parsing konsisten.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        stripped = "\n".join(lines)
    return stripped


class BANTCriterion(BaseModel):
    """Sub-kriteria BANT dengan skor di-clamp ke rentang 0-25 (defense-in-depth)."""

    score: int = Field(ge=0, le=25)
    evidence: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> int:
        try:
            return max(0, min(25, int(v)))
        except (TypeError, ValueError):
            return 0


class BANTExtractionResult(BaseModel):
    """Kontrak output ekstraksi BANT dari dokumen (BANT scoring)."""

    budget: BANTCriterion
    authority: BANTCriterion
    need: BANTCriterion
    timeline: BANTCriterion
    use_case_tags: list[str] = Field(default_factory=list, max_length=5)


RequirementKategori = Literal[
    "Fungsional", "Teknis", "Kepatuhan", "Integrasi", "Timeline", "Asumsi"
]
REQUIREMENT_KATEGORI: tuple[str, ...] = get_args(RequirementKategori)
REQUIREMENT_MAX_ITEMS = 200
REQUIREMENT_MAX_BUTIR_CHARS = 1000


class RequirementItem(BaseModel):
    """Satu butir Requirement: kategori dari himpunan tetap + teks butir."""

    kategori: RequirementKategori
    butir: str = Field(min_length=1, max_length=REQUIREMENT_MAX_BUTIR_CHARS)

    @field_validator("butir", mode="after")
    @classmethod
    def _strip_non_kosong(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("butir tidak boleh kosong")
        return v


class RequirementExtractionResult(BaseModel):
    """Kontrak keluaran LLM untuk generate Requirement: daftar butir (minimal 1)."""

    items: list[RequirementItem] = Field(min_length=1, max_length=REQUIREMENT_MAX_ITEMS)


class ActionItem(BaseModel):
    """Item aksi hasil note polishing."""

    description: str
    pic: Optional[str] = None


class PolishResult(BaseModel):
    """Kontrak output note polishing (discussion points + action items)."""

    discussion_points: list[str]
    action_items: list[ActionItem]


@dataclass
class OutputValidationResult(Generic[T]):
    """Hasil validasi output terstruktur LLM terhadap Pydantic contract."""

    valid: bool
    data: Optional[T] = None
    error: Optional[str] = None


def validate_llm_json(content: Any, contract: type[BaseModel]) -> OutputValidationResult:
    """
    Validasi response terstruktur LLM terhadap Pydantic contract (Output_Validator).

    - Jika ``content`` string, bersihkan code-fence via ``strip_code_fence`` lalu
      ``json.loads``.
    - Validasi terhadap ``contract`` (mis. ``BANTExtractionResult`` / ``PolishResult``).
    - Sukses: ``valid=True`` + ``data`` instance contract.
    - Gagal (``JSONDecodeError`` / ``ValidationError``): ``valid=False`` + ``error``,
      dan tulis ``logger.warning`` alasan kegagalan (Requirement 6).
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(strip_code_fence(content))
        except json.JSONDecodeError as e:
            error = f"JSON tidak valid: {e}"
            logger.warning("Validasi output gagal — %s", error)
            return OutputValidationResult(valid=False, error=error)
    else:
        parsed = content

    try:
        data = contract.model_validate(parsed)
    except ValidationError as e:
        error = f"Response tidak sesuai schema {contract.__name__}: {e}"
        logger.warning("Validasi output gagal — %s", error)
        return OutputValidationResult(valid=False, error=error)

    return OutputValidationResult(valid=True, data=data)


def is_nonempty_summary(text: Any) -> bool:
    """
    Validasi ringan untuk ringkasan prosa project summary.

    True iff ``text`` adalah string non-kosong (setelah ``strip``) dengan panjang
    dalam batas wajar (``<= settings.LLM_MAX_INPUT_CHARS``).
    """
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return len(text) <= settings.LLM_MAX_INPUT_CHARS
