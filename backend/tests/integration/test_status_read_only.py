"""
`Closed` dan `Lost` read-only (issue #122, ADR 0013, spec §2.0), terhadap Postgres nyata.

Aksi tulis turunan proyek (activity log, subtask, dokumen, Requirement) ditolak dengan 409
Conflict saat proyek `Closed`/`Lost`. 409 dipilih karena penolakannya bergantung pada KEADAAN
proyek, bukan peran (403) atau bentuk input (400/422), dan konsisten dengan penolakan keadaan
lain di API (Requirement `Final`, event kalender ganda). Cek akses (403) tetap lebih dulu:
pihak tak berhak tidak boleh mengetahui keadaan proyek. Sebelum `Closed` (termasuk
`Handed Over`) semua aksi tetap boleh.
"""

import pytest
from sqlalchemy import func, select

from app.models import ActivityLog, Document, Subtask
from tests.integration.helpers_t60 import API, bearer, buat_proyek, buat_user
from tests.integration.model_helpers import bangun_document, bangun_log, bangun_subtask

LOGS = f"{API}/activity-logs"
CAL = f"{API}/calendar"
PROYEK = f"{API}/projects"


class Ctx:
    def __init__(self, api, db, lead, sa, proyek):
        self.api, self.db, self.lead, self.sa, self.proyek = api, db, lead, sa, proyek

    @property
    def id(self) -> str:
        return self.proyek.id_project

    async def subtask(self) -> Subtask:
        st = bangun_subtask(self.id, assigned_sa=self.lead.id)
        self.db.add(st)
        await self.db.commit()
        return st

    async def dokumen(self) -> Document:
        dok = bangun_document(self.id, self.lead.id, status="Draft")
        self.db.add(dok)
        await self.db.commit()
        return dok

    async def log(self) -> ActivityLog:
        log = bangun_log(self.lead.id, self.id)
        self.db.add(log)
        await self.db.commit()
        return log


@pytest.fixture
def ctx_pabrik(api, db_session):
    async def _buat(status: str, **o) -> Ctx:
        lead = await buat_user(db_session, "Lead_SA")
        sa = await buat_user(db_session, "SA")
        if status in ("On Hold",):
            o.setdefault("previous_status", "Assigned")
        elif status in ("Closed",):
            o.setdefault("previous_status", "Handed Over")
        proyek = await buat_proyek(db_session, lead, assigned_sa=sa, status=status, **o)
        return Ctx(api, db_session, lead, sa, proyek)

    return _buat


# --- aksi tulis: nama -> (coroutine yang mengembalikan response) sebagai Lead_SA


async def _buat_log(c: Ctx):
    badan = {
        "id_project": c.id,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1",
        "raw_notes": "catatan",
    }
    return await c.api.client.post(LOGS, json=badan, headers=bearer(c.lead))


async def _polish_ulang(c: Ctx):
    log = await c.log()
    return await c.api.client.post(f"{LOGS}/{log.id_log}/polish", headers=bearer(c.lead))


async def _petakan_kalender(c: Ctx):
    badan = {
        "gcal_event_id": "evt-ro",
        "work_type": "Project",
        "project_id": c.id,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Rapat",
    }
    return await c.api.client.post(f"{CAL}/map", json=badan, headers=bearer(c.lead))


async def _buat_subtask(c: Ctx):
    return await c.api.client.post(
        f"{PROYEK}/{c.id}/subtasks", json={"title": "Baru"}, headers=bearer(c.lead)
    )


async def _ubah_status_subtask(c: Ctx):
    st = await c.subtask()
    return await c.api.client.patch(
        f"{PROYEK}/subtasks/{st.id_subtask}/status",
        json={"status": "in_progress"},
        headers=bearer(c.lead),
    )


async def _assign_subtask(c: Ctx):
    st = await c.subtask()
    return await c.api.client.patch(
        f"{PROYEK}/subtasks/{st.id_subtask}/assign",
        json={"assigned_sa": None},
        headers=bearer(c.lead),
    )


async def _hapus_subtask(c: Ctx):
    st = await c.subtask()
    return await c.api.client.delete(f"{PROYEK}/subtasks/{st.id_subtask}", headers=bearer(c.lead))


