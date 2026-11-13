"""
Test tiket 5B-5 (#37): sumber berubah setelah override → notifikasi sekali + banner dua aksi.

Seam: (1) titik masuk background `resummarize_if_source_changed` (sesi DB, LLM, dan
`notification_service.send_notification` di-mock di boundary); (2) HTTP API TestClient:
GET daftar dokumen (flag `source_changed`), POST keep-version, dan POST regenerate (#34).
Hanya menegaskan perilaku eksternal: notifikasi terkirim ke siapa/berapa kali, isi/hash
Requirement, flag di respons.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User
from app.services import requirement_generator as rg
from tests.test_doc_ready import _make_project, _make_user, _result_scalar
from tests.test_projects_questionnaire_api import FakeSession, _result, jawaban_kuat
from tests.test_requirement_documents_api import PRJ, _requirement
from tests.test_requirement_generate_api import _Ctx, _source, llm_ok
from tests.test_requirement_resummarize import BARU
from tests.test_requirement_resummarize import _proyek as _proyek_resum
from tests.test_requirement_resummarize import _requirement as _req_resum

SA_ID = uuid.uuid4()
STALE = "0" * 64


def _user(role, email):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role
    u.email = email
    return u


def _jalankan(proyek, requirement, sources, sa=None, leads=(), panggil=1):
    """Jalankan titik masuk `panggil` kali; return (provider LLM, mock notifikasi)."""
    bg = FakeSession()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sources)
        if "FROM documents" in sql:
            return _result(one=requirement)
        if "FROM users" in sql:
            return _result(items=list(leads)) if "WHERE users.role" in sql else _result(one=sa)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    provider = MagicMock()
    provider.complete_text = AsyncMock(return_value=llm_ok(BARU))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
    ), patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()), patch(
        "app.services.requirement_generator.notification_service.send_notification",
        new_callable=AsyncMock,
    ) as notify:
        for _ in range(panggil):
            asyncio.run(rg.resummarize_if_source_changed("PRJ-X"))
    return provider, notify


def _events(notify):
    return [c.args[0] for c in notify.await_args_list]


# --------------------------------------------------------------------------- notifikasi
def test_override_dan_sumber_berubah_notifikasi_ke_sa_ditugaskan_konten_tetap():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True, stale=True)
    proyek = _proyek_resum()
    sa = _user("SA", "sa@x.id")
    proyek.assigned_sa = sa.id
    provider, notify = _jalankan(proyek, req, sumber, sa=sa)

    [event] = _events(notify)
    assert event.recipient_user_id == sa.id
    assert event.recipient_email == "sa@x.id"
    assert event.event_type.value == "status_change"
    assert event.reference_id == "PRJ-X"
    assert event.metadata["requirement_source_changed"] is True
    assert "Requirement" in event.metadata["message"]
    # Konten dan hash tersimpan tidak berubah, LLM tidak dipanggil.
    provider.complete_text.assert_not_called()
    assert [i["butir"] for i in req.content] == ["Butir lama"]
    assert req.source_hash == STALE
    assert req.is_overridden is True


def test_tanpa_sa_notifikasi_ke_semua_lead_sa():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True, stale=True)
    lead1, lead2 = _user("Lead_SA", "l1@x.id"), _user("Lead_SA", "l2@x.id")
    proyek = _proyek_resum()
    proyek.assigned_sa = None
    _, notify = _jalankan(proyek, req, sumber, leads=[lead1, lead2])
    assert {e.recipient_user_id for e in _events(notify)} == {lead1.id, lead2.id}
    assert all(e.metadata["requirement_source_changed"] for e in _events(notify))


def test_notifikasi_hanya_sekali_per_hash_basi_yang_sama():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True, stale=True)
    proyek = _proyek_resum()
    sa = _user("SA", "sa@x.id")
    proyek.assigned_sa = sa.id
    _, notify = _jalankan(proyek, req, sumber, sa=sa, panggil=3)
    assert notify.await_count == 1
    assert req.source_changed_notified_hash == rg.compute_source_hash(
        jawaban_kuat(), [("MoM", "MoM baru")]
    )


def test_hash_basi_berubah_lagi_mengirim_notifikasi_ulang():
    sa = _user("SA", "sa@x.id")
    proyek = _proyek_resum()
    proyek.assigned_sa = sa.id
    sumber1 = [_source(text="MoM revisi 1")]
    req = _req_resum(jawaban_kuat(), sumber1, overridden=True, stale=True)
    _, notify1 = _jalankan(proyek, req, sumber1, sa=sa)
    assert notify1.await_count == 1

    sumber2 = [_source(text="MoM revisi 2")]  # hash basi baru; hash notifikasi lama terbawa
    _, notify2 = _jalankan(proyek, req, sumber2, sa=sa)
    assert notify2.await_count == 1


def test_final_tanpa_override_hanya_notifikasi_tidak_di_resummarize():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, status="Final", overridden=False, stale=True)
    proyek = _proyek_resum()
    sa = _user("SA", "sa@x.id")
    proyek.assigned_sa = sa.id
    provider, notify = _jalankan(proyek, req, sumber, sa=sa)
    assert notify.await_count == 1
    provider.complete_text.assert_not_called()
    assert [i["butir"] for i in req.content] == ["Butir lama"]
    assert req.source_hash == STALE


def test_override_tapi_hash_sama_tidak_ada_notifikasi():
    sumber = [_source(text="MoM")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True)
    _, notify = _jalankan(_proyek_resum(), req, sumber)
    notify.assert_not_called()


def test_draft_tanpa_override_di_resummarize_tanpa_notifikasi():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, stale=True)
    provider, notify = _jalankan(_proyek_resum(), req, sumber)
    notify.assert_not_called()
    provider.complete_text.assert_awaited_once()


def test_kegagalan_kirim_notifikasi_tidak_melempar_dan_dicoba_lagi_kemudian():
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True, stale=True)
    proyek = _proyek_resum()
    sa = _user("SA", "sa@x.id")
    proyek.assigned_sa = sa.id
    bg = FakeSession()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sumber)
        if "FROM documents" in sql:
            return _result(one=req)
        if "FROM users" in sql:
            return _result(one=sa)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.requirement_generator.notification_service.send_notification",
        new=AsyncMock(side_effect=RuntimeError("smtp down")),
    ):
        asyncio.run(rg.resummarize_if_source_changed("PRJ-X"))
    assert req.source_changed_notified_hash is None  # belum ditandai → pemicu berikut mencoba lagi


# --------------------------------------------------------------------------- API
@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _setup(user, results):
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return session


def _docs_result(docs):
    r = MagicMock()
    r.scalars.return_value.all.return_value = docs
    return r


def _sumber_hash(sources):
    return rg.compute_source_hash(
        jawaban_kuat(), [(s.doc_type, s.extracted_text) for s in sources]
    )


def _project_with_answers(assigned_sa=None):
    p = _make_project()
    p.id_project = PRJ
    p.assigned_sa = assigned_sa
    p.qualification_answers = jawaban_kuat()
    p.collaborators = []
    return p


@pytest.mark.parametrize(
    "status,overridden,hash_basi,diharapkan",
    [
        ("Draft", True, True, True),
        ("Final", False, True, True),
        ("Draft", True, False, False),
        ("Final", False, False, False),
        ("Draft", False, True, False),  # belum override: jalur re-summarize otomatis
    ],
)
def test_get_dokumen_mengembalikan_flag_source_changed(status, overridden, hash_basi, diharapkan):
    sumber = [_source(text="MoM")]
    req = _requirement(status)
    req.is_overridden = overridden
    req.source_hash = STALE if hash_basi else _sumber_hash(sumber)
    sa = _make_user("SA")
    results = [
        _result_scalar(_project_with_answers(assigned_sa=sa.id)),
        _docs_result([req]),
        _result(items=sumber),
    ]
    _setup(sa, results)
    resp = TestClient(app).get(f"/api/v1/projects/{PRJ}/documents")
    assert resp.status_code == 200
    [doc] = resp.json()["data"]["documents"]
    assert doc["source_changed"] is diharapkan


def _keep(user, project, req, sumber):
    session = _setup(
        user, [_result_scalar(project), _result_scalar(req), _result(items=sumber)]
    )
    session.commit = AsyncMock()
    resp = TestClient(app).post(f"/api/v1/projects/{PRJ}/requirement/keep-version")
    return resp, session


def test_pertahankan_versi_saya_memperbarui_hash_tanpa_mengubah_konten():
    sumber = [_source(text="MoM baru")]
    req = _requirement()
    req.is_overridden = True
    req.source_hash = STALE
    konten_lama = [dict(i) for i in req.content]
    sa = _make_user("SA")
    resp, session = _keep(sa, _project_with_answers(assigned_sa=sa.id), req, sumber)
    assert resp.status_code == 200
    assert req.source_hash == _sumber_hash(sumber)
    assert req.content == konten_lama
    assert req.is_overridden is True
    assert resp.json()["data"]["source_changed"] is False
    session.commit.assert_awaited()


def test_pertahankan_versi_berlaku_untuk_final_tanpa_override():
    sumber = [_source(text="MoM baru")]
    req = _requirement("Final")
    req.source_hash = STALE
    resp, _ = _keep(_make_user("Lead_SA"), _project_with_answers(), req, sumber)
    assert resp.status_code == 200
    assert req.source_hash == _sumber_hash(sumber)
    assert req.status == "Final"


def test_pertahankan_versi_ditolak_bila_belum_override_dan_bukan_final():
    req = _requirement("Draft")
    req.source_hash = STALE
    resp, _ = _keep(_make_user("Lead_SA"), _project_with_answers(), req, [_source(text="x")])
    assert resp.status_code == 409
    assert req.source_hash == STALE


@pytest.mark.parametrize("role", ["Sales", "SA"])
def test_pertahankan_versi_ditolak_untuk_peran_tidak_berhak(role):
    req = _requirement()
    req.is_overridden = True
    req.source_hash = STALE
    # SA yang bukan ditugaskan pada proyek ini juga ditolak.
    resp, _ = _keep(
        _make_user(role), _project_with_answers(assigned_sa=uuid.uuid4()), req, []
    )
    assert resp.status_code == 403
    assert req.source_hash == STALE


def test_pertahankan_versi_404_bila_requirement_belum_ada():
    session = _setup(
        _make_user("Lead_SA"), [_result_scalar(_project_with_answers()), _result_scalar(None)]
    )
    session.commit = AsyncMock()
    resp = TestClient(app).post(f"/api/v1/projects/{PRJ}/requirement/keep-version")
    assert resp.status_code == 404


def test_generate_ulang_menimpa_konten_dan_menghapus_override_lalu_banner_hilang():
    """Aksi 'Generate ulang (timpa edit saya)' = endpoint regenerate #34 + generate replace."""
    sumber = [_source(text="MoM baru")]
    req = _req_resum(jawaban_kuat(), sumber, overridden=True, stale=True)
    proyek = _proyek_resum()
    proyek.requirement_generation_status = "pending"
    bg = FakeSession()

    async def _execute(stmt, *a, **k):
        sql = str(stmt)
        if "FROM source_documents" in sql:
            return _result(items=sumber)
        if "FROM documents" in sql:
            return _result(one=req)
        return _result(one=proyek)

    bg.execute = AsyncMock(side_effect=_execute)
    provider = MagicMock()
    provider.complete_text = AsyncMock(return_value=llm_ok(BARU))
    with patch("app.core.database.AsyncSessionLocal", new=lambda: _Ctx(bg)), patch(
        "app.services.requirement_generator.llm_factory.get_provider", return_value=provider
    ), patch("app.services.requirement_generator.asyncio.sleep", new=AsyncMock()):
        asyncio.run(rg.generate_pending_requirement("PRJ-X", True))
    assert [i["butir"] for i in req.content] == ["Butir hasil re-summarize"]
    assert req.is_overridden is False
    assert req.source_hash == rg.compute_source_hash(jawaban_kuat(), [("MoM", "MoM baru")])
    assert rg.is_source_changed(req, req.source_hash) is False
