"""
Cabang defensif `SLATimer` yang tidak bisa dicapai lewat Postgres karena FK (tiket B5 #58):
user Sales sudah tidak ada saat lock/unlock. Dicek lewat sesi terprogram; yang ditegaskan adalah
hasil (False, Drive tidak disentuh), bukan urutan query.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sla_timer import SLATimer


def _sesi(*hasil_query):
    def _hasil(obj):
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        return r

    sesi = AsyncMock()
    sesi.execute.side_effect = [_hasil(o) for o in hasil_query]
    return sesi


def _proyek(solutions="sol-1"):
    p = MagicMock()
    p.id_project = "PRJ-1"
    p.sales_pic = uuid.uuid4()
    p.gdrive_solutions_folder_id = solutions
    return p


async def test_lock_dilewati_bila_user_sales_tidak_ditemukan():
    sla = MagicMock(is_locked=False)
    with patch("app.services.sla_timer.folder_provisioner.lock_solutions_folder") as kunci:
        hasil = await SLATimer()._lock_solutions_with_retry(_proyek(), sla, _sesi(None))

    assert hasil is False
    kunci.assert_not_called()
    assert sla.is_locked is False


async def test_unlock_dilewati_bila_user_sales_tidak_ditemukan():
    proyek = _proyek()
    sla = MagicMock()
    with patch("app.services.sla_timer.folder_provisioner.unlock_solutions_folder") as buka:
        hasil = await SLATimer()._unlock_solutions_with_retry("PRJ-1", sla, _sesi(proyek, None))

    assert hasil is False
    buka.assert_not_called()


@pytest.mark.parametrize("solutions", [None, ""])
async def test_lock_dilewati_bila_folder_solutions_belum_tercatat(solutions):
    sla = MagicMock(is_locked=False)
    sesi = _sesi()

    hasil = await SLATimer()._lock_solutions_with_retry(_proyek(solutions), sla, sesi)

    assert hasil is False and sla.is_locked is False
    sesi.execute.assert_not_called()
