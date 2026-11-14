"""
Integrasi endpoint pelaporan modul assignment terhadap Postgres nyata (tiket B5 #58, spec #49):
daftar proyek menunggu assignment, ketersediaan/workload SA, dan tiga laporan utilisasi.
Hak akses per peran ditegakkan di semua endpoint (hanya Lead_SA/Admin).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_log
from tests.integration.support_assignment import bangun_dunia

PENDING = "/api/v1/projects/pending-assignment"
TERSEDIA = "/api/v1/sa/available"
UTIL_SA = "/api/v1/sa/utilization"
UTIL_PROYEK = "/api/v1/utilization/projects"
UTIL_RINGKAS = "/api/v1/utilization/summary"
SEMUA_URL = [PENDING, TERSEDIA, UTIL_SA, UTIL_PROYEK, UTIL_RINGKAS]


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


def _waktu(tahun: int, bulan: int) -> datetime:
    return datetime(tahun, bulan, 15, 9, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- hak akses


@pytest.mark.parametrize("url", SEMUA_URL)
@pytest.mark.parametrize(
    ("peran", "diizinkan"),
    [("lead", True), ("admin", True), ("sa", False), ("sales", False)],
)
async def test_endpoint_pelaporan_hanya_lead_sa_dan_admin(dunia, api, url, peran, diizinkan):
    resp = await api.client.get(url, headers=dunia.h[peran])

    assert resp.status_code == (200 if diizinkan else 403), resp.text


@pytest.mark.parametrize("url", SEMUA_URL)
async def test_endpoint_pelaporan_tanpa_login_ditolak(api, url):
    resp = await api.client.get(url)

    assert resp.status_code in (401, 403)


# ----------------------------------------------------------------------------- pending & workload


async def test_pending_assignment_hanya_proyek_pending_terbaru_dulu(dunia, api):
    lama = await dunia.buat_proyek(project_name="Lama", bant_score=70)
    baru = await dunia.buat_proyek(project_name="Baru", bant_score=90)
    await dunia.buat_proyek(project_name="Sudah", status="Assigned", assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(project_name="Butuh Klarifikasi", status="Intake", qualification_state="Need Clarification")

    resp = await api.client.get(PENDING, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [p["project_name"] for p in data] == ["Baru", "Lama"]
    assert [p["id_project"] for p in data] == [baru.id_project, lama.id_project]
    assert data[0]["bant_score"] == 90 and data[0]["status"] == "Awaiting Assignment"
    assert "2 proyek" in resp.json()["message"]


async def test_pending_assignment_kosong(dunia, api):
    resp = await api.client.get(PENDING, headers=dunia.h["lead"])

    assert resp.json()["data"] == []


async def test_sa_tersedia_menghitung_proyek_aktif_sesuai_definisi_workload(dunia, api):
    # Definisi sama dengan `/workload/beban`: Won/Handed Over aktif; Lost/Closed/On Hold tidak.
    await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(status="Submitted", assigned_sa=dunia.sa.id)
    for status in ("Won", "Handed Over"):
        await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)
    for status in ("Lost", "Closed", "On Hold"):
        await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)
    await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa2.id)

    resp = await api.client.get(TERSEDIA, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    beban = {u["email"]: u["active_project_count"] for u in resp.json()["data"]}
    # Kandidat = SA dan Lead_SA (ADR 0012); Sales/Product tidak ikut. Admin berrole SA ikut.
    # `role` tersedia agar UI bisa menyaring Lead_SA untuk dropdown "Lead SA" (#135).
    peran = {u["email"]: u["role"] for u in resp.json()["data"]}
    assert peran[dunia.lead.email] == "Lead_SA"
    assert peran[dunia.sa.email] == "SA"
    assert beban == {
        dunia.sa.email: 4,
        dunia.sa2.email: 1,
        dunia.admin.email: 0,
        dunia.lead.email: 0,
    }


# ----------------------------------------------------------------------------- utilisasi SA


async def _catat(dunia, sa, proyek_id, jam, waktu, **o):
    dunia.db.add(
        bangun_log(sa.id, proyek_id, duration_hours=Decimal(str(jam)), created_at=waktu, **o)
    )


async def test_utilisasi_sa_jam_per_bulan_dan_ringkasan(dunia, api):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    await _catat(dunia, dunia.sa, proyek.id_project, "2.5", _waktu(2026, 1))
    await _catat(dunia, dunia.sa, proyek.id_project, "1.5", _waktu(2026, 1))
    await _catat(dunia, dunia.sa, proyek.id_project, "4", _waktu(2026, 3))
    await _catat(dunia, dunia.lead, proyek.id_project, "3", _waktu(2026, 3))
    await _catat(dunia, dunia.sa2, proyek.id_project, "9", _waktu(2025, 12))  # tahun lain
    await dunia.db.commit()

    resp = await api.client.get(UTIL_SA, params={"year": 2026}, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["year"] == 2026
    per_sa = {r["sa_name"]: r for r in data["monthly_data"]}
    # SA + Lead_SA saja (admin berrole SA ikut sebagai SA).
    assert set(per_sa) == {dunia.sa.name, dunia.sa2.name, dunia.lead.name, dunia.admin.name}
    assert per_sa[dunia.sa.name]["months"]["1"] == 4.0
    assert per_sa[dunia.sa.name]["months"]["3"] == 4.0
    assert per_sa[dunia.sa.name]["total_hours"] == 8.0
    assert per_sa[dunia.sa2.name]["total_hours"] == 0
    assert data["summary"]["months"]["3"] == 7.0
    assert data["summary"]["total_hours"] == 11.0 and data["summary"]["sa_count"] == 4
    assert len(per_sa[dunia.sa.name]["months"]) == 12


async def test_utilisasi_sa_default_tahun_berjalan(dunia, api):
    resp = await api.client.get(UTIL_SA, headers=dunia.h["lead"])

    assert resp.json()["data"]["year"] == datetime.now(timezone.utc).year


async def test_utilisasi_sa_filter_per_sa_dan_sa_id_tidak_valid_diabaikan(dunia, api):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    await _catat(dunia, dunia.sa, proyek.id_project, "2", _waktu(2026, 5))
    await _catat(dunia, dunia.sa2, proyek.id_project, "6", _waktu(2026, 5))
    await dunia.db.commit()

    satu = await api.client.get(
        UTIL_SA, params={"year": 2026, "sa_id": str(dunia.sa.id)}, headers=dunia.h["admin"]
    )
    rusak = await api.client.get(
        UTIL_SA, params={"year": 2026, "sa_id": "bukan-uuid"}, headers=dunia.h["admin"]
    )
    tak_dikenal = await api.client.get(
        UTIL_SA, params={"year": 2026, "sa_id": str(uuid.uuid4())}, headers=dunia.h["admin"]
    )

    assert [r["sa_name"] for r in satu.json()["data"]["monthly_data"]] == [dunia.sa.name]
    assert satu.json()["data"]["summary"]["total_hours"] == 2.0
    assert rusak.json()["data"]["summary"]["sa_count"] == 4  # filter diabaikan → semua SA/Lead
    assert tak_dikenal.json()["data"]["monthly_data"] == []


# ----------------------------------------------------------------------------- utilisasi proyek


async def test_utilisasi_proyek_tanpa_log_kosong(dunia, api):
    await dunia.buat_proyek()

    resp = await api.client.get(UTIL_PROYEK, headers=dunia.h["lead"])

    assert resp.json()["data"] == []


async def test_utilisasi_proyek_total_personel_dan_urutan_jam_menurun(dunia, api):
    besar = await dunia.buat_proyek(project_name="Besar", status="Assigned")
    kecil = await dunia.buat_proyek(project_name="Kecil", status="Submitted")
    await _catat(dunia, dunia.sa, besar.id_project, "3", _waktu(2026, 1))
    await _catat(dunia, dunia.sa, besar.id_project, "2", _waktu(2026, 2))
    await _catat(dunia, dunia.sa2, besar.id_project, "10", _waktu(2026, 2))
    await _catat(dunia, dunia.sa, kecil.id_project, "1", _waktu(2026, 2))
    await dunia.db.commit()

    resp = await api.client.get(UTIL_PROYEK, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [p["project_name"] for p in data] == ["Besar", "Kecil"]
    assert data[0]["total_hours"] == 15.0 and data[0]["status"] == "Assigned"
    assert [(s["sa_name"], s["hours"]) for s in data[0]["sa_personnel"]] == [
        (dunia.sa2.name, 10.0),
        (dunia.sa.name, 5.0),
    ]
    assert data[1]["total_hours"] == 1.0


# ----------------------------------------------------------------------------- ringkasan utilisasi


async def test_ringkasan_utilisasi_work_type_dan_fase_proyek(dunia, api):
    proyek = await dunia.buat_proyek(status="Assigned")
    await _catat(
        dunia, dunia.sa, proyek.id_project, "3", _waktu(2026, 1), project_phase="Implementation"
    )
    await _catat(
        dunia,
        dunia.sa,
        proyek.id_project,
        "2",
        _waktu(2026, 1),
        project_phase="Pre-Implementation",
    )
    await _catat(
        dunia,
        dunia.lead,
        proyek.id_project,
        "1",
        _waktu(2026, 2),
        project_phase="Post-Implementation",
    )
    await _catat(
        dunia,
        dunia.sa,
        None,
        "4",
        _waktu(2026, 2),
        work_type="Non-Project",
        project_phase=None,
        subtask_category="Training",
    )
    await _catat(dunia, dunia.sa, proyek.id_project, "7", _waktu(2025, 6))  # tahun lain
    await dunia.db.commit()

    resp = await api.client.get(UTIL_RINGKAS, params={"year": 2026}, headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["year"] == 2026
    wt = data["work_type"]
    assert wt["months"]["1"] == {"Project": 5.0, "Non-Project": 0.0}
    assert wt["months"]["2"] == {"Project": 1.0, "Non-Project": 4.0}
    assert wt["totals"] == {"Project": 6.0, "Non-Project": 4.0} and wt["grand_total"] == 10.0
    assert data["project_phase"]["totals"] == {
        "Pre-Implementation": 2.0,
        "Implementation": 3.0,
        "Post-Implementation": 1.0,
    }
    assert data["project_phase"]["total"] == 6.0


async def test_ringkasan_utilisasi_default_tahun_berjalan_kosong(dunia, api):
    resp = await api.client.get(UTIL_RINGKAS, headers=dunia.h["lead"])

    data = resp.json()["data"]
    assert data["year"] == datetime.now(timezone.utc).year
    assert data["work_type"]["grand_total"] == 0 and data["project_phase"]["total"] == 0


# ----------------------------------------------------------------- proyek terhapus & error


async def test_utilisasi_proyek_terhapus_tidak_tampil_di_tabel_proyek_tetapi_jam_sa_tetap(
    dunia, api
):
    """ADR 0009: jam kerja proyek terhapus tetap dihitung per SA, tidak per proyek."""
    from sqlalchemy import update

    from app.models import Project

    hidup = await dunia.buat_proyek(project_name="Hidup", status="Assigned")
    mati = await dunia.buat_proyek(project_name="Mati", status="Assigned")
    await _catat(dunia, dunia.sa, hidup.id_project, "2", _waktu(2026, 4))
    await _catat(dunia, dunia.sa, mati.id_project, "5", _waktu(2026, 4))
    await dunia.db.commit()
    await dunia.db.execute(
        update(Project)
        .where(Project.id_project == mati.id_project)
        .values(deleted_at=_waktu(2026, 5)),
        execution_options={"include_deleted": True},
    )
    await dunia.db.commit()

    per_proyek = await api.client.get(UTIL_PROYEK, headers=dunia.h["lead"])
    per_sa = await api.client.get(UTIL_SA, params={"year": 2026}, headers=dunia.h["lead"])

    assert [p["project_name"] for p in per_proyek.json()["data"]] == ["Hidup"]
    sa = next(r for r in per_sa.json()["data"]["monthly_data"] if r["sa_name"] == dunia.sa.name)
    assert sa["total_hours"] == 7.0


async def test_utilisasi_sa_error_tak_terduga_menjadi_500_tanpa_mengubah_data(
    dunia, api, monkeypatch
):
    from app.api import assignment

    def _meledak(*a, **k):
        raise RuntimeError("query meledak")

    monkeypatch.setattr(assignment, "select", _meledak)

    resp = await api.client.get(UTIL_SA, headers=dunia.h["lead"])

    assert resp.status_code == 500
    assert "query meledak" in resp.text
