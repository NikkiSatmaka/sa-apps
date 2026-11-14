"""
Tampilan kualifikasi untuk detail proyek (read-only, tidak mengubah data).

Proyek baru: jawaban kuesioner + sub-skor + feedback (bila skor < gate).
Proyek lama (qualification_answers NULL): metadata BANT lama dikembalikan apa adanya
sebagai `legacy_data`; tanpa backfill (ADR 0010).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from app.core import status as status_konst
from app.schemas.scoring import BANTSubScores
from app.services import bant_rubric

LEGACY_KEYS = (
    "budget_mrr",
    "pic_name",
    "pic_position",
    "pic_email",
    "need_description",
    "timeline_target",
)


def _extract_sub_scores(detail: dict[str, Any]) -> Optional[BANTSubScores]:
    """Sub-skor dari bant_detail; None bila tidak lengkap/tidak valid (mis. proyek lama)."""
    try:
        return BANTSubScores.model_validate(
            {k: detail.get(k) for k in bant_rubric.SUB_SCORE_KEYS}, strict=True
        )
    except ValidationError:
        return None


def _override_view(project: Any) -> Optional[dict[str, int]]:
    """Sub-skor override Lead SA (batas bawah) bila ada dan valid; selain itu None."""
    raw = getattr(project, "override_sub_scores", None)
    if not isinstance(raw, dict):
        return None
    sub = _extract_sub_scores(raw)
    return sub.model_dump() if sub is not None else None


def build_qualification_view(project: Any) -> dict[str, Any]:
    detail = dict(project.bant_detail or {})
    answers = project.qualification_answers
    is_legacy = answers is None
    # Selama qualification_state Scoring skor rubrik hanya sementara; jangan tampil sebagai hasil final.
    scoring_pending = (
        project.status == status_konst.INTAKE
        and project.qualification_state == status_konst.QS_SCORING
    )

    sub_scores = None if scoring_pending else _extract_sub_scores(detail)
    feedback = None
    score = project.bant_score
    if sub_scores is not None and score is not None and score < bant_rubric.GATE_THRESHOLD:
        feedback = bant_rubric.generate_feedback(sub_scores)

    legacy_data = None
    if is_legacy:
        legacy_data = {k: detail[k] for k in LEGACY_KEYS if k in detail} or None

    return {
        "legacy": is_legacy,
        "scoring_pending": scoring_pending,
        "schema_version": None if is_legacy else project.qualification_schema_version,
        "answers": None if is_legacy else dict(answers),
        "sub_scores": sub_scores.model_dump() if sub_scores is not None else None,
        "feedback": feedback,
        "override_sub_scores": _override_view(project),
        "legacy_data": legacy_data,
    }
