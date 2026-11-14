"""
Akses BACA pada status SLA, hasil BANT, dan rekomendasi (tiket #88, spec #87).

Matriks peran × aksi di Postgres nyata. Keputusan pemilik produk 2026-11-10: SEMUA proyek dapat
dibaca semua pengguna terautentikasi (Lead_SA, Admin, Sales PIC, SA ditugaskan, collaborator, dan
pihak tak terkait) -> 200. Hanya akses TULIS yang dibatasi (lihat test K2-K5).
"""

import pytest
from sqlalchemy import select

from app.models import SLATracking
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.support_akses import (
    AKTOR_BACA,
    AKTOR_TIDAK_BERHAK,
    ID_PROYEK,
)

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

ENDPOINT = ["sla-status", "bant-result", "recommendations"]


def _url(aksi: str, id_proyek: str = ID_PROYEK) -> str:
    return f"/api/v1/projects/{id_proyek}/{aksi}"


@pytest.mark.parametrize("aksi", ENDPOINT)
@pytest.mark.parametrize("aktor", AKTOR_BACA)
async def test_pihak_berhak_membaca_200(api, skenario_akses, aksi, aktor):
    resp = await api.client.get(_url(aksi), headers=skenario_akses.header(aktor))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "success"


@pytest.mark.parametrize("aksi", ENDPOINT)
@pytest.mark.parametrize("aktor", AKTOR_TIDAK_BERHAK)
async def test_pihak_tak_terkait_tetap_boleh_membaca_tanpa_panggilan_luar(
    api, skenario_akses, fake_llm, fake_drive, fake_gmail, aksi, aktor
):
    """Keputusan 2026-11-10: semua proyek dapat dibaca siapa pun. Membaca tidak memicu LLM/Drive/Gmail."""
    resp = await api.client.get(_url(aksi), headers=skenario_akses.header(aktor))

    assert resp.status_code == 200, resp.text
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


async def test_sla_status_pihak_berhak_tetap_menghitung_ulang(api, skenario_akses):
    """Kontrol untuk test di atas: pembacaan sah memang mengubah tracker (10 hari → red)."""
    resp = await api.client.get(_url("sla-status"), headers=skenario_akses.header("sa"))
    assert resp.json()["data"]["status"] == "red"


@pytest.mark.parametrize("aksi", ENDPOINT)
async def test_proyek_tak_ada_404_untuk_semua_pihak(api, skenario_akses, aksi):
    resp = await api.client.get(
        _url(aksi, "PRJ-TIDAK-ADA"), headers=skenario_akses.header("sa_luar")
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("aksi", ENDPOINT)
async def test_tanpa_login_401(api, skenario_akses, aksi):
    assert (await api.client.get(_url(aksi))).status_code in (401, 403)


async def test_sla_tanpa_tracker_404_untuk_semua_pihak(api, db_session, skenario_akses):
    """Proyek ada, tracker belum ada -> 404 untuk siapa pun (membaca terbuka untuk semua)."""
    await db_session.execute(SLATracking.__table__.delete())
    await db_session.commit()

    berhak = await api.client.get(_url("sla-status"), headers=skenario_akses.header("lead"))
    luar = await api.client.get(_url("sla-status"), headers=skenario_akses.header("sa_luar"))

    assert berhak.status_code == 404
    assert luar.status_code == 404


async def test_rekomendasi_untuk_proyek_diminta_tetap_lintas_proyek(api, skenario_akses):
    """Akses dicek ke proyek yang diminta; hasil RAG tetap proyek Won lain."""
    resp = await api.client.get(
        _url("recommendations"), headers=skenario_akses.header("kolab_viewer")
    )
    ids = [r["id_project"] for r in resp.json()["data"]]
    assert "PRJ-AKSES-REF" in ids


async def test_bant_result_berisi_skor_untuk_pihak_berhak(api, skenario_akses):
    resp = await api.client.get(_url("bant-result"), headers=skenario_akses.header("sales_pic"))
    assert resp.json()["data"]["total_score"] == 80
