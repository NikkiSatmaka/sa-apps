"""
Akses UBAH_PROYEK pada PATCH proyek dan TAMBAH_KOLABORATOR pada POST collaborators
(tiket #91, spec #87).

Matriks peran × aksi di Postgres nyata:
- PATCH proyek: Sales PIC, SA ditugaskan, Lead_SA, Admin, dan collaborator contributor berhasil;
  collaborator viewer serta pihak tak terkait mendapat 403 dan TIDAK ada kolom proyek yang berubah.
- Tambah collaborator: Lead_SA, Admin, SA ditugaskan, dan Sales PIC proyek itu berhasil; collaborator
  (viewer/contributor) dan SA/Sales tak terkait mendapat 403 tanpa baris collaborator baru.
  Aturan peran-target (Sales→Sales, SA→SA, dst.) tetap berlaku untuk pihak berhak.

Penolakan harus tanpa efek samping: sesi request di-commit (`komit_sesi_request`) supaya
penulisan-lalu-403 terlihat, dan fake LLM/Drive/Gmail tidak boleh dipanggil.
"""

import pytest
from sqlalchemy import func, inspect, select

from app.models import Project, User
from app.models.project_collaborator import ProjectCollaborator
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_user, simpan
from tests.integration.support_akses import ID_PROYEK

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

PESAN_403 = "Anda tidak memiliki akses ke proyek ini."

# Hubungan yang boleh mengubah proyek (matriks #87) dan yang tidak.
AKTOR_UBAH = ["sales_pic", "sa", "lead", "admin", "kolab_contrib"]
AKTOR_UBAH_DITOLAK = ["kolab_viewer", "kolab_lain", "sales_luar", "sa_luar"]

# Hubungan yang boleh menambah collaborator dan yang tidak.
AKTOR_TAMBAH = ["sales_pic", "sa", "lead", "admin"]
AKTOR_TAMBAH_DITOLAK = ["kolab_viewer", "kolab_contrib", "kolab_lain", "sales_luar", "sa_luar"]

BODY_UBAH = {
    "project_name": "Nama Diubah",
    "customer_name": "Customer Diubah",
    "estimasi_nilai": 123456,
    "target_submit": "2031-01-31",
    "bant_detail": {"catatan": "ditambah lewat PATCH"},
}


def _url_proyek() -> str:
    return f"/api/v1/projects/{ID_PROYEK}"


def _url_kolab() -> str:
    return f"/api/v1/projects/{ID_PROYEK}/collaborators"


async def _snapshot(db, proyek: Project) -> dict:
    """Nilai seluruh kolom proyek dari baris di DB (bukan dari objek identity-map yang basi)."""
    await db.refresh(proyek)
    return {c.key: getattr(proyek, c.key) for c in inspect(Project).column_attrs}


async def _jumlah_kolab(db) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ProjectCollaborator)
            .where(ProjectCollaborator.id_project == ID_PROYEK)
        )
    ).scalar_one()


async def _target(db, peran: str, nama: str) -> User:
    user = bangun_user(role=peran, email=f"{nama}@target.test", google_id=f"g-{nama}")
    await simpan(db, user)
    return user


def _peran_target(aktor: str, skenario) -> str:
    """Peran target yang lolos aturan peran-target untuk `aktor` (agar yang diuji murni akses)."""
    return "Sales" if skenario.aktor[aktor].role == "Sales" else "SA"


# ---------------------------------------------------------------- PATCH proyek


