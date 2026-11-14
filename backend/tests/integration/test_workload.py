"""
Integrasi tampilan workload Lead_SA (issue #127, Tracker-5, spec §2.5) terhadap Postgres nyata.

Empat tampilan: `/workload/beban`, `/workload/jatuh-tempo`, `/workload/macet`,
`/workload/butuh-aksi`. Semuanya hanya untuk Lead_SA atau `is_admin` (403 untuk yang lain).

Definisi "project aktif": tidak soft-deleted dan status bukan Closed, Lost, On Hold.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.project_assignment import ProjectAssignment
from app.services import workload
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_log, bangun_subtask
from tests.integration.support_assignment import bangun_dunia

BASE = "/api/v1/workload"


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


async def _get(api, dunia, bagian: str, peran: str = "lead"):
    return await api.client.get(f"{BASE}/{bagian}", headers=dunia.h[peran])


async def _simpan(dunia, *objek):
    dunia.db.add_all(objek)
    await dunia.db.commit()


async def _tambahan(dunia, id_project: str, user):
    await _simpan(
        dunia,
        ProjectAssignment(id_project=id_project, user_id=user.id, added_by=dunia.lead.id),
    )


BAGIAN = ["beban"]


# --- akses ---


@pytest.mark.parametrize("bagian", BAGIAN)
@pytest.mark.parametrize("peran", ["sales", "produk", "sa"])
async def test_non_lead_sa_ditolak_403(dunia, api, bagian, peran):
    resp = await _get(api, dunia, bagian, peran)
    assert resp.status_code == 403


@pytest.mark.parametrize("bagian", BAGIAN)
@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_lead_sa_dan_admin_boleh(dunia, api, bagian, peran):
    resp = await _get(api, dunia, bagian, peran)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("bagian", BAGIAN)
async def test_tanpa_login_ditolak(api, bagian):
    resp = await api.client.get(f"{BASE}/{bagian}")
    assert resp.status_code in (401, 403)


# --- (1) beban ---


def _beban(resp) -> dict[str, dict]:
    return {i["name"]: i for i in resp.json()["data"]["items"]}


async def test_beban_hitung_subtask_project_dan_multi_sa(dunia, api):
    # P1: SA utama = sa. P2: SA utama = sa2, SA tambahan = sa (dihitung untuk keduanya).
    p1 = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    p2 = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa2.id)
    await _tambahan(dunia, p2.id_project, dunia.sa)
    await _simpan(
        dunia,
        bangun_subtask(p1.id_project, assigned_sa=dunia.sa.id, status="open"),
        bangun_subtask(p1.id_project, assigned_sa=dunia.sa.id, status="in_progress"),
        bangun_subtask(p1.id_project, assigned_sa=dunia.sa.id, status="done"),
        bangun_subtask(p2.id_project, assigned_sa=dunia.sa2.id, status="open"),
        bangun_subtask(p2.id_project, assigned_sa=None, status="open"),
    )

    beban = _beban(await _get(api, dunia, "beban"))

    assert beban[dunia.sa.name]["project_aktif"] == 2
    assert beban[dunia.sa.name]["subtask_aktif"] == 2
    assert beban[dunia.sa2.name]["project_aktif"] == 1
    assert beban[dunia.sa2.name]["subtask_aktif"] == 1
    assert beban[dunia.lead.name]["project_aktif"] == 0
    assert beban[dunia.lead.name]["subtask_aktif"] == 0


async def test_beban_hanya_sa_dan_lead_sa_yang_tercantum(dunia, api):
    beban = _beban(await _get(api, dunia, "beban"))
    assert dunia.sales.name not in beban
    assert dunia.produk.name not in beban
    assert {dunia.sa.name, dunia.sa2.name, dunia.lead.name} <= set(beban)


@pytest.mark.parametrize("status", ["On Hold", "Closed", "Lost"])
async def test_beban_project_tak_aktif_dikecualikan(dunia, api, status):
    p = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)
    await _tambahan(dunia, p.id_project, dunia.sa2)
    await _simpan(dunia, bangun_subtask(p.id_project, assigned_sa=dunia.sa.id, status="open"))

    beban = _beban(await _get(api, dunia, "beban"))

    for sa in (dunia.sa, dunia.sa2):
        assert beban[sa.name]["project_aktif"] == 0
        assert beban[sa.name]["subtask_aktif"] == 0


@pytest.mark.parametrize("status", ["Won", "Handed Over"])
async def test_beban_won_dan_handed_over_masih_dihitung(dunia, api, status):
    # SA masih bekerja di sana (HLD setelah Won, handover), jadi project tetap aktif.
    p = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)
    await _simpan(dunia, bangun_subtask(p.id_project, assigned_sa=dunia.sa.id, status="open"))

    beban = _beban(await _get(api, dunia, "beban"))

    assert beban[dunia.sa.name]["project_aktif"] == 1
    assert beban[dunia.sa.name]["subtask_aktif"] == 1


async def test_beban_project_soft_deleted_dikecualikan(dunia, api):
    p = await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa.id,
        deleted_at=datetime.now(UTC),
        deleted_by=dunia.lead.id,
    )
    await _tambahan(dunia, p.id_project, dunia.sa2)
    await _simpan(dunia, bangun_subtask(p.id_project, assigned_sa=dunia.sa.id, status="open"))

    beban = _beban(await _get(api, dunia, "beban"))

    assert beban[dunia.sa.name]["project_aktif"] == 0
    assert beban[dunia.sa.name]["subtask_aktif"] == 0
    assert beban[dunia.sa2.name]["project_aktif"] == 0


async def test_beban_project_dihitung_sekali_walau_sa_utama_dan_tambahan_sekaligus(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    await _tambahan(dunia, p.id_project, dunia.sa)

    beban = _beban(await _get(api, dunia, "beban"))

    assert beban[dunia.sa.name]["project_aktif"] == 1


async def test_beban_jam_terlog_minggu_ini(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    sekarang = datetime.now(UTC)
    await _simpan(
        dunia,
        bangun_log(dunia.sa.id, p.id_project, duration_hours=Decimal("2.50"), created_at=sekarang),
        bangun_log(dunia.sa.id, None, duration_hours=Decimal("1.00"), created_at=sekarang),
        # minggu lalu: tidak dihitung
        bangun_log(
            dunia.sa.id,
            p.id_project,
            duration_hours=Decimal("8.00"),
            created_at=sekarang - timedelta(days=8),
        ),
        bangun_log(dunia.sa2.id, p.id_project, duration_hours=Decimal("4.00"), created_at=sekarang),
    )

    beban = _beban(await _get(api, dunia, "beban"))

    assert beban[dunia.sa.name]["jam_minggu_ini"] == 3.5
    assert beban[dunia.sa2.name]["jam_minggu_ini"] == 4.0
    assert beban[dunia.lead.name]["jam_minggu_ini"] == 0


async def test_beban_batas_minggu_senin_00_00_utc(dunia):
    # Rabu 2030-01-09; Senin minggu itu 2030-01-07 00:00 UTC.
    rabu = datetime(2030, 1, 9, 10, 0, tzinfo=UTC)
    senin = datetime(2030, 1, 7, 0, 0, tzinfo=UTC)
    await _simpan(
        dunia,
        bangun_log(dunia.sa.id, None, duration_hours=Decimal("1"), created_at=senin),
        bangun_log(
            dunia.sa.id,
            None,
            duration_hours=Decimal("10"),
            created_at=senin - timedelta(seconds=1),
        ),
        bangun_log(dunia.sa.id, None, duration_hours=Decimal("2"), created_at=rabu),
        # sesudah "sekarang" (tidak mungkin di produksi) tetap di luar jendela minggu berjalan
        bangun_log(
            dunia.sa.id,
            None,
            duration_hours=Decimal("100"),
            created_at=senin + timedelta(days=7),
        ),
    )

    hasil = await workload.hitung_beban(dunia.db, rabu)

    assert {b.name: b for b in hasil}[dunia.sa.name].jam_minggu_ini == 3.0


def test_awal_minggu_adalah_senin_utc():
    assert workload.awal_minggu(datetime(2030, 1, 13, 23, 59, tzinfo=UTC)) == datetime(
        2030, 1, 7, tzinfo=UTC
    )
    assert workload.awal_minggu(datetime(2030, 1, 7, 0, 0, tzinfo=UTC)) == datetime(
        2030, 1, 7, tzinfo=UTC
    )

