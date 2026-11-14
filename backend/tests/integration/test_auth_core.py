"""
Integrasi auth dan core terhadap Postgres nyata (tiket #55, spec #49).

Mencakup: demo login (+ blok produksi), OAuth Google (HTTP Google di-fake pada boundary; user
tersimpan di Postgres), refresh/logout/me, dependency `get_current_user`, matriks hak akses
`ensure_project_access` untuk semua peran, `core/database`, dan rate limiter pada app nyata.
Pasangan unit-nya: `tests/test_auth_*.py`, `tests/test_core_*.py`, `tests/test_rate_limiter.py`.
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import database
from app.core.config import settings
from app.core.dependencies import TingkatAkses, ensure_project_access
from app.models import Project, User
from app.models.project_collaborator import ProjectCollaborator
from tests._auth_support import buat_token, pasang_google
from tests.integration.conftest import patch_session_factory
from tests.integration.model_helpers import bangun_user

AUTH = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _auth_default(monkeypatch):
    """Tanpa pembatasan domain/mapping kecuali test mengatur sendiri."""
    from app.services.auth_service import auth_service

    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "")
    monkeypatch.setattr(settings, "ROLE_MAPPING", "{}")
    monkeypatch.setattr(auth_service, "_role_mapping", None)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _jumlah_user(db) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


# --------------------------------------------------------------------------- demo login


async def test_demo_login_menyimpan_user_dan_token_bisa_dipakai_di_me(api, db_session):
    resp = await api.client.post(f"{AUTH}/demo-login", json={"role": "Lead_SA"})
    assert resp.status_code == 200
    token = resp.json()["tokens"]["access_token"]

    user = (
        await db_session.execute(select(User).where(User.email == "demo-lead@portal-sa.local"))
    ).scalar_one()
    assert user.role == "Lead_SA"
    assert str(user.id) == resp.json()["user"]["id"]

    me = await api.client.get(f"{AUTH}/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_demo_login_berulang_tidak_menggandakan_user(api, db_session):
    for _ in range(3):
        assert (await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})).status_code == 200
    assert await _jumlah_user(db_session) == 1


async def test_login_demo_admin_membuat_identitas_lead_admin_terpisah(api):
    from app.services.auth_service import auth_service

    lead = await api.login_demo("Lead_SA")
    admin = await api.login_demo("Admin")
    klaim_lead = auth_service.verify_access_token(lead["Authorization"][7:])
    klaim_admin = auth_service.verify_access_token(admin["Authorization"][7:])

    assert klaim_lead["role"] == klaim_admin["role"] == "Lead_SA"
    assert klaim_lead["is_admin"] is True
    assert klaim_admin["is_admin"] is True
    assert klaim_lead["sub"] != klaim_admin["sub"]
    me = await api.client.get(f"{AUTH}/me", headers=admin)
    assert me.status_code == 200
    assert me.json()["id"] == klaim_admin["sub"]


async def test_demo_login_diblok_di_produksi_dan_tidak_menulis_ke_db(api, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEMO_MODE", True)

    resp = await api.client.post(f"{AUTH}/demo-login", json={"role": "Sales"})

    assert resp.status_code == 403
    assert await _jumlah_user(db_session) == 0
    cfg = (await api.client.get(f"{AUTH}/config")).json()
    assert cfg["demo_mode"] is False


async def test_demo_login_menolak_role_admin(api, db_session):
    resp = await api.client.post(f"{AUTH}/demo-login", json={"role": "Admin"})

    assert resp.status_code == 422
    assert await _jumlah_user(db_session) == 0


# --------------------------------------------------------------------------- OAuth Google


async def test_callback_user_baru_tersimpan_dengan_peran_dari_mapping(api, db_session, monkeypatch):
    from app.services.auth_service import auth_service

    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "perusahaan.id")
    monkeypatch.setattr(settings, "ROLE_MAPPING", '{"*@perusahaan.id": "Sales"}')
    monkeypatch.setattr(auth_service, "_role_mapping", None)
    pasang_google(monkeypatch)

    resp = await api.client.get(f"{AUTH}/callback", params={"code": "kode-ok"})

    assert resp.status_code == 200
    exchange = await api.client.post(
        f"{AUTH}/callback/exchange", json={"code": resp.json()["handoff_code"]}
    )
    user = (await db_session.execute(select(User).where(User.google_id == "g-123"))).scalar_one()
    assert (user.email, user.role, user.avatar_url) == (
        "budi@perusahaan.id",
        "Sales",
        "http://a/b.png",
    )
    me = await api.client.get(f"{AUTH}/me", headers=_bearer(exchange.json()["access_token"]))
    assert me.json()["role"] == "Sales"


async def test_callback_mapping_peran_tidak_valid_user_baru_jadi_sa_bukan_500(
    api, db_session, monkeypatch
):
    """#80: peran asing di mapping tak boleh melanggar `chk_users_role` saat user baru disimpan."""
    from app.services.auth_service import auth_service

    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "perusahaan.id")
    # Disetel langsung (melewati validator Settings) = mapping yang lolos dari fail-fast startup.
    monkeypatch.setattr(settings, "ROLE_MAPPING", '{"*@perusahaan.id": "Superuser"}')
    monkeypatch.setattr(auth_service, "_role_mapping", None)
    pasang_google(monkeypatch)

    resp = await api.client.get(f"{AUTH}/callback", params={"code": "kode-ok"})

    assert resp.status_code == 200, resp.text
    user = (await db_session.execute(select(User).where(User.google_id == "g-123"))).scalar_one()
    assert user.role == "SA"


