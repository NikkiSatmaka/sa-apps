"""
Penyelarasan akhir kebijakan akses proyek (tiket #92, spec #87).

1. Polish ulang activity log: kepemilikan log TETAP ditegakkan (orang lain → 404) DAN penulis harus
   masih punya akses TULIS ke proyek log tersebut. Penulis yang kini viewer / kehilangan akses
   ditolak 403 SEBELUM panggilan LLM, log tidak berubah.
2. Rute yang dimigrasikan dari pemeriksa buatan sendiri ke titik keputusan bersama berperilaku
   setara: matriks peran × aksi di bawah mengunci aturan lama (tidak ada yang melonggar).
3. Rute yang tetap menjadi pengecualian SAH (role gate Lead_SA/Admin) benar-benar menolak semua
   peran lain TANPA efek samping.

Penolakan = 403 TANPA efek samping: sesi request di-commit (`komit_sesi_request`) supaya
penulisan-lalu-403 terlihat; fake LLM/Drive/Gmail tidak boleh dipanggil.
"""

import pytest
from sqlalchemy import func, inspect, select

from app.models import (
    ActivityLog,
    AuditLog,
    Document,
    NotificationLog,
    Project,
    Subtask,
)
from app.models.project_collaborator import ProjectCollaborator
from tests.integration.b6_support import komit_sesi_request  # noqa: F401  (fixture)
from tests.integration.model_helpers import bangun_log, bangun_subtask
from tests.integration.support_akses import ID_PROYEK

API = "/api/v1"
SEMUA_AKTOR = [
    "sales_pic",
    "sa",
    "lead",
    "admin",
    "kolab_viewer",
    "kolab_contrib",
    "kolab_lain",
    "sales_luar",
    "sa_luar",
]

pytestmark = pytest.mark.usefixtures("komit_sesi_request")

PESAN_403 = "Anda tidak memiliki akses ke proyek ini."
HASIL_POLISH = {
    "discussion_points": ["Bahas arsitektur"],
    "action_items": [{"description": "Kirim BOQ", "pic": "Budi"}],
}


async def _snapshot(db, model_obj) -> dict:
    await db.refresh(model_obj)
    return {c.key: getattr(model_obj, c.key) for c in inspect(type(model_obj)).column_attrs}


# ---------------------------------------------------------------- polish ulang


@pytest.mark.parametrize("penulis", ["lead", "admin", "sa", "kolab_contrib"])
async def test_polish_ulang_penulis_yang_masih_berhak_tulis_berhasil(
    api, db_session, skenario_akses, fake_llm, penulis
):
    user = skenario_akses.aktor[penulis]
    log = bangun_log(user.id, ID_PROYEK, ai_polished_notes=None)
    db_session.add(log)
    await db_session.commit()
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish", headers=skenario_akses.header(penulis)
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(log)
    assert log.ai_polished_notes == HASIL_POLISH


@pytest.mark.parametrize("penulis", ["kolab_viewer", "sales_pic", "kolab_lain", "sales_luar", "sa_luar"])
async def test_polish_ulang_penulis_tanpa_akses_tulis_403_tanpa_efek_samping(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, penulis
):
    """Penulis log yang kini viewer / bukan lagi pihak proyek: ditolak SEBELUM LLM."""
    user = skenario_akses.aktor[penulis]
    log = bangun_log(user.id, ID_PROYEK, ai_polished_notes=None)
    db_session.add(log)
    await db_session.commit()
    sebelum = await _snapshot(db_session, log)

    resp = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish", headers=skenario_akses.header(penulis)
    )

    assert resp.status_code == 403
    assert resp.json()["message"] == PESAN_403
    assert await _snapshot(db_session, log) == sebelum
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


