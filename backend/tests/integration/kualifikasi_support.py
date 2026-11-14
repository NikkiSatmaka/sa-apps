"""
Helper dan fixture bersama test integrasi kualifikasi/scoring/proyek (tiket B8, #61).

Dipisah dari `conftest.py` bersama agar tiket paralel tidak bentrok. Fixture di sini harus
diimpor eksplisit oleh modul test yang memakainya.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, NotificationLog, Project, SourceDocument, User
from tests._auth_support import buat_token
from tests.integration.model_helpers import bangun_kolaborator, bangun_user, simpan
from tests.test_projects_questionnaire_api import jawaban_kuat, jawaban_lemah

URL = "/api/v1/projects"

PDF = ("pdf-bytes", "application/pdf")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def bearer(user: User) -> dict[str, str]:
    """Header Authorization untuk user yang dibuat langsung di DB."""
    return {"Authorization": f"Bearer {buat_token(user.id)}"}


def json_bant(
    budget: int = 25,
    authority: int = 25,
    need: int = 25,
    timeline: int = 25,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Keluaran ekstraksi BANT ala Gemini (kontrak `BANTExtractionResult`)."""
    return {
        "budget": {"score": budget, "evidence": "ada"},
        "authority": {"score": authority, "evidence": "ada"},
        "need": {"score": need, "evidence": "ada"},
        "timeline": {"score": timeline, "evidence": "ada"},
        "use_case_tags": tags if tags is not None else ["cloud"],
    }


def form(answers: dict | None = None, **override: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_name": "Proyek Uji",
        "customer_name": "PT Uji",
        "target_submit": str(date.today() + timedelta(days=30)),
        "estimasi_nilai": "500000000",
    }
    if answers is not None:
        data["qualification_answers"] = json.dumps(answers)
    data.update(override)
    return data


def berkas(*nama: str, mime: str = "application/pdf") -> list[tuple[str, tuple[str, bytes, str]]]:
    """Daftar `files` multipart untuk httpx."""
    return [("files", (n, b"%PDF-1.4 isi " + n.encode(), mime)) for n in nama]


@pytest_asyncio.fixture
async def api(api, session_factory):
    """
    Menimpa fixture `api` bersama untuk modul yang mengimpornya.

    Harness memakai SATU koneksi. Sesi request (`get_db`) masih memegang savepoint terbuka saat
    background task (scoring/ekstraksi) berjalan di sesi lain pada koneksi yang sama; menutup
    sesi request dengan rollback ikut membatalkan hasil background task, padahal di produksi
    keduanya memakai koneksi terpisah. Di sini sesi request di-commit saat ditutup (semua endpoint
    sudah commit eksplisit, jadi tidak ada data lain yang ikut tersimpan) agar hasil background
    task terlihat seperti di produksi.
    """
    from app.core.database import get_db
    from app.main import app

    async def _get_db_commit():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = _get_db_commit
    yield api


@pytest.fixture
def tanpa_tunggu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry scoring tanpa jeda nyata (konstanta modul di-patch, bukan sleep sungguhan)."""
    monkeypatch.setattr("app.services.scoring_engine.RETRY_INTERVAL_SECONDS", 0)


@pytest.fixture
def gen_req_scoring(api, monkeypatch: pytest.MonkeyPatch):
    """Mock generate Requirement untuk router scoring (`api` hanya mem-patch router projects)."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr("app.api.scoring.generate_pending_requirement", mock)
    return mock


async def ambil_proyek(db: AsyncSession, id_project: str) -> Project:
    """Muat ulang proyek dari DB (abaikan identity map)."""
    hasil = await db.execute(
        select(Project)
        .where(Project.id_project == id_project)
        .execution_options(populate_existing=True)
    )
    return hasil.scalar_one()


async def id_product_demo(api) -> str:
    """ID user Product demo (dibuat lewat demo login bila belum ada)."""
    headers = await api.login_demo("Product")
    return (await api.client.get("/api/v1/auth/me", headers=headers)).json()["id"]


async def buat_proyek(
    api,
    headers: dict[str, str],
    answers: dict | None = None,
    *,
    files: list | None = None,
    file_types: list[str] | None = None,
    **override: Any,
):
    """POST /projects; kembalikan respons mentah.

    Bila `product_pic` tidak diberikan, Product demo dipakai (pembuat Sales/Lead_SA/Admin wajib
    memilih Product, ADR 0014; untuk pembuat Product isian itu diabaikan backend).
    """
    if "product_pic" not in override:
        override["product_pic"] = await id_product_demo(api)
    data = form(jawaban_kuat() if answers is None else answers, **override)
    if file_types is not None:
        data["file_types"] = file_types
    return await api.client.post(URL, data=data, headers=headers, files=files or None)


async def user_baru(db: AsyncSession, role: str, **o: Any) -> User:
    user = bangun_user(role=role, **o)
    await simpan(db, user)
    return user


async def jadikan_kolaborator(
    db: AsyncSession, id_project: str, user: User, penambah: User, role: str = "contributor"
) -> None:
    await simpan(db, bangun_kolaborator(id_project, user.id, penambah.id, role=role))


async def set_status(db: AsyncSession, id_project: str, status: str, **kolom: Any) -> Project:
    """Ubah status/kolom proyek langsung di DB (menyiapkan skenario pasca-gate).

    Selain `Intake`, `qualification_state` otomatis `Qualified` (ADR 0013) kecuali diberikan.
    """
    proyek = await ambil_proyek(db, id_project)
    proyek.status = status
    if status != "Intake":
        kolom.setdefault("qualification_state", "Qualified")
    if status == "Lost":
        kolom.setdefault("lost_reason", "Alasan uji")
    for k, v in kolom.items():
        setattr(proyek, k, v)
    await db.commit()
    return proyek


async def audit_proyek(
    db: AsyncSession, id_project: str, action: str = "bant_override"
) -> list[AuditLog]:
    hasil = await db.execute(
        select(AuditLog).where(AuditLog.entity_id == id_project, AuditLog.action == action)
    )
    return list(hasil.scalars().all())


async def notif_untuk(db: AsyncSession, id_project: str) -> list[NotificationLog]:
    hasil = await db.execute(
        select(NotificationLog).where(NotificationLog.reference_id == id_project)
    )
    return list(hasil.scalars().all())


async def source_docs(db: AsyncSession, id_project: str) -> list[SourceDocument]:
    hasil = await db.execute(
        select(SourceDocument)
        .where(SourceDocument.id_project == id_project)
        .order_by(SourceDocument.filename)
        .execution_options(populate_existing=True)
    )
    return list(hasil.scalars().all())


__all__ = [
    "api",
    "URL",
    "PDF",
    "DOCX_MIME",
    "bearer",
    "json_bant",
    "form",
    "berkas",
    "tanpa_tunggu",
    "gen_req_scoring",
    "ambil_proyek",
    "buat_proyek",
    "user_baru",
    "jadikan_kolaborator",
    "set_status",
    "audit_proyek",
    "notif_untuk",
    "source_docs",
    "jawaban_kuat",
    "jawaban_lemah",
    "uuid",
]
