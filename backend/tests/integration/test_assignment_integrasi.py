"""
Integrasi assignment, reassign, seeding subtask, timer SLA, dan provisioning folder terhadap
Postgres nyata dengan Drive palsu (tiket B5 #58, spec #49).

Alur utama `assign → timer SLA → provisioning` diuji lewat endpoint nyata. Background task
provisioning ditangkap lalu `_trigger_folder_provisioner` ASLI dijalankan setelah request selesai
(harness satu koneksi: sesi request yang masih terbuka me-rollback hasil task; pola
`test_fake_boundary_contoh.py`).
"""

import pytest
from sqlalchemy import func, select

from app.models import Subtask
from app.services.folder_provisioner import folder_provisioner
from app.services.sla_timer import sla_timer
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_subtask
from tests.integration.support_assignment import (
    ASSIGN,
    REASSIGN,
    REPROVISION,
    ambil_proyek,
    ambil_sla,
    bangun_dunia,
    daftar_notif,
    daftar_subtask,
    jalankan_provisioning,
    rekam_background,
)

JUDUL_DEFAULT = ["Requirement", "BoQ", "PropTek", "HLD"]


@pytest.fixture(autouse=True)
def _sesi_service_terpatch(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)


@pytest.fixture
async def dunia(db_session):
    return await bangun_dunia(db_session)


# ----------------------------------------------------------------------------- assign: alur penuh


