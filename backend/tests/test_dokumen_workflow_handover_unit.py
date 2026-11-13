"""
Unit test (tanpa DB/Docker) untuk dokumen, workflow, dan handover (tiket B6, #59, spec #49).

Fokus: fungsi murni state machine (properti Hypothesis) dan cabang defensif yang tidak bisa
dicapai lewat Postgres nyata karena FK (user SA/Sales yang hilang, proyek tak ada saat service
dipanggil langsung). Jalur normal diuji di `tests/integration/test_*_api.py`.
"""

import asyncio
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st

from app.api import documents, workflow
from app.core.dependencies import TingkatAkses, ensure_project_access
from app.services.handover_service import HandoverError, HandoverService, _generate_audit_id

SEMUA_STATUS = [
    "New",
    "Pending Assignment",
    "Assigned",
    "Ready",
    "Closed-Win",
    "Handover Complete",
    "Lost",
    "Need Clarification",
    "Scoring Pending",
    "Manual Review Required",
]


def _hasil(nilai):
    """Hasil `db.execute` yang mendukung `scalar_one_or_none`/`scalars().all()`/`.first()`."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = nilai
    r.scalars.return_value.all.return_value = [] if nilai is None else [nilai]
    r.scalars.return_value.first.return_value = nilai
    return r


def _db(*hasil):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_hasil(h) for h in hasil])
    db.commit = AsyncMock()
    return db


# ------------------------------ state machine proyek


@given(st.sampled_from(SEMUA_STATUS), st.booleans())
def test_status_berikutnya_selalu_valid_dan_lost_hanya_privileged_non_terminal(status, privileged):
    berikut = workflow._get_valid_next_statuses(status, privileged)

    assert len(berikut) == len(set(berikut))
    assert set(berikut) <= set(SEMUA_STATUS)
    boleh_lost = privileged and status not in ("Handover Complete", "Lost")
    assert ("Lost" in berikut) == boleh_lost
    forward = workflow.VALID_FORWARD_TRANSITIONS.get(status)
    assert (forward in berikut) == (forward is not None)
    # Tidak pernah ada transisi mundur atau ke status yang sama.
    assert status not in berikut


@given(st.sampled_from(SEMUA_STATUS), st.text(max_size=30), st.booleans())
def test_transisi_valid_ekuivalen_dengan_keanggotaan_daftar_berikutnya(status, tujuan, privileged):
    assert workflow._is_valid_transition(status, tujuan, privileged) == (
        tujuan in workflow._get_valid_next_statuses(status, privileged)
    )


@pytest.mark.parametrize("terminal", ["Lost", "Handover Complete"])
@pytest.mark.parametrize("privileged", [True, False])
def test_status_terminal_tanpa_lost(terminal, privileged):
    assert "Lost" not in workflow._get_valid_next_statuses(terminal, privileged)


def test_rantai_forward_linear_tanpa_siklus_dan_berakhir_di_closed_win():
    """`Closed-Win` → `Handover Complete` hanya lewat POST /handover (issue #76), bukan state machine ini."""
    status, terlihat = "New", []
    while status in workflow.VALID_FORWARD_TRANSITIONS:
        terlihat.append(status)
        status = workflow.VALID_FORWARD_TRANSITIONS[status]
    assert status == "Closed-Win"
    assert len(terlihat) == len(set(terlihat)) == 4


@pytest.mark.parametrize("status", SEMUA_STATUS)
@pytest.mark.parametrize("privileged", [True, False])
def test_handover_complete_tidak_pernah_menjadi_tujuan_valid_patch_status(status, privileged):
    assert "Handover Complete" not in workflow._get_valid_next_statuses(status, privileged)
    assert workflow._is_valid_transition(status, "Handover Complete", privileged) is False


def test_id_audit_berformat_tanggal_dan_acak_enam_karakter():
    pola = re.compile(r"^AUDIT-\d{8}-[A-Z0-9]{6}$")
    for _ in range(50):
        assert pola.match(workflow._generate_audit_id())
        assert pola.match(_generate_audit_id())


# DIUBAH di #92: `workflow._check_project_access` (sinkron) dihapus; aturannya pindah ke titik
# keputusan bersama `TingkatAkses.UBAH_STATUS`. Kedua test di bawah menguji aturan yang sama
# (peran tak dikenal ditolak 403; Lead_SA/Admin lolos tanpa kepemilikan) lewat `ensure_project_access`.
# UBAH_STATUS tidak membaca collaborator sehingga `db` tidak dipakai.
async def test_akses_proyek_peran_tidak_dikenal_ditolak():
    proyek = SimpleNamespace(sales_pic=uuid.uuid4(), product_pic=uuid.uuid4(), assigned_sa=uuid.uuid4())
    user = SimpleNamespace(role="Intern", is_admin=False, id=uuid.uuid4())

    with pytest.raises(HTTPException) as err:
        await ensure_project_access(None, proyek, user, TingkatAkses.UBAH_STATUS)

    assert err.value.status_code == 403


@pytest.mark.parametrize(("peran", "is_admin"), [("Lead_SA", False), ("SA", True)])
async def test_akses_proyek_privileged_lolos_tanpa_kepemilikan(peran, is_admin):
    proyek = SimpleNamespace(sales_pic=uuid.uuid4(), product_pic=uuid.uuid4(), assigned_sa=None)
    user = SimpleNamespace(role=peran, is_admin=is_admin, id=uuid.uuid4())
    await ensure_project_access(None, proyek, user, TingkatAkses.UBAH_STATUS)


# ------------------------------ state machine dokumen


def test_tabel_transisi_dokumen_maju_dan_mundur_saling_berkebalikan():
    maju, mundur = documents.VALID_TRANSITIONS, documents.BACKWARD_TRANSITIONS
    assert set(maju) == set(mundur) == {"Draft", "Reviewed", "Final"}
    for awal, tujuan_list in maju.items():
        for tujuan in tujuan_list:
            assert awal in mundur[tujuan]  # setiap langkah maju punya langkah mundur
            assert tujuan not in mundur[awal]  # tidak ada arah ganda
    assert maju["Final"] == [] and mundur["Draft"] == []
    # Tidak ada loncat Draft <-> Final.
    assert "Final" not in maju["Draft"] + mundur["Draft"]
    assert "Draft" not in maju["Final"] + mundur["Final"]


# ------------------------------ _handle_doc_ready defensif


def _dokumen():
    return SimpleNamespace(id_doc="DOC-1", id_project="PRJ-1", doc_type="BOQ")


async def test_doc_ready_proyek_tidak_ditemukan_dilewati(monkeypatch):
    kirim = AsyncMock()
    buka = AsyncMock()
    monkeypatch.setattr(documents.notification_service, "send_notification", kirim)
    monkeypatch.setattr(documents.folder_provisioner, "unlock_solutions_folder", buka)

    await documents._handle_doc_ready(_dokumen(), _db(None))

    kirim.assert_not_awaited()
    buka.assert_not_awaited()


async def test_doc_ready_user_sales_tidak_ditemukan_dilewati(monkeypatch):
    kirim = AsyncMock()
    buka = AsyncMock()
    monkeypatch.setattr(documents.notification_service, "send_notification", kirim)
    monkeypatch.setattr(documents.folder_provisioner, "unlock_solutions_folder", buka)
    proyek = SimpleNamespace(
        id_project="PRJ-1",
        project_name="P",
        customer_name="C",
        dq_number="DQ-12345",
        sales_pic=uuid.uuid4(),
        gdrive_solutions_folder_id="sol",
    )

    await documents._handle_doc_ready(_dokumen(), _db(proyek, None))

    kirim.assert_not_awaited()
    buka.assert_not_awaited()


# ------------------------------ notifikasi HLD defensif


async def test_notifikasi_hld_user_sa_hilang_dilewati(monkeypatch):
    kirim = AsyncMock()
    monkeypatch.setattr(workflow.notification_service, "send_notification", kirim)
    proyek = SimpleNamespace(
        id_project="PRJ-1", project_name="P", customer_name="C", assigned_sa=uuid.uuid4()
    )

    await workflow._notify_mandatory_hld(proyek, _db(None))

    kirim.assert_not_awaited()


async def test_notifikasi_hld_proyek_tanpa_sa_tidak_menyentuh_db(monkeypatch):
    kirim = AsyncMock()
    monkeypatch.setattr(workflow.notification_service, "send_notification", kirim)
    db = _db()

    await workflow._notify_mandatory_hld(SimpleNamespace(id_project="P", assigned_sa=None), db)

    kirim.assert_not_awaited()
    db.execute.assert_not_awaited()


# ------------------------------ handover_service defensif


async def test_kesiapan_proyek_tidak_ada_mengembalikan_tidak_siap():
    hasil = await HandoverService().check_handover_readiness("PRJ-X", _db(None))

    assert hasil == {
        "ready": False,
        "missing_items": ["Proyek tidak ditemukan"],
        "pmo_email": None,
        "delivery_email": None,
        "project_status": None,
        "hld_status": None,
    }


async def test_trigger_handover_proyek_tidak_ada_error_dan_tanpa_commit():
    db = _db(None)

    with pytest.raises(HandoverError, match="tidak ditemukan"):
        await HandoverService().trigger_handover("PRJ-X", uuid.uuid4(), db)

    db.commit.assert_not_awaited()


@given(st.lists(st.sampled_from(["Draft", "Reviewed", "Final"]), min_size=1, max_size=5))
def test_kesiapan_hld_final_jika_dan_hanya_jika_ada_dokumen_hld_final(daftar_status):
    asyncio.run(_cek_kesiapan_hld(daftar_status))


async def _cek_kesiapan_hld(daftar_status):
    proyek = SimpleNamespace(
        status="Closed-Win",
        pmo_lead_email="p@x.id",
        delivery_lead_email="d@x.id",
        gdrive_folder_id="m",
        gdrive_solutions_folder_id="s",
    )
    hld = [SimpleNamespace(status=s) for s in daftar_status]
    db = MagicMock()
    r_proyek = _hasil(proyek)
    r_hld = MagicMock()
    r_hld.scalars.return_value.all.return_value = hld
    db.execute = AsyncMock(side_effect=[r_proyek, r_hld])

    hasil = await HandoverService().check_handover_readiness("PRJ-1", db)

    assert hasil["ready"] == ("Final" in daftar_status)
    assert hasil["hld_status"] == ("Final" if "Final" in daftar_status else daftar_status[0])