async def test_polish_ulang_orang_lain_tetap_404_walau_berhak_tulis(
    api, db_session, skenario_akses, fake_llm
):
    """Kepemilikan log tetap ditegakkan: Lead_SA bukan penulis → 404, bukan 200."""
    penulis = skenario_akses.aktor["kolab_contrib"]
    log = bangun_log(penulis.id, ID_PROYEK, ai_polished_notes=None)
    db_session.add(log)
    await db_session.commit()

    resp = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish", headers=skenario_akses.header("lead")
    )

    assert resp.status_code == 404
    assert fake_llm.jumlah() == 0


async def test_polish_ulang_log_non_project_tetap_hanya_kepemilikan(
    api, db_session, skenario_akses, fake_llm
):
    """Log Non-Project tidak terkait proyek: tidak ada cek akses proyek, hanya kepemilikan."""
    user = skenario_akses.aktor["sales_luar"]
    log = bangun_log(
        user.id, None, work_type="Non-Project", project_phase=None, ai_polished_notes=None
    )
    db_session.add(log)
    await db_session.commit()
    fake_llm.sukses("structure_text", HASIL_POLISH)

    resp = await api.client.post(
        f"/api/v1/activity-logs/{log.id_log}/polish", headers=skenario_akses.header("sales_luar")
    )

    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------- rute yang dimigrasikan
#
# Aturan masing-masing rute SEBELUM dimigrasikan ke titik keputusan bersama dikunci di sini
# (matriks peran × aksi). Migrasi tidak boleh melonggarkan satu sel pun. Aktor `kolab_*` berperan
# SA tetapi BUKAN SA ditugaskan; `sales_luar` berperan Sales tetapi bukan PIC.

BODY_BUTIR = {"kategori": "Fungsional", "butir": "Sistem harus bisa X"}


async def _keadaan(db, proyek: Project) -> dict:
    """Seluruh kolom proyek + jumlah baris yang bisa ditulis rute (audit, notifikasi, dst.)."""
    await db.refresh(proyek)

    async def hitung(model):
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()

    return {
        "proyek": {c.key: getattr(proyek, c.key) for c in inspect(Project).column_attrs},
        "audit": await hitung(AuditLog),
        "notif": await hitung(NotificationLog),
        "kolab": await hitung(ProjectCollaborator),
        "dokumen": await hitung(Document),
        "subtask": await hitung(Subtask),
        "log": await hitung(ActivityLog),
    }


# (nama, method, path, body, aktor berhak, status sukses yang diharapkan untuk berhak)
RUTE_MIGRASI = [
    # BACA terbuka untuk semua pengguna terautentikasi (keputusan 2026-11-10).
    ("detail-proyek", "GET", "/projects/{p}", None, list(SEMUA_AKTOR), {200}),
    ("daftar-kolaborator", "GET", "/projects/{p}/collaborators", None, list(SEMUA_AKTOR), {200}),
    ("hapus-kolaborator", "DELETE", "/projects/{p}/collaborators/{kolab_lain_id}", None,
     ["sales_pic", "sa", "lead", "admin"], {200, 404}),
    # Gerbang UBAH_STATUS + hak per transisi (#121): Assigned -> Submitted hanya SA ditugaskan,
    # Lead_SA, Admin (Sales PIC 403). Proyek uji tanpa dokumen wajib, jadi yang berhak mencapai
    # syarat dokumen (400); matriks per transisi lengkap: `test_workflow_transisi.py`.
    ("ubah-status", "PATCH", "/projects/{p}/status", {"new_status": "Submitted"},
     ["sa", "lead", "admin"], {400}),
    ("status-handover", "GET", "/projects/{p}/handover-status", None,
     ["sa", "lead", "admin"], {200}),
    ("picu-handover", "POST", "/projects/{p}/handover", None,
     ["sa", "lead", "admin"], {400}),
    ("requirement-regenerate", "POST", "/projects/{p}/requirement/regenerate", None,
     ["sa", "lead", "admin"], {409}),
    ("requirement-keep-version", "POST", "/projects/{p}/requirement/keep-version", None,
     ["sa", "lead", "admin"], {404}),
    ("requirement-tambah-butir", "POST", "/projects/{p}/requirement/items", BODY_BUTIR,
     ["sa", "lead", "admin"], {404}),
    ("requirement-ubah-butir", "PUT", "/projects/{p}/requirement/items/abc12345", BODY_BUTIR,
     ["sa", "lead", "admin"], {404}),
    ("requirement-hapus-butir", "DELETE", "/projects/{p}/requirement/items/abc12345", None,
     ["sa", "lead", "admin"], {404}),
    ("jawaban-kuesioner", "PUT", "/projects/{p}/qualification-answers", {},
     ["sales_pic", "lead", "admin"], {400}),
    # #147: SA ditugaskan boleh membuat subtask (spec §2.0/§2.5); dulu role gate Lead_SA/Admin
    # (SAH-10), kini lewat titik keputusan. Sales PIC, collaborator, SA luar: 403.
    ("buat-subtask", "POST", "/projects/{p}/subtasks", {"title": "Subtask uji"},
     ["sa", "lead", "admin"], {201}),
]