@pytest.mark.parametrize("aktor", AKTOR_UBAH)
async def test_pihak_berhak_mengubah_proyek(api, db_session, skenario_akses, aktor):
    resp = await api.client.patch(
        _url_proyek(), json=BODY_UBAH, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 200, resp.text
    sesudah = await _snapshot(db_session, skenario_akses.proyek)
    assert sesudah["project_name"] == "Nama Diubah"
    assert sesudah["customer_name"] == "Customer Diubah"
    assert float(sesudah["estimasi_nilai"]) == 123456
    assert str(sesudah["target_submit"]) == "2031-01-31"
    assert sesudah["bant_detail"]["catatan"] == "ditambah lewat PATCH"


@pytest.mark.parametrize("aktor", AKTOR_UBAH_DITOLAK)
async def test_pihak_tak_berhak_ubah_proyek_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    sebelum = await _snapshot(db_session, skenario_akses.proyek)

    resp = await api.client.patch(
        _url_proyek(), json=BODY_UBAH, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    # tidak ada satu kolom pun yang berubah (termasuk updated_at)
    assert await _snapshot(db_session, skenario_akses.proyek) == sebelum
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


async def test_viewer_ditolak_ubah_proyek_walau_bukan_field_sensitif(
    api, db_session, skenario_akses
):
    """Satu field saja pun ditolak: viewer read-only, bukan hanya untuk field tertentu."""
    sebelum = await _snapshot(db_session, skenario_akses.proyek)

    resp = await api.client.patch(
        _url_proyek(),
        json={"project_name": "Hanya Nama"},
        headers=skenario_akses.header("kolab_viewer"),
    )

    assert resp.status_code == 403
    assert await _snapshot(db_session, skenario_akses.proyek) == sebelum


async def test_ubah_proyek_tak_ada_404(api, skenario_akses):
    resp = await api.client.patch(
        "/api/v1/projects/PRJ-TIDAK-ADA",
        json=BODY_UBAH,
        headers=skenario_akses.header("kolab_viewer"),
    )
    assert resp.status_code == 404


async def test_ubah_proyek_tanpa_login_ditolak(api, skenario_akses):
    resp = await api.client.patch(_url_proyek(), json=BODY_UBAH)
    assert resp.status_code in (401, 403)


# ----------------------------------------------------------- POST collaborators


@pytest.mark.parametrize("aktor", AKTOR_TAMBAH)
async def test_pihak_berhak_menambah_collaborator(api, db_session, skenario_akses, aktor):
    target = await _target(db_session, _peran_target(aktor, skenario_akses), f"t-{aktor}")
    awal = await _jumlah_kolab(db_session)

    resp = await api.client.post(
        _url_kolab(), json={"user_id": str(target.id)}, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 200, resp.text
    assert await _jumlah_kolab(db_session) == awal + 1
    baris = (
        await db_session.execute(
            select(ProjectCollaborator).where(
                ProjectCollaborator.id_project == ID_PROYEK,
                ProjectCollaborator.user_id == target.id,
            )
        )
    ).scalar_one()
    assert (baris.role, baris.added_by) == ("viewer", skenario_akses.aktor[aktor].id)


@pytest.mark.parametrize("aktor", AKTOR_TAMBAH_DITOLAK)
async def test_pihak_tak_berhak_tambah_collaborator_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, aktor
):
    target = await _target(db_session, _peran_target(aktor, skenario_akses), f"t-{aktor}")
    awal = await _jumlah_kolab(db_session)

    resp = await api.client.post(
        _url_kolab(), json={"user_id": str(target.id)}, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    assert await _jumlah_kolab(db_session) == awal
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


async def test_akses_dicek_sebelum_target_user_dicari(api, skenario_akses):
    """Pihak luar tidak boleh tahu apakah user target ada: 403, bukan 404."""
    import uuid

    resp = await api.client.post(
        _url_kolab(),
        json={"user_id": str(uuid.uuid4())},
        headers=skenario_akses.header("sa_luar"),
    )
    assert resp.status_code == 403


async def test_tambah_collaborator_proyek_tak_ada_404(api, skenario_akses):
    resp = await api.client.post(
        "/api/v1/projects/PRJ-TIDAK-ADA/collaborators",
        json={"user_id": str(skenario_akses.aktor["sa"].id)},
        headers=skenario_akses.header("sa_luar"),
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("aktor", "peran_target"),
    [("sales_pic", "SA"), ("sa", "Sales"), ("sa", "Lead_SA")],
)
async def test_aturan_peran_target_tetap_berlaku_untuk_pihak_berhak(
    api, db_session, skenario_akses, aktor, peran_target
):
    """Sales PIC hanya menambah Sales, SA ditugaskan hanya SA — walau berhak atas proyek."""
    target = await _target(db_session, peran_target, f"tt-{aktor}-{peran_target}")
    awal = await _jumlah_kolab(db_session)

    resp = await api.client.post(
        _url_kolab(), json={"user_id": str(target.id)}, headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403
    assert await _jumlah_kolab(db_session) == awal


async def test_tambah_collaborator_contributor_oleh_pihak_berhak(api, db_session, skenario_akses):
    target = await _target(db_session, "SA", "t-contrib")
    resp = await api.client.post(
        _url_kolab(),
        json={"user_id": str(target.id), "role": "contributor"},
        headers=skenario_akses.header("sa"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "contributor"
