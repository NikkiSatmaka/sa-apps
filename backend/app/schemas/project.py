"""
Pydantic schemas untuk Project submission dan response.
Validasi input form request pre-sales sesuai requirement 2.1.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
    status: str = Field(default="New", description="Status awal proyek")
    sales_pic: UUID = Field(..., description="ID requester yang membuat request (Sales/SA/Lead_SA)")
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
