"""
Integrasi notifikasi terhadap Postgres nyata + fake Gmail (tiket #60, spec #49).

Mencakup API (`/notifications`: daftar, paginasi, hitung belum dibaca, penandaan baca, isolasi
antar-user) dan `notification_service` (in-app, email sukses/retry/gagal akhir/tanpa Gmail,
`dispatch_email_for_user`). Pasangan unit: `tests/test_notification_service_t60.py`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import NotificationLog
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)
from tests.integration.helpers_t60 import (
    API,
    bearer,
    buat_notifikasi,
    buat_user,
)

NOTIF = f"{API}/notifications"


@pytest_asyncio.fixture
async def api_servis(api, session_factory: async_sessionmaker[AsyncSession]):
    """
    `api` dengan `get_db` yang melepas savepoint-nya saat request selesai.

    Endpoint yang memanggil service yang membuka sesi sendiri (mis. `notification_service`)
    berjalan sementara sesi `Depends(get_db)` milik `get_current_user` masih terbuka. Pada harness
    satu koneksi (B2), penutupan sesi itu melakukan ROLLBACK TO SAVEPOINT dan ikut membatalkan
    tulisan sesi service. Melepas (commit) savepoint kosong sebelum ditutup menjaga tulisan itu
    tanpa mengubah perilaku produksi; hanya dipakai test yang memang melewati jalur tersebut.
    """
    from app.core.database import get_db
    from app.main import app

    async def _get_db_komit() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = _get_db_komit
    return api


async def _tunggu_task_latar() -> None:
    """Tunggu task background email (create_task) selesai agar hasilnya terlihat di DB."""
    sekarang = asyncio.current_task()
    tersisa = [t for t in asyncio.all_tasks() if t is not sekarang and not t.done()]
    if tersisa:
        await asyncio.wait(tersisa, timeout=5)


async def _log_email(db, user) -> list[NotificationLog]:
    hasil = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.recipient_user_id == user.id, NotificationLog.channel == "email")
        .execution_options(populate_existing=True)
    )
    return list(hasil.scalars().all())


# ---  API


async def test_daftar_hanya_milik_sendiri_inapp_terbaru_dulu(api_servis, db_session):
    saya = await buat_user(db_session, "SA")
    lain = await buat_user(db_session, "SA")
    lama = await buat_notifikasi(db_session, saya, menit_lalu=30, reference_id="PRJ-LAMA")
    baru = await buat_notifikasi(db_session, saya, menit_lalu=1, reference_id="PRJ-BARU")
    await buat_notifikasi(db_session, saya, channel="email", reference_id="PRJ-EMAIL")
    await buat_notifikasi(db_session, lain, reference_id="PRJ-ORANG-LAIN")

    resp = await api_servis.client.get(NOTIF, headers=bearer(saya))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [i["id"] for i in data["items"]] == [baru.id, lama.id]
    assert data["total"] == 2
    assert (data["page"], data["per_page"]) == (1, 20)
    item = data["items"][0]
    assert item["event_type"] == "assignment"
    assert item["channel"] == "in-app"
    assert item["reference_id"] == "PRJ-BARU"
    assert item["read_at"] is None


async def test_paginasi_25_notifikasi_dua_halaman_tanpa_tumpang_tindih(api_servis, db_session):
    saya = await buat_user(db_session, "SA")
    for i in range(25):
        await buat_notifikasi(db_session, saya, menit_lalu=i)

    h1 = (await api_servis.client.get(NOTIF, params={"page": 1}, headers=bearer(saya))).json()[
        "data"
    ]
    h2 = (await api_servis.client.get(NOTIF, params={"page": 2}, headers=bearer(saya))).json()[
        "data"
    ]
    h3 = (await api_servis.client.get(NOTIF, params={"page": 3}, headers=bearer(saya))).json()[
        "data"
    ]

    assert (len(h1["items"]), len(h2["items"]), len(h3["items"])) == (20, 5, 0)
    assert h1["total"] == h2["total"] == h3["total"] == 25
    id1 = {i["id"] for i in h1["items"]}
    id2 = {i["id"] for i in h2["items"]}
    assert not id1 & id2 and len(id1 | id2) == 25
    # Urutan global menurun menurut waktu: item terakhir hal. 1 lebih baru dari awal hal. 2.
    assert h1["items"][-1]["created_at"] > h2["items"][0]["created_at"]


async def test_per_page_di_atas_20_dan_halaman_nol_ditolak(api_servis, db_session):
    saya = await buat_user(db_session, "SA")
    h = bearer(saya)

    assert (
        await api_servis.client.get(NOTIF, params={"per_page": 21}, headers=h)
    ).status_code == 422
    assert (
        await api_servis.client.get(NOTIF, params={"per_page": 0}, headers=h)
    ).status_code == 422
    assert (await api_servis.client.get(NOTIF, params={"page": 0}, headers=h)).status_code == 422
    kecil = (await api_servis.client.get(NOTIF, params={"per_page": 1}, headers=h)).json()["data"]
    assert kecil["per_page"] == 1


async def test_tanpa_token_ditolak_401(api_servis):
    for metode, url in (
        ("get", NOTIF),
        ("get", f"{NOTIF}/unread-count"),
        ("patch", f"{NOTIF}/NTF-X/read"),
    ):
        resp = await getattr(api_servis.client, metode)(url)
        assert resp.status_code == 401, (metode, url)


async def test_unread_count_mengabaikan_email_milik_lain_dan_yang_sudah_dibaca(
    api_servis, db_session
):
    saya = await buat_user(db_session, "SA")
    lain = await buat_user(db_session, "SA")
    await buat_notifikasi(db_session, saya, status="sent")
    await buat_notifikasi(db_session, saya, status="pending")
    await buat_notifikasi(db_session, saya, status="read")
    await buat_notifikasi(db_session, saya, channel="email", status="sent")
    await buat_notifikasi(db_session, lain, status="sent")

    resp = await api_servis.client.get(f"{NOTIF}/unread-count", headers=bearer(saya))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"unread_count": 2}


async def test_unread_count_nol_bila_tidak_ada_notifikasi(api_servis, db_session):
    saya = await buat_user(db_session, "Sales")

    resp = await api_servis.client.get(f"{NOTIF}/unread-count", headers=bearer(saya))

    assert resp.json()["data"] == {"unread_count": 0}


async def test_tandai_dibaca_mengisi_status_read_at_dan_menurunkan_hitungan(api_servis, db_session):
    saya = await buat_user(db_session, "SA")
    n1 = await buat_notifikasi(db_session, saya, menit_lalu=2)
    await buat_notifikasi(db_session, saya, menit_lalu=1)
    h = bearer(saya)

    resp = await api_servis.client.patch(f"{NOTIF}/{n1.id}/read", headers=h)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"id": n1.id, "status": "read"}
    await db_session.refresh(n1)
    assert n1.status == "read" and n1.read_at is not None
    assert (await api_servis.client.get(f"{NOTIF}/unread-count", headers=h)).json()["data"] == {
        "unread_count": 1
    }
    daftar = (await api_servis.client.get(NOTIF, headers=h)).json()["data"]["items"]
    dibaca = next(i for i in daftar if i["id"] == n1.id)
    assert dibaca["status"] == "read" and dibaca["read_at"] is not None


async def test_tandai_dibaca_idempoten_tetap_200(api_servis, db_session):
    saya = await buat_user(db_session, "SA")
    n = await buat_notifikasi(db_session, saya)

    r1 = await api_servis.client.patch(f"{NOTIF}/{n.id}/read", headers=bearer(saya))
    r2 = await api_servis.client.patch(f"{NOTIF}/{n.id}/read", headers=bearer(saya))

    assert r1.status_code == r2.status_code == 200


async def test_tandai_dibaca_notifikasi_user_lain_ditolak_dan_tidak_berubah(api_servis, db_session):
    pemilik = await buat_user(db_session, "SA")
    penyusup = await buat_user(db_session, "Lead_SA")
    n = await buat_notifikasi(db_session, pemilik)

    resp = await api_servis.client.patch(f"{NOTIF}/{n.id}/read", headers=bearer(penyusup))

    # #78: tetap 404 agar keberadaan notifikasi orang lain tidak bocor, dan pesannya sama dengan
    # id yang memang tidak ada (sebelumnya "tidak memiliki akses" justru membocorkannya).
    assert resp.status_code == 404
    assert "tidak ditemukan" in resp.json()["message"]
    assert "akses" not in resp.json()["message"].lower()
    await db_session.refresh(n)
    assert n.status == "pending" and n.read_at is None


async def test_tandai_dibaca_id_tidak_ada_404(api_servis, db_session):
    saya = await buat_user(db_session, "SA")

    resp = await api_servis.client.patch(f"{NOTIF}/NTF-TIDAK-ADA/read", headers=bearer(saya))

    assert resp.status_code == 404
    assert "tidak ditemukan" in resp.json()["message"]


# ---  service: in-app & email


def _event(user, **o) -> NotificationEvent:
    dasar = dict(
        event_type=NotificationEventType.ASSIGNMENT,
        recipient_user_id=user.id,
        recipient_email=user.email,
        reference_id="PRJ-T60",
        metadata={"k": "v"},
    )
    dasar.update(o)
    return NotificationEvent(**dasar)


async def test_send_notification_tanpa_gmail_hanya_inapp_tersimpan(api, db_session, fake_gmail):
    fake_gmail.terkonfigurasi = False
    user = await buat_user(db_session, "SA")

    await notification_service.send_notification(_event(user))
    await _tunggu_task_latar()

    baris = (
        (
            await db_session.execute(
                select(NotificationLog).where(NotificationLog.recipient_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(b.channel, b.status, b.reference_id) for b in baris] == [("in-app", "sent", "PRJ-T60")]
    assert baris[0].notification_metadata == {"k": "v"}
    assert baris[0].id.startswith("NOTIF-")
    assert fake_gmail.percobaan == []


async def test_send_notification_dengan_gmail_inapp_dan_email_terkirim(api, db_session, fake_gmail):
    user = await buat_user(db_session, "SA")

    await notification_service.send_notification(
        _event(user, subject="Subjek Khusus", template="tpl-khusus")
    )
    await fake_gmail.tunggu_percobaan(1)
    await _tunggu_task_latar()

    assert len(fake_gmail.terkirim) == 1
    surat = fake_gmail.terkirim[0]
    assert surat.to == user.email
    assert surat.subject == "Subjek Khusus"
    assert surat.template == "tpl-khusus"
    assert surat.context["reference_id"] == "PRJ-T60"
    email = await _log_email(db_session, user)
    assert [e.status for e in email] == ["sent"]
    # In-app tetap ada dan terlihat lewat API.
    daftar = (await api.client.get(NOTIF, headers=bearer(user))).json()["data"]
    assert daftar["total"] == 1


async def test_email_gagal_dua_kali_lalu_berhasil_status_sent_tiga_percobaan(
    api, db_session, fake_gmail
):
    fake_gmail.fail_next(2)
    user = await buat_user(db_session, "SA")

    await notification_service.send_notification(_event(user))
    await fake_gmail.tunggu_percobaan(3)
    await _tunggu_task_latar()

    assert [s.berhasil for s in fake_gmail.percobaan] == [False, False, True]
    assert [e.status for e in await _log_email(db_session, user)] == ["sent"]
    assert fake_gmail.percobaan[0].subject == "[Portal SA] Anda ditugaskan ke proyek baru"


async def test_email_gagal_terus_berhenti_di_tiga_percobaan_status_failed(
    api, db_session, fake_gmail
):
    fake_gmail.fail_always()
    user = await buat_user(db_session, "SA")

    await notification_service.send_notification(_event(user))
    await fake_gmail.tunggu_percobaan(3)
    await _tunggu_task_latar()

    assert len(fake_gmail.percobaan) == 3
    assert [e.status for e in await _log_email(db_session, user)] == ["failed"]
    # Kegagalan email tidak mengganggu notifikasi in-app.
    daftar = (await api.client.get(NOTIF, headers=bearer(user))).json()["data"]
    assert daftar["total"] == 1


async def test_dispatch_email_for_user_mengirim_email_tanpa_inapp(api, db_session, fake_gmail):
    user = await buat_user(db_session, "Lead_SA")

    await notification_service.dispatch_email_for_user(
        NotificationEventType.SLA_REMINDER, user.id, reference_id="PRJ-SLA", metadata={"h": 3}
    )
    await asyncio.gather(*notification_service._background_tasks)

    assert len(fake_gmail.terkirim) == 1
    assert fake_gmail.terkirim[0].to == user.email
    assert fake_gmail.terkirim[0].subject == "[Portal SA] Reminder: DQ Number belum diinput"
    channels = (
        (
            await db_session.execute(
                select(NotificationLog.channel).where(NotificationLog.recipient_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert channels == ["email"]


async def test_dispatch_email_for_user_tanpa_gmail_tidak_melakukan_apa_apa(
    api, db_session, fake_gmail
):
    fake_gmail.terkonfigurasi = False
    user = await buat_user(db_session, "SA")

    await notification_service.dispatch_email_for_user(
        NotificationEventType.SLA_ESCALATION, user.id
    )

    assert not notification_service._background_tasks
    assert fake_gmail.percobaan == []
    assert await _log_email(db_session, user) == []


async def test_dispatch_email_for_user_tidak_ada_tidak_raise_dan_tidak_kirim(
    api, db_session, fake_gmail
):
    await notification_service.dispatch_email_for_user(NotificationEventType.HANDOVER, uuid.uuid4())

    assert not notification_service._background_tasks
    assert fake_gmail.percobaan == []


async def test_service_membatasi_per_page_maksimal_20_walau_dipanggil_langsung(api, db_session):
    user = await buat_user(db_session, "SA")
    for i in range(22):
        await buat_notifikasi(db_session, user, menit_lalu=i)

    hasil = await notification_service.get_user_notifications(user.id, page=1, per_page=500)

    assert (hasil["per_page"], len(hasil["items"]), hasil["total"]) == (20, 20, 22)