async def test_assign_memulai_timer_seed_subtask_notifikasi_lalu_provisioning_sukses(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek(project_name="Core Banking", customer_name="PT Bank")
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(
        ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["assigned_sa_name"] == dunia.sa.name
    assert data["notification_sent"] is True and data["folder_provisioning_triggered"] is True
    assert data["project"]["status"] == "Assigned"
    assert data["project"]["folder_provisioning_status"] == "pending"

    # Status & penugasan tersimpan.
    p = await ambil_proyek(dunia.db, pid)
    assert (p.status, p.assigned_sa, p.folder_provisioning_status) == (
        "Assigned",
        dunia.sa.id,
        "pending",
    )
    assert p.assigned_at is not None
    # Timer SLA aktif sejak H+0, memakai waktu assignment.
    sla = await ambil_sla(dunia.db, pid)
    assert (sla.current_status, sla.days_elapsed, sla.is_locked) == ("green", 0, False)
    assert sla.started_at == p.assigned_at and sla.stopped_at is None
    # Checklist default ditugaskan ke SA proyek.
    subtask = await daftar_subtask(dunia.db, pid)
    assert sorted(s.title for s in subtask) == sorted(JUDUL_DEFAULT)
    assert {(s.status, s.assigned_sa) for s in subtask} == {("open", dunia.sa.id)}
    # Notifikasi in-app untuk SA.
    notif = await daftar_notif(dunia.db, pid, "assignment")
    assert [n.recipient_user_id for n in notif] == [dunia.sa.id]
    assert notif[0].notification_metadata["project_name"] == "Core Banking"
    assert notif[0].notification_metadata["assigned_by"] == dunia.lead.name
    # Provisioning dijadwalkan dengan email SA, Lead_SA, dan Sales yang benar.
    assert tugas == [(pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)]

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "provisioned"
    assert fake_drive.folder[p.gdrive_folder_id]["name"] == "PT Bank - Core Banking"
    assert fake_drive.folder[p.gdrive_solutions_folder_id]["name"] == "Solutions"
    assert fake_drive.folder[p.gdrive_solutions_folder_id]["parent"] == p.gdrive_folder_id
    assert fake_drive.peran(p.gdrive_folder_id, dunia.sa.email) == "writer"
    assert fake_drive.peran(p.gdrive_folder_id, dunia.lead.email) == "writer"
    # Sales tidak punya akses ke Solutions (menunggu DQ Number).
    assert fake_drive.peran(p.gdrive_solutions_folder_id, dunia.sales.email) is None


async def test_assign_provisioning_gagal_status_failed_lalu_provision_ulang_berhasil(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)
    fake_drive.fail_next("provision_project_folder")
    await api.client.post(
        ASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "failed"
    assert (p.gdrive_folder_id, p.gdrive_solutions_folder_id) == (None, None)
    assert fake_drive.folder == {}
    # Kegagalan Drive tidak membatalkan assignment, timer, maupun subtask.
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.sa.id)
    assert (await ambil_sla(dunia.db, pid)) is not None
    assert len(await daftar_subtask(dunia.db, pid)) == 4

    # Provision ulang (Lead_SA): menandai pending lalu menjadwalkan task yang sama.
    resp = await api.client.post(REPROVISION.format(pid), headers=dunia.h["lead"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["folder_provisioning_status"] == "pending"
    assert tugas[1] == (pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)
    await jalankan_provisioning(dunia.db, tugas[1])
    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "provisioned" and p.gdrive_folder_id is not None

    # Guard idempotensi (ADR 0006): sudah ada folder → 409 dan Drive tidak disentuh lagi.
    panggilan_sebelum = len(fake_drive.panggilan)
    lagi = await api.client.post(REPROVISION.format(pid), headers=dunia.h["admin"])
    assert lagi.status_code == 409
    assert len(fake_drive.panggilan) == panggilan_sebelum
    assert len(tugas) == 2


async def test_provisioning_error_tak_terduga_tidak_meledak_dan_status_tetap_pending(
    dunia, api, fake_drive, monkeypatch
):
    proyek = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)
    await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    async def _meledak(*a, **k):
        raise RuntimeError("Drive tidak terduga")

    monkeypatch.setattr(folder_provisioner, "provision_project_folder", _meledak)

    await jalankan_provisioning(dunia.db, tugas[0])  # tidak boleh raise

    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "pending" and p.gdrive_folder_id is None


async def test_provisioning_proyek_hilang_dilewati_tanpa_menyentuh_drive(dunia, fake_drive):
    await jalankan_provisioning(
        dunia.db, ("PRJ-TIDAK-ADA", dunia.sa.email, dunia.lead.email, dunia.sales.email)
    )

    assert fake_drive.panggilan == []


# ----------------------------------------------------------------------------- assign: validasi


async def test_assign_dua_kali_ditolak_tanpa_menggandakan_subtask_atau_timer(
    dunia, api, monkeypatch
):
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    rekam_background(monkeypatch)
    url = ASSIGN.format(pid)
    await api.client.post(url, json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"])

    kedua = await api.client.post(url, json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"])

    assert kedua.status_code == 400 and "Assigned" in kedua.json()["message"]
    p = await ambil_proyek(dunia.db, pid)
    assert p.assigned_sa == dunia.sa.id
    assert len(await daftar_subtask(dunia.db, pid)) == 4
    assert len(await daftar_notif(dunia.db, pid, "assignment")) == 1


@pytest.mark.parametrize("status", ["Need Clarification", "Ready", "Closed-Win", "Lost"])
async def test_assign_hanya_untuk_pending_assignment(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 400
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == (status, None)
    assert await ambil_sla(dunia.db, proyek.id_project) is None


async def test_assign_proyek_tidak_ada_404_dan_sa_tidak_ada_404(dunia, api):
    proyek = await dunia.buat_proyek()
    import uuid

    tanpa_proyek = await api.client.post(
        ASSIGN.format("PRJ-TIDAK-ADA"), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    tanpa_sa = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(uuid.uuid4())},
        headers=dunia.h["lead"],
    )

    assert tanpa_proyek.status_code == 404 and tanpa_sa.status_code == 404
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Pending Assignment"


@pytest.mark.parametrize("target", ["sales_lain", "lead", "admin"])
async def test_assign_target_bukan_sa_ditolak(dunia, api, target):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project),
        json={"sa_id": str(getattr(dunia, target).id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Pending Assignment", None)
    assert await daftar_subtask(dunia.db, proyek.id_project) == []


async def test_assign_body_tanpa_sa_id_422(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(ASSIGN.format(proyek.id_project), json={}, headers=dunia.h["lead"])

    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("peran", "diizinkan"),
    [("lead", True), ("admin", True), ("sa", False), ("sales", False)],
)
async def test_assign_hak_akses_per_peran(dunia, api, monkeypatch, peran, diizinkan):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h[peran]
    )

    p = await ambil_proyek(dunia.db, proyek.id_project)
    if diizinkan:
        assert resp.status_code == 200, resp.text
        assert p.status == "Assigned"
    else:
        assert resp.status_code == 403
        assert (p.status, p.assigned_sa) == ("Pending Assignment", None)
        assert await ambil_sla(dunia.db, proyek.id_project) is None


async def test_assign_tanpa_login_ditolak(dunia, api):
    proyek = await dunia.buat_proyek()

    resp = await api.client.post(ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)})

    assert resp.status_code in (401, 403)


async def test_assign_tetap_berhasil_walau_timer_gagal_dimulai(dunia, api, monkeypatch):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    async def _gagal(*a, **k):
        raise RuntimeError("timer rusak")

    monkeypatch.setattr(sla_timer, "start_timer", _gagal)

    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, proyek.id_project)).status == "Assigned"
    assert await ambil_sla(dunia.db, proyek.id_project) is None


# ----------------------------------------------------------------------------- seeding idempoten


async def test_assign_tidak_seed_bila_proyek_sudah_punya_subtask(dunia, api, monkeypatch):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)
    dunia.db.add(bangun_subtask(proyek.id_project, title="Sudah Ada"))
    await dunia.db.commit()

    await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert [s.title for s in await daftar_subtask(dunia.db, proyek.id_project)] == ["Sudah Ada"]