async def _buat_dokumen(c: Ctx):
    badan = {"doc_type": "PropTek", "gdrive_link": "https://drive.example/x", "folder_type": "Solutions"}
    return await c.api.client.post(f"{PROYEK}/{c.id}/documents", json=badan, headers=bearer(c.lead))


async def _ubah_status_dokumen(c: Ctx):
    dok = await c.dokumen()
    return await c.api.client.patch(
        f"{API}/documents/{dok.id_doc}/status",
        json={"new_status": "Reviewed"},
        headers=bearer(c.lead),
    )


async def _tambah_butir_requirement(c: Ctx):
    return await c.api.client.post(
        f"{PROYEK}/{c.id}/requirement/items",
        json={"kategori": "Asumsi", "butir": "Manual"},
        headers=bearer(c.lead),
    )


async def _generate_ulang_requirement(c: Ctx):
    return await c.api.client.post(f"{PROYEK}/{c.id}/requirement/regenerate", headers=bearer(c.lead))


async def _pertahankan_versi_requirement(c: Ctx):
    return await c.api.client.post(
        f"{PROYEK}/{c.id}/requirement/keep-version", headers=bearer(c.lead)
    )


AKSI_TULIS = {
    "log": _buat_log,
    "polish_ulang": _polish_ulang,
    "kalender": _petakan_kalender,
    "subtask_buat": _buat_subtask,
    "subtask_status": _ubah_status_subtask,
    "subtask_assign": _assign_subtask,
    "subtask_hapus": _hapus_subtask,
    "dokumen_buat": _buat_dokumen,
    "dokumen_status": _ubah_status_dokumen,
    "requirement_butir": _tambah_butir_requirement,
    "requirement_regenerate": _generate_ulang_requirement,
    "requirement_keep": _pertahankan_versi_requirement,
}
# Aksi yang harus tetap boleh sebelum `Closed`, termasuk `Handed Over` (spec §2.0).
AKSI_BOLEH_SAAT_HANDED_OVER = ["log", "kalender", "subtask_buat", "subtask_status", "dokumen_buat"]


@pytest.mark.parametrize("status", ["Closed", "Lost"])
@pytest.mark.parametrize("aksi", list(AKSI_TULIS))
async def test_aksi_tulis_ditolak_409_pada_closed_dan_lost(ctx_pabrik, status, aksi):
    c = await ctx_pabrik(status)

    resp = await AKSI_TULIS[aksi](c)

    assert resp.status_code == 409, resp.text
    assert "read-only" in resp.json()["message"]


@pytest.mark.parametrize("aksi", AKSI_BOLEH_SAAT_HANDED_OVER)
async def test_aksi_tulis_diizinkan_pada_handed_over(ctx_pabrik, fake_llm, aksi):
    c = await ctx_pabrik("Handed Over")

    resp = await AKSI_TULIS[aksi](c)

    assert resp.status_code in (200, 201), resp.text


async def test_penolakan_read_only_tidak_menyimpan_apa_pun(ctx_pabrik):
    c = await ctx_pabrik("Closed")

    await _buat_log(c)
    await _buat_subtask(c)
    await _buat_dokumen(c)

    for model, kolom in ((ActivityLog, ActivityLog.id_project), (Subtask, Subtask.id_project)):
        jumlah = (
            await c.db.execute(select(func.count()).select_from(model).where(kolom == c.id))
        ).scalar_one()
        assert jumlah == 0
    jumlah_dok = (
        await c.db.execute(
            select(func.count()).select_from(Document).where(Document.id_project == c.id)
        )
    ).scalar_one()
    assert jumlah_dok == 0


async def test_cek_akses_403_lebih_dulu_dari_read_only(ctx_pabrik, db_session):
    c = await ctx_pabrik("Closed")
    luar = await buat_user(db_session, "SA")  # SA tidak ditugaskan: tidak berhak tulis
    badan = {
        "id_project": c.id,
        "project_phase": "Pre-Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1",
        "raw_notes": "x",
    }

    resp = await c.api.client.post(LOGS, json=badan, headers=bearer(luar))

    assert resp.status_code == 403


async def test_baca_tetap_boleh_pada_closed(ctx_pabrik):
    c = await ctx_pabrik("Closed")

    resp = await c.api.client.get(f"{PROYEK}/{c.id}/subtasks", headers=bearer(c.lead))

    assert resp.status_code == 200
