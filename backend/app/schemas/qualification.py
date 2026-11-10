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

from app.services.bant_rubric import (
    BUDGET_DIALOKASIKAN_CHOICES,
    JENIS_WORKLOAD_CHOICES,
    LINGKUNGAN_CHOICES,
    PERAN_PIC_CHOICES,
    TARGET_GO_LIVE_CHOICES,
)

FIELD_PREFIX = "qualification_answers"
MAX_MRR = 999_999_999_999
MAX_TEXT_LENGTH = 2000
MAX_SHORT_LENGTH = 200
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# (nama field, wajib, tipe)  — tipe: "choice:<tuple>", "text", "short", "number"
_SPEC: tuple[tuple[str, bool, str], ...] = (
    ("mrr", False, "number"),
    ("budget_dialokasikan", True, "choice"),
    ("pic_nama", False, "short"),
    ("pic_jabatan", False, "short"),
    ("pic_email", False, "email"),
    ("peran_pic", True, "choice"),
    ("stakeholder_lain", False, "text"),
    ("masalah_bisnis", True, "text"),
    ("jenis_workload", True, "choice"),
    ("lingkungan", True, "choice"),
    ("skala", True, "short"),
    ("persyaratan_khusus", False, "text"),
    ("kompetitor", False, "text"),
    ("target_go_live", True, "choice"),
)
_CHOICES = {
    "budget_dialokasikan": BUDGET_DIALOKASIKAN_CHOICES,
    "peran_pic": PERAN_PIC_CHOICES,
    "jenis_workload": JENIS_WORKLOAD_CHOICES,
    "lingkungan": LINGKUNGAN_CHOICES,
    "target_go_live": TARGET_GO_LIVE_CHOICES,
}
QUESTIONNAIRE_FIELDS = tuple(name for name, _, _ in _SPEC)


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

    for name, required, kind in _SPEC:
        value = raw.get(name)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            if required:
                errors.append(_err(name, "Wajib diisi."))
            result[name] = None
            continue

        if kind == "choice":
            if value not in _CHOICES[name]:
                errors.append(_err(name, f"Pilihan tidak valid. Pilih salah satu: {', '.join(_CHOICES[name])}."))
                continue
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(_err(name, "Harus berupa angka."))
                continue
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(_err(name, "Harus berupa angka."))
                continue
            if value < 0 or value > MAX_MRR:
                errors.append(_err(name, f"Harus antara 0 dan {MAX_MRR:,}."))
                continue
        else:
            if not isinstance(value, str):
                errors.append(_err(name, "Harus berupa teks."))
                continue
            limit = MAX_TEXT_LENGTH if kind == "text" else MAX_SHORT_LENGTH
            if len(value) > limit:
                errors.append(_err(name, f"Maksimal {limit} karakter."))
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
