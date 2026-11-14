"""
Migration 023 (issue #125): tabel `project_comments` dan event notifikasi `komentar`.

Memakai database sementara per test (`database_kosong_url`). Yang diuji: revisi menyambung ke 022,
upgrade membuat tabel + constraint, downgrade membuangnya (dan CHECK event_type kembali ke daftar
lama), upgrade ulang, kunci asing, CHECK `body` tidak kosong, dan cascade saat proyek dihapus.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _revisi_lama_ke_baru, _sql, _versi
from tests.integration.test_migration_020_status import _proyek, _user

REVISI_BARU = "023"
REVISI_LAMA = "022"
SEKARANG = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _ada_tabel(url: str) -> bool:
    return bool(_sql(url, "SELECT 1 FROM information_schema.tables WHERE table_name = 'project_comments'"))


def _constraint(url: str) -> set[str]:
    baris = _sql(url, "SELECT conname FROM pg_constraint WHERE conrelid = 'project_comments'::regclass")
    return {b[0] for b in baris}


def _komentar(url: str, id_project: str, author: str, id_comment: str = "CMT-1", **kolom) -> None:
    nilai = {
        "id_comment": id_comment,
        "id_project": id_project,
        "author_id": author,
        "body": "Halo",
        "created_at": SEKARANG,
        **kolom,
    }
    nama = list(nilai)
    _sql(
        url,
        f"INSERT INTO project_comments ({', '.join(nama)}) "
        f"VALUES ({', '.join(f':{n}' for n in nama)})",
        nilai,
    )


def _notifikasi(url: str, user: str, event_type: str) -> None:
    _sql(
        url,
        "INSERT INTO notification_logs (id, event_type, recipient_user_id, channel, status, "
        "created_at) VALUES (:id, :e, :u, 'in-app', 'sent', :t)",
        {"id": f"N-{uuid.uuid4().hex[:8]}", "e": event_type, "u": user, "t": SEKARANG},
    )


def _siapkan_head(url: str) -> tuple[str, str]:
    jalankan_alembic(url, "upgrade", "head")
    user = _user(url)
    return _proyek(url, user, "PRJ-CMT", "Assigned"), user


def test_revisi_023_adalah_head_dan_menyambung_ke_022(database_kosong_url):
    jalankan_alembic(database_kosong_url, "upgrade", "head")

    urutan = _revisi_lama_ke_baru()
    assert urutan[-1] == REVISI_BARU
    assert urutan[urutan.index(REVISI_BARU) - 1] == REVISI_LAMA
    assert _versi(database_kosong_url) == _head() == REVISI_BARU


def test_upgrade_membuat_tabel_dan_constraint(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    assert not _ada_tabel(url)

    jalankan_alembic(url, "upgrade", "head")

    assert _ada_tabel(url)
    assert {"chk_project_comments_body"} <= _constraint(url)


def test_downgrade_membuang_tabel(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _versi(url) == REVISI_LAMA
    assert not _ada_tabel(url)


def test_downgrade_membuang_notifikasi_komentar_dan_mengembalikan_check(database_kosong_url):
    url = database_kosong_url
    proyek, user = _siapkan_head(url)
    _notifikasi(url, user, "komentar")
    _notifikasi(url, user, "assignment")

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _sql(url, "SELECT event_type FROM notification_logs") == [("assignment",)]
    with pytest.raises(DBAPIError, match="chk_notification_logs_event_type"):
        _notifikasi(url, user, "komentar")


def test_upgrade_ulang_setelah_downgrade(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == REVISI_BARU
    assert _ada_tabel(url)


def test_head_menyimpan_komentar_apa_adanya(database_kosong_url):
    url = database_kosong_url
    proyek, user = _siapkan_head(url)

    _komentar(url, proyek, user, body="Mohon cek BOQ")

    assert _sql(url, "SELECT id_comment, id_project, author_id::text, body FROM project_comments") == [
        ("CMT-1", proyek, user, "Mohon cek BOQ")
    ]


def test_head_event_notifikasi_komentar_diterima(database_kosong_url):
    url = database_kosong_url
    _, user = _siapkan_head(url)

    _notifikasi(url, user, "komentar")

    assert _sql(url, "SELECT event_type FROM notification_logs") == [("komentar",)]


@pytest.mark.parametrize("body", ["", "   ", "\n\t"])
def test_head_body_kosong_atau_spasi_ditolak(database_kosong_url, body):
    url = database_kosong_url
    proyek, user = _siapkan_head(url)

    with pytest.raises(DBAPIError, match="chk_project_comments_body"):
        _komentar(url, proyek, user, body=body)


def test_head_proyek_tidak_ada_ditolak_fk(database_kosong_url):
    url = database_kosong_url
    _, user = _siapkan_head(url)

    with pytest.raises(DBAPIError, match="foreign key"):
        _komentar(url, "PRJ-GAIB", user)


def test_head_penulis_tidak_ada_ditolak_fk(database_kosong_url):
    url = database_kosong_url
    proyek, _ = _siapkan_head(url)

    with pytest.raises(DBAPIError, match="foreign key"):
        _komentar(url, proyek, str(uuid.uuid4()))


def test_head_hapus_proyek_menghapus_komentarnya(database_kosong_url):
    url = database_kosong_url
    proyek, user = _siapkan_head(url)
    _komentar(url, proyek, user)

    _sql(url, "DELETE FROM projects WHERE id_project = :p", {"p": proyek})

    assert _sql(url, "SELECT count(*) FROM project_comments") == [(0,)]
