# ruff: noqa: F811  -- fixture bersama diimpor lalu dipakai sebagai argumen (pola pytest)
"""
Filter `involved=me` pada daftar proyek dan ringkasan status (issue #109, ADR 0011/0014).

Seam: HTTP API terhadap Postgres nyata. Cocok bila user adalah `created_by`, `sales_pic`,
`product_pic`, `lead_sa`, SA utama, SA tambahan (ProjectAssignments), atau collaborator.
"""

import pytest

from app.models import ProjectAssignment
from tests.integration.kualifikasi_support import (  # noqa: F401
    api,
    bearer,
    jadikan_kolaborator,
    tanpa_tunggu,
    user_baru,
)
from tests.integration.model_helpers import bangun_project, simpan

API = "/api/v1"

pytestmark = pytest.mark.usefixtures("tanpa_tunggu")


async def _ids(api, user, query: str = "involved=me", path: str = "projects") -> set[str]:
    resp = await api.client.get(f"{API}/{path}?{query}", headers=bearer(user))
    assert resp.status_code == 200, resp.text
    return {d["id_project"] for d in resp.json()["data"]}


async def _proyek_orang_lain(db, **o):
    """Proyek yang tidak melibatkan `target`: semua peran diisi user lain."""
    pembuat = await user_baru(db, "Product")
    p = bangun_project(None, created_by=pembuat.id, product_pic=pembuat.id, **o)
    await simpan(db, p)
    return p


@pytest.mark.parametrize(
    "role,kolom",
    [
        ("Sales", "created_by"),
        ("Sales", "sales_pic"),
        ("Product", "product_pic"),
        ("Lead_SA", "lead_sa"),
        ("SA", "assigned_sa"),
    ],
)
async def test_involved_me_cocok_untuk_kolom_orang_di_project(api, db_session, role, kolom):
    target = await user_baru(db_session, role)
    pembuat = await user_baru(db_session, "Product")
    dasar = {"created_by": pembuat.id, "product_pic": pembuat.id}
    dasar[kolom] = target.id
    terlibat = bangun_project(None, **dasar)
    await simpan(db_session, terlibat)
    tak_terkait = await _proyek_orang_lain(db_session)

    hasil = await _ids(api, target)

    assert hasil == {terlibat.id_project}
    assert tak_terkait.id_project not in hasil


async def test_involved_me_cocok_untuk_sa_tambahan(api, db_session):
    sa = await user_baru(db_session, "SA")
    lead = await user_baru(db_session, "Lead_SA")
    proyek = await _proyek_orang_lain(db_session)
    await simpan(
        db_session,
        ProjectAssignment(id_project=proyek.id_project, user_id=sa.id, added_by=lead.id),
    )
    await _proyek_orang_lain(db_session)

    assert await _ids(api, sa) == {proyek.id_project}


async def test_involved_me_cocok_untuk_collaborator(api, db_session):
    viewer = await user_baru(db_session, "Sales")
    penambah = await user_baru(db_session, "Lead_SA")
    proyek = await _proyek_orang_lain(db_session)
    await jadikan_kolaborator(db_session, proyek.id_project, viewer, penambah)
    await _proyek_orang_lain(db_session)

    assert await _ids(api, viewer) == {proyek.id_project}


async def test_involved_me_kosong_bila_tidak_terkait(api, db_session):
    orang_asing = await user_baru(db_session, "Sales")
    await _proyek_orang_lain(db_session)

    assert await _ids(api, orang_asing) == set()
    # Tanpa filter: baca tetap terbuka (ADR 0011).
    assert len(await _ids(api, orang_asing, query="sort=-updated_at")) == 1


async def test_involved_me_tidak_menggandakan_baris_untuk_project_multi_hubungan(
    api, db_session
):
    user = await user_baru(db_session, "SA")
    lead = await user_baru(db_session, "Lead_SA")
    proyek = bangun_project(
        user.id, created_by=user.id, product_pic=user.id, lead_sa=user.id, assigned_sa=user.id
    )
    await simpan(db_session, proyek)
    await simpan(
        db_session,
        ProjectAssignment(id_project=proyek.id_project, user_id=user.id, added_by=lead.id),
    )
    await jadikan_kolaborator(db_session, proyek.id_project, user, lead)

    resp = await api.client.get(f"{API}/projects?involved=me", headers=bearer(user))
    ringkasan = await api.client.get(
        f"{API}/projects/status-summary?involved=me", headers=bearer(user)
    )

    assert [d["id_project"] for d in resp.json()["data"]] == [proyek.id_project]
    assert sum(r["count"] for r in ringkasan.json()["data"]) == 1


async def test_involved_me_berlaku_untuk_admin_dan_lead_sa(api, db_session):
    admin = await user_baru(db_session, "Admin")
    lead = await user_baru(db_session, "Lead_SA")
    milik_admin = bangun_project(
        None, created_by=admin.id, product_pic=admin.id, status="Intake"
    )
    await simpan(db_session, milik_admin)
    await _proyek_orang_lain(db_session)

    assert await _ids(api, admin) == {milik_admin.id_project}
    assert await _ids(api, lead) == set()


async def test_status_summary_involved_me_menghitung_hanya_proyek_terlibat(api, db_session):
    sales = await user_baru(db_session, "Sales")
    mine = bangun_project(sales.id)
    await simpan(db_session, mine)
    await _proyek_orang_lain(db_session)

    ringkasan = await api.client.get(
        f"{API}/projects/status-summary?involved=me", headers=bearer(sales)
    )

    assert sum(r["count"] for r in ringkasan.json()["data"]) == 1