async def test_seed_subtask_dua_kali_tetap_satu_set_dengan_id_unik(dunia):
    from app.api.assignment import _seed_default_subtasks

    proyek = await dunia.buat_proyek()
    pid = proyek.id_project

    await _seed_default_subtasks(dunia.db, pid, dunia.sa.id)
    await dunia.db.commit()
    await _seed_default_subtasks(dunia.db, pid, dunia.sa2.id)
    await dunia.db.commit()

    subtask = await daftar_subtask(dunia.db, pid)
    assert sorted(s.title for s in subtask) == sorted(JUDUL_DEFAULT)
    assert len({s.id_subtask for s in subtask}) == 4
    assert {s.assigned_sa for s in subtask} == {dunia.sa.id}  # set kedua tidak menimpa


# ----------------------------------------------------------------------------- reassign


async def _assign(api, dunia, monkeypatch, **proyek_opsi):
    proyek = await dunia.buat_proyek(**proyek_opsi)
    rekam_background(monkeypatch)
    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    assert resp.status_code == 200, resp.text
    return proyek.id_project


async def test_reassign_mengganti_sa_menotifikasi_sa_baru_tanpa_duplikasi_timer_atau_subtask(
    dunia, api, monkeypatch
):
    pid = await _assign(api, dunia, monkeypatch)
    sla_awal = await ambil_sla(dunia.db, pid)
    started_at = sla_awal.started_at

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["assigned_sa"] == str(dunia.sa2.id)
    assert (data["assigned_sa_email"], data["status"]) == (dunia.sa2.email, "Assigned")
    p = await ambil_proyek(dunia.db, pid)
    assert p.assigned_sa == dunia.sa2.id
    notif = {n.recipient_user_id: n for n in await daftar_notif(dunia.db, pid, "assignment")}
    assert set(notif) == {dunia.sa.id, dunia.sa2.id}
    assert notif[dunia.sa2.id].notification_metadata["previous_sa_id"] == str(dunia.sa.id)
    assert len(await daftar_subtask(dunia.db, pid)) == 4  # seeding idempoten
    jumlah_sla = await dunia.db.scalar(
        select(func.count()).select_from(type(sla_awal)).where(type(sla_awal).project_id == pid)
    )
    assert jumlah_sla == 1
    assert (await ambil_sla(dunia.db, pid)).started_at == started_at


@pytest.mark.parametrize("status", ["Ready", "Assigned"])
async def test_reassign_diizinkan_pada_assigned_dan_ready(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id, assigned_at=None)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["admin"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == (status, dunia.sa2.id)


async def test_reassign_pada_pending_assignment_menjadikan_assigned_dan_seed_subtask(
    dunia, api, monkeypatch
):
    proyek = await dunia.buat_proyek()
    rekam_background(monkeypatch)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert (p.status, p.assigned_sa) == ("Assigned", dunia.sa.id)
    assert len(await daftar_subtask(dunia.db, proyek.id_project)) == 4


async def test_reassign_dari_pending_assignment_memulai_timer_sla_dan_provisioning_folder(
    dunia, api, fake_drive, monkeypatch
):
    """#77: reassign dari Pending Assignment setara assign: tracker SLA + folder Drive dibuat."""
    proyek = await dunia.buat_proyek()
    pid = proyek.id_project
    tugas = rekam_background(monkeypatch)
    assert await ambil_sla(dunia.db, pid) is None

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, pid)
    sla = await ambil_sla(dunia.db, pid)
    assert sla is not None and sla.started_at == p.assigned_at
    assert (sla.current_status, sla.is_locked, sla.stopped_at) == ("green", False, None)
    assert p.folder_provisioning_status == "pending"
    assert tugas == [(pid, dunia.sa.email, dunia.lead.email, dunia.sales.email)]

    await jalankan_provisioning(dunia.db, tugas[0])

    p = await ambil_proyek(dunia.db, pid)
    assert p.folder_provisioning_status == "provisioned"
    assert fake_drive.peran(p.gdrive_folder_id, dunia.sa.email) == "writer"


