"""
Dunia bersama untuk test integrasi kebijakan akses proyek (spec #87, tiket #88–#92).

`skenario_akses`: satu proyek ("PRJ-AKSES-1") dengan seluruh aktor — Sales PIC, SA ditugaskan,
Lead_SA, Admin, collaborator viewer/contributor, serta pihak luar (collaborator proyek lain, Sales
dan SA tak terkait). Tiket K2–K4 memakai ulang fixture ini; jangan menggandakannya.

Proyek sengaja punya hasil BANT, `use_case_tags`, dan SLA tracker yang SUDAH LEWAT 10 hari tetapi
masih berstatus `green`: pembacaan SLA yang lolos cek akan mengubah baris itu menjadi `red`,
sehingga penolakan yang diam-diam menulis dulu terdeteksi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.models.project_collaborator import ProjectCollaborator
from tests._auth_support import buat_token
from tests.integration.model_helpers import bangun_sla, bangun_user, simpan

ID_PROYEK = "PRJ-AKSES-1"

# Keputusan pemilik produk 2026-11-10: SEMUA proyek dapat DIBACA semua pengguna terautentikasi;
# hanya akses TULIS yang dibatasi. Karena itu aktor tak terkait (collaborator proyek lain, Sales
# dan SA tak terkait) ikut membaca; `AKTOR_TIDAK_BERHAK` kini berarti "tak terkait": ditolak untuk
# aksi tulis/kelola, tetapi BUKAN untuk membaca.
AKTOR_TERKAIT = ["sales_pic", "sa", "lead", "admin", "kolab_viewer", "kolab_contrib"]
AKTOR_TIDAK_BERHAK = ["kolab_lain", "sales_luar", "sa_luar"]
AKTOR_BACA = AKTOR_TERKAIT + AKTOR_TIDAK_BERHAK


@dataclass
class SkenarioAkses:
    proyek: Project
    aktor: dict[str, User]

    def header(self, nama: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {buat_token(self.aktor[nama].id)}"}


async def _user(db: AsyncSession, role: str, nama: str) -> User:
    user = bangun_user(role=role, email=f"{nama}@akses.test", google_id=f"g-{nama}")
    await simpan(db, user)
    return user


@pytest.fixture
async def skenario_akses(db_session: AsyncSession) -> SkenarioAkses:
    db = db_session
    a = {
        "sales_pic": await _user(db, "Sales", "sales-pic"),
        "sa": await _user(db, "SA", "sa-ditugaskan"),
        "lead": await _user(db, "Lead_SA", "lead"),
        "admin": await _user(db, "Admin", "admin"),
        "kolab_viewer": await _user(db, "SA", "kolab-viewer"),
        "kolab_contrib": await _user(db, "SA", "kolab-contributor"),
        "kolab_lain": await _user(db, "SA", "kolab-proyek-lain"),
        "sales_luar": await _user(db, "Sales", "sales-luar"),
        "sa_luar": await _user(db, "SA", "sa-luar"),
    }
    proyek = Project(
        id_project=ID_PROYEK,
        project_name="Proyek Akses",
        customer_name="PT Akses",
        created_by=a["sales_pic"].id,
        product_pic=a["sales_pic"].id,
        sales_pic=a["sales_pic"].id,
        assigned_sa=a["sa"].id,
        target_submit=date.today() + timedelta(days=30),
        bant_score=80,
        bant_detail={"budget": 20, "authority": 20, "need": 20, "timeline": 20},
        use_case_tags=["etl", "dwh"],
        status="Assigned",
        qualification_state="Qualified",
    )
    lain = Project(
        id_project="PRJ-AKSES-2",
        project_name="Proyek Lain",
        customer_name="PT Lain",
        created_by=a["sales_pic"].id,
        product_pic=a["sales_pic"].id,
        sales_pic=a["sales_pic"].id,
        target_submit=date.today() + timedelta(days=30),
    )
    referensi = Project(
        id_project="PRJ-AKSES-REF",
        project_name="Referensi Won",
        customer_name="PT Referensi",
        created_by=a["sales_pic"].id,
        product_pic=a["sales_pic"].id,
        sales_pic=a["sales_pic"].id,
        target_submit=date.today() + timedelta(days=30),
        status="Won",
        qualification_state="Qualified",
        use_case_tags=["etl"],
    )
    db.add_all([proyek, lain, referensi])
    await db.flush()
    for kunci, peran, pid in (
        ("kolab_viewer", "viewer", ID_PROYEK),
        ("kolab_contrib", "contributor", ID_PROYEK),
        ("kolab_lain", "viewer", lain.id_project),
    ):
        db.add(
            ProjectCollaborator(
                id_project=pid, user_id=a[kunci].id, role=peran, added_by=a["lead"].id
            )
        )
    await simpan(
        db,
        bangun_sla(
            ID_PROYEK,
            started_at=datetime.now(timezone.utc) - timedelta(days=10),
            current_status="green",
            days_elapsed=0,
        ),
    )
    await db.commit()
    return SkenarioAkses(proyek=proyek, aktor=a)
