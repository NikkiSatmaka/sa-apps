"""
Pydantic schemas untuk Project submission dan response.
Validasi input form request pre-sales sesuai requirement 2.1.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.integration_operation import IntegrationOperationResponse


class ProjectCreate(BaseModel):
    """
    Schema validasi untuk pembuatan proyek baru.
    Digunakan sebagai form data (bukan JSON body) karena endpoint menerima file upload.

    Validasi sesuai requirement 2.1:
    - project_name: max 150 karakter, wajib
    - customer_name: max 150 karakter, wajib
    - target_submit: tidak boleh tanggal di masa lalu
    - estimasi_nilai: rentang 0.01 - 999,999,999,999.00
    """

    project_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Nama proyek (wajib, maksimal 150 karakter)",
    )
    customer_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Nama customer/perusahaan (wajib, maksimal 150 karakter)",
    )
    target_submit: date = Field(
        ...,
        description="Target tanggal submit proposal (tidak boleh masa lalu)",
    )
    estimasi_nilai: Decimal = Field(
        ...,
        ge=Decimal("0.01"),
        le=Decimal("999999999999.00"),
        description="Estimasi nilai proyek dalam IDR (0.01 - 999,999,999,999.00)",
    )

    @field_validator("target_submit")
    @classmethod
    def target_submit_not_in_past(cls, v: date) -> date:
        """Validasi target_submit tidak boleh tanggal di masa lalu."""
        if v < date.today():
            raise ValueError("Target submit tidak boleh tanggal di masa lalu")
        return v

    @field_validator("project_name", "customer_name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Trim whitespace di awal/akhir; nama yang hanya berisi spasi dianggap kosong."""
        v = v.strip()
        if not v:
            raise ValueError("Tidak boleh kosong atau hanya spasi")
        return v


class FileUploadResult(BaseModel):
    """
    Hasil upload per file — menandakan sukses atau gagal.
    Digunakan untuk partial failure reporting (requirement 2.6).
    """

    filename: str = Field(..., description="Nama file original")
    success: bool = Field(..., description="True jika upload berhasil")
    error: Optional[str] = Field(None, description="Pesan error jika gagal")
    size_bytes: Optional[int] = Field(None, description="Ukuran file dalam bytes")


class OrangProyek(BaseModel):
    """Ringkasan satu orang pada project (id + nama + email)."""

    id: UUID
    name: Optional[str] = None
    email: Optional[str] = None



class ProjectListPersonResponse(BaseModel):
    """Ringkasan orang yang disertakan dalam item daftar proyek."""

    id: str
    name: Optional[str] = None
    email: Optional[str] = None


class ProjectListItemResponse(BaseModel):
    """Satu item daftar proyek yang telah dipaginasi."""

    id_project: str
    project_name: str
    customer_name: str
    status: str
    qualification_state: Optional[str] = None
    dq_number: Optional[str] = None
    bant_score: Optional[int] = None
    use_case_tags: list[str]
    estimasi_nilai: Optional[str] = None
    target_submit: Optional[str] = None
    assigned_sa: Optional[str] = None
    created_by: Optional[ProjectListPersonResponse] = None
    product_pic: Optional[ProjectListPersonResponse] = None
    sales_pic: Optional[ProjectListPersonResponse] = None
    gdrive_folder_id: Optional[str] = None
    folder_provisioning_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProjectListPageResponse(BaseModel):
    """Paginated page returned by GET /projects."""

    items: list[ProjectListItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProjectDetailResponse(BaseModel):
    """Detail payload returned by GET /projects/{project_id}."""

    id_project: str
    project_name: str
    customer_name: str
    status: str
    qualification_state: Optional[str] = None
    previous_status: Optional[str] = None
    lost_reason: Optional[str] = None
    dq_number: Optional[str] = None
    bant_score: Optional[int] = None
    bant_detail: Optional[dict[str, Any]] = None
    qualification: Optional[dict[str, Any]] = None
    use_case_tags: list[str] = Field(default_factory=list)
    estimasi_nilai: Optional[str] = None
    target_submit: Optional[str] = None
    created_by: Optional[ProjectListPersonResponse] = None
    product_pic: Optional[ProjectListPersonResponse] = None
    sales_pic: Optional[ProjectListPersonResponse] = None
    lead_sa: Optional[ProjectListPersonResponse] = None
    assigned_sa: Optional[ProjectListPersonResponse] = None
    collaborators: list[dict[str, Any]] = Field(default_factory=list)
    source_documents: list[dict[str, Any]] = Field(default_factory=list)
    folder_provisioning_status: Optional[str] = None
    folder_provisioning_operation: Optional[dict[str, Any]] = None
    integration_operations: list[IntegrationOperationResponse] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ProjectResponse(BaseModel):
    """
    Schema response data proyek yang baru dibuat.
    Mengikuti format standar: dikembalikan dalam field 'data' dari StandardResponse.
    """

    id_project: str = Field(..., description="ID unik proyek")
    project_name: str
    customer_name: str
    target_submit: date
    estimasi_nilai: Decimal
    status: str = Field(default="Intake", description="Status awal proyek")
    qualification_state: str = Field(
        default="Scoring", description="Gate kualifikasi awal (Scoring, Need Clarification, Qualified)"
    )
    created_by: OrangProyek = Field(..., description="Pembuat project")
    product_pic: OrangProyek = Field(..., description="Product penanggung jawab (selalu ada)")
    sales_pic: Optional[OrangProyek] = Field(
        None, description="Sales PIC (opsional; project boleh tanpa Sales)"
    )
    created_at: datetime
    files: list[FileUploadResult] = Field(
        default_factory=list,
        description="Hasil upload per file",
    )
    scoring_triggered: bool = Field(
        default=False,
        description="True jika scoring engine di-trigger",
    )
    bant_score: Optional[int] = Field(
        None,
        description="Skor BANT hasil rubrik backend (None bila menunggu analisis file)",
    )
    sub_scores: Optional[dict[str, int]] = Field(
        None, description="Sub-skor BANT per kriteria (budget/authority/need/timeline)"
    )
    feedback: Optional[str] = Field(
        None, description="Penjelasan kriteria lemah bila skor di bawah threshold"
    )

    class Config:
        from_attributes = True
