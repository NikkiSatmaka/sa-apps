"""
Service NotificationService — Modul untuk mengelola notifikasi in-app dan email.

Fitur utama:
- Kirim notifikasi in-app (selalu aktif)
- Kirim email via Gmail API (graceful fallback jika tidak dikonfigurasi)
- Event types: assignment, status_change, sla_reminder, sla_escalation, handover, doc_ready
- Logging semua notifikasi ke NotificationLogs
- Email retry: 3x interval 30s

Sesuai requirement 14.1–14.6.
"""

import asyncio
import base64
import json
import logging
import random
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from enum import Enum
from functools import partial
from typing import Any, Optional
from uuid import UUID

from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy import and_, func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification_log import NotificationLog
from app.models.user import User

logger = logging.getLogger(__name__)


# Interval retry email dalam detik
EMAIL_RETRY_INTERVAL = 30
EMAIL_MAX_RETRIES = 3

# Scope minimal untuk mengirim email via Gmail API.
GMAIL_SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailConfigError(Exception):
    """Kredensial Gmail belum dikonfigurasi atau formatnya tidak valid."""

    pass


class NotificationEventType(str, Enum):
    """Tipe event notifikasi yang didukung (requirement 14.1)."""

    ASSIGNMENT = "assignment"  # SA ditugaskan ke proyek
    STATUS_CHANGE = "status_change"  # Status proyek berubah
    SLA_REMINDER = "sla_reminder"  # H+3 DQ Number reminder
    SLA_ESCALATION = "sla_escalation"  # H+5 eskalasi ke Lead SA dan Admin
    HANDOVER = "handover"  # Handover ke PMO/Delivery
    DOC_READY = "doc_ready"  # Dokumen siap review
    KOMENTAR = "komentar"  # Komentar baru di thread proyek (#125)


@dataclass
class NotificationEvent:
    """
    Data class untuk event notifikasi yang akan dikirim.

    Berisi informasi lengkap yang dibutuhkan untuk mengirim notifikasi
    ke recipient melalui channel yang sesuai.
    """

    event_type: NotificationEventType
    recipient_user_id: UUID
    recipient_email: str
    reference_id: Optional[str] = None
    metadata: Optional[dict] = None
    subject: Optional[str] = None  # Subject email (opsional)
    template: Optional[str] = None  # Template email (opsional)


