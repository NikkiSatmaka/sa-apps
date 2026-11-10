"""
Tampilan kualifikasi untuk detail proyek (read-only, tidak mengubah data).

Proyek baru: jawaban kuesioner + sub-skor + feedback (bila skor < gate).
Proyek lama (qualification_answers NULL): metadata BANT lama dikembalikan apa adanya
sebagai `legacy_data`; tanpa backfill (ADR 0010).
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.scoring import BANTSubScores
from app.services import bant_rubric

SUB_SCORE_KEYS = ("budget", "authority", "need", "timeline")
LEGACY_KEYS = (
    "budget_mrr",
    "pic_name",
    "pic_position",
    "pic_email",
    "need_description",
    "timeline_target",
)


def _extract_sub_scores(detail: dict[str, Any]) -> Optional[dict[str, int]]:
    if not all(
        isinstance(detail.get(k), int) and not isinstance(detail.get(k), bool)
        for k in SUB_SCORE_KEYS
    ):
        return None
    return {k: int(detail[k]) for k in SUB_SCORE_KEYS}


def build_qualification_view(project: Any) -> dict[str, Any]:
    detail = dict(project.bant_detail or {})
    answers = project.qualification_answers
    is_legacy = answers is None

    sub_scores = _extract_sub_scores(detail)
    feedback = None
    score = project.bant_score
    if sub_scores is not None and score is not None and score < bant_rubric.GATE_THRESHOLD:
        feedback = bant_rubric.generate_feedback(BANTSubScores(**sub_scores))

    legacy_data = None
    if is_legacy:
        legacy_data = {k: detail[k] for k in LEGACY_KEYS if k in detail} or None

    return {
        "legacy": is_legacy,
        "schema_version": None if is_legacy else project.qualification_schema_version,
        "answers": None if is_legacy else dict(answers),
        "sub_scores": sub_scores,
        "feedback": feedback,
        "legacy_data": legacy_data,
    }
