"""
Unit test `notification_service` (tiket #60, spec #49): inisialisasi kredensial Gmail, penyusunan
dan pengiriman email, subject default, serta jalur gagal yang tidak boleh melempar.

Boundary Google dipalsukan (`build`, `service_account`, objek layanan Gmail). Alur retry/status
tersimpan di Postgres diuji di `tests/integration/test_notifikasi_t60.py`; retry dengan mock sesi
sudah dicakup `tests/test_notification_email.py` (tidak diubah).
"""

import base64
import email
import json
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services import notification_service as modul
from app.services.notification_service import (
    GmailConfigError,
    NotificationEvent,
    NotificationEventType,
    NotificationService,
    _generate_notification_id,
)


@pytest.fixture
def svc():
    return NotificationService()


@pytest.fixture
def gmail_aktif(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", json.dumps({"type": "service_account"}))
    monkeypatch.setattr(settings, "GMAIL_SENDER", "")


def _layanan_gmail(gagal: Exception | None = None):
    """Objek bergaya googleapiclient: users().messages().send(userId, body).execute()."""
    layanan = MagicMock()
    kirim = layanan.users.return_value.messages.return_value.send
    if gagal is not None:
        kirim.return_value.execute.side_effect = gagal
    else:
        kirim.return_value.execute.return_value = {"id": "m1"}
    return layanan, kirim


# ---  ID & event


def test_id_notifikasi_berformat_tanggal_dan_enam_karakter_acak():
    assert re.fullmatch(r"NOTIF-\d{8}-[A-Z0-9]{6}", _generate_notification_id())


def test_id_notifikasi_praktis_unik():
    assert len({_generate_notification_id() for _ in range(200)}) == 200


def test_event_default_opsional_kosong():
    ev = NotificationEvent(
        event_type=NotificationEventType.DOC_READY,
        recipient_user_id=uuid.uuid4(),
        recipient_email="a@b.id",
    )

    assert (ev.reference_id, ev.metadata, ev.subject, ev.template) == (None, None, None, None)


# ---  konfigurasi Gmail


@pytest.mark.parametrize(("nilai", "diharapkan"), [("", False), ("  \n ", False), ("{}", True)])
def test_is_gmail_configured(monkeypatch, svc, nilai, diharapkan):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", nilai)

    assert svc._is_gmail_configured() is diharapkan


def test_get_gmail_service_tanpa_kredensial_raise_config_error(monkeypatch, svc):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "")

    with pytest.raises(GmailConfigError, match="belum dikonfigurasi"):
        svc._get_gmail_service()


def test_get_gmail_service_json_rusak_raise_config_error(monkeypatch, svc):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "{bukan json")

    with pytest.raises(GmailConfigError, match="tidak valid"):
        svc._get_gmail_service()


def test_get_gmail_service_kredensial_ditolak_google_auth_raise_config_error(
    monkeypatch, svc, gmail_aktif
):
    sa = MagicMock()
    sa.Credentials.from_service_account_info.side_effect = ValueError("kunci privat hilang")
    monkeypatch.setattr(modul, "service_account", sa)

    with pytest.raises(GmailConfigError, match="kunci privat hilang"):
        svc._get_gmail_service()


def test_get_gmail_service_membangun_sekali_dengan_scope_kirim_dan_di_cache(
    monkeypatch, svc, gmail_aktif
):
    sa = MagicMock()
    build = MagicMock(return_value="LAYANAN")
    monkeypatch.setattr(modul, "service_account", sa)
    monkeypatch.setattr(modul, "build", build)

    pertama = svc._get_gmail_service()
    kedua = svc._get_gmail_service()

    assert pertama == kedua == "LAYANAN"
    build.assert_called_once()
    assert build.call_args.args == ("gmail", "v1")
    _, kwargs = sa.Credentials.from_service_account_info.call_args
    assert kwargs["scopes"] == ["https://www.googleapis.com/auth/gmail.send"]
    sa.Credentials.from_service_account_info.return_value.with_subject.assert_not_called()


def test_get_gmail_service_delegasi_ke_pengirim_bila_diset(monkeypatch, svc, gmail_aktif):
    monkeypatch.setattr(settings, "GMAIL_SENDER", " portal@contoh.id ")
    sa = MagicMock()
    monkeypatch.setattr(modul, "service_account", sa)
    monkeypatch.setattr(modul, "build", MagicMock())

    svc._get_gmail_service()

    sa.Credentials.from_service_account_info.return_value.with_subject.assert_called_once_with(
        "portal@contoh.id"
    )


# ---  send_email


async def test_send_email_tanpa_gmail_false_dan_tidak_menyentuh_layanan(monkeypatch, svc):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "")
    layanan, kirim = _layanan_gmail()
    svc._gmail_service = layanan

    assert await svc.send_email("a@b.id", "S", "t", {}) is False
    kirim.assert_not_called()


async def test_send_email_sukses_pesan_mime_benar(monkeypatch, svc, gmail_aktif):
    monkeypatch.setattr(settings, "GMAIL_SENDER", "portal@contoh.id")
    layanan, kirim = _layanan_gmail()
    svc._gmail_service = layanan

    ok = await svc.send_email(
        "tujuan@contoh.id", "Subjek Uji", "tpl", {"reference_id": "PRJ-9", "metadata": None}
    )

    assert ok is True
    kwargs = kirim.call_args.kwargs
    assert kwargs["userId"] == "me"
    pesan = email.message_from_bytes(base64.urlsafe_b64decode(kwargs["body"]["raw"]))
    assert pesan["To"] == "tujuan@contoh.id"
    assert pesan["Subject"] == "Subjek Uji"
    assert pesan["From"] == "portal@contoh.id"
    assert "Referensi: PRJ-9" in pesan.get_payload(decode=True).decode("utf-8")


