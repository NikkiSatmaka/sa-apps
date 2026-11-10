"""
Ekstraksi teks Source document (MoM/RFP) via Gemini.

Panggilan LLM TERPISAH dari scoring dan berjalan di background (sesi DB sendiri).
Kegagalan di sini hanya menandai baris `failed`; tidak pernah dilempar ke pemanggil
sehingga tidak mempengaruhi create proyek maupun scoring. File asli tidak disimpan.
"""

import logging
import uuid
from typing import Any

from app.models.source_document import SourceDocument
from app.services.llm_provider import llm_factory
from app.utils.guardrails import check_document_size

logger = logging.getLogger(__name__)

# Batas output untuk ekstraksi teks penuh (parse_document default hanya 8192).
EXTRACTION_MAX_OUTPUT_TOKENS = 32768
# finishReason Gemini yang menandakan respons berhenti karena batas token.
_TRUNCATION_REASONS = {"MAX_TOKENS", "LENGTH"}

EXTRACTION_PROMPT = (
    "Ekstrak seluruh teks dari dokumen terlampir apa adanya (verbatim), dengan urutan asli. "
    "Pertahankan judul, daftar, dan tabel dalam bentuk teks biasa. Jangan meringkas, "
    "menafsirkan, atau menambah komentar. Jika dokumen tidak memiliki teks yang dapat "
    "dibaca, kembalikan string kosong."
)

# (id baris SourceDocument, filename, konten bytes, mime_type)
ExtractionItem = tuple[uuid.UUID, str, bytes, str]


async def _extract_one(db: Any, item: ExtractionItem) -> None:
    doc_id, filename, content, mime_type = item
    doc = await db.get(SourceDocument, doc_id)
    if doc is None:
        logger.warning("[SourceDoc] Baris %s tidak ditemukan; dilewati.", doc_id)
        return

    try:
        guard = check_document_size(content, mime_type, filename)
        provider = llm_factory.get_provider()
        response = await provider.parse_document(
            file_content=guard.safe_value,
            mime_type=mime_type,
            prompt=EXTRACTION_PROMPT,
            max_output_tokens=EXTRACTION_MAX_OUTPUT_TOKENS,
        )
        if response.status != "success" or not isinstance(response.content, (str, type(None))):
            raise RuntimeError(response.error_message or "Respons ekstraksi tidak valid.")

        text = (response.content or "").strip()
        if not text:
            doc.extraction_status = "empty"
            doc.extracted_text = None
        else:
            doc.extraction_status = "extracted"
            doc.extracted_text = text
            doc.truncated = (response.metadata.finish_reason or "").upper() in _TRUNCATION_REASONS
    except Exception as e:
        logger.error("[SourceDoc] Ekstraksi '%s' gagal: %s", filename, e)
        doc.extraction_status = "failed"
        doc.extracted_text = None

    await db.commit()


async def extract_source_documents(project_id: str, items: list[ExtractionItem]) -> None:
    """Background task: ekstrak teks tiap Source document; tidak pernah melempar."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            for item in items:
                try:
                    await _extract_one(db, item)
                except Exception as e:  # satu file gagal tidak menghentikan file lain
                    logger.error("[SourceDoc] Proyek %s, file %s: %s", project_id, item[1], e)
    except Exception as e:
        logger.error("[SourceDoc] Ekstraksi proyek %s gagal: %s", project_id, e)
