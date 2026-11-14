"""
Migration 021 (issue #122): kolom jeda SLA pada `sla_tracking` (`paused_at`,
`paused_total_seconds`) untuk status `On Hold`.

Memakai database sementara per test (`database_kosong_url`). Yang diuji: upgrade mempertahankan
baris lama (tidak sedang jeda, akumulasi 0), downgrade membuang kolom, dan constraint pada head.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _revisi_lama_ke_baru, _sql, _versi
from tests.integration.test_migration_020_status import _proyek, _user

REVISI_BARU = "021"
REVISI_LAMA = "020"
MULAI = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _kolom(url: str) -> set[str]:
    baris = _sql(
        url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'sla_tracking'",
    )
    return {b[0] for b in baris}


def _sla(url: str, id_project: str, **kolom) -> None:
    nama = ["id", "project_id", "started_at", *kolom]
    nilai = {"id": f"SLA-{id_project}", "project_id": id_project, "started_at": MULAI, **kolom}
    _sql(
        url,
        f"INSERT INTO sla_tracking ({', '.join(nama)}) VALUES ({', '.join(f':{n}' for n in nama)})",
        nilai,
    )


def test_revisi_021_ada_di_rantai_dan_head_mengikutinya(database_kosong_url):
    """Head bergeser seiring revisi baru; yang dijaga: 021 tetap dalam rantai tepat setelah 020."""
    jalankan_alembic(database_kosong_url, "upgrade", "head")

    urutan = _revisi_lama_ke_baru()
    assert urutan[urutan.index(REVISI_BARU) - 1] == REVISI_LAMA
    assert _versi(database_kosong_url) == _head() == urutan[-1]


def test_upgrade_mempertahankan_baris_lama_tanpa_jeda(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    _proyek(url, _user(url), "PRJ-SLA", "Assigned")
    _sla(url, "PRJ-SLA")

    jalankan_alembic(url, "upgrade", "head")

    assert _sql(
        url, "SELECT paused_at, paused_total_seconds FROM sla_tracking WHERE project_id = 'PRJ-SLA'"
    ) == [(None, 0)]


def test_downgrade_membuang_kolom_jeda(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    assert {"paused_at", "paused_total_seconds"} <= _kolom(url)

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _versi(url) == REVISI_LAMA
    assert not {"paused_at", "paused_total_seconds"} & _kolom(url)


def test_upgrade_ulang_setelah_downgrade(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    jalankan_alembic(url, "upgrade", "head")

    assert _versi(url) == _head()


def test_head_akumulasi_jeda_tidak_boleh_negatif(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    _proyek(url, _user(url), "PRJ-NEG", "Assigned")

    with pytest.raises(DBAPIError, match="chk_sla_tracking_paused_total_seconds"):
        _sla(url, "PRJ-NEG", paused_total_seconds=-1)


def test_head_akumulasi_jeda_default_nol_dan_paused_at_boleh_kosong(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    _proyek(url, _user(url), "PRJ-DEF", "Assigned")

    _sla(url, "PRJ-DEF")

    assert _sql(
        url, "SELECT paused_at, paused_total_seconds FROM sla_tracking WHERE project_id = 'PRJ-DEF'"
    ) == [(None, 0)]


def test_head_akumulasi_jeda_tidak_boleh_null(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    _proyek(url, _user(url), "PRJ-NUL", "Assigned")

    with pytest.raises(DBAPIError, match="not-null"):
        _sla(url, "PRJ-NUL", paused_total_seconds=None)
