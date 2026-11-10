"""
Validasi jawaban Kuesioner kualifikasi v1 (12 pertanyaan; #11 = field header target_submit).

Validasi dilakukan manual (bukan Pydantic default) agar error selalu berformat
`{field, reason}` yang sama dengan validasi header di POST /projects.
Kunci tak dikenal ditolak, sehingga klien tidak bisa menyelipkan skor mentah.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from app.schemas.qualification_definition import (
    EMAIL_PATTERN,
    answer_questions,
)

FIELD_PREFIX = "qualification_answers"
_EMAIL_RE = re.compile(EMAIL_PATTERN)

# Semua aturan (wajib, tipe, pilihan, batas) dibaca dari definisi kuesioner.
QUESTIONNAIRE_FIELDS = tuple(q.name for q in answer_questions())


def _err(field: str, reason: str) -> dict[str, str]:
    return {"field": f"{FIELD_PREFIX}.{field}" if field else FIELD_PREFIX, "reason": reason}


def validate_answers(raw: Any) -> tuple[Optional[dict[str, Any]], list[dict[str, str]]]:
    """
    Validasi dan normalisasi jawaban (dict). Return (jawaban, errors);
    jawaban None bila ada error. Semua field v1 selalu hadir di hasil (None bila kosong).
    """
    if not isinstance(raw, dict):
        return None, [_err("", "Jawaban kuesioner harus berupa objek JSON.")]

    errors: list[dict[str, str]] = []
    result: dict[str, Any] = {}

    for key in raw:
        if key not in QUESTIONNAIRE_FIELDS:
            errors.append(_err(str(key), "Field tidak dikenal pada kuesioner."))

    for q in answer_questions():
        name, required, kind = q.name, q.required, q.type
        value = raw.get(name)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            if required:
                errors.append(_err(name, "Wajib diisi."))
            result[name] = None
            continue

        if kind == "choice":
            if value not in q.choices:
                errors.append(_err(name, f"Pilihan tidak valid. Pilih salah satu: {', '.join(q.choices)}."))
                continue
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(_err(name, "Harus berupa angka."))
                continue
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(_err(name, "Harus berupa angka."))
                continue
            if value < q.min_value or value > q.max_value:
                errors.append(_err(name, f"Harus antara {q.min_value:,.0f} dan {q.max_value:,.0f}."))
                continue
        else:
            if not isinstance(value, str):
                errors.append(_err(name, "Harus berupa teks."))
                continue
            if len(value) > q.max_length:
                errors.append(_err(name, f"Maksimal {q.max_length} karakter."))
                continue
            if kind == "email" and not _EMAIL_RE.match(value):
                errors.append(_err(name, "Format email tidak valid."))
                continue
        result[name] = value

    if errors:
        return None, errors
    return result, []


def parse_answers(raw_json: Optional[str]) -> tuple[Optional[dict[str, Any]], list[dict[str, str]]]:
    """Parse string JSON dari form multipart lalu validasi."""
    if raw_json is None or not raw_json.strip():
        return None, [_err("", "Jawaban kuesioner kualifikasi wajib diisi.")]
    try:
        parsed = json.loads(raw_json)
    except (ValueError, TypeError):
        return None, [_err("", "Jawaban kuesioner bukan JSON yang valid.")]
    return validate_answers(parsed)