def _generate_notification_id() -> str:
    """
    Generate ID notifikasi unik.
    Format: NOTIF-{YYYYMMDD}-{random 6 chars}
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"NOTIF-{date_part}-{random_part}"


class NotificationService:
    """
    Service class untuk manajemen notifikasi.

    Menangani:
    - Pengiriman notifikasi in-app (selalu aktif)
    - Pengiriman email via Gmail API (graceful fallback)
    - Query notifikasi user dengan pagination
    - Mark as read
    - Logging semua event ke NotificationLogs

    Requirement: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
    """

    def __init__(self) -> None:
        """Inisialisasi service. Gmail service dibangun lazy saat pertama dipakai."""
        self._gmail_service = None
        self._background_tasks: set[asyncio.Task] = set()

    def _is_gmail_configured(self) -> bool:
        """
        Cek apakah Gmail credentials sudah dikonfigurasi.
        Return False jika belum — email akan di-skip (graceful fallback).
        """
        return bool(settings.GMAIL_CREDENTIALS and settings.GMAIL_CREDENTIALS.strip())

    def _get_gmail_service(self):
        """
        Lazy initialization Gmail service memakai service account credentials.

        Kredensial dibaca dari settings.GMAIL_CREDENTIALS (JSON service account,
        format sama dengan GDRIVE_SERVICE_ACCOUNT_KEY). Jika GMAIL_SENDER di-set,
        kredensial di-delegate (impersonate) ke alamat tersebut — diperlukan untuk
        service account dengan domain-wide delegation.

        Raises:
            GmailConfigError: Jika kredensial kosong atau formatnya tidak valid.
        """
        if self._gmail_service is not None:
            return self._gmail_service

        if not self._is_gmail_configured():
            raise GmailConfigError(
                "Gmail credentials belum dikonfigurasi. "
                "Set GMAIL_CREDENTIALS di environment variables."
            )

        try:
            key_data = json.loads(settings.GMAIL_CREDENTIALS)
            credentials = service_account.Credentials.from_service_account_info(
                key_data,
                scopes=GMAIL_SEND_SCOPES,
            )
            # Domain-wide delegation: impersonate alamat pengirim bila di-set.
            sender = (settings.GMAIL_SENDER or "").strip()
            if sender:
                credentials = credentials.with_subject(sender)
            self._gmail_service = build("gmail", "v1", credentials=credentials)
            return self._gmail_service
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Gagal parse Gmail credentials: {e}")
            raise GmailConfigError(f"Format GMAIL_CREDENTIALS tidak valid: {e}")

    async def send_notification(self, event: NotificationEvent) -> None:
        """
        Kirim notifikasi in-app + email (jika tersedia).

        Flow:
        1. Selalu buat in-app notification record (status: sent)
        2. Jika Gmail dikonfigurasi, coba kirim email (async, retry 3x)
        3. Log semua ke NotificationLogs

        Args:
            event: NotificationEvent berisi detail event yang akan dikirim.

        Requirement: 14.1, 14.2, 14.3
        """
        async with AsyncSessionLocal() as db:
            try:
                # 1. Buat in-app notification (selalu aktif)
                inapp_id = _generate_notification_id()
                inapp_log = NotificationLog(
                    id=inapp_id,
                    event_type=event.event_type.value,
                    recipient_user_id=event.recipient_user_id,
                    channel="in-app",
                    status="sent",
                    reference_id=event.reference_id,
                    notification_metadata=event.metadata,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(inapp_log)
                await db.commit()

                logger.info(
                    f"In-app notification terkirim: {inapp_id} "
                    f"(type={event.event_type.value}, recipient={event.recipient_user_id})"
                )

                # 2. Kirim email jika Gmail dikonfigurasi (requirement 14.4)
                if self._is_gmail_configured():
                    # Email dikirim async — tidak memblokir flow utama
                    asyncio.create_task(self._send_email_with_retry(event))
                else:
                    logger.info("Gmail tidak dikonfigurasi — email dilewati (graceful fallback).")

            except Exception as e:
                logger.error(f"Gagal mengirim notifikasi: {e}")
                # Notifikasi tidak boleh menggagalkan flow utama
                # Hanya log error dan lanjut

    async def dispatch_email_for_user(
        self,
        event_type: NotificationEventType,
        recipient_user_id: UUID,
        reference_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Picu email saja (tanpa in-app) untuk caller yang sudah menulis NotificationLog
        in-app sendiri dalam transaksinya — mis. reminder/eskalasi SLA.

        Graceful: no-op bila Gmail belum dikonfigurasi; tidak pernah raise. Email
        dikirim di background dengan retry (`_send_email_with_retry`).
        """
        if not self._is_gmail_configured():
            return

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.id == recipient_user_id))
                user = result.scalar_one_or_none()

            if user is None or not user.email:
                logger.warning(
                    f"Email {event_type.value} dilewati: user {recipient_user_id} "
                    f"tidak ditemukan / tanpa email."
                )
                return

            event = NotificationEvent(
                event_type=event_type,
                recipient_user_id=user.id,
                recipient_email=user.email,
                reference_id=reference_id,
                metadata=metadata,
            )
            task = asyncio.create_task(self._send_email_with_retry(event))
            # Simpan referensi agar task tidak di-GC sebelum selesai.
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except Exception as e:  # noqa: BLE001 - email tidak boleh menggagalkan caller
            logger.error(f"Gagal menjadwalkan email {event_type.value}: {e}")

    async def send_email_langsung(
        self,
        to: str,
        event_type: NotificationEventType,
        reference_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        subject: Optional[str] = None,
    ) -> bool:
        """
        Kirim email SAJA ke alamat yang tidak punya akun portal (mis. PMO/Delivery Lead, #76).

        Tidak menulis `NotificationLog` karena kolom penerimanya wajib user portal. Email dikirim
        di background dengan retry yang sama (`EMAIL_MAX_RETRIES`, jeda `EMAIL_RETRY_INTERVAL`);
        kegagalan akhir hanya masuk application log. Tidak pernah raise.

        Returns:
            True bila pengiriman dijadwalkan, False bila Gmail belum dikonfigurasi.
        """
        if not self._is_gmail_configured():
            logger.info(f"Email langsung ke {to} dilewati: Gmail belum dikonfigurasi.")
            return False

        task = asyncio.create_task(
            self._kirim_email_langsung(to, event_type, reference_id, metadata, subject)
        )
        # Simpan referensi agar task tidak di-GC sebelum selesai.
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return True

    async def _kirim_email_langsung(
        self,
        to: str,
        event_type: NotificationEventType,
        reference_id: Optional[str],
        metadata: Optional[dict],
        subject: Optional[str],
    ) -> None:
        for attempt in range(1, EMAIL_MAX_RETRIES + 1):
            success = await self.send_email(
                to=to,
                subject=subject or self._get_default_subject(event_type),
                template=event_type.value,
                context={
                    "event_type": event_type.value,
                    "reference_id": reference_id,
                    "metadata": metadata,
                },
            )
            if success:
                return
            if attempt < EMAIL_MAX_RETRIES:
                await asyncio.sleep(EMAIL_RETRY_INTERVAL)
        logger.error(f"Email langsung gagal setelah {EMAIL_MAX_RETRIES} percobaan ke {to}")

    async def _send_email_with_retry(self, event: NotificationEvent) -> None:
        """
        Kirim email dengan retry mechanism (requirement 14.5).

        Retry: 3 kali dengan interval 30 detik.
        Jika semua retry gagal, log status 'failed'.

        Args:
            event: NotificationEvent berisi detail email.
        """
        async with AsyncSessionLocal() as db:
            # Buat record email notification (status: pending)
            email_id = _generate_notification_id()
            email_log = NotificationLog(
                id=email_id,
                event_type=event.event_type.value,
                recipient_user_id=event.recipient_user_id,
                channel="email",
                status="pending",
                reference_id=event.reference_id,
                notification_metadata=event.metadata,
                created_at=datetime.now(timezone.utc),
            )
            db.add(email_log)
            await db.commit()

            # Coba kirim email dengan retry
            for attempt in range(1, EMAIL_MAX_RETRIES + 1):
                success = await self.send_email(
                    to=event.recipient_email,
                    subject=event.subject or self._get_default_subject(event.event_type),
                    template=event.template or event.event_type.value,
                    context={
                        "event_type": event.event_type.value,
                        "reference_id": event.reference_id,
                        "metadata": event.metadata,
                    },
                )

                if success:
                    # Update status ke 'sent'
                    await db.execute(
                        update(NotificationLog)
                        .where(NotificationLog.id == email_id)
                        .values(status="sent")
                    )
                    await db.commit()
                    logger.info(
                        f"Email terkirim: {email_id} ke {event.recipient_email} (attempt {attempt})"
                    )
                    return

                # Retry — tunggu 30 detik sebelum coba lagi
                if attempt < EMAIL_MAX_RETRIES:
                    logger.warning(
                        f"Email gagal (attempt {attempt}/{EMAIL_MAX_RETRIES}), "
                        f"retry dalam {EMAIL_RETRY_INTERVAL}s..."
                    )
                    await asyncio.sleep(EMAIL_RETRY_INTERVAL)

            # Semua retry gagal — update status ke 'failed'
            await db.execute(
                update(NotificationLog)
                .where(NotificationLog.id == email_id)
                .values(status="failed")
            )
            await db.commit()
            logger.error(
                f"Email gagal setelah {EMAIL_MAX_RETRIES} percobaan: "
                f"{email_id} ke {event.recipient_email}"
            )

    async def send_email(
        self,
        to: str,
        subject: str,
        template: str,
        context: dict,
    ) -> bool:
        """
        Kirim email via Gmail API (requirement 14.4).

        Return False jika Gmail tidak dikonfigurasi atau pengiriman gagal.
        Ini adalah graceful fallback — tidak akan raise exception.

        Args:
            to: Alamat email penerima.
            subject: Subject email.
            template: Nama template email.
            context: Data konteks untuk template.

        Returns:
            True jika email berhasil dikirim, False jika gagal.
        """
        if not self._is_gmail_configured():
            logger.info("Gmail API belum dikonfigurasi — email tidak dikirim.")
            return False

        try:
            # Panggilan Gmail API bersifat synchronous (blocking); jalankan di
            # executor agar tidak memblokir event loop async.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                partial(self._send_email_sync, to, subject, template, context),
            )
            logger.info(
                f"[Gmail API] Email terkirim ke {to} | Subject: {subject} | Template: {template}"
            )
            return True

        except Exception as e:
            # Graceful fallback: jangan raise. Retry ditangani oleh caller
            # (_send_email_with_retry) sesuai kontrak 3x interval 30s.
            logger.error(f"Gagal mengirim email ke {to}: {e}")
            return False

    def _build_email_body(self, template: str, context: dict) -> str:
        """
        Susun body email plain-text dari template dan context.

        Untuk MVP body cukup informatif: menyebut reference_id bila ada.
        Template HTML penuh bisa ditambahkan belakangan tanpa mengubah kontrak.
        """
        reference_id = context.get("reference_id")
        lines = [
            "Halo,",
            "",
            "Anda menerima notifikasi dari Portal SA.",
        ]
        if reference_id:
            lines.append(f"Referensi: {reference_id}")
        lines += [
            "",
            "Silakan buka Portal SA untuk detail lebih lanjut.",
            "",
            "Email ini dikirim otomatis, mohon tidak membalas.",
        ]
        return "\n".join(lines)

    def _send_email_sync(
        self,
        to: str,
        subject: str,
        template: str,
        context: dict,
    ) -> None:
        """
        Kirim email via Gmail API (synchronous — dipanggil dari executor).

        Menyusun MIME message, meng-encode base64url, lalu memanggil
        users().messages().send(). Raise exception bila gagal (ditangkap caller).
        """
        service = self._get_gmail_service()

        message = MIMEText(self._build_email_body(template, context), "plain", "utf-8")
        message["To"] = to
        message["Subject"] = subject
        sender = (settings.GMAIL_SENDER or "").strip()
        if sender:
            message["From"] = sender

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

    async def get_user_notifications(
        self,
        user_id: UUID,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """
        Ambil riwayat notifikasi user dengan pagination (requirement 14.7).

        Hanya menampilkan notifikasi in-app, diurutkan terbaru terlebih dahulu.

        Args:
            user_id: UUID user yang ingin dilihat notifikasinya.
            page: Halaman yang diminta (1-based).
            per_page: Jumlah item per halaman (default 20).

        Returns:
            Dict berisi items, total, page, per_page.
        """
        async with AsyncSessionLocal() as db:
            # Batasi per_page maksimal 20
            per_page = min(per_page, 20)

            # Kondisi: hanya in-app notification untuk user tertentu
            conditions = [
                NotificationLog.recipient_user_id == user_id,
                NotificationLog.channel == "in-app",
            ]
            where_clause = and_(*conditions)

            # Hitung total
            count_query = select(func.count()).select_from(NotificationLog).where(where_clause)
            total_result = await db.execute(count_query)
            total = total_result.scalar() or 0

            # Query data dengan pagination, urut terbaru
            offset = (page - 1) * per_page
            data_query = (
                select(NotificationLog)
                .where(where_clause)
                .order_by(NotificationLog.created_at.desc())
                .offset(offset)
                .limit(per_page)
            )
            result = await db.execute(data_query)
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    async def mark_as_read(self, notification_id: str, user_id: UUID) -> None:
        """
        Tandai notifikasi sebagai dibaca (requirement 14.8).

        Hanya bisa dilakukan oleh pemilik notifikasi.

        Args:
            notification_id: ID notifikasi yang akan ditandai.
            user_id: UUID user yang meminta (untuk validasi ownership).

        Raises:
            ValueError: Jika notifikasi tidak ditemukan atau bukan milik user.
        """
        async with AsyncSessionLocal() as db:
            # Cari notifikasi
            result = await db.execute(
                select(NotificationLog).where(NotificationLog.id == notification_id)
            )
            notification = result.scalar_one_or_none()

            if notification is None:
                raise ValueError(f"Notifikasi '{notification_id}' tidak ditemukan.")

            # Validasi ownership. Pesan sengaja sama dengan "tidak ditemukan" agar keberadaan
            # notifikasi milik orang lain tidak bocor.
            if notification.recipient_user_id != user_id:
                raise ValueError(f"Notifikasi '{notification_id}' tidak ditemukan.")

            # Update status dan read_at
            notification.status = "read"
            notification.read_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"Notifikasi {notification_id} ditandai dibaca oleh {user_id}")

    async def get_unread_count(self, user_id: UUID) -> int:
        """
        Hitung jumlah notifikasi in-app yang belum dibaca.

        Args:
            user_id: UUID user yang ingin dicek.

        Returns:
            Jumlah notifikasi yang belum dibaca.
        """
        async with AsyncSessionLocal() as db:
            count_query = (
                select(func.count())
                .select_from(NotificationLog)
                .where(
                    and_(
                        NotificationLog.recipient_user_id == user_id,
                        NotificationLog.channel == "in-app",
                        NotificationLog.status != "read",
                    )
                )
            )
            result = await db.execute(count_query)
            return result.scalar() or 0

    def _get_default_subject(self, event_type: NotificationEventType) -> str:
        """
        Dapatkan subject email default berdasarkan tipe event.

        Args:
            event_type: Tipe event notifikasi.

        Returns:
            String subject email.
        """
        subjects = {
            NotificationEventType.ASSIGNMENT: "[Portal SA] Anda ditugaskan ke proyek baru",
            NotificationEventType.STATUS_CHANGE: "[Portal SA] Status proyek berubah",
            NotificationEventType.SLA_REMINDER: "[Portal SA] Reminder: DQ Number belum diinput",
            NotificationEventType.SLA_ESCALATION: "[Portal SA] ESKALASI: DQ Number melewati batas",
            NotificationEventType.HANDOVER: "[Portal SA] Handover proyek ke tim Delivery",
            NotificationEventType.DOC_READY: "[Portal SA] Dokumen siap untuk review",
            NotificationEventType.KOMENTAR: "[Portal SA] Komentar baru di proyek",
        }
        return subjects.get(event_type, "[Portal SA] Notifikasi baru")


# Singleton instance — digunakan oleh modul lain
notification_service = NotificationService()