async def test_callback_user_existing_diperbarui_peran_tetap(api, db_session, monkeypatch):
    from app.services.auth_service import auth_service

    db_session.add(
        User(
            id=uuid.uuid4(),
            email="lama@perusahaan.id",
            name="Nama Lama",
            role="Lead_SA",
            google_id="g-123",
        )
    )
    await db_session.commit()
    # mapping sekarang menunjuk peran lain; peran yang sudah tersimpan tidak boleh berubah
    monkeypatch.setattr(settings, "ROLE_MAPPING", '{"*@perusahaan.id": "Sales"}')
    monkeypatch.setattr(auth_service, "_role_mapping", None)
    pasang_google(monkeypatch)

    resp = await api.client.get(f"{AUTH}/callback", params={"code": "k"})

    assert resp.status_code == 200
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert (users[0].name, users[0].email, users[0].role) == (
        "Budi",
        "budi@perusahaan.id",
        "Lead_SA",
    )


async def test_callback_domain_ditolak_tidak_menyimpan_user(api, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "perusahaan.id")
    pasang_google(monkeypatch, profil={"id": "g-x", "email": "x@gmail.com", "name": "X"})

    resp = await api.client.get(f"{AUTH}/callback", params={"code": "k"})

    assert resp.status_code == 403
    assert await _jumlah_user(db_session) == 0


async def test_callback_kode_tidak_valid_tidak_menyimpan_user(api, db_session, monkeypatch):
    pasang_google(monkeypatch, token_status=400, token_body="invalid_grant")
    resp = await api.client.get(f"{AUTH}/callback", params={"code": "basi"})
    assert resp.status_code == 502
    assert await _jumlah_user(db_session) == 0


async def test_callback_handoff_hanya_dapat_ditukar_satu_kali(api, monkeypatch):
    pasang_google(monkeypatch)
    callback = await api.client.get(f"{AUTH}/callback", params={"code": "kode-ok"})
    assert callback.status_code == 200
    code = callback.json()["handoff_code"]
    assert "access_token" not in callback.text
    assert "refresh_token" not in callback.text

    tukar = await api.client.post(f"{AUTH}/callback/exchange", json={"code": code})
    assert tukar.status_code == 200
    assert tukar.json()["user"]["email"] == "budi@perusahaan.id"
    assert tukar.json()["access_token"]
    assert "refresh_token" not in tukar.json()
    assert "HttpOnly" in tukar.headers["set-cookie"]

    pakai_ulang = await api.client.post(f"{AUTH}/callback/exchange", json={"code": code})
    assert pakai_ulang.status_code == 401