def _kasus(daftar):
    for nama, method, path, body, berhak, ok in daftar:
        for aktor in SEMUA_AKTOR:
            yield pytest.param(
                method, path, body, aktor, aktor in berhak, ok, id=f"{nama}-{aktor}"
            )


def _url(path: str, skenario) -> str:
    return API + path.format(p=ID_PROYEK, kolab_lain_id=skenario.aktor["kolab_lain"].id)


@pytest.mark.parametrize("method,path,body,aktor,berhak,ok", list(_kasus(RUTE_MIGRASI)))
async def test_matriks_rute_dimigrasikan(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, method, path, body, aktor, berhak, ok
):
    sebelum = await _keadaan(db_session, skenario_akses.proyek)

    resp = await api.client.request(
        method, _url(path, skenario_akses), json=body, headers=skenario_akses.header(aktor)
    )

    if berhak:
        assert resp.status_code in ok, resp.text
    else:
        assert resp.status_code == 403, resp.text
        assert await _keadaan(db_session, skenario_akses.proyek) == sebelum
        assert fake_llm.jumlah() == 0
        assert fake_drive.panggilan == []
        assert fake_gmail.percobaan == []


async def test_rute_dimigrasikan_proyek_tak_ada_tetap_404_sebelum_403(api, skenario_akses):
    """Urutan 404 → 403 dipertahankan: proyek tak ada selalu 404, siapa pun pemintanya."""
    for _nama, method, path, body, _berhak, _ok in RUTE_MIGRASI:
        resp = await api.client.request(
            method,
            API + path.format(p="PRJ-TIDAK-ADA", kolab_lain_id=skenario_akses.aktor["kolab_lain"].id),
            json=body,
            headers=skenario_akses.header("sa_luar"),
        )
        assert resp.status_code == 404, (method, path, resp.text)


# ---------------------------------------------------------------- pengecualian SAH: role gate
#
# Rute ini hanya untuk Lead_SA/Admin lewat role gate (403 sebelum proyek dimuat). Test ini
# membuktikan klaim "sudah paling ketat" di daftar PENGECUALIAN_SAH: semua peran/hubungan lain
# ditolak tanpa efek samping, dan Lead_SA/Admin lolos gate (404 untuk target yang tak ada).

BODY_ASSIGN = lambda sk: {"sa_id": str(sk.aktor["sa_luar"].id)}  # noqa: E731
BODY_SKOR = {"budget": 20, "authority": 20, "need": 20, "timeline": 20, "reason": "uji akses"}
BODY_HANDOVER = {"pmo_email": "pmo@uji.test", "delivery_email": "delivery@uji.test"}

