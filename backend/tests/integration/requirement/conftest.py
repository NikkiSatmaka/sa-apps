"""
Harness test integrasi siklus hidup Requirement (tiket B9, spec #49).

Dibangun di atas fixture `api` (Postgres nyata, rollback per test) dan `fake_llm` (adapter palsu
terdaftar di `llm_factory`). Beda dengan `api` polos: generate Requirement NYATA dijalankan
(background task tidak di-mock), jadi yang diuji adalah rantai lengkap trigger → LLM palsu →
baris `Document` di Postgres.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from io import BytesIO
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Document, NotificationLog, Project, SourceDocument, User
from tests.integration.conftest import KlienApi
from tests.integration.fakes.llm import FakeLLM, respons_sukses
from tests.test_projects_questionnaire_api import jawaban_kuat, jawaban_lemah

PROJECTS = "/api/v1/projects"
PDF = "application/pdf"

BUTIR_AWAL = (("Fungsional", "Login terpusat SSO"), ("Teknis", "Hosting di data center lokal"))
BUTIR_BARU = (("Integrasi", "Integrasi dengan ERP"), ("Timeline", "Go-live 3 bulan"))


def items_json(*butir: tuple[str, str]) -> str:
    """Keluaran LLM Requirement yang valid (JSON string, seperti Gemini nyata)."""
    return json.dumps({"items": [{"kategori": k, "butir": b} for k, b in butir]})


def form_proyek(jawaban: dict[str, Any], *, tipe: tuple[str, ...] = ()) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_name": "Proyek Requirement",
        "customer_name": "PT Requirement",
        "target_submit": str(date.today() + timedelta(days=30)),
        "estimasi_nilai": "500000000",
        "qualification_answers": json.dumps(jawaban),
    }
    if tipe:
        data["file_types"] = list(tipe)
    return data


def bant_json(skor: int = 20) -> str:
    kriteria = {"score": skor, "evidence": "bukti"}
    return json.dumps(
        {
            "budget": kriteria,
            "authority": kriteria,
            "need": kriteria,
            "timeline": kriteria,
            "use_case_tags": ["cloud"],
        }
    )


@dataclass
class Skenario:
    """Pembantu skenario: akses API, DB, dan fake LLM dalam satu objek."""

    api: KlienApi
    llm: FakeLLM
    db: Any
    _header: dict[str, dict[str, str]] = field(default_factory=dict)

    # ------------------------------------------------------------------ auth & data
    async def header(self, role: str) -> dict[str, str]:
        if role not in self._header:
            self._header[role] = await self.api.login_demo(role)
        return self._header[role]

    async def user(self, role: str) -> User:
        await self.header(role)
        email = {
            "Sales": "demo-sales@portal-sa.local",
            "SA": "demo-sa@portal-sa.local",
            "Lead_SA": "demo-lead@portal-sa.local",
            "Admin": "demo-admin@portal-sa.local",
            "Product": "demo-product@portal-sa.local",
        }[role]
        return (await self.db.execute(select(User).where(User.email == email))).scalar_one()

    async def req(self, metode: str, url: str, role: str | None = None, **kw: Any):
        headers = await self.header(role) if role else {}
        return await self.api.client.request(metode, url, headers=headers, **kw)

    # ------------------------------------------------------------------ proyek
    async def buat_proyek(
        self,
        jawaban: dict[str, Any] | None = None,
        *,
        files: list[tuple[str, bytes]] | None = None,
        tipe: tuple[str, ...] = (),
    ) -> str:
        """Sales membuat proyek; return id_project. Background task selesai saat respons kembali."""
        data = form_proyek(jawaban if jawaban is not None else jawaban_kuat(), tipe=tipe)
        # Pembuat Sales wajib memilih Product (ADR 0014).
        data["product_pic"] = str((await self.user("Product")).id)
        berkas = [("files", (nama, BytesIO(isi), PDF)) for nama, isi in (files or [])]
        resp = await self.req("POST", PROJECTS, "Sales", data=data, files=berkas or None)
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]["id_project"]

    async def proyek_lolos_gate(self, butir=BUTIR_AWAL) -> str:
        """Proyek lolos gate (tanpa file) dengan Requirement ready dari LLM palsu."""
        await self.header("Lead_SA")
        self.llm.sukses("complete_text", items_json(*butir))
        return await self.buat_proyek(jawaban_kuat())

    async def proyek(self, id_project: str) -> Project:
        return (
            await self.db.execute(
                select(Project)
                .where(Project.id_project == id_project)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def requirement(self, id_project: str) -> Document | None:
        return (
            await self.db.execute(
                select(Document)
                .where(Document.id_project == id_project, Document.doc_type == "Requirement")
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def jumlah_requirement(self, id_project: str) -> int:
        baris = (
            await self.db.execute(
                select(Document.id_doc).where(
                    Document.id_project == id_project, Document.doc_type == "Requirement"
                )
            )
        ).all()
        return len(baris)

    async def sumber(self, id_project: str) -> list[SourceDocument]:
        return list(
            (
                await self.db.execute(
                    select(SourceDocument)
                    .where(SourceDocument.id_project == id_project)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )

    async def notifikasi_sumber_berubah(self, id_project: str) -> list[NotificationLog]:
        baris = (
            await self.db.execute(
                select(NotificationLog)
                .where(NotificationLog.reference_id == id_project)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [
            n
            for n in baris
            if (n.notification_metadata or {}).get("requirement_source_changed") is True
        ]

    async def tetapkan(self, id_project: str, **kolom: Any) -> None:
        """Ubah kolom proyek langsung di DB (penyiapan keadaan, mis. SA ditugaskan)."""
        proyek = await self.proyek(id_project)
        for k, v in kolom.items():
            setattr(proyek, k, v)
        await self.db.flush()

    async def tugaskan_sa(self, id_project: str) -> User:
        sa = await self.user("SA")
        await self.tetapkan(id_project, assigned_sa=sa.id, status="Assigned")
        return sa

    async def pengguna_baru(self, role: str) -> tuple[User, dict[str, str]]:
        """User tambahan di DB (bukan demo) + header JWT asli untuknya."""
        from app.services.auth_service import auth_service
        from tests.integration.model_helpers import bangun_user, simpan

        user = bangun_user(role=role)
        await simpan(self.db, user)
        token = auth_service._create_token_pair(user).access_token
        return user, {"Authorization": f"Bearer {token}"}

    async def kolaborator(self, id_project: str, user: User, role: str = "viewer") -> None:
        from app.models import ProjectCollaborator
        from tests.integration.model_helpers import simpan

        penambah = await self.user("Lead_SA")
        await simpan(
            self.db,
            ProjectCollaborator(
                id_project=id_project, user_id=user.id, role=role, added_by=penambah.id
            ),
        )

    def butir_id(self, doc: Document) -> list[str]:
        return [i["id"] for i in doc.content]


@pytest_asyncio.fixture
async def skenario(
    api: KlienApi,
    fake_llm: FakeLLM,
    db_session,
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> Skenario:
    """
    Generate Requirement NYATA (tidak di-mock) terhadap fake LLM + Postgres nyata.

    Jeda retry dinolkan (tanpa waktu nyata); Gmail dimatikan (hanya notifikasi in-app).

    Penyesuaian harness: FastAPI menutup sesi request SETELAH background task selesai. Di harness
    satu-koneksi (savepoint), penutupan itu me-rollback savepoint request yang masih terbuka
    (mis. dari `refresh` pasca-commit) dan ikut membuang hasil background task yang bersarang di
    dalamnya. Di produksi tiap sesi punya koneksi sendiri sehingga ini tidak terjadi. Override
    `get_db` di bawah men-commit (melepas savepoint, tanpa menulis apa pun) bila handler sukses;
    saat handler melempar HTTPException, sesi tetap di-rollback seperti biasa.
    """
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app
    from app.services import requirement_generator, scoring_engine

    async def _get_db_req():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = _get_db_req

    monkeypatch.setattr(
        "app.api.projects.generate_pending_requirement",
        requirement_generator.generate_pending_requirement,
    )
    monkeypatch.setattr(requirement_generator, "RETRY_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(scoring_engine, "RETRY_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "")
    return Skenario(api=api, llm=fake_llm, db=db_session)


__all__ = [
    "BUTIR_AWAL",
    "BUTIR_BARU",
    "Skenario",
    "bant_json",
    "items_json",
    "jawaban_kuat",
    "jawaban_lemah",
    "respons_sukses",
    "uuid",
]