async def test_calendar_callback_location_hanya_membawa_kode_terbatas(api, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
    pasang_google(monkeypatch, token_body={"access_token": "GOOGLE-SECRET"})
    callback = await api.client.get(
        f"{AUTH}/callback",
        params={"code": "google-code", "state": "calendar_auth|http://localhost:3000/activity-logs/calendar"},
        follow_redirects=False,
    )
    location = callback.headers["location"]
    assert "GOOGLE-SECRET" not in location
    code = location.split("gcal_code=", 1)[1]
    exchanged = await api.client.post(f"{AUTH}/calendar/exchange", json={"code": code})
    assert exchanged.json() == {"access_token": "GOOGLE-SECRET"}
    assert (
        await api.client.post(f"{AUTH}/calendar/exchange", json={"code": code})
    ).status_code == 401


# ------------------------------------------------------------------------- refresh / logout / sesi


async def test_refresh_menghasilkan_access_token_baru_yang_valid(api):
    login = (await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})).json()

    resp = await api.client.post(f"{AUTH}/refresh")

    assert resp.status_code == 200
    me = await api.client.get(f"{AUTH}/me", headers=_bearer(resp.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == login["user"]["id"]


async def test_refresh_cookie_rotasi_reuse_mencabut_sesi(api):
    login = await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})
    cookie_awal = login.cookies.get("refresh_token")
    assert cookie_awal
    assert "refresh_token" not in login.json()["tokens"]

    pertama = await api.client.post(f"{AUTH}/refresh", cookies={"refresh_token": cookie_awal})
    assert pertama.status_code == 200
    cookie_baru = pertama.cookies.get("refresh_token")
    assert cookie_baru and cookie_baru != cookie_awal

    reuse = await api.client.post(f"{AUTH}/refresh", cookies={"refresh_token": cookie_awal})
    assert reuse.status_code == 401
    assert 'refresh_token=""' in reuse.headers["set-cookie"]

    setelah_reuse = await api.client.post(f"{AUTH}/refresh", cookies={"refresh_token": cookie_baru})
    assert setelah_reuse.status_code == 401


async def test_refresh_menolak_origin_silang_tanpa_mengonsumsi_cookie(api):
    login = await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})
    cookie = login.cookies.get("refresh_token")
    assert cookie
    csrf = await api.client.post(
        f"{AUTH}/refresh",
        cookies={"refresh_token": cookie},
        headers={"Origin": "https://penyerang.example"},
    )
    assert csrf.status_code == 403
    valid = await api.client.post(f"{AUTH}/refresh", cookies={"refresh_token": cookie})
    assert valid.status_code == 200


async def test_refresh_token_tidak_diterima_sebagai_kredensial_api(api):
    """Refresh token ditolak di endpoint terproteksi (dependency get_current_user)."""
    login_response = await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})
    refresh = login_response.cookies.get("refresh_token")
    assert refresh
    resp = await api.client.get("/api/v1/projects", headers=_bearer(refresh))
    assert resp.status_code == 401


async def test_access_token_tidak_diterima_di_endpoint_refresh(api):
    login = (await api.client.post(f"{AUTH}/demo-login", json={"role": "SA"})).json()
    resp = await api.client.post(
        f"{AUTH}/refresh", cookies={"refresh_token": login["tokens"]["access_token"]}
    )
    assert resp.status_code == 401


async def test_logout_mencabut_cookie_dan_idempotent_tanpa_cookie(api):
    headers = await api.login_demo("Sales")
    assert (await api.client.post(f"{AUTH}/logout", headers=headers)).status_code == 200
    assert (await api.client.post(f"{AUTH}/logout")).status_code == 200


