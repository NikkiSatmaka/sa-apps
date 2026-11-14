"""Skema respons tampilan workload Lead_SA (issue #127, spec §2.5)."""

import uuid

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
