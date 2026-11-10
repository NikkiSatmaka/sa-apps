"""
Test migration Alembic terhadap Postgres nyata (spec #49, tiket B2).

Memakai database sementara KHUSUS per test (`database_kosong_url`) karena test ini
mengubah versi skema (downgrade). Constraint dokumen diuji di database bersama (head)
dengan rollback per test.
"""

import asyncio
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.conftest import BACKEND_DIR, jalankan_alembic


def _revisi_lama_ke_baru() -> list[str]:
    """
    Rantai revisi dari berkas migration (tanpa `import alembic`: folder `backend/alembic/`
    menimpa package alembic di sys.path test). Rantai harus linear (satu head).
    """
    induk_dari: dict[str, str | None] = {}
    for berkas in (BACKEND_DIR / "alembic" / "versions").glob("2*.py"):
        isi = berkas.read_text()
        rev = re.search(r'^revision[^=]*=\s*"([^"]+)"', isi, re.M).group(1)
        down = re.search(r'^down_revision[^=]*=\s*(None|"[^"]+")', isi, re.M).group(1)
        induk_dari[rev] = None if down == "None" else down.strip('"')
    anak_dari = {induk: rev for rev, induk in induk_dari.items()}
    assert len(anak_dari) == len(induk_dari), "rantai migration bercabang"
    urutan = [anak_dari[None]]
    while urutan[-1] in anak_dari:
        urutan.append(anak_dari[urutan[-1]])
    assert len(urutan) == len(induk_dari)
    return urutan


def _head() -> str:
    return _revisi_lama_ke_baru()[-1]


def _sql(url: str, statement: str, params: dict | None = None):
    """Jalankan satu pernyataan (commit) dan kembalikan baris hasilnya (bila ada)."""

    async def _run():
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                hasil = await conn.execute(text(statement), params or {})
                return hasil.fetchall() if hasil.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _versi(url: str) -> str | None:
    tabel = _sql(url, "SELECT to_regclass('public.alembic_version')")[0][0]
    if tabel is None:
        return None
    baris = _sql(url, "SELECT version_num FROM alembic_version")
    return baris[0][0] if baris else None


def _tabel_aplikasi(url: str) -> set[str]:
    baris = _sql(
        url,
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'",
    )
    return {b[0] for b in baris}


USER_ID = str(uuid.uuid4())


def _isi_user_dan_proyek(url: str) -> None:
    _sql(
        url,
        "INSERT INTO users (id, email, name, role, google_id) "
        "VALUES (:id, 'mig@portal-sa.local', 'Mig', 'Sales', 'g-mig')",
        {"id": USER_ID},
    )
    _sql(
        url,
        "INSERT INTO projects "
        "(id_project, project_name, customer_name, sales_pic, target_submit) "
        "VALUES ('PRJ-MIG', 'Proyek Mig', 'PT Mig', :u, '2030-01-01')",
        {"u": USER_ID},
    )


def _doc(url: str, id_doc: str, doc_type: str, link: str | None, created_by: str | None) -> None:
    _sql(
        url,
        "INSERT INTO documents "
        "(id_doc, id_project, doc_type, folder_type, gdrive_link, created_by) "
        "VALUES (:d, 'PRJ-MIG', :t, 'Solutions', :l, :c)",
        {"d": id_doc, "t": doc_type, "l": link, "c": created_by},
    )


def _ids_dokumen(url: str) -> set[str]:
    return {b[0] for b in _sql(url, "SELECT id_doc FROM documents")}


# --------------------------------------------------------------------------- upgrade / downgrade


def test_upgrade_dari_kosong_ke_head(database_kosong_url):
    assert _versi(database_kosong_url) is None
    assert _tabel_aplikasi(database_kosong_url) == set()

    jalankan_alembic(database_kosong_url, "upgrade", "head")

    assert _versi(database_kosong_url) == _head()
    assert {
        "users",
        "projects",
        "documents",
        "activity_logs",
        "audit_logs",
        "notification_logs",
        "sla_tracking",
        "project_collaborators",
        "source_documents",
        "subtasks",
    } <= _tabel_aplikasi(database_kosong_url)


def test_downgrade_bertahap_sampai_awal_lalu_upgrade_ulang(database_kosong_url):
    url = database_kosong_url
    urutan = _revisi_lama_ke_baru()
    assert len(urutan) >= 15
    jalankan_alembic(url, "upgrade", "head")

    # Turun satu langkah demi satu: versi harus mundur ke induknya tepat satu per satu.
    for indeks in range(len(urutan) - 1, -1, -1):
        assert _versi(url) == urutan[indeks]
        jalankan_alembic(url, "downgrade", "-1")
        induk = urutan[indeks - 1] if indeks > 0 else None
        assert _versi(url) == induk
        assert _tabel_aplikasi(url) == set() or indeks > 0

    assert _tabel_aplikasi(url) == set()

    jalankan_alembic(url, "upgrade", "head")
    assert _versi(url) == _head()
    assert "documents" in _tabel_aplikasi(url)