RUTE_ROLE_GATE = [
    ("hapus-proyek", "DELETE", "/projects/{p}", lambda sk: None, "proyek"),
    ("assign", "POST", "/projects/{p}/assign", BODY_ASSIGN, "proyek"),
    ("reassign", "POST", "/projects/{p}/reassign", BODY_ASSIGN, "proyek"),
    ("provision-folder", "POST", "/projects/{p}/provision-folder", lambda sk: None, "proyek"),
    ("handover-config", "POST", "/projects/{p}/handover-config", lambda sk: BODY_HANDOVER, "proyek"),
    ("score-manual", "POST", "/projects/{p}/score-manual", lambda sk: BODY_SKOR, "proyek"),
    ("assign-subtask", "PATCH", "/projects/subtasks/{s}/assign", lambda sk: {"assigned_sa": None}, "subtask"),
    ("hapus-subtask", "DELETE", "/projects/subtasks/{s}", lambda sk: None, "subtask"),
]


def _kasus_role_gate():
    for nama, method, path, body, target in RUTE_ROLE_GATE:
        for aktor in SEMUA_AKTOR:
            yield pytest.param(method, path, body, target, aktor, id=f"{nama}-{aktor}")


@pytest.mark.parametrize("method,path,body,target,aktor", list(_kasus_role_gate()))
async def test_role_gate_lead_admin_menolak_semua_hubungan_lain(
    api, db_session, skenario_akses, fake_llm, fake_drive, fake_gmail, method, path, body, target, aktor
):
    subtask = bangun_subtask(ID_PROYEK)
    db_session.add(subtask)
    await db_session.commit()
    url = API + path.format(p=ID_PROYEK, s=subtask.id_subtask)
    ada_target = {"proyek": ID_PROYEK, "subtask": subtask.id_subtask}[target]
    tak_ada = API + path.format(p="PRJ-TIDAK-ADA", s="SUB-TIDAK-ADA")
    assert ada_target in url

    if aktor in ("lead", "admin"):
        # Lolos gate: target yang tak ada → 404 (bukan 403); tidak ada efek samping.
        resp = await api.client.request(
            method, tak_ada, json=body(skenario_akses), headers=skenario_akses.header(aktor)
        )
        assert resp.status_code == 404, resp.text
        return

    sebelum = await _keadaan(db_session, skenario_akses.proyek)
    sub_sebelum = await db_session.get(Subtask, subtask.id_subtask)
    status_sub = (sub_sebelum.status, sub_sebelum.assigned_sa)

    resp = await api.client.request(
        method, url, json=body(skenario_akses), headers=skenario_akses.header(aktor)
    )

    assert resp.status_code == 403, resp.text
    assert await _keadaan(db_session, skenario_akses.proyek) == sebelum
    await db_session.refresh(subtask)
    assert (subtask.status, subtask.assigned_sa) == status_sub
    assert fake_llm.jumlah() == 0
    assert fake_drive.panggilan == []
    assert fake_gmail.percobaan == []


# ---------------------------------------------------------------- status subtask (aturan pemilik)


@pytest.mark.parametrize(
    "aktor,boleh",
    [
        ("lead", True),
        ("admin", True),
        ("sa", True),  # pemilik subtask
        ("sales_pic", False),
        ("kolab_viewer", False),
        ("kolab_contrib", False),
        ("kolab_lain", False),
        ("sales_luar", False),
        ("sa_luar", False),
    ],
)
async def test_status_subtask_hanya_pemilik_subtask_atau_lead_admin(
    api, db_session, skenario_akses, aktor, boleh
):
    """Aturan kepemilikan SUBTASK, ditambah akses TULIS ke proyeknya (bukan lagi pengecualian
    SAH-4). Pemilik yang sudah kehilangan akses tulis ditolak: lihat test_akses_perbaikan_review."""
    subtask = bangun_subtask(ID_PROYEK, assigned_sa=skenario_akses.aktor["sa"].id)
    db_session.add(subtask)
    await db_session.commit()

    resp = await api.client.patch(
        f"{API}/projects/subtasks/{subtask.id_subtask}/status",
        json={"status": "done"},
        headers=skenario_akses.header(aktor),
    )

    await db_session.refresh(subtask)
    if boleh:
        assert resp.status_code == 200, resp.text
        assert subtask.status == "done"
    else:
        assert resp.status_code == 403, resp.text
        assert subtask.status == "open"
