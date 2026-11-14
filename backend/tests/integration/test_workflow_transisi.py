"""
State machine status proyek (issue #121, ADR 0013, spec §2.0 "Siklus status") terhadap Postgres
nyata: SATU test per transisi valid dan per transisi ditolak, per peran.

Peran yang diuji (semua melewati JWT asli):
- `Sales_PIC`, `Product_PIC`: PIC proyek itu.   - `Sales_lain`: Sales yang bukan PIC.
- `SA`: SA utama.  `SA_tambahan`: SA di `project_assignments`.  `SA_lain`: SA tak ditugaskan.
- `Lead_SA`, `Admin` (`is_admin`).

Transisi lewat `PATCH /projects/{id}/status`; `Handed Over` hanya lewat handover dan `Assigned`
hanya lewat penugasan. `Intake` → `Awaiting Assignment` oleh sistem (gate BANT), bukan endpoint ini.
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, ProjectAssignment
from tests.integration.b6_support import (  # noqa: F401
    API,
    buat_dokumen,
    buat_proyek,
    komit_sesi_request,
    muat,
    siapkan_dunia,
    user_baru,
)

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

PERAN = [
    "Sales_PIC",
    "Product_PIC",
    "Sales_lain",
    "SA",
    "SA_tambahan",
    "SA_lain",
    "Lead_SA",
    "Admin",
]
SEMUA_STATUS = [
    "Intake",
    "Awaiting Assignment",
    "Assigned",
    "In Progress",
    "Submitted",
    "Won",
    "Handed Over",
    "Closed",
    "Lost",
    "On Hold",
]

# Peran yang BERHAK per kelompok hak (sisanya 403). Lead_SA dan Admin selalu berhak.
HAK_SA = {"SA", "SA_tambahan", "Lead_SA", "Admin"}  # SA ditugaskan (utama/tambahan)
HAK_PIC = {"Sales_PIC", "Product_PIC", "Lead_SA", "Admin"}  # Sales/Product PIC
HAK_LEAD = {"Lead_SA", "Admin"}

# (status awal, status tujuan, peran yang berhak). Semua lewat PATCH /status.
TRANSISI_VALID = [
    ("Assigned", "Submitted", HAK_SA),
    ("In Progress", "Submitted", HAK_SA),
    ("Submitted", "In Progress", HAK_SA),
    ("Submitted", "Won", HAK_PIC),
    ("Handed Over", "Closed", HAK_LEAD),
    ("Intake", "Lost", HAK_LEAD),
    ("Awaiting Assignment", "Lost", HAK_LEAD),
    ("Assigned", "Lost", HAK_LEAD),
    ("In Progress", "Lost", HAK_LEAD),
    ("Submitted", "Lost", HAK_LEAD),
    ("Won", "Lost", HAK_LEAD),
    ("On Hold", "Lost", HAK_LEAD),
]


class Skenario:
    """Proyek + semua peran uji. `proyek(status)` membuat proyek baru pada status itu."""

    def __init__(self, api, db, dunia, tambahan):
        self.api, self.db, self.dunia = api, db, dunia
        self.user = {**dunia.user, **{k: v[0] for k, v in tambahan.items()}}
        self.header = {**dunia.header, **{k: v[1] for k, v in tambahan.items()}}
        self.header["Sales_PIC"] = dunia.header["Sales"]
        self.user["Sales_PIC"] = dunia.user["Sales"]

    async def proyek(self, status: str, *, dokumen: bool = True, **kolom) -> Project:
        kolom.setdefault("product_pic", self.user["Product_PIC"].id)
        if status == "On Hold":
            kolom.setdefault("previous_status", "Assigned")
        p = await buat_proyek(self.db, self.dunia, status=status, **kolom)
        if dokumen:
            for tipe in ("PropTek", "BOQ", "Mandays"):
                await buat_dokumen(self.db, p, self.dunia, doc_type=tipe, status="Reviewed")
        self.db.add(
            ProjectAssignment(
                id_project=p.id_project,
                user_id=self.user["SA_tambahan"].id,
                added_by=self.user["Lead_SA"].id,
            )
        )
        await self.db.commit()
        return p

    async def ubah(self, p: Project, tujuan: str, peran: str, **extra):
        return await self.api.client.patch(
            f"{API}/projects/{p.id_project}/status",
            json={"new_status": tujuan, **extra},
            headers=self.header[peran],
        )

    async def status(self, p: Project) -> str:
        return (await muat(self.db, Project, id_project=p.id_project)).status

    async def audit(self, p: Project) -> list[AuditLog]:
        return list(
            (await self.db.execute(select(AuditLog).where(AuditLog.entity_id == p.id_project)))
            .scalars()
            .all()
        )


@pytest.fixture
async def skenario(api, db_session):
    dunia = await siapkan_dunia(api, db_session)
    tambahan = {
        "Product_PIC": await user_baru(db_session, "Product"),
        "Sales_lain": await user_baru(db_session, "Sales"),
        "SA_tambahan": await user_baru(db_session, "SA"),
        "SA_lain": await user_baru(db_session, "SA"),
    }
    return Skenario(api, db_session, dunia, tambahan)


def _kasus(daftar):
    """Satu kasus per (transisi, peran)."""
    return [
        pytest.param(awal, tujuan, peran, peran in berhak, id=f"{awal}->{tujuan}-{peran}")
        for awal, tujuan, berhak in daftar
        for peran in PERAN
    ]


def _tambah_alasan(tujuan: str) -> dict:
    return {"reason": "Kalah tender"} if tujuan == "Lost" else {}


# --------------------------------------------------------------------------- transisi valid x peran


@pytest.mark.parametrize(("awal", "tujuan", "peran", "diizinkan"), _kasus(TRANSISI_VALID))
async def test_setiap_transisi_valid_per_peran_diizinkan_atau_403(
    skenario, awal, tujuan, peran, diizinkan
):
    p = await skenario.proyek(awal)

    resp = await skenario.ubah(p, tujuan, peran, **_tambah_alasan(tujuan))

    if diizinkan:
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert (data["old_status"], data["new_status"]) == (awal, tujuan)
        assert await skenario.status(p) == tujuan
        [audit] = await skenario.audit(p)
        assert audit.action == "status_change"
        assert audit.performed_by == skenario.user[peran].id
        assert audit.old_value == {"status": awal}
        assert audit.new_value["status"] == tujuan
    else:
        assert resp.status_code == 403, resp.text
        assert await skenario.status(p) == awal
        assert await skenario.audit(p) == []


# --------------------------------------------------------------------------- transisi ditolak (400)

TRANSISI_TIDAK_VALID = [
    ("Intake", "Awaiting Assignment"),  # hanya sistem (gate BANT)
    ("Intake", "Submitted"),
    ("Awaiting Assignment", "Submitted"),  # loncat
    ("Awaiting Assignment", "Won"),
    ("Assigned", "Won"),  # loncat
    ("Assigned", "In Progress"),  # In Progress otomatis, bukan lewat PATCH
    ("Assigned", "Awaiting Assignment"),  # mundur
    ("In Progress", "Won"),
    ("In Progress", "Assigned"),
    ("Submitted", "Assigned"),
    ("Submitted", "Awaiting Assignment"),
    ("Submitted", "Closed"),
    ("Won", "Submitted"),  # mundur
    ("Won", "Closed"),  # harus lewat Handed Over
    ("Won", "In Progress"),
    ("Handed Over", "Won"),
    ("Handed Over", "Submitted"),
    ("Handed Over", "Lost"),  # Lost hanya sebelum Handed Over
    ("Closed", "Handed Over"),
    ("Closed", "Lost"),
    ("Closed", "Won"),
    ("Closed", "Submitted"),
    ("Lost", "Lost"),
    ("Lost", "Submitted"),
    ("Lost", "Assigned"),
    ("Assigned", "Assigned"),  # sama
    ("Assigned", "Status-Ngawur"),  # tidak dikenal
    ("Assigned", "Pending DQ"),  # bukan status proyek (ADR 0001, 2026-11-10)
    ("Assigned", "Ready"),  # nama status lama
    ("Submitted", "Closed-Win"),
    ("Assigned", "On Hold"),  # jeda dikerjakan di #122
    ("On Hold", "Assigned"),
    ("On Hold", "Submitted"),
]


@pytest.mark.parametrize(("awal", "tujuan"), TRANSISI_TIDAK_VALID)
@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_setiap_transisi_tidak_valid_400_status_tetap_tanpa_audit(
    skenario, awal, tujuan, peran
):
    p = await skenario.proyek(awal, **({"lost_reason": "x"} if awal == "Lost" else {}))

    resp = await skenario.ubah(p, tujuan, peran, reason="alasan")

    assert resp.status_code == 400, resp.text
    assert "tidak valid" in resp.json()["message"] or "Gunakan" in resp.json()["message"]
    assert await skenario.status(p) == awal
    assert await skenario.audit(p) == []


@pytest.mark.parametrize("peran", PERAN)
@pytest.mark.parametrize("awal", ["Assigned", "Submitted", "Closed"])
async def test_transisi_tidak_valid_oleh_peran_tanpa_hubungan_tetap_ditolak(skenario, peran, awal):
    """Apa pun perannya, lompatan yang tidak ada di tabel tidak pernah 200."""
    p = await skenario.proyek(awal)

    resp = await skenario.ubah(p, "Awaiting Assignment", peran)

    assert resp.status_code in (400, 403)
    assert await skenario.status(p) == awal


@pytest.mark.parametrize("peran", PERAN)
async def test_handed_over_hanya_lewat_handover_semua_peran_ditolak(skenario, peran):
    p = await skenario.proyek("Won")

    resp = await skenario.ubah(p, "Handed Over", peran)

    assert resp.status_code in (400, 403), resp.text
    if resp.status_code == 400:
        assert "/handover" in resp.json()["message"]
    assert await skenario.status(p) == "Won"
    assert await skenario.audit(p) == []


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
async def test_assigned_hanya_lewat_penugasan_arahkan_ke_endpoint_assign(skenario, peran):
    p = await skenario.proyek("Awaiting Assignment", sa=False)

    resp = await skenario.ubah(p, "Assigned", peran)

    assert resp.status_code == 400, resp.text
    assert "/assign" in resp.json()["message"]
    assert await skenario.status(p) == "Awaiting Assignment"


async def test_pesan_transisi_tidak_valid_menyebut_status_terminal(skenario):
    p = await skenario.proyek("Closed")

    resp = await skenario.ubah(p, "Submitted", "Lead_SA")

    assert resp.status_code == 400
    assert "status terminal" in resp.json()["message"]


async def test_pesan_transisi_tidak_valid_menyebut_tujuan_yang_diperbolehkan(skenario):
    p = await skenario.proyek("Assigned")

    resp = await skenario.ubah(p, "Won", "Lead_SA")

    pesan = resp.json()["message"]
    assert resp.status_code == 400
    assert "'Submitted'" in pesan and "'Lost'" in pesan


# --------------------------------------------------------------------------- Sales PIC: hanya Won (dan jeda)


@pytest.mark.parametrize("peran", ["Sales_PIC", "Product_PIC"])
@pytest.mark.parametrize(
    ("awal", "tujuan"),
    [
        ("Assigned", "Submitted"),
        ("In Progress", "Submitted"),
        ("Submitted", "In Progress"),
        ("Handed Over", "Closed"),
        ("Assigned", "Lost"),
        ("Won", "Lost"),
    ],
)
async def test_sales_dan_product_pic_tidak_lagi_boleh_mengubah_status_selain_won(
    skenario, peran, awal, tujuan
):
    p = await skenario.proyek(awal)

    resp = await skenario.ubah(p, tujuan, peran, **_tambah_alasan(tujuan))

    assert resp.status_code == 403
    assert await skenario.status(p) == awal


async def test_sales_bukan_pic_dan_sa_tak_ditugaskan_ditolak_403_dengan_pesan_kepemilikan(
    skenario,
):
    p = await skenario.proyek("Submitted")

    r_sales = await skenario.ubah(p, "Won", "Sales_lain")
    r_sa = await skenario.ubah(p, "In Progress", "SA_lain")

    assert (r_sales.status_code, r_sa.status_code) == (403, 403)
    assert "milik Anda" in r_sales.json()["message"]
    assert "ditugaskan kepada Anda" in r_sa.json()["message"]
    assert await skenario.status(p) == "Submitted"


async def test_created_by_tanpa_pic_tidak_berhak_won(skenario):
    pembuat, header = await user_baru(skenario.db, "Sales")
    p = await skenario.proyek("Submitted", created_by=pembuat.id)

    resp = await skenario.api.client.patch(
        f"{API}/projects/{p.id_project}/status", json={"new_status": "Won"}, headers=header
    )

    assert resp.status_code == 403


# --------------------------------------------------------------------------- syarat Submitted


@pytest.mark.parametrize("tipe_hilang", ["PropTek", "BOQ", "Mandays"])
@pytest.mark.parametrize("awal", ["Assigned", "In Progress"])
async def test_submitted_ditolak_bila_satu_dokumen_wajib_tidak_ada(skenario, tipe_hilang, awal):
    p = await skenario.proyek(awal, dokumen=False)
    for tipe in {"PropTek", "BOQ", "Mandays"} - {tipe_hilang}:
        await buat_dokumen(skenario.db, p, skenario.dunia, doc_type=tipe, status="Reviewed")

    resp = await skenario.ubah(p, "Submitted", "SA")

    assert resp.status_code == 400, resp.text
    assert tipe_hilang in resp.json()["message"]
    assert await skenario.status(p) == awal
    assert await skenario.audit(p) == []


@pytest.mark.parametrize("tipe_draft", ["PropTek", "BOQ", "Mandays"])
async def test_submitted_ditolak_bila_dokumen_wajib_masih_draft(skenario, tipe_draft):
    p = await skenario.proyek("Assigned", dokumen=False)
    for tipe in ("PropTek", "BOQ", "Mandays"):
        status_doc = "Draft" if tipe == tipe_draft else "Reviewed"
        await buat_dokumen(skenario.db, p, skenario.dunia, doc_type=tipe, status=status_doc)

    resp = await skenario.ubah(p, "Submitted", "Lead_SA")

    assert resp.status_code == 400
    assert tipe_draft in resp.json()["message"]
    assert await skenario.status(p) == "Assigned"


async def test_submitted_ditolak_menyebut_semua_dokumen_yang_kurang(skenario):
    p = await skenario.proyek("Assigned", dokumen=False)

    resp = await skenario.ubah(p, "Submitted", "Admin")

    pesan = resp.json()["message"]
    assert resp.status_code == 400
    assert all(tipe in pesan for tipe in ("PropTek", "BOQ", "Mandays"))


@pytest.mark.parametrize("status_doc", ["Reviewed", "Final"])
async def test_submitted_diterima_bila_semua_dokumen_wajib_minimal_reviewed(skenario, status_doc):
    p = await skenario.proyek("Assigned", dokumen=False)
    for tipe in ("PropTek", "BOQ", "Mandays"):
        await buat_dokumen(skenario.db, p, skenario.dunia, doc_type=tipe, status=status_doc)

    resp = await skenario.ubah(p, "Submitted", "SA")

    assert resp.status_code == 200, resp.text
    assert await skenario.status(p) == "Submitted"


async def test_submitted_cukup_satu_dokumen_reviewed_per_tipe_meski_ada_draft_lain(skenario):
    p = await skenario.proyek("Assigned")
    await buat_dokumen(skenario.db, p, skenario.dunia, doc_type="BOQ", status="Draft")

    resp = await skenario.ubah(p, "Submitted", "SA")

    assert resp.status_code == 200, resp.text


async def test_dokumen_proyek_lain_tidak_memenuhi_syarat_submitted(skenario):
    p = await skenario.proyek("Assigned", dokumen=False)
    lain = await skenario.proyek("Assigned")  # punya ketiga dokumen, tetapi proyek lain

    resp = await skenario.ubah(p, "Submitted", "SA")

    assert resp.status_code == 400
    assert lain.id_project != p.id_project
    assert await skenario.status(p) == "Assigned"


async def test_syarat_dokumen_tidak_berlaku_untuk_revisi_submitted_ke_in_progress(skenario):
    p = await skenario.proyek("Submitted", dokumen=False)

    resp = await skenario.ubah(p, "In Progress", "SA")

    assert resp.status_code == 200, resp.text


async def test_hak_diperiksa_sebelum_syarat_dokumen(skenario):
    """Sales PIC tanpa hak mendapat 403 (bukan 400 yang membocorkan kondisi dokumen)."""
    p = await skenario.proyek("Assigned", dokumen=False)

    resp = await skenario.ubah(p, "Submitted", "Sales_PIC")

    assert resp.status_code == 403


# --------------------------------------------------------------------------- Lost + lost_reason


@pytest.mark.parametrize("peran", ["Lead_SA", "Admin"])
@pytest.mark.parametrize("reason", [None, "", "   "])
@pytest.mark.parametrize("awal", ["Intake", "Assigned", "Won"])
async def test_lost_tanpa_lost_reason_ditolak(skenario, peran, reason, awal):
    p = await skenario.proyek(awal)
    extra = {} if reason is None else {"reason": reason}

    resp = await skenario.ubah(p, "Lost", peran, **extra)

    assert resp.status_code == 400, resp.text
    assert "reason" in resp.json()["message"].lower() or "alasan" in resp.json()["message"].lower()
    baris = await muat(skenario.db, Project, id_project=p.id_project)
    assert (baris.status, baris.lost_reason, baris.previous_status) == (awal, None, None)
    assert await skenario.audit(p) == []


@pytest.mark.parametrize("awal", ["Intake", "Awaiting Assignment", "Assigned", "Submitted", "Won"])
async def test_lost_menyimpan_lost_reason_previous_status_dan_audit(skenario, awal):
    p = await skenario.proyek(awal)

    resp = await skenario.ubah(p, "Lost", "Lead_SA", reason="  Kalah tender  ")

    assert resp.status_code == 200, resp.text
    baris = await muat(skenario.db, Project, id_project=p.id_project)
    assert (baris.status, baris.lost_reason, baris.previous_status) == (
        "Lost",
        "Kalah tender",
        awal,
    )
    [audit] = await skenario.audit(p)
    assert audit.old_value == {"status": awal}
    assert audit.new_value == {"status": "Lost", "lost_reason": "Kalah tender"}


async def test_lost_dari_on_hold_mempertahankan_previous_status_sebelum_jeda(skenario):
    p = await skenario.proyek("On Hold", previous_status="Submitted")

    resp = await skenario.ubah(p, "Lost", "Admin", reason="Customer batal")

    assert resp.status_code == 200, resp.text
    baris = await muat(skenario.db, Project, id_project=p.id_project)
    assert (baris.status, baris.previous_status) == ("Lost", "Submitted")


async def test_lost_reason_di_atas_500_karakter_ditolak_422(skenario):
    p = await skenario.proyek("Assigned")

    resp = await skenario.ubah(p, "Lost", "Lead_SA", reason="x" * 501)

    assert resp.status_code == 422
    assert await skenario.status(p) == "Assigned"


# --------------------------------------------------------------------------- tabel hak di kode


async def test_tidak_ada_tujuan_valid_dari_status_terminal(skenario):
    from app.api import workflow

    assert workflow.status_berikutnya("Closed") == []
    assert workflow.status_berikutnya("Lost") == []
    assert set(SEMUA_STATUS) >= set(workflow.status_berikutnya("Submitted"))
