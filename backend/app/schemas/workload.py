"""Skema respons tampilan workload Lead_SA (issue #127, spec §2.5)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class BebanSA(BaseModel):
    """Beban satu SA/Lead_SA. Project dengan banyak SA dihitung untuk tiap SA."""

    user_id: uuid.UUID
    name: str
    email: str
    role: str
    project_aktif: int
    subtask_aktif: int
    jam_minggu_ini: float


class BebanResponse(BaseModel):
    minggu_mulai: str
    items: list[BebanSA]


class SubtaskJatuhTempo(BaseModel):
    id_subtask: str
    id_project: str
    project_name: str
    title: str
    status: str
    assigned_sa: uuid.UUID | None
    assigned_sa_name: str | None
    due_date: date
    hari_lagi: int
    terlambat: bool


class ProjectJatuhTempo(BaseModel):
    id_project: str
    project_name: str
    customer_name: str
    status: str
    target_submit: date
    hari_lagi: int
    terlambat: bool


class JatuhTempoResponse(BaseModel):
    hari_peringatan: int
    subtask: list[SubtaskJatuhTempo]
    project: list[ProjectJatuhTempo]


class ProjectMacet(BaseModel):
    id_project: str
    project_name: str
    customer_name: str
    status: str
    masuk_status_sejak: datetime
    hari_di_status: int
    ambang_hari: int
    sumber: str  # "audit" (jejak status_change) atau "updated_at" (cadangan)


class MacetResponse(BaseModel):
    ambang_hari: dict[str, int]
    items: list[ProjectMacet]
