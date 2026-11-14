"""Perhitungan hari SLA dengan jeda On Hold (issue #122): fungsi murni `hari_berjalan`."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.sla_timer import hari_berjalan

MULAI = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _sla(**o):
    dasar = {"started_at": MULAI, "paused_at": None, "paused_total_seconds": 0}
    dasar.update(o)
    return SimpleNamespace(**dasar)


def test_tanpa_jeda_hari_penuh_sejak_mulai():
    assert hari_berjalan(_sla(), MULAI + timedelta(days=3, hours=23)) == 3


def test_sedang_dijeda_waktu_membeku_pada_paused_at():
    sla = _sla(paused_at=MULAI + timedelta(days=2))

    assert hari_berjalan(sla, MULAI + timedelta(days=30)) == 2


def test_akumulasi_jeda_selesai_dikurangkan():
    sla = _sla(paused_total_seconds=int(timedelta(days=4).total_seconds()))

    assert hari_berjalan(sla, MULAI + timedelta(days=9, hours=23)) == 5


def test_akumulasi_dan_jeda_berjalan_dihitung_bersama():
    sla = _sla(
        paused_total_seconds=int(timedelta(days=4).total_seconds()),
        paused_at=MULAI + timedelta(days=10),
    )

    assert hari_berjalan(sla, MULAI + timedelta(days=99)) == 6


def test_tidak_pernah_negatif():
    sla = _sla(paused_total_seconds=int(timedelta(days=10).total_seconds()))

    assert hari_berjalan(sla, MULAI + timedelta(days=1)) == 0
