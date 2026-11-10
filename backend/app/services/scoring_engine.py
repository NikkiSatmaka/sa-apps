"""
Scoring Engine — Modul AI untuk BANT scoring via LLM.

Bertanggung jawab untuk:
- Menganalisis Source document via LLM untuk ekstraksi BANT
- Menghitung BANT Score (0-100) dari sub-skor per kriteria
- Menerapkan threshold gating (>= 60 lolos, < 60 klarifikasi)
- Override skor oleh Lead_SA/Admin dan re-score dari jawaban kuesioner
- Mencari proyek serupa berdasarkan use_case_tags (RAG recommendation)

Retry strategy:
- Timeout 30s per request (dikonfigurasi di LLM provider)
- Retry 3x dengan interval 10s
- Semua retry gagal → gate memakai skor rubrik saja; "Manual Review Required"
  hanya bila skor rubrik tidak dapat dihitung (proyek tanpa jawaban kuesioner)

Skor akhir per kriteria = max(rubrik, AI, override) (ADR 0010; override Lead SA = batas bawah,
#41). Hasil AI disimpan terpisah di `projects.ai_scoring_result`, override di
`projects.override_sub_scores`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.notification_log import NotificationLog
from app.models.project import Project
from app.models.user import User
from app.schemas.scoring import (
    BANTResult,
    BANTSubScores,
    RecommendedDocumentInfo,
    SimilarProjectResult,
)
from app.services import bant_rubric
from app.services.llm_provider import LLMResponse, llm_factory
from app.utils.guardrails import (
    BANTExtractionResult,
    check_document_size,
    strip_code_fence,
    validate_llm_json,
)

logger = logging.getLogger(__name__)

# MIME types yang didukung untuk scoring dokumen
SUPPORTED_SCORING_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Prompt untuk ekstraksi BANT dari dokumen
BANT_EXTRACTION_PROMPT = """Analyze this document and extract BANT (Budget, Authority, Need, Timeline) indicators.
For each criterion, determine:
- Budget: Is there mention of budget, investment amount, or financial allocation?
- Authority: Is the decision maker or approval authority identified?
- Need: Are technical/business needs clearly stated?
- Timeline: Is there a target date, deadline, or implementation timeline?

Score each criterion from 0-25:
- 25: Explicitly found and clearly stated in the document
- 10-20: Partially or implicitly mentioned
- 0: Not found at all

Also identify up to 5 use case tags that describe the project's technical needs.

Return ONLY valid JSON (no markdown, no code fences):
{"budget": {"score": <0-25>, "evidence": "<brief evidence>"}, "authority": {"score": <0-25>, "evidence": "<brief evidence>"}, "need": {"score": <0-25>, "evidence": "<brief evidence>"}, "timeline": {"score": <0-25>, "evidence": "<brief evidence>"}, "use_case_tags": ["tag1", "tag2"]}"""

# Hasil scoring hanya boleh mengubah status proyek dari status-status ini.
# Status Assigned dan sesudahnya tidak pernah ditimpa (mis. hasil AI yang selesai terlambat).
SCORING_MUTABLE_STATUSES = frozenset({"New", "Scoring Pending", "Need Clarification"})

# Override Lead_SA/Admin (#30) hanya untuk status yang menunggu keputusan manual.
OVERRIDE_ALLOWED_STATUSES = frozenset({"Need Clarification", "Manual Review Required"})

# Interval retry dalam detik
RETRY_INTERVAL_SECONDS = 10
MAX_SCORING_RETRIES = 3


def _generate_audit_id() -> str:
    """ID audit log: AUDIT-{YYYYMMDD}-{random6} (selaras dengan workflow.py)."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"AUDIT-{date_part}-{random_part}"