async def test_send_email_tanpa_pengirim_tidak_ada_header_from(monkeypatch, svc, gmail_aktif):
    layanan, kirim = _layanan_gmail()
    svc._gmail_service = layanan

    await svc.send_email("a@b.id", "S", "t", {})

    pesan = email.message_from_bytes(
        base64.urlsafe_b64decode(kirim.call_args.kwargs["body"]["raw"])
    )
    assert pesan["From"] is None


async def test_send_email_subject_non_ascii_tetap_terkirim(monkeypatch, svc, gmail_aktif):
    layanan, kirim = _layanan_gmail()
    svc._gmail_service = layanan

    assert await svc.send_email("a@b.id", "Proyek baru — ✓", "t", {}) is True


@pytest.mark.parametrize(
    "galat", [RuntimeError("API 500"), TimeoutError("lambat"), GmailConfigError("rusak")]
)
async def test_send_email_gagal_mengembalikan_false_tanpa_raise(
    monkeypatch, svc, gmail_aktif, galat
):
    layanan, _ = _layanan_gmail(gagal=galat)
    svc._gmail_service = layanan

    assert await svc.send_email("a@b.id", "S", "t", {}) is False


async def test_send_email_config_error_saat_membangun_layanan_false(monkeypatch, svc):
    monkeypatch.setattr(settings, "GMAIL_CREDENTIALS", "{rusak")

    assert await svc.send_email("a@b.id", "S", "t", {}) is False


def test_build_email_body_dengan_dan_tanpa_referensi(svc):
    dengan = svc._build_email_body("t", {"reference_id": "PRJ-1"})
    tanpa = svc._build_email_body("t", {})

    assert "Referensi: PRJ-1" in dengan
    assert "Referensi:" not in tanpa
    assert "Portal SA" in tanpa and "tidak membalas" in tanpa


# ---  subject default


@pytest.mark.parametrize(
    ("tipe", "potongan"),
    [
        (NotificationEventType.ASSIGNMENT, "ditugaskan"),
        (NotificationEventType.STATUS_CHANGE, "Status proyek berubah"),
        (NotificationEventType.SLA_REMINDER, "Reminder"),
        (NotificationEventType.SLA_ESCALATION, "ESKALASI"),
        (NotificationEventType.HANDOVER, "Handover"),
        (NotificationEventType.DOC_READY, "siap untuk review"),
    ],
)
def test_subject_default_setiap_tipe_event(svc, tipe, potongan):
    subject = svc._get_default_subject(tipe)

    assert subject.startswith("[Portal SA]") and potongan in subject


def test_subject_default_tipe_tidak_dikenal_fallback(svc):
    assert svc._get_default_subject("tipe_baru") == "[Portal SA] Notifikasi baru"


def test_semua_tipe_event_punya_subject_spesifik(svc):
    umum = "[Portal SA] Notifikasi baru"
    assert all(svc._get_default_subject(t) != umum for t in NotificationEventType)


# ---  ketahanan


def _sesi_meledak(monkeypatch):
    def _factory():
        raise ConnectionError("db mati")

    monkeypatch.setattr(modul, "AsyncSessionLocal", _factory)


async def test_send_notification_kegagalan_db_tidak_melempar_dan_email_tidak_dijadwalkan(
    monkeypatch, svc, gmail_aktif
):
    sesi = MagicMock()
    sesi.__aenter__ = AsyncMock(return_value=sesi)
    sesi.__aexit__ = AsyncMock(return_value=False)
    sesi.commit = AsyncMock(side_effect=ConnectionError("db mati"))
    monkeypatch.setattr(modul, "AsyncSessionLocal", lambda: sesi)
    kirim = AsyncMock()
    monkeypatch.setattr(svc, "_send_email_with_retry", kirim)
    ev = NotificationEvent(
        event_type=NotificationEventType.ASSIGNMENT,
        recipient_user_id=uuid.uuid4(),
        recipient_email="a@b.id",
    )

    assert await svc.send_notification(ev) is None
    kirim.assert_not_called()


async def test_dispatch_email_kegagalan_db_tidak_melempar_dan_tidak_menjadwalkan(
    monkeypatch, svc, gmail_aktif
):
    _sesi_meledak(monkeypatch)

    await svc.dispatch_email_for_user(NotificationEventType.SLA_REMINDER, uuid.uuid4())

    assert not svc._background_tasks


@pytest.mark.parametrize("email_user", [None, ""])
async def test_dispatch_email_user_tanpa_email_dilewati(monkeypatch, svc, gmail_aktif, email_user):
    sesi = MagicMock()
    sesi.__aenter__ = AsyncMock(return_value=sesi)
    sesi.__aexit__ = AsyncMock(return_value=False)
    hasil = MagicMock()
    hasil.scalar_one_or_none.return_value = SimpleNamespace(id=uuid.uuid4(), email=email_user)
    sesi.execute = AsyncMock(return_value=hasil)
    monkeypatch.setattr(modul, "AsyncSessionLocal", lambda: sesi)

    await svc.dispatch_email_for_user(NotificationEventType.HANDOVER, uuid.uuid4())

    assert not svc._background_tasks


def test_event_komentar_punya_subject_default_sendiri():
    """Issue #125: event `komentar` tidak jatuh ke subject generik."""
    from app.services.notification_service import NotificationEventType, NotificationService

    subject = NotificationService()._get_default_subject(NotificationEventType.KOMENTAR)

    assert NotificationEventType.KOMENTAR.value == "komentar"
    assert subject == "[Portal SA] Komentar baru di proyek"