async def _assign_dan_provision(api, dunia, fake_drive, monkeypatch):
    """Proyek Assigned ke `dunia.sa` dengan folder Drive sungguh-sungguh dibuat (fake)."""
    proyek = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)
    resp = await api.client.post(
        ASSIGN.format(proyek.id_project), json={"sa_id": str(dunia.sa.id)}, headers=dunia.h["lead"]
    )
    assert resp.status_code == 200, resp.text
    await jalankan_provisioning(dunia.db, tugas[0])
    return (await ambil_proyek(dunia.db, proyek.id_project)).gdrive_folder_id, proyek.id_project


async def test_reassign_memindahkan_akses_drive_sa_baru_diberi_sa_lama_dicabut(
    dunia, api, fake_drive, monkeypatch
):
    """#77: SA baru mendapat Editor di folder master, SA lama dicabut; Lead_SA tetap."""
    master, pid = await _assign_dan_provision(api, dunia, fake_drive, monkeypatch)
    assert fake_drive.peran(master, dunia.sa.email) == "writer"

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert fake_drive.peran(master, dunia.sa2.email) == "writer"
    assert fake_drive.peran(master, dunia.sa.email) is None
    assert fake_drive.peran(master, dunia.lead.email) == "writer"
    [panggilan] = fake_drive.panggilan_operasi("reassign_sa_access")
    assert panggilan.argumen == {
        "master_folder_id": master,
        "old_sa_email": dunia.sa.email,
        "new_sa_email": dunia.sa2.email,
    }


async def test_reassign_tetap_berhasil_walau_drive_gagal(dunia, api, fake_drive, monkeypatch):
    master, pid = await _assign_dan_provision(api, dunia, fake_drive, monkeypatch)
    fake_drive.fail_always("reassign_sa_access")

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    assert (await ambil_proyek(dunia.db, pid)).assigned_sa == dunia.sa2.id
    # Drive gagal: akses lama belum dicabut (dapat dirapikan dengan provision ulang / manual).
    assert fake_drive.peran(master, dunia.sa.email) == "writer"


async def test_reassign_tanpa_folder_tidak_menyentuh_drive(dunia, api, fake_drive):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 200, resp.text
    assert fake_drive.panggilan_operasi("reassign_sa_access") == []
    assert fake_drive.panggilan_operasi("provision_project_folder") == []


async def test_reassign_sla_melanjutkan_hitungan_dan_subtask_tidak_dipindahkan(
    dunia, api, monkeypatch
):
    """#77: timer SLA TIDAK direset (started_at tetap) dan subtask SA lama tetap miliknya."""
    pid = await _assign(api, dunia, monkeypatch)
    sla_awal = await ambil_sla(dunia.db, pid)

    resp = await api.client.post(
        REASSIGN.format(pid), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )

    assert resp.status_code == 200, resp.text
    p = await ambil_proyek(dunia.db, pid)
    sla = await ambil_sla(dunia.db, pid)
    assert sla.id == sla_awal.id and sla.started_at == sla_awal.started_at
    assert sla.started_at < p.assigned_at  # assigned_at mencatat SA saat ini, bukan awal SLA
    assert (sla.stopped_at, sla.is_locked) == (None, False)
    assert {s.assigned_sa for s in await daftar_subtask(dunia.db, pid)} == {dunia.sa.id}


@pytest.mark.parametrize(
    "status", ["Closed-Win", "Handover Complete", "Lost", "Need Clarification"]
)
async def test_reassign_status_tidak_valid_ditolak(dunia, api, status):
    proyek = await dunia.buat_proyek(status=status, assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h["lead"],
    )

    assert resp.status_code == 400
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == dunia.sa.id


async def test_reassign_proyek_tidak_ada_sa_tidak_ada_dan_target_bukan_sa(dunia, api):
    import uuid

    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    url = REASSIGN.format(proyek.id_project)

    tanpa_proyek = await api.client.post(
        REASSIGN.format("PRJ-TIDAK-ADA"), json={"sa_id": str(dunia.sa2.id)}, headers=dunia.h["lead"]
    )
    tanpa_sa = await api.client.post(
        url, json={"sa_id": str(uuid.uuid4())}, headers=dunia.h["lead"]
    )
    bukan_sa = await api.client.post(
        url, json={"sa_id": str(dunia.sales_lain.id)}, headers=dunia.h["lead"]
    )

    assert (tanpa_proyek.status_code, tanpa_sa.status_code, bukan_sa.status_code) == (404, 404, 400)
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == dunia.sa.id
    assert await daftar_notif(dunia.db, proyek.id_project, "assignment") == []