async def test_get_current_user_endpoint_terproteksi(api, db_session):
    """Token valid → 200; kedaluwarsa/rusak/tanpa/user dihapus → 401 pada endpoint terproteksi."""
    headers = await api.login_demo("Sales")
    url = "/api/v1/projects"
    assert (await api.client.get(url, headers=headers)).status_code == 200

    assert (await api.client.get(url)).status_code == 401
    assert (await api.client.get(url, headers=_bearer("rusak"))).status_code == 401
    kedaluwarsa = buat_token(uuid.uuid4(), berlaku=timedelta(seconds=-5))
    resp = await api.client.get(url, headers=_bearer(kedaluwarsa))
    assert resp.status_code == 401
    assert "expired" in resp.json()["message"]
    # token sah tapi user tidak ada di DB
    hantu = buat_token(uuid.uuid4())
    assert (await api.client.get(url, headers=_bearer(hantu))).status_code == 401

    # user dihapus setelah login → token lama tidak lagi berlaku
    me = (await api.client.get(f"{AUTH}/me", headers=headers)).json()
    await db_session.execute(User.__table__.delete().where(User.id == uuid.UUID(me["id"])))
    await db_session.commit()
    assert (await api.client.get(url, headers=headers)).status_code == 401


# --------------------------------------------------------------------------- matriks authz


async def _user(db, role: str, nama: str) -> User:
    u = bangun_user(role=role, email=f"{nama}@contoh.id", name=nama, google_id=f"g-{nama}")
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
async def skenario(db_session):
    """Satu proyek dan seluruh aktor: pemilik, SA, collaborator, privileged, dan pihak luar."""
    db = db_session
    a = {
        "sales_pic": await _user(db, "Sales", "sales-pic"),
        "sa": await _user(db, "SA", "sa-ditugaskan"),
        "lead": await _user(db, "Lead_SA", "lead"),
        "admin": await _user(db, "Admin", "admin"),
        "kolab_viewer": await _user(db, "SA", "kolab-viewer"),
        "kolab_contrib": await _user(db, "SA", "kolab-contributor"),
        "kolab_lain": await _user(db, "SA", "kolab-proyek-lain"),
        "sales_luar": await _user(db, "Sales", "sales-luar"),
        "sa_luar": await _user(db, "SA", "sa-luar"),
    }
    proyek = Project(
        id_project="PRJ-AUTHZ-1",
        project_name="Proyek Authz",
        customer_name="PT Authz",
        created_by=a["sales_pic"].id,
        product_pic=a["sales_pic"].id,
        sales_pic=a["sales_pic"].id,
        assigned_sa=a["sa"].id,
        target_submit=date.today() + timedelta(days=30),
    )
    lain = Project(
        id_project="PRJ-AUTHZ-2",
        project_name="Proyek Lain",
        customer_name="PT Lain",
        created_by=a["sales_pic"].id,
        product_pic=a["sales_pic"].id,
        sales_pic=a["sales_pic"].id,
        target_submit=date.today() + timedelta(days=30),
    )
    db.add_all([proyek, lain])
    await db.flush()
    for kunci, rol, pid in (
        ("kolab_viewer", "viewer", proyek.id_project),
        ("kolab_contrib", "contributor", proyek.id_project),
        ("kolab_lain", "viewer", lain.id_project),
    ):
        db.add(
            ProjectCollaborator(
                id_project=pid,
                user_id=a[kunci].id,
                role=rol,
                added_by=a["lead"].id,
            )
        )
    await db.commit()
    return proyek, a


DIIZINKAN = ["sales_pic", "sa", "lead", "admin", "kolab_viewer", "kolab_contrib"]
DITOLAK = ["kolab_lain", "sales_luar", "sa_luar"]


@pytest.mark.parametrize("aktor", DIIZINKAN)
async def test_ensure_project_access_diizinkan_untuk_aktor_berhak(db_session, skenario, aktor):
    proyek, a = skenario
    assert await ensure_project_access(db_session, proyek, a[aktor]) is None


@pytest.mark.parametrize("aktor", DITOLAK)
async def test_ensure_project_access_menolak_pihak_luar_untuk_tulis(db_session, skenario, aktor):
    proyek, a = skenario
    with pytest.raises(HTTPException) as exc:
        await ensure_project_access(db_session, proyek, a[aktor], TingkatAkses.UBAH_PROYEK)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("aktor", DITOLAK)