class ScoringEngine:
    """
    Engine untuk BANT scoring proyek.

    Mendukung scoring otomatis via LLM (parsing dokumen PDF/DOCX untuk ekstraksi BANT),
    re-score dari jawaban kuesioner, dan override Lead_SA/Admin.

    Threshold gating:
    - Score >= 60: Status "Pending Assignment", notifikasi ke Lead_SA
    - Score < 60: Status "Need Clarification", feedback ke Sales
    """

    async def score_documents(
        self,
        project_id: str,
        files: list[tuple[bytes, str, str]],
        db: AsyncSession,
    ) -> BANTResult:
        """
        Scoring otomatis via LLM dari Source document.

        Args:
            project_id: ID proyek yang akan di-score.
            files: List of (content_bytes, mime_type, filename).
            db: Database session.

        Returns:
            BANTResult dengan total skor, sub-skor, tags, dan status.
        """
        # Filter hanya file PDF/DOCX yang didukung
        valid_files = []
        for content, mime_type, filename in files:
            if mime_type in SUPPORTED_SCORING_MIME_TYPES:
                valid_files.append((content, mime_type, filename))
            else:
                logger.warning(
                    f"File '{filename}' dengan mime type '{mime_type}' "
                    f"dilewati — hanya PDF/DOCX yang didukung untuk scoring."
                )

        # Skor rubrik dihitung ulang dari jawaban kuesioner (fungsi murni); None bila tidak ada.
        project = await self._load_project(db, project_id)
        rubric = self._rubric_scores(project)

        # Jika tidak ada file valid: pakai rubrik bila ada, selain itu arahkan ke manual
        if not valid_files and rubric is not None:
            return await self._fallback_to_rubric(db, project_id, project, rubric)
        if not valid_files:
            logger.info(
                f"Project {project_id}: Tidak ada file PDF/DOCX valid. Arahkan ke scoring manual."
            )
            result = BANTResult(
                total_score=0,
                sub_scores=BANTSubScores(budget=0, authority=0, need=0, timeline=0),
                use_case_tags=[],
                status="Need Clarification",
                feedback="Tidak ada file valid (PDF/DOCX) untuk dianalisis. "
                "Lengkapi dokumen atau jawaban kuesioner kualifikasi.",
            )
            await self._update_project_scoring(db, project_id, result)
            return result

        # Proses setiap file valid via LLM dengan retry
        all_extractions: list[dict[str, Any]] = []
        provider = llm_factory.get_provider()

        for content, mime_type, filename in valid_files:
            extraction = await self._extract_bant_with_retry(
                provider, content, mime_type, filename, project_id, db
            )
            if extraction is not None:
                all_extractions.append(extraction)

        # AI gagal setelah semua retry → gate memakai skor rubrik saja
        if not all_extractions and rubric is not None:
            logger.error(
                f"Project {project_id}: Semua file gagal diekstrak. "
                f"Gate memakai skor rubrik."
            )
            return await self._fallback_to_rubric(db, project_id, project, rubric)

        # AI gagal dan rubrik tidak dapat dihitung → Manual Review Required
        if not all_extractions:
            logger.error(
                f"Project {project_id}: Semua file gagal diekstrak. "
                f"Tandai sebagai 'Manual Review Required'."
            )
            await self._mark_manual_review_required(db, project_id)
            return BANTResult(
                total_score=0,
                sub_scores=BANTSubScores(budget=0, authority=0, need=0, timeline=0),
                use_case_tags=[],
                status="Manual Review Required",
                feedback="Scoring otomatis gagal setelah beberapa percobaan. "
                "Lead SA akan melakukan scoring manual.",
            )

        # Agregasi hasil dari semua file — ambil skor tertinggi per kriteria
        ai_sub_scores = self._aggregate_scores(all_extractions)
        use_case_tags = self._aggregate_tags(all_extractions)
        # Muat ulang proyek: override bisa berubah selama LLM berjalan (hasil AI terlambat)
        project = await self._refresh_project(db, project_id, project)
        # Skor akhir per kriteria = max(rubrik, AI, override); komponen None dilewati
        sub_scores = self._merge_max(rubric, ai_sub_scores, self._stored_override(project))
        total_score = bant_rubric.total_score(sub_scores)
        ai_result = {
            "sub_scores": ai_sub_scores.model_dump(),
            "use_case_tags": use_case_tags,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }

        # Terapkan threshold gating (dengan guard status) dan simpan hasil
        feedback = None
        if total_score < bant_rubric.GATE_THRESHOLD:
            feedback = bant_rubric.generate_feedback(sub_scores)

        result = BANTResult(
            total_score=total_score,
            sub_scores=sub_scores,
            use_case_tags=use_case_tags,
            status=bant_rubric.decide_status(total_score),
            feedback=feedback,
        )
        return await self._apply_scoring_result(db, project_id, result, ai_result=ai_result)

    async def override_score(
        self,
        project_id: str,
        budget: int,
        authority: int,
        need: int,
        timeline: int,
        reason: str,
        performed_by: uuid.UUID,
        db: AsyncSession,
    ) -> BANTResult:
        """
        Override skor BANT oleh Lead_SA/Admin (#30).

        Override disimpan terpisah (`override_sub_scores`) sebagai batas bawah; gate 60
        lewat jalur tulis yang sama dengan scoring lain (dengan guard status override),
        dan audit log (nilai lama/baru, pelaku, alasan) ditulis dalam commit yang sama.
        """
        override = BANTSubScores(
            budget=budget, authority=authority, need=need, timeline=timeline
        )
        project = await self._load_project(db, project_id)
        # Override = batas bawah: skor akhir = max(rubrik, AI tersimpan, override baru).
        # Override baru menggantikan override lama (bukan di-max dengannya).
        sub_scores = self._merge_max(
            self._rubric_scores(project), self._stored_ai(project), override
        )
        result = self._build_result(sub_scores, project)
        return await self._apply_scoring_result(
            db,
            project_id,
            result,
            mutable_statuses=OVERRIDE_ALLOWED_STATUSES,
            audit={"action": "bant_override", "performed_by": performed_by, "reason": reason},
            override_scores=override,
        )

    async def rescore_from_answers(
        self,
        db: AsyncSession,
        project: Project,
        answers: dict[str, Any],
    ) -> BANTResult:
        """
        Re-score setelah jawaban kuesioner diedit (#32).

        Skor per kriteria = max(rubrik dari jawaban baru, hasil AI tersimpan di
        `ai_scoring_result`, override di `override_sub_scores`), lalu gate 60 lewat jalur tulis dengan guard status.
        Jawaban baru disimpan dalam commit yang sama dengan skor. Hasil AI tidak ditimpa.
        """
        rubric = bant_rubric.compute_rubric_scores(answers, project.target_submit)
        sub_scores = self._merge_max(rubric, self._stored_ai(project), self._stored_override(project))
        result = self._build_result(sub_scores, project)
        project.qualification_answers = answers
        return await self._apply_scoring_result(db, project.id_project, result)

    async def _apply_scoring_result(
        self,
        db: AsyncSession,
        project_id: str,
        result: BANTResult,
        ai_result: Optional[dict[str, Any]] = None,
        *,
        mutable_statuses: frozenset[str] = SCORING_MUTABLE_STATUSES,
        audit: Optional[dict[str, Any]] = None,
        override_scores: Optional[BANTSubScores] = None,
    ) -> BANTResult:
        """
        Simpan hasil scoring + terapkan gate 60, dengan guard status.

        Hanya proyek berstatus New / Scoring Pending / Need Clarification yang berubah.
        Selain itu (mis. Assigned) skor, status, dan notifikasi tidak disentuh, dan
        `status` pada hasil yang dikembalikan mencerminkan status proyek sebenarnya.
        Notifikasi Lead_SA dikirim hanya bila proyek benar-benar menjadi Pending Assignment.
        """
        applied, effective_status = await self._update_project_scoring(
            db,
            project_id,
            result,
            ai_result=ai_result,
            mutable_statuses=mutable_statuses,
            audit=audit,
            override_scores=override_scores,
        )
        if applied and result.status == "Pending Assignment":
            await self._notify_lead_sa(db, project_id, result.total_score)
        if effective_status is not None and effective_status != result.status:
            result = result.model_copy(update={"status": effective_status})
        return result

    async def search_similar_projects(
        self,
        use_case_tags: list[str],
        exclude_project_id: str,
        db: AsyncSession,
    ) -> list[SimilarProjectResult]:
        """
        RAG: Cari proyek Closed-Win yang mirip berdasarkan use_case_tags.

        Kriteria:
        - Proyek berstatus "Closed-Win"
        - Minimal 1 tag yang sama dengan proyek saat ini
        - Diurutkan descending berdasarkan jumlah tag cocok
        - Maksimal 5 hasil
        - Sertakan daftar dokumen (PropTek, BOQ, HLD, dll.) beserta link GDrive

        Args:
            use_case_tags: Tags proyek saat ini.
            exclude_project_id: ID proyek yang dikecualikan dari hasil.
            db: Database session.

        Returns:
            List proyek serupa (max 5) dengan info dokumen.
        """
        if not use_case_tags:
            return []

        # Query proyek Closed-Win yang punya use_case_tags
        result = await db.execute(
            select(Project).where(
                and_(
                    Project.status == "Closed-Win",
                    Project.id_project != exclude_project_id,
                    Project.use_case_tags.isnot(None),
                )
            )
        )
        closed_projects = result.scalars().all()

        # Hitung kecocokan tag untuk setiap proyek
        scored_projects: list[tuple[Project, int]] = []
        tags_set = set(tag.lower() for tag in use_case_tags)

        for project in closed_projects:
            project_tags = project.use_case_tags or []
            project_tags_lower = set(tag.lower() for tag in project_tags)
            matching = len(tags_set & project_tags_lower)
            if matching > 0:
                scored_projects.append((project, matching))

        # Urutkan descending berdasarkan jumlah tag cocok
        scored_projects.sort(key=lambda x: x[1], reverse=True)

        # Ambil max 5 hasil
        top_projects = scored_projects[:5]

        if not top_projects:
            return []

        # Fetch dokumen untuk proyek-proyek yang ditemukan
        project_ids = [p.id_project for p, _ in top_projects]
        docs_result = await db.execute(
            select(Document).where(Document.id_project.in_(project_ids))
        )
        all_docs = docs_result.scalars().all()

        # Group dokumen per proyek
        docs_by_project: dict[str, list[RecommendedDocumentInfo]] = {}
        for doc in all_docs:
            if not doc.gdrive_link:
                continue  # Requirement (tanpa file Drive) tidak direkomendasikan
            if doc.id_project not in docs_by_project:
                docs_by_project[doc.id_project] = []
            docs_by_project[doc.id_project].append(
                RecommendedDocumentInfo(
                    id_doc=doc.id_doc,
                    doc_type=doc.doc_type,
                    gdrive_link=doc.gdrive_link,
                    status=doc.status,
                )
            )

        # Buat hasil akhir dengan info dokumen
        results = []
        for project, matching_count in top_projects:
            results.append(
                SimilarProjectResult(
                    id_project=project.id_project,
                    project_name=project.project_name,
                    customer_name=project.customer_name,
                    use_case_tags=project.use_case_tags or [],
                    matching_tags=matching_count,
                    status=project.status,
                    documents=docs_by_project.get(project.id_project, []),
                )
            )

        return results

    # =========================================================================
    # Private helper methods
    # =========================================================================

    async def _extract_bant_with_retry(
        self,
        provider: Any,
        content: bytes,
        mime_type: str,
        filename: str,
        project_id: str,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        """
        Ekstrak BANT dari satu file dengan retry 3x interval 10s.

        Returns:
            Dict hasil ekstraksi JSON, atau None jika semua retry gagal.
        """
        for attempt in range(1, MAX_SCORING_RETRIES + 1):
            try:
                logger.info(
                    f"Project {project_id}: Ekstraksi BANT dari '{filename}' "
                    f"(attempt {attempt}/{MAX_SCORING_RETRIES})"
                )
                # Guardrail dokumen: byte clamp sebelum dikirim ke LLM (Req 8.1).
                guard = check_document_size(content, mime_type, filename)
                response: LLMResponse = await provider.parse_document(
                    file_content=guard.safe_value,
                    mime_type=mime_type,
                    prompt=BANT_EXTRACTION_PROMPT,
                )

                if response.status == "success" and response.content:
                    # Validasi output terstruktur terhadap kontrak (Req 8.4, 6.1).
                    validation = validate_llm_json(response.content, BANTExtractionResult)
                    if validation.valid:
                        logger.info(
                            f"Project {project_id}: Berhasil ekstrak BANT dari '{filename}'"
                        )
                        return validation.data.model_dump()
                    else:
                        logger.warning(
                            f"Project {project_id}: Response LLM untuk '{filename}' "
                            f"gagal validasi schema."
                        )
                else:
                    logger.warning(
                        f"Project {project_id}: LLM error untuk '{filename}' — "
                        f"type: {response.error_type}, msg: {response.error_message}"
                    )

            except Exception as e:
                logger.error(
                    f"Project {project_id}: Exception saat parsing '{filename}' "
                    f"(attempt {attempt}): {e}"
                )

            # Tunggu sebelum retry (kecuali attempt terakhir)
            if attempt < MAX_SCORING_RETRIES:
                logger.info(f"Retry dalam {RETRY_INTERVAL_SECONDS}s...")
                await asyncio.sleep(RETRY_INTERVAL_SECONDS)

        # Semua retry gagal
        logger.error(
            f"Project {project_id}: Gagal ekstrak BANT dari '{filename}' "
            f"setelah {MAX_SCORING_RETRIES} percobaan."
        )
        return None

    def _parse_llm_response(self, content: Any) -> Optional[dict[str, Any]]:
        """Parse response LLM menjadi dict BANT. Handle string atau dict."""
        if isinstance(content, dict):
            return content

        if isinstance(content, str):
            # Bersihkan markdown code fences via helper guardrail bersama.
            try:
                return json.loads(strip_code_fence(content))
            except json.JSONDecodeError:
                return None

        return None

    def _aggregate_scores(self, extractions: list[dict[str, Any]]) -> BANTSubScores:
        """
        Agregasi sub-skor dari multiple dokumen.
        Ambil skor tertinggi per kriteria (best evidence wins).
        """
        budget = 0
        authority = 0
        need = 0
        timeline = 0

        for extraction in extractions:
            b = extraction.get("budget", {})
            a = extraction.get("authority", {})
            n = extraction.get("need", {})
            t = extraction.get("timeline", {})

            budget = max(budget, self._safe_score(b))
            authority = max(authority, self._safe_score(a))
            need = max(need, self._safe_score(n))
            timeline = max(timeline, self._safe_score(t))

        return BANTSubScores(
            budget=min(budget, 25),
            authority=min(authority, 25),
            need=min(need, 25),
            timeline=min(timeline, 25),
        )

    def _safe_score(self, criteria: Any) -> int:
        """Ambil score dari dict kriteria dengan aman."""
        if isinstance(criteria, dict):
            score = criteria.get("score", 0)
            if isinstance(score, (int, float)):
                return max(0, min(25, int(score)))
        return 0

    def _aggregate_tags(self, extractions: list[dict[str, Any]]) -> list[str]:
        """Kumpulkan use_case_tags unik dari semua hasil ekstraksi (max 5)."""
        all_tags: list[str] = []
        seen: set[str] = set()

        for extraction in extractions:
            tags = extraction.get("use_case_tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str) and tag.lower() not in seen:
                        seen.add(tag.lower())
                        all_tags.append(tag)

        return all_tags[:5]

    async def _update_project_scoring(
        self,
        db: AsyncSession,
        project_id: str,
        result: BANTResult,
        ai_result: Optional[dict[str, Any]] = None,
        *,
        mutable_statuses: frozenset[str] = SCORING_MUTABLE_STATUSES,
        audit: Optional[dict[str, Any]] = None,
        override_scores: Optional[BANTSubScores] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Update record proyek dengan hasil scoring BANT (guard status).

        Return (diterapkan, status efektif): status baru bila diterapkan, status saat ini
        bila di-guard, None bila proyek tidak ditemukan.
        Sub-skor di-merge ke bant_detail agar metadata legacy tidak terhapus.
        """
        stmt = select(Project).where(Project.id_project == project_id)
        query_result = await db.execute(stmt)
        project = query_result.scalar_one_or_none()

        if not project:
            logger.error(f"Project {project_id} tidak ditemukan di database.")
            return False, None

        if project.status not in mutable_statuses:
            logger.warning(
                f"Project {project_id}: hasil scoring diabaikan — "
                f"status '{project.status}' tidak boleh ditimpa."
            )
            return False, project.status

        old_detail = dict(project.bant_detail or {})
        if audit is not None:
            # Tangkap nilai lama sebelum ditimpa; audit di-commit bersama perubahan skor.
            old_value = {
                "bant_score": project.bant_score,
                "sub_scores": {k: old_detail.get(k) for k in result.sub_scores.model_dump()},
                "status": project.status,
                "override_sub_scores": self._plain_override(project),
            }
            new_value = {
                "bant_score": result.total_score,
                "sub_scores": result.sub_scores.model_dump(),
                "status": result.status,
                "override_sub_scores": (
                    override_scores.model_dump() if override_scores is not None else None
                ),
                "reason": audit["reason"],
            }
            db.add(
                AuditLog(
                    id=_generate_audit_id(),
                    entity_type="project",
                    entity_id=project_id,
                    action=audit["action"],
                    performed_by=audit["performed_by"],
                    old_value=old_value,
                    new_value=new_value,
                )
            )

        detail = dict(old_detail)
        detail.update(result.sub_scores.model_dump())
        project.bant_score = result.total_score
        project.bant_detail = detail
        project.use_case_tags = result.use_case_tags
        if ai_result is not None:
            project.ai_scoring_result = ai_result
        if override_scores is not None:
            project.override_sub_scores = override_scores.model_dump()
        project.status = result.status
        if result.status == "Pending Assignment" and project.requirement_generation_status is None:
            # Pertama kali lolos gate: tandai agar Requirement di-generate di background (#33).
            # Atomik dengan commit status; pemanggil yang menjalankan generate-nya.
            project.requirement_generation_status = "pending"
        project.updated_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            f"Project {project_id}: Updated — "
            f"bant_score={result.total_score}, status={result.status}"
        )
        return True, result.status

    async def _load_project(self, db: AsyncSession, project_id: str) -> Optional[Project]:
        """Ambil proyek (None bila tidak ditemukan)."""
        result = await db.execute(select(Project).where(Project.id_project == project_id))
        return result.scalar_one_or_none()

    def _rubric_scores(self, project: Optional[Project]) -> Optional[BANTSubScores]:
        """Hitung ulang sub-skor rubrik dari jawaban kuesioner; None bila tidak dapat dihitung."""
        if project is None or not isinstance(project.qualification_answers, dict):
            return None
        return bant_rubric.compute_rubric_scores(
            project.qualification_answers, project.target_submit
        )

    async def _refresh_project(
        self, db: AsyncSession, project_id: str, project: Optional[Project]
    ) -> Optional[Project]:
        """Segarkan state proyek dari DB (override/AI bisa berubah selama LLM berjalan)."""
        if project is None:
            return None
        try:
            await db.refresh(project)
        except Exception:  # noqa: BLE001 - segar-ulang best effort; pakai state yang ada
            logger.warning(f"Project {project_id}: gagal refresh, memakai state sebelumnya.")
        return project

    @staticmethod
    def _as_sub_scores(raw: Any) -> Optional[BANTSubScores]:
        """Validasi dict sub-skor tersimpan; None bila tidak ada/tidak valid."""
        if not isinstance(raw, dict):
            return None
        try:
            return BANTSubScores(**{k: raw[k] for k in bant_rubric.SUB_SCORE_KEYS})
        except (KeyError, TypeError, ValueError):
            logger.warning("Sub-skor tersimpan tidak valid, diabaikan.")
            return None

    def _stored_ai(self, project: Optional[Project]) -> Optional[BANTSubScores]:
        """Sub-skor AI tersimpan (`ai_scoring_result.sub_scores`)."""
        ai = getattr(project, "ai_scoring_result", None)
        return self._as_sub_scores(ai.get("sub_scores")) if isinstance(ai, dict) else None

    def _stored_override(self, project: Optional[Project]) -> Optional[BANTSubScores]:
        """Sub-skor override Lead SA tersimpan (`override_sub_scores`)."""
        return self._as_sub_scores(getattr(project, "override_sub_scores", None))

    def _plain_override(self, project: Project) -> Optional[dict[str, Any]]:
        """Override tersimpan sebagai dict polos (untuk audit log)."""
        stored = self._stored_override(project)
        return stored.model_dump() if stored is not None else None

    @staticmethod
    def _merge_max(*components: Optional[BANTSubScores]) -> BANTSubScores:
        """Skor akhir per kriteria = nilai tertinggi antar komponen (rubrik/AI/override)."""
        present = [c for c in components if c is not None]
        return BANTSubScores(
            **{k: max(getattr(c, k) for c in present) for k in bant_rubric.SUB_SCORE_KEYS}
        )

    @staticmethod
    def _build_result(sub_scores: BANTSubScores, project: Optional[Project]) -> BANTResult:
        """Bangun hasil scoring (total, status gate, feedback) dari sub-skor akhir."""
        total = bant_rubric.total_score(sub_scores)
        return BANTResult(
            total_score=total,
            sub_scores=sub_scores,
            use_case_tags=list((project.use_case_tags if project else None) or []),
            status=bant_rubric.decide_status(total),
            feedback=(
                bant_rubric.generate_feedback(sub_scores)
                if total < bant_rubric.GATE_THRESHOLD
                else None
            ),
        )

    async def _fallback_to_rubric(
        self,
        db: AsyncSession,
        project_id: str,
        project: Optional[Project],
        rubric: BANTSubScores,
    ) -> BANTResult:
        """AI tidak menghasilkan skor: gate 60 dengan max(rubrik, AI tersimpan, override)."""
        sub_scores = self._merge_max(
            rubric, self._stored_ai(project), self._stored_override(project)
        )
        return await self._apply_scoring_result(
            db, project_id, self._build_result(sub_scores, project)
        )

    async def fallback_after_failure(self, db: AsyncSession, project_id: str) -> None:
        """
        Jaring pengaman scoring background: exception di luar retry LLM (mis. error DB atau
        error tak terduga) tidak boleh membiarkan proyek menggantung di `Scoring Pending`.

        Gate memakai skor rubrik (guard status sama dengan jalur lain); bila rubrik tidak
        dapat dihitung → `Manual Review Required`.
        """
        project = await self._load_project(db, project_id)
        rubric = self._rubric_scores(project)
        if rubric is not None:
            await self._fallback_to_rubric(db, project_id, project, rubric)
        else:
            await self._mark_manual_review_required(db, project_id)

    async def _mark_manual_review_required(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> None:
        """Tandai proyek sebagai 'Manual Review Required' dan notifikasi Lead_SA."""
        stmt = select(Project).where(Project.id_project == project_id)
        result = await db.execute(stmt)
        project = result.scalar_one_or_none()

        if not project or project.status not in SCORING_MUTABLE_STATUSES:
            return

        project.status = "Manual Review Required"
        project.updated_at = datetime.now(timezone.utc)
        await db.commit()

        # Kirim notifikasi ke Lead_SA
        await self._notify_lead_sa(db, project_id, score=0, manual_review=True)

    async def notify_new_opportunity(
        self, db: AsyncSession, project_id: str, score: int
    ) -> None:
        """Notifikasi 'New Opportunity' ke Lead_SA untuk proyek yang baru lolos gate."""
        await self._notify_lead_sa(db, project_id, score)

    async def _notify_lead_sa(
        self,
        db: AsyncSession,
        project_id: str,
        score: int,
        manual_review: bool = False,
    ) -> None:
        """
        Kirim notifikasi in-app ke semua Lead_SA.
        Notification_Service belum full-implemented, jadi kita langsung INSERT ke tabel.
        """
        # Cari semua user dengan role Lead_SA
        result = await db.execute(select(User).where(User.role == "Lead_SA"))
        lead_sa_users = result.scalars().all()

        if not lead_sa_users:
            logger.warning("Tidak ada Lead_SA yang terdaftar untuk menerima notifikasi.")
            return

        for lead_sa in lead_sa_users:
            notification_id = f"notif-{uuid.uuid4().hex[:12]}"
            metadata_content = {"project_id": project_id, "bant_score": score}
            if manual_review:
                metadata_content["reason"] = "Scoring otomatis gagal, perlu review manual"

            notification = NotificationLog(
                id=notification_id,
                event_type="status_change",
                recipient_user_id=lead_sa.id,
                channel="in-app",
                status="sent",
                reference_id=project_id,
                notification_metadata=metadata_content,
                created_at=datetime.now(timezone.utc),
            )
            db.add(notification)

        await db.commit()
        logger.info(
            f"Notifikasi dikirim ke {len(lead_sa_users)} Lead_SA untuk project {project_id}"
        )


# Singleton instance
scoring_engine = ScoringEngine()
