"""
Pydantic schemas untuk DQ Number input dan document gating.
Validasi format DQ Number sesuai requirement 6.5.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Regex format DQ Number: alfanumerik + hyphen, 5-20 karakter
DQ_NUMBER_PATTERN = r"^[A-Za-z0-9\-]{5,20}$"


class DQNumberInput(BaseModel):
    """
    Schema validasi untuk input DQ Number.
    Format valid: alfanumerik dan tanda hubung, panjang 5-20 karakter.
    """

    dq_number: str = Field(
        ...,
        min_length=5,
        max_length=20,
        description="Nomor DQ (alfanumerik + hyphen, 5-20 karakter)",
    )

    @field_validator("dq_number")
    @classmethod
    def validate_dq_format(cls, v: str) -> str:
        """Validasi format DQ Number sesuai regex requirement."""
        # fullmatch: `$` pada re.match menerima newline di akhir ('ABC-1\n'), padahal CHECK DB menolaknya.
        if not re.fullmatch(DQ_NUMBER_PATTERN, v):
            raise ValueError(
                "Format DQ Number tidak valid. "
                "Hanya boleh alfanumerik dan tanda hubung, panjang 5-20 karakter."
            )
        return v


class DQNumberResponse(BaseModel):
    """Response setelah DQ Number berhasil diinput."""

    id_project: str
    project_name: str
    customer_name: str
    dq_number: str
    status: str
    message: Optional[str] = None

    class Config:
        from_attributes = True


class SolutionsDocumentResponse(BaseModel):
    """Response untuk dokumen Solutions yang bisa diakses."""

    id_doc: str
    doc_type: str
    status: str
    gdrive_link: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True