async def test_ensure_project_access_baca_terbuka_untuk_pihak_luar(db_session, skenario, aktor):
    """Keputusan 2026-11-10: semua proyek dapat dibaca semua pengguna; hanya tulis yang dibatasi."""
    proyek, a = skenario
    assert await ensure_project_access(db_session, proyek, a[aktor]) is None


async def test_keanggotaan_collaborator_berlaku_per_proyek(db_session, skenario):
    """Contributor proyek lain boleh menulis di proyek itu saja, bukan di proyek ini."""
    proyek, a = skenario
    lain = (
        await db_session.execute(select(Project).where(Project.id_project == "PRJ-AUTHZ-2"))
    ).scalar_one()
    await db_session.execute(
        ProjectCollaborator.__table__.update()
        .where(ProjectCollaborator.user_id == a["kolab_lain"].id)
        .values(role="contributor")
    )
    await db_session.commit()
    await ensure_project_access(db_session, lain, a["kolab_lain"], TingkatAkses.TULIS)
    with pytest.raises(HTTPException):
        await ensure_project_access(db_session, proyek, a["kolab_lain"], TingkatAkses.TULIS)


async def test_mencabut_collaborator_mencabut_akses_tulis(db_session, skenario):
    proyek, a = skenario
    await ensure_project_access(db_session, proyek, a["kolab_contrib"], TingkatAkses.TULIS)
    await db_session.execute(
        ProjectCollaborator.__table__.delete().where(
            ProjectCollaborator.user_id == a["kolab_contrib"].id
        )
    )
    await db_session.commit()
    with pytest.raises(HTTPException):
        await ensure_project_access(db_session, proyek, a["kolab_contrib"], TingkatAkses.TULIS)


def _token_user(user: User) -> dict[str, str]:
    return _bearer(buat_token(user.id))


@pytest.mark.parametrize("aktor", DIIZINKAN)
async def test_http_baca_subtask_diizinkan(api, skenario, aktor):
    proyek, a = skenario
    resp = await api.client.get(
        f"/api/v1/projects/{proyek.id_project}/subtasks", headers=_token_user(a[aktor])
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("aktor", DITOLAK)
async def test_http_baca_subtask_pihak_luar_tetap_200(api, skenario, aktor):
    """Keputusan 2026-11-10: membaca terbuka untuk semua pengguna terautentikasi."""
    proyek, a = skenario
    resp = await api.client.get(
        f"/api/v1/projects/{proyek.id_project}/subtasks", headers=_token_user(a[aktor])
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("aktor", ["sales_pic", "sa", "lead", "admin", "kolab_contrib"])
async def test_http_ubah_proyek_oleh_pihak_berhak(api, db_session, skenario, aktor):
    proyek, a = skenario
    resp = await api.client.patch(
        f"/api/v1/projects/{proyek.id_project}",
        json={"project_name": f"Diubah {aktor}"},
        headers=_token_user(a[aktor]),
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(proyek)
    assert proyek.project_name == f"Diubah {aktor}"


@pytest.mark.parametrize("aktor", DITOLAK)
async def test_http_ubah_proyek_pihak_luar_403_dan_data_tidak_berubah(
    api, db_session, skenario, aktor
):
    proyek, a = skenario
    resp = await api.client.patch(
        f"/api/v1/projects/{proyek.id_project}",
        json={"project_name": "Dibajak"},
        headers=_token_user(a[aktor]),
    )
    assert resp.status_code == 403
    await db_session.refresh(proyek)
    assert proyek.project_name == "Proyek Authz"


@pytest.mark.parametrize(
    ("role", "status_diharapkan"),
    [("Sales", 403), ("Product", 403), ("SA", 403), ("Lead_SA", 404), ("Admin", 404)],
)
async def test_require_role_pada_endpoint_nyata(api, role, status_diharapkan):
    """
    `score-manual` memakai `require_privileged` (Lead_SA atau `is_admin`): Sales/SA ditolak 403 sebelum
    proyek dicari; Lead_SA/Admin lolos gerbang peran (lalu 404 karena proyek memang tidak ada).
    """
    headers = await api.login_demo(role)
    resp = await api.client.post(
        "/api/v1/projects/TIDAK-ADA/score-manual",
        json={"budget": 10, "authority": 10, "need": 10, "timeline": 10, "reason": "uji"},
        headers=headers,
    )
    assert resp.status_code == status_diharapkan, resp.text


# --------------------------------------------------------------------------- core/database


async def test_check_database_health_true_pada_postgres_nyata(monkeypatch, session_factory):
    patch_session_factory(monkeypatch, session_factory)
    assert await database.check_database_health() is True


async def test_get_db_memberi_sesi_yang_bisa_query_lalu_menutupnya(monkeypatch, database_uji_url):
    engine = create_async_engine(database_uji_url, poolclass=NullPool)
    try:
        monkeypatch.setattr(
            database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False)
        )
        gen = database.get_db()
        sesi = await gen.__anext__()
        assert (await sesi.execute(select(func.count()).select_from(User))).scalar_one() >= 0
        assert sesi.in_transaction()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert not sesi.in_transaction()  # sesi sudah ditutup, transaksi dilepas
    finally:
        await engine.dispose()


async def test_check_database_health_false_bila_server_tidak_terjangkau(monkeypatch):
    engine = create_async_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x", poolclass=NullPool)
    try:
        monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine))
        assert await database.check_database_health() is False
    finally:
        await engine.dispose()