def test_upgrade_ulang_dengan_data_requirement_hasil_generate_dibuang_dokumen_lain_tetap(
    database_kosong_url,
):
    """Turun ke 013 membuang Requirement tanpa link/pembuat (tak bisa NOT NULL); naik lagi aman."""
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    _isi_user_dan_proyek(url)
    _doc(url, "DOC-HLD", "HLD", "https://drive.example/hld", USER_ID)
    _doc(url, "DOC-REQ", "Requirement", None, None)
    assert _ids_dokumen(url) == {"DOC-HLD", "DOC-REQ"}

    jalankan_alembic(url, "downgrade", "013")
    assert _versi(url) == "013"
    assert _ids_dokumen(url) == {"DOC-HLD"}

    jalankan_alembic(url, "upgrade", "head")
    assert _versi(url) == _head()
    assert _ids_dokumen(url) == {"DOC-HLD"}
    # Setelah naik lagi, Requirement tanpa link/pembuat kembali sah.
    _doc(url, "DOC-REQ-2", "Requirement", None, None)
    assert _ids_dokumen(url) == {"DOC-HLD", "DOC-REQ-2"}


def test_upgrade_dari_013_mempertahankan_requirement_lama_dengan_nilai_bawaan(database_kosong_url):
    """Requirement era 013 (link & pembuat terisi) bertahan dan dapat default kolom baru."""
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "013")
    _isi_user_dan_proyek(url)
    _doc(url, "DOC-LAMA", "Requirement", "https://drive.example/req", USER_ID)
    _doc(url, "DOC-PROPTEK", "PropTek", "https://drive.example/pt", USER_ID)

    jalankan_alembic(url, "upgrade", "head")

    baris = _sql(
        url,
        "SELECT id_doc, gdrive_link, created_by::text, content, is_overridden, source_truncated "
        "FROM documents ORDER BY id_doc",
    )
    assert [tuple(b) for b in baris] == [
        ("DOC-LAMA", "https://drive.example/req", USER_ID, None, False, False),
        ("DOC-PROPTEK", "https://drive.example/pt", USER_ID, None, False, False),
    ]
    assert _sql(url, "SELECT requirement_generation_status FROM projects")[0][0] is None


# --------------------------------------------------------------------------- constraint dokumen


async def _proyek(db, id_project: str, user_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO projects "
            "(id_project, project_name, customer_name, sales_pic, target_submit) "
            "VALUES (:p, 'P', 'C', :u, '2030-01-01')"
        ),
        {"p": id_project, "u": user_id},
    )


async def _user(db) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, name, role, google_id) VALUES (:i, :e, 'U', 'SA', :g)"),
        {"i": uid, "e": f"{uid}@portal-sa.local", "g": f"g-{uid}"},
    )
    return uid


async def _dokumen(db, id_doc, id_project, doc_type, link, created_by) -> None:
    await db.execute(
        text(
            "INSERT INTO documents "
            "(id_doc, id_project, doc_type, folder_type, gdrive_link, created_by) "
            "VALUES (:d, :p, :t, 'Solutions', :l, :c)"
        ),
        {"d": id_doc, "p": id_project, "t": doc_type, "l": link, "c": created_by},
    )


async def _ditolak(db, nama_constraint: str, **dokumen) -> None:
    """Pernyataan harus ditolak Postgres oleh `nama_constraint`; sesi tetap bisa dipakai."""
    with pytest.raises(IntegrityError) as err:
        async with db.begin_nested():
            await _dokumen(db, **dokumen)
    assert nama_constraint in str(err.value)


async def test_gdrive_link_null_ditolak_untuk_non_requirement(db_session):
    uid = await _user(db_session)
    await _proyek(db_session, "PRJ-C1", uid)
    await _ditolak(
        db_session,
        "chk_documents_gdrive_link_required",
        id_doc="D1",
        id_project="PRJ-C1",
        doc_type="HLD",
        link=None,
        created_by=uid,
    )


async def test_created_by_null_ditolak_untuk_non_requirement(db_session):
    uid = await _user(db_session)
    await _proyek(db_session, "PRJ-C2", uid)
    await _ditolak(
        db_session,
        "chk_documents_created_by_required",
        id_doc="D2",
        id_project="PRJ-C2",
        doc_type="BOQ",
        link="https://drive.example/boq",
        created_by=None,
    )


async def test_requirement_kedua_per_proyek_ditolak_tetapi_proyek_lain_boleh(db_session):
    uid = await _user(db_session)
    await _proyek(db_session, "PRJ-C3", uid)
    await _proyek(db_session, "PRJ-C4", uid)
    await _dokumen(
        db_session, "R1", "PRJ-C3", "Requirement", None, None
    )  # null sah utk Requirement

    await _ditolak(
        db_session,
        "uq_documents_requirement_per_project",
        id_doc="R2",
        id_project="PRJ-C3",
        doc_type="Requirement",
        link=None,
        created_by=None,
    )
    # Proyek lain dan dokumen non-Requirement kedua di proyek yang sama tetap sah.
    await _dokumen(db_session, "R3", "PRJ-C4", "Requirement", None, None)
    await _dokumen(db_session, "H1", "PRJ-C3", "HLD", "https://drive.example/a", uid)
    await _dokumen(db_session, "H2", "PRJ-C3", "HLD", "https://drive.example/b", uid)
    jumlah = (await db_session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    assert jumlah == 4  # R1, R3, H1, H2 (R2 ditolak)
