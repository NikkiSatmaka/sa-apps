"""
Schema Pydantic untuk endpoint Document Tracking.
Digunakan untuk validasi request/response pada fitur CRUD dan state machine dokumen.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DocTypeEnum(str, Enum):
    """Tipe dokumen yang tersedia di sistem."""

    Requirement = "Requirement"
    PropTek = "PropTek"
    BOQ = "BOQ"
    Mandays = "Mandays"
    MoM = "MoM"
    RFP = "RFP"
    HLD = "HLD"


class FolderTypeEnum(str, Enum):
    """Tipe folder penyimpanan dokumen di Google Drive."""

    Inventory = "Inventory"
    Diagram = "Diagram"
    Solutions = "Solutions"


class DocStatusEnum(str, Enum):
    """Status dokumen dalam state machine."""

    Draft = "Draft"
    Reviewed = "Reviewed"
    Final = "Final"


class DocumentCreate(BaseModel):
    """Request body untuk membuat dokumen baru."""

    doc_type: DocTypeEnum = Field(
        ...,
        description="Tipe dokumen: Requirement, PropTek, BOQ, Mandays, MoM, RFP, HLD",
    )
    gdrive_link: str = Field(
        ...,
        min_length=1,
        description="Link Google Drive dokumen (wajib diisi)",
    )
    folder_type: FolderTypeEnum = Field(
        ...,
        description="Tipe folder penyimpanan: Inventory, Diagram, Solutions",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Catatan tambahan untuk dokumen (maks 500 karakter)",
    )


class DocumentStatusUpdate(BaseModel):
    """Request body untuk mengubah status dokumen."""

    new_status: DocStatusEnum = Field(
        ...,
        description="Status baru dokumen: Draft, Reviewed, Final",
    )


class DocumentResponse(BaseModel):
    """Response data lengkap dokumen."""

    id_doc: str = Field(..., description="ID dokumen unik")
    id_project: str = Field(..., description="ID proyek pemilik dokumen")
    doc_type: str = Field(..., description="Tipe dokumen")
    status: str = Field(..., description="Status dokumen saat ini")
    gdrive_link: Optional[str] = Field(
        None, description="Link Google Drive (kosong hanya untuk Requirement)"
    )
    folder_type: str = Field(..., description="Tipe folder penyimpanan")
    notes: Optional[str] = Field(None, description="Catatan tambahan")
    created_by: Optional[uuid.UUID] = Field(
        None, description="User yang membuat dokumen (kosong untuk Requirement hasil sistem)"
    )
    updated_by: Optional[uuid.UUID] = Field(None, description="User yang terakhir update")
    created_at: datetime = Field(..., description="Waktu pembuatan")
    updated_at: datetime = Field(..., description="Waktu update terakhir")
    # Khusus Requirement (konten turunan AI); default untuk dokumen jenis lain
    content: Optional[list[dict[str, Any]]] = Field(
        None, description="Daftar butir Requirement [{id, kategori, butir}]"
    )
    is_overridden: bool = Field(False, description="True bila konten diedit manual")
    source_hash: Optional[str] = Field(None, description="Hash sumber saat generate")
    generated_at: Optional[datetime] = Field(None, description="Waktu generate AI terakhir")
    source_truncated: bool = Field(False, description="True bila teks sumber terpotong")
    source_changed: bool = Field(
        False,
        description=(
            "True bila Requirement yang di-override/Final punya sumber yang sudah berubah "
            "(hash sumber saat ini berbeda dari tersimpan); UI menampilkan banner"
        ),
    )