# ------------------------------------------------------------------------- rate limiter app nyata


@pytest.fixture
def batas_rendah(monkeypatch):
    """Bangun ulang middleware stack app dengan batas 3/menit & jam terkendali."""
    from app.main import app

    class Jam:
        sekarang = 5000.0

        def time(self):
            return self.sekarang

    jam = Jam()
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 3)
    monkeypatch.setattr("app.core.rate_limiter.time", jam)
    app.middleware_stack = None
    try:
        yield jam
    finally:
        app.middleware_stack = None  # dibangun ulang dengan batas asli pada request berikutnya


async def test_rate_limit_pada_app_nyata_429_header_dan_reset(api, batas_rendah):
    url = f"{AUTH}/config"
    assert [(await api.client.get(url)).status_code for _ in range(3)] == [200, 200, 200]

    resp = await api.client.get(url)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "61"
    assert resp.json()["status"] == "error"
    # /health tidak dibatasi walau kuota habis
    assert (await api.client.get("/health")).status_code != 429

    batas_rendah.sekarang += 61
    assert (await api.client.get(url)).status_code == 200


async def test_rate_limit_per_pengguna_dua_pengguna_satu_ip_tidak_saling_memblokir(
    api, batas_rendah
):
    """Dua pengguna dari IP yang sama (peer sama) punya kuota sendiri-sendiri."""
    ha = await api.login_demo("SA")
    hb = await api.login_demo("Lead_SA")
    url = f"{AUTH}/me"

    assert [(await api.client.get(url, headers=ha)).status_code for _ in range(3)] == [
        200,
        200,
        200,
    ]
    assert (await api.client.get(url, headers=ha)).status_code == 429
    assert (await api.client.get(url, headers=hb)).status_code == 200


async def test_rate_limit_anonim_per_ip_xff_dipalsukan_diabaikan_saat_hop_nol(
    api, batas_rendah, monkeypatch
):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
    url = f"{AUTH}/config"
    for i in range(3):
        resp = await api.client.get(url, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert resp.status_code == 200
    assert (await api.client.get(url, headers={"X-Forwarded-For": "10.0.0.99"})).status_code == 429


async def test_rate_limit_anonim_hop_satu_membedakan_klien_dari_entri_kanan(
    api, batas_rendah, monkeypatch
):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    url = f"{AUTH}/config"
    palsu = {"X-Forwarded-For": "6.6.6.6, 203.0.113.5"}
    for _ in range(3):
        assert (await api.client.get(url, headers=palsu)).status_code == 200
    lain_kiri = {"X-Forwarded-For": "7.7.7.7, 203.0.113.5"}
    assert (await api.client.get(url, headers=lain_kiri)).status_code == 429
    klien_lain = {"X-Forwarded-For": "6.6.6.6, 203.0.113.6"}
    assert (await api.client.get(url, headers=klien_lain)).status_code == 200
