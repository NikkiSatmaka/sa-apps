"""
Pydantic schemas untuk BANT Scoring.
Digunakan untuk validasi input/output API scoring endpoint.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class BANTSubScores(BaseModel):
    """Detail sub-skor BANT per kriteria."""

    budget: int = Field(ge=0, le=25, description="Sub-skor Budget (0-25)")
    authority: int = Field(ge=0, le=25, description="Sub-skor Authority (0-25)")
    need: int = Field(ge=0, le=25, description="Sub-skor Need (0-25)")
    timeline: int = Field(ge=0, le=25, description="Sub-skor Timeline (0-25)")


class BANTResult(BaseModel):
    """Hasil scoring BANT — dikembalikan oleh ScoringEngine."""

    total_score: int = Field(ge=0, le=100, description="Total skor BANT (0-100)")
    sub_scores: BANTSubScores
    use_case_tags: list[str] = Field(default_factory=list, max_length=5)
    status: str = Field(description="Status proyek setelah scoring (Intake atau Awaiting Assignment)")
    qualification_state: str = Field(
        default="Scoring",
        description="Gate kualifikasi setelah scoring (Need Clarification, Manual Review, Qualified)",
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Feedback untuk Sales jika skor < 60",
    )


class BANTOverrideInput(BaseModel):
    """
    Input override skor BANT oleh Lead_SA/Admin.
    Empat sub-skor bernilai integer 0-25, alasan wajib (tidak boleh kosong).
    """

    budget: int = Field(ge=0, le=25, description="Skor Budget (0-25)")
    authority: int = Field(ge=0, le=25, description="Skor Authority (0-25)")
    need: int = Field(ge=0, le=25, description="Skor Need (0-25)")
    timeline: int = Field(ge=0, le=25, description="Skor Timeline (0-25)")
    reason: str = Field(description="Alasan override (wajib, dicatat di audit log)")

    @field_validator("reason")
    @classmethod
    def reason_tidak_kosong(cls, v: str) -> str:
        """Alasan wajib diisi; whitespace saja dianggap kosong."""
        v = v.strip()
        if not v:
            raise ValueError("Alasan override wajib diisi")
        return v


class RecommendedDocumentInfo(BaseModel):
    """Info dokumen dari proyek Won yang direkomendasikan."""

    id_doc: str
    doc_type: str = Field(description="Tipe dokumen: PropTek, BOQ, Mandays, MoM, RFP, HLD")
    gdrive_link: str = Field(description="Link Google Drive dokumen")
    status: str = Field(description="Status dokumen: Draft, Reviewed, Final")


class SimilarProjectResult(BaseModel):
    """Hasil pencarian proyek serupa (RAG recommendation)."""

    id_project: str
    project_name: str
    customer_name: str
    use_case_tags: list[str] = Field(default_factory=list)
    matching_tags: int = Field(description="Jumlah tag yang cocok")
    status: str
    documents: list[RecommendedDocumentInfo] = Field(
        default_factory=list,
        description="Daftar dokumen dari proyek Won (PropTek, BOQ, HLD, dll.)",
    )