@pytest.mark.parametrize(
    ("peran", "diizinkan"),
    [("lead", True), ("admin", True), ("sa", False), ("sales", False)],
)
async def test_reassign_hak_akses_per_peran(dunia, api, peran, diizinkan):
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)

    resp = await api.client.post(
        REASSIGN.format(proyek.id_project),
        json={"sa_id": str(dunia.sa2.id)},
        headers=dunia.h[peran],
    )

    expected = dunia.sa2.id if diizinkan else dunia.sa.id
    assert resp.status_code == (200 if diizinkan else 403)
    assert (await ambil_proyek(dunia.db, proyek.id_project)).assigned_sa == expected


# ----------------------------------------------------------------------------- re-provision


@pytest.mark.parametrize("peran", ["sa", "sales"])
async def test_reprovision_hanya_lead_sa_dan_admin(dunia, api, monkeypatch, peran):
    proyek = await dunia.buat_proyek(
        status="Assigned", assigned_sa=dunia.sa.id, folder_provisioning_status="failed"
    )
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h[peran])

    assert resp.status_code == 403 and tugas == []
    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "failed"


@pytest.mark.parametrize("peran", ["lead", "admin"])
async def test_reprovision_oleh_lead_sa_atau_admin_menjadwalkan_dengan_email_pemanggil(
    dunia, api, monkeypatch, peran
):
    proyek = await dunia.buat_proyek(
        status="Assigned", assigned_sa=dunia.sa.id, folder_provisioning_status="failed"
    )
    tugas = rekam_background(monkeypatch)

    resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h[peran])

    assert resp.status_code == 200, resp.text
    pemanggil = getattr(dunia, peran)
    assert tugas == [(proyek.id_project, dunia.sa.email, pemanggil.email, dunia.sales.email)]
    assert (await ambil_proyek(dunia.db, proyek.id_project)).folder_provisioning_status == "pending"


async def test_reprovision_proyek_belum_di_assign_400_dan_tidak_ada_404(dunia, api, monkeypatch):
    belum = await dunia.buat_proyek()
    tugas = rekam_background(monkeypatch)

    tanpa_sa = await api.client.post(REPROVISION.format(belum.id_project), headers=dunia.h["lead"])
    tidak_ada = await api.client.post(REPROVISION.format("PRJ-TIDAK-ADA"), headers=dunia.h["lead"])

    assert (tanpa_sa.status_code, tidak_ada.status_code) == (400, 404)
    assert tugas == []
    assert (await ambil_proyek(dunia.db, belum.id_project)).folder_provisioning_status is None


async def test_drive_palsu_gagal_permanen_provisioning_failed_tanpa_folder_yatim_di_db(
    dunia, api, fake_drive, monkeypatch
):
    fake_drive.fail_always("provision_project_folder")
    proyek = await dunia.buat_proyek(status="Assigned", assigned_sa=dunia.sa.id)
    tugas = rekam_background(monkeypatch)

    for _ in range(2):  # dua percobaan provision ulang, keduanya gagal
        resp = await api.client.post(REPROVISION.format(proyek.id_project), headers=dunia.h["lead"])
        assert resp.status_code == 200, resp.text
        await jalankan_provisioning(dunia.db, tugas[-1])

    p = await ambil_proyek(dunia.db, proyek.id_project)
    assert p.folder_provisioning_status == "failed" and p.gdrive_folder_id is None
    assert len(fake_drive.panggilan_operasi("provision_project_folder")) == 2
    assert all(not c.berhasil for c in fake_drive.panggilan)


# ----------------------------------------------------------------------------- daftar subtask dasar


async def test_subtask_default_dapat_dibaca_dan_dikerjakan_sa_pemilik_setelah_assign(
    dunia, api, monkeypatch
):
    pid = await _assign(api, dunia, monkeypatch)

    daftar = await api.client.get(f"/api/v1/projects/{pid}/subtasks", headers=dunia.h["sa"])

    assert daftar.status_code == 200, daftar.text
    isi = daftar.json()["data"]
    assert isi["total"] == 4
    assert {i["assigned_sa_name"] for i in isi["items"]} == {dunia.sa.name}
    # Subtask tersimpan benar di tabel.
    jumlah = await dunia.db.scalar(
        select(func.count()).select_from(Subtask).where(Subtask.id_project == pid)
    )
    assert jumlah == 4
