"""
Integrasi tampilan workload Lead_SA (issue #127, Tracker-5, spec §2.5) terhadap Postgres nyata.

Empat tampilan: `/workload/beban`, `/workload/jatuh-tempo`, `/workload/macet`,
`/workload/butuh-aksi`. Semuanya hanya untuk Lead_SA atau `is_admin` (403 untuk yang lain).

Definisi "project aktif": tidak soft-deleted dan status bukan Closed, Lost, On Hold.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.project_assignment import ProjectAssignment
from app.services import workload
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_audit, bangun_log, bangun_subtask
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


BAGIAN = ["beban", "jatuh-tempo", "macet", "butuh-aksi"]


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


def _log_nonproyek(sa_id, **o):
    return bangun_log(sa_id, None, work_type="Non-Project", project_phase=None, **o)


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
        _log_nonproyek(dunia.sa.id, duration_hours=Decimal("1.00"), created_at=sekarang),
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
        _log_nonproyek(dunia.sa.id, duration_hours=Decimal("1"), created_at=senin),
        _log_nonproyek(
            dunia.sa.id, duration_hours=Decimal("10"), created_at=senin - timedelta(seconds=1)
        ),
        _log_nonproyek(dunia.sa.id, duration_hours=Decimal("2"), created_at=rabu),
        # Senin berikutnya: di luar jendela minggu berjalan
        _log_nonproyek(
            dunia.sa.id, duration_hours=Decimal("24"), created_at=senin + timedelta(days=7)
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



# --- (2) jatuh tempo ---


def _hari_ini() -> date:
    return datetime.now(UTC).date()


def _jt(resp) -> dict:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_jatuh_tempo_subtask_terlambat_dan_mendekati(dunia, api):
    hari_ini = _hari_ini()
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id, project_name="Alfa")
    kemarin = bangun_subtask(
        p.id_project, assigned_sa=dunia.sa.id, due_date=hari_ini - timedelta(days=1), title="Kemarin"
    )
    hari_h = bangun_subtask(p.id_project, due_date=hari_ini, title="HariIni", status="in_progress")
    h3 = bangun_subtask(p.id_project, due_date=hari_ini + timedelta(days=3), title="Tiga")
    h4 = bangun_subtask(p.id_project, due_date=hari_ini + timedelta(days=4), title="Empat")
    await _simpan(dunia, kemarin, hari_h, h3, h4)

    data = _jt(await _get(api, dunia, "jatuh-tempo"))

    assert data["hari_peringatan"] == 3
    judul = [s["title"] for s in data["subtask"]]
    assert judul == ["Kemarin", "HariIni", "Tiga"]  # urut due_date naik; "Empat" di luar jendela
    k, h, t = data["subtask"]
    assert (k["terlambat"], k["hari_lagi"]) == (True, -1)
    assert (h["terlambat"], h["hari_lagi"]) == (False, 0)
    assert (t["terlambat"], t["hari_lagi"]) == (False, 3)
    assert k["id_subtask"] == kemarin.id_subtask
    assert k["id_project"] == p.id_project
    assert k["project_name"] == "Alfa"
    assert k["status"] == "open"
    assert k["assigned_sa"] == str(dunia.sa.id)
    assert k["assigned_sa_name"] == dunia.sa.name
    assert h["assigned_sa"] is None
    assert h["assigned_sa_name"] is None


async def test_jatuh_tempo_subtask_selesai_atau_tanpa_due_date_tidak_muncul(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    lampau = _hari_ini() - timedelta(days=10)
    await _simpan(
        dunia,
        bangun_subtask(p.id_project, due_date=lampau, status="done"),
        bangun_subtask(p.id_project, due_date=None),
    )

    data = _jt(await _get(api, dunia, "jatuh-tempo"))

    assert data["subtask"] == []


async def test_jatuh_tempo_project_tak_aktif_dikecualikan(dunia, api):
    lampau = _hari_ini() - timedelta(days=10)
    tak_aktif = [
        await dunia.buat_proyek(status=st, assigned_sa=dunia.sa.id, target_submit=lampau)
        for st in ("On Hold", "Closed", "Lost")
    ]
    terhapus = await dunia.buat_proyek(
        status="In Progress",
        assigned_sa=dunia.sa.id,
        target_submit=lampau,
        deleted_at=datetime.now(UTC),
        deleted_by=dunia.lead.id,
    )
    await _simpan(
        dunia,
        *[bangun_subtask(p.id_project, due_date=lampau) for p in (*tak_aktif, terhapus)],
    )

    data = _jt(await _get(api, dunia, "jatuh-tempo"))

    assert data["subtask"] == []
    assert data["project"] == []


async def test_jatuh_tempo_project_target_submit(dunia, api):
    hari_ini = _hari_ini()
    kasus = {
        "Telat": ("In Progress", hari_ini - timedelta(days=2)),
        "Dekat": ("Awaiting Assignment", hari_ini + timedelta(days=3)),
        "Jauh": ("Assigned", hari_ini + timedelta(days=4)),
        # sudah diserahkan atau menang: target_submit tidak lagi relevan
        "SudahSubmit": ("Submitted", hari_ini - timedelta(days=2)),
        "SudahWon": ("Won", hari_ini - timedelta(days=2)),
    }
    for nama, (st, target) in kasus.items():
        await dunia.buat_proyek(
            status=st, project_name=nama, customer_name="CustX", target_submit=target
        )

    data = _jt(await _get(api, dunia, "jatuh-tempo"))

    assert [p["project_name"] for p in data["project"]] == ["Telat", "Dekat"]
    telat, dekat = data["project"]
    assert (telat["terlambat"], telat["hari_lagi"]) == (True, -2)
    assert (dekat["terlambat"], dekat["hari_lagi"]) == (False, 3)
    assert telat["status"] == "In Progress"
    assert telat["customer_name"] == "CustX"
    assert telat["target_submit"] == (hari_ini - timedelta(days=2)).isoformat()


# --- (3) macet ---


def _audit_status(dunia, id_project: str, status: str, umur: timedelta, **o):
    return bangun_audit(
        dunia.lead.id,
        entity_id=id_project,
        action=o.pop("action", "status_change"),
        new_value={"status": status},
        created_at=datetime.now(UTC) - umur,
        **o,
    )


def _macet(resp) -> dict:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_macet_memakai_audit_status_terakhir_yang_cocok(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id, project_name="Lama")
    await _simpan(
        dunia,
        _audit_status(dunia, p.id_project, "Assigned", timedelta(days=40)),
        _audit_status(dunia, p.id_project, "In Progress", timedelta(days=15)),
        # aksi lain yang memuat status yang sama bukan perpindahan status
        _audit_status(dunia, p.id_project, "In Progress", timedelta(days=1), action="people_change"),
    )

    data = _macet(await _get(api, dunia, "macet"))

    assert [i["project_name"] for i in data["items"]] == ["Lama"]
    item = data["items"][0]
    assert item["id_project"] == p.id_project
    assert item["status"] == "In Progress"
    assert item["hari_di_status"] == 15
    assert item["ambang_hari"] == 14
    assert item["sumber"] == "audit"
    assert item["customer_name"] == p.customer_name


async def test_macet_audit_lama_status_lain_diabaikan_bila_baru_pindah(dunia, api):
    p = await dunia.buat_proyek(status="In Progress", assigned_sa=dunia.sa.id)
    await _simpan(
        dunia,
        _audit_status(dunia, p.id_project, "Assigned", timedelta(days=40)),
        _audit_status(dunia, p.id_project, "In Progress", timedelta(days=2)),
    )

    data = _macet(await _get(api, dunia, "macet"))

    assert data["items"] == []


async def test_macet_tanpa_audit_memakai_updated_at(dunia, api):
    p = await dunia.buat_proyek(
        status="Awaiting Assignment", updated_at=datetime.now(UTC) - timedelta(days=5)
    )

    data = _macet(await _get(api, dunia, "macet"))

    item = data["items"][0]
    assert item["id_project"] == p.id_project
    assert item["sumber"] == "updated_at"
    assert item["hari_di_status"] == 5
    assert item["ambang_hari"] == 2


@pytest.mark.parametrize(
    ("status", "ambang"),
    [
        ("Intake", 3),
        ("Awaiting Assignment", 2),
        ("Assigned", 3),
        ("In Progress", 14),
        ("Submitted", 14),
        ("Won", 7),
        ("Handed Over", 14),
    ],
)
async def test_macet_ambang_per_status(dunia, api, status, ambang):
    pas = await dunia.buat_proyek(
        status=status, updated_at=datetime.now(UTC) - timedelta(days=ambang, minutes=1)
    )
    kurang = await dunia.buat_proyek(
        status=status, updated_at=datetime.now(UTC) - timedelta(days=ambang, minutes=-5)
    )

    data = _macet(await _get(api, dunia, "macet"))

    assert [i["id_project"] for i in data["items"]] == [pas.id_project]
    assert kurang.id_project not in [i["id_project"] for i in data["items"]]
    assert data["ambang_hari"][status] == ambang


async def test_macet_tak_aktif_dan_soft_deleted_dikecualikan(dunia, api):
    lama = datetime.now(UTC) - timedelta(days=365)
    for st in ("On Hold", "Closed", "Lost"):
        await dunia.buat_proyek(status=st, updated_at=lama)
    await dunia.buat_proyek(
        status="In Progress", updated_at=lama, deleted_at=datetime.now(UTC), deleted_by=dunia.lead.id
    )

    data = _macet(await _get(api, dunia, "macet"))

    assert data["items"] == []
    for st in ("On Hold", "Closed", "Lost"):
        assert st not in data["ambang_hari"]


async def test_macet_diurutkan_terlama_dulu(dunia, api):
    sekarang = datetime.now(UTC)
    a = await dunia.buat_proyek(status="Assigned", updated_at=sekarang - timedelta(days=4))
    b = await dunia.buat_proyek(status="Assigned", updated_at=sekarang - timedelta(days=9))
    c = await dunia.buat_proyek(status="In Progress", updated_at=sekarang - timedelta(days=20))

    data = _macet(await _get(api, dunia, "macet"))

    assert [i["id_project"] for i in data["items"]] == [c.id_project, b.id_project, a.id_project]


# --- (4) butuh aksi ---


def _aksi(resp) -> list[tuple[str, str]]:
    assert resp.status_code == 200, resp.text
    return [(i["jenis"], i["id_project"]) for i in resp.json()["data"]["items"]]


async def test_butuh_aksi_awaiting_assignment(dunia, api):
    p = await dunia.buat_proyek(status="Awaiting Assignment", project_name="Antri")

    resp = await _get(api, dunia, "butuh-aksi")

    assert _aksi(resp) == [("awaiting_assignment", p.id_project)]
    item = resp.json()["data"]["items"][0]
    assert item["project_name"] == "Antri"
    assert item["customer_name"] == p.customer_name
    assert item["status"] == "Awaiting Assignment"


async def test_butuh_aksi_need_clarification_hanya_pada_intake(dunia, api):
    nc = await dunia.buat_proyek(status="Intake", qualification_state="Need Clarification")
    await dunia.buat_proyek(status="Intake", qualification_state="Scoring")
    await dunia.buat_proyek(status="Intake", qualification_state="Manual Review")
    await dunia.buat_proyek(status="Awaiting Assignment", qualification_state="Qualified")
    await dunia.buat_proyek(
        status="On Hold", previous_status="Intake", qualification_state="Need Clarification"
    )

    aksi = _aksi(await _get(api, dunia, "butuh-aksi"))

    assert ("need_clarification", nc.id_project) in aksi
    assert [j for j, _ in aksi].count("need_clarification") == 1


@pytest.mark.parametrize("status", ["Assigned", "In Progress", "Submitted", "Won", "Handed Over"])
async def test_butuh_aksi_dq_kosong_setelah_titik_gate(dunia, api, status):
    kosong = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id, dq_number=None)
    await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id, dq_number="DQ-12345")

    aksi = _aksi(await _get(api, dunia, "butuh-aksi"))

    assert aksi == [("dq_kosong", kosong.id_project)]


async def test_butuh_aksi_dq_kosong_tidak_berlaku_sebelum_assigned_atau_tak_aktif(dunia, api):
    await dunia.buat_proyek(status="Intake", qualification_state="Qualified", dq_number=None)
    await dunia.buat_proyek(status="On Hold", previous_status="In Progress", dq_number=None)
    await dunia.buat_proyek(status="Closed", dq_number=None)
    await dunia.buat_proyek(status="Lost", dq_number=None)

    aksi = _aksi(await _get(api, dunia, "butuh-aksi"))

    assert aksi == []


async def test_butuh_aksi_soft_deleted_dikecualikan(dunia, api):
    hapus = {"deleted_at": datetime.now(UTC), "deleted_by": dunia.lead.id}
    await dunia.buat_proyek(status="Awaiting Assignment", **hapus)
    await dunia.buat_proyek(status="In Progress", dq_number=None, **hapus)
    await dunia.buat_proyek(status="Intake", qualification_state="Need Clarification", **hapus)

    assert _aksi(await _get(api, dunia, "butuh-aksi")) == []


async def test_butuh_aksi_campuran_diurutkan_menurut_jenis_lalu_pembuatan(dunia, api):
    sekarang = datetime.now(UTC)
    dq = await dunia.buat_proyek(
        status="In Progress", dq_number=None, created_at=sekarang - timedelta(days=3)
    )
    nc = await dunia.buat_proyek(
        status="Intake",
        qualification_state="Need Clarification",
        created_at=sekarang - timedelta(days=2),
    )
    aa_baru = await dunia.buat_proyek(
        status="Awaiting Assignment", created_at=sekarang - timedelta(days=1)
    )
    aa_lama = await dunia.buat_proyek(
        status="Awaiting Assignment", created_at=sekarang - timedelta(days=5)
    )

    aksi = _aksi(await _get(api, dunia, "butuh-aksi"))

    assert aksi == [
        ("awaiting_assignment", aa_lama.id_project),
        ("awaiting_assignment", aa_baru.id_project),
        ("dq_kosong", dq.id_project),
        ("need_clarification", nc.id_project),
    ]
