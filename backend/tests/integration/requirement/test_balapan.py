"""
Balapan sungguhan pada Requirement (tiket B9, spec #49): beberapa koneksi Postgres nyata yang
benar-benar commit (BUKAN harness rollback satu-koneksi), karena yang diuji justru lock baris,
unique index, dan UPDATE bersyarat. Database sementara dibuat/dihapus per test.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Document, Project
from app.services import requirement_generator as rg
from tests.integration.conftest import ServerUji, patch_session_factory
from tests.integration.fakes.llm import FakeLLM
from tests.integration.model_helpers import bangun_project, bangun_user, simpan
from tests.integration.requirement.conftest import BUTIR_AWAL, items_json, jawaban_kuat


@pytest.fixture
def url_db_nyata(server_uji: ServerUji) -> Iterator[str]:
    """Database sementara TERMIGRASI (sinkron, karena membuat DB memakai asyncio.run)."""
    url = server_uji.buat_database(migrasi=True)
    try:
        yield url
    finally:
        server_uji.hapus_database(make_url(url).database)


@dataclass
class Nyata:
    factory: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    id_project: str
    header_lead: dict[str, str]
    llm: FakeLLM

    async def baca(self, pernyataan):
        async with self.factory() as db:
            return (await db.execute(pernyataan)).scalars().all()

    async def status(self) -> str | None:
        async with self.factory() as db:
            return (
                await db.execute(
                    select(Project.requirement_generation_status).where(
                        Project.id_project == self.id_project
                    )
                )
            ).scalar_one()

    async def jumlah_requirement(self) -> int:
        async with self.factory() as db:
            return (
                await db.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        Document.id_project == self.id_project, Document.doc_type == "Requirement"
                    )
                )
            ).scalar_one()


@pytest_asyncio.fixture
async def nyata(
    url_db_nyata: str, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Nyata]:
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app
    from app.services.auth_service import auth_service

    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "")
    monkeypatch.setattr(rg, "RETRY_INTERVAL_SECONDS", 0)
    engine = create_async_engine(url_db_nyata, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    patch_session_factory(monkeypatch, factory)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    async with factory() as db:
        sales, lead = bangun_user(role="Sales"), bangun_user(role="Lead_SA")
        await simpan(db, sales, lead)
        proyek = bangun_project(
            sales.id,
            status="Pending Assignment",
            qualification_answers=jawaban_kuat(),
            requirement_generation_status="pending",
        )
        await simpan(db, proyek)
        await db.commit()
        id_project = proyek.id_project
        token = auth_service._create_token_pair(lead).access_token
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield Nyata(
                factory=factory,
                client=client,
                id_project=id_project,
                header_lead={"Authorization": f"Bearer {token}"},
                llm=fake_llm,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


async def test_dua_trigger_bersamaan_di_satu_proses_hanya_satu_generate(nyata):
    nyata.llm.sukses("complete_text", items_json(*BUTIR_AWAL))

    await asyncio.gather(
        rg.generate_pending_requirement(nyata.id_project),
        rg.generate_pending_requirement(nyata.id_project),
        rg.generate_pending_requirement(nyata.id_project),
    )

    assert nyata.llm.jumlah("complete_text") == 1
    assert await nyata.jumlah_requirement() == 1
    assert await nyata.status() == "ready"


async def test_balapan_lintas_proses_unique_index_menyisakan_satu_baris_dan_status_ready(
    nyata, monkeypatch
):
    """
    Meniru dua proses (tanpa lock asyncio): keduanya melihat `pending` dan belum ada Requirement,
    keduanya memanggil LLM, lalu keduanya mencoba INSERT. Unique index menolak yang kedua dan
    penanganan IntegrityError harus menganggapnya `ready`, bukan `failed`.
    """
    nyata.llm.sukses("complete_text", items_json(*BUTIR_AWAL), tetap=True)

    @contextlib.asynccontextmanager
    async def tanpa_lock(_project_id):
        yield

    monkeypatch.setattr(rg, "_project_lock", tanpa_lock)
    pagar = asyncio.Barrier(2)
    asli = rg._summarize

    async def tunggu_rekan(*args, **kwargs):
        hasil = await asli(*args, **kwargs)
        await asyncio.wait_for(pagar.wait(), timeout=10)  # pastikan keduanya lolos cek "belum ada"
        return hasil

    monkeypatch.setattr(rg, "_summarize", tunggu_rekan)

    await asyncio.gather(
        rg.generate_pending_requirement(nyata.id_project),
        rg.generate_pending_requirement(nyata.id_project),
    )

    assert nyata.llm.jumlah("complete_text") == 2  # kedua "proses" benar-benar berbalapan
    assert await nyata.jumlah_requirement() == 1
    assert await nyata.status() == "ready"


async def test_dua_generate_ulang_bersamaan_satu_202_satu_409_dan_llm_sekali(nyata, monkeypatch):
    nyata.llm.sukses("complete_text", items_json(*BUTIR_AWAL), tetap=True)
    await rg.generate_pending_requirement(nyata.id_project)  # keadaan awal: ready
    assert await nyata.status() == "ready"
    assert nyata.llm.jumlah("complete_text") == 1

    gerbang = asyncio.Event()
    asli = rg._summarize

    async def tahan(*args, **kwargs):
        await asyncio.wait_for(gerbang.wait(), timeout=10)  # tahan generate pemenang di background
        return await asli(*args, **kwargs)

    monkeypatch.setattr(rg, "_summarize", tahan)
    url = f"/api/v1/projects/{nyata.id_project}/requirement/regenerate"
    tugas = [
        asyncio.create_task(nyata.client.post(url, headers=nyata.header_lead)) for _ in range(2)
    ]

    selesai, tersisa = await asyncio.wait(tugas, timeout=10, return_when=asyncio.FIRST_COMPLETED)
    # Yang kalah selesai lebih dulu (409) selagi pemenang masih menunggu gerbang.
    assert [t.result().status_code for t in selesai] == [409]
    gerbang.set()
    hasil_pemenang = await asyncio.gather(*tersisa)

    assert [r.status_code for r in hasil_pemenang] == [202]
    assert nyata.llm.jumlah("complete_text") == 2  # 1 awal + 1 generate ulang (bukan 3)
    assert await nyata.status() == "ready"
    assert await nyata.jumlah_requirement() == 1


async def test_generate_ulang_saat_pending_ditolak_dan_tidak_menimpa_status(nyata):
    async with nyata.factory() as db:
        proyek = (
            await db.execute(select(Project).where(Project.id_project == nyata.id_project))
        ).scalar_one()
        proyek.requirement_generation_status = "pending"
        await db.commit()

    resp = await nyata.client.post(
        f"/api/v1/projects/{nyata.id_project}/requirement/regenerate", headers=nyata.header_lead
    )

    assert resp.status_code == 409
    assert await nyata.status() == "pending"
    assert nyata.llm.jumlah() == 0


async def test_proyek_hilang_di_tengah_generate_tidak_melempar_dan_tidak_menyisakan_dokumen(
    nyata, monkeypatch
):
    """Proyek dihapus saat LLM berjalan: INSERT Document melanggar FK → ditangani tanpa crash."""
    nyata.llm.sukses("complete_text", items_json(*BUTIR_AWAL))
    asli = rg._summarize

    async def hapus_proyek_setelah_llm(*args, **kwargs):
        hasil = await asli(*args, **kwargs)
        async with nyata.factory() as db:
            proyek = (
                await db.execute(select(Project).where(Project.id_project == nyata.id_project))
            ).scalar_one()
            await db.delete(proyek)
            await db.commit()
        return hasil

    monkeypatch.setattr(rg, "_summarize", hapus_proyek_setelah_llm)

    await rg.generate_pending_requirement(nyata.id_project)  # tidak boleh melempar

    assert await nyata.jumlah_requirement() == 0
    assert await nyata.baca(select(Project).where(Project.id_project == nyata.id_project)) == []
