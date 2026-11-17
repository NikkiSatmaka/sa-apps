"""
Unit tests untuk pengiriman email via Gmail API di NotificationService.

Menguji:
- Jalur sukses: email terkirim via Gmail API (service di-mock, tanpa jaringan nyata).
- Graceful fallback: tanpa kredensial Gmail, email di-skip tanpa crash.
- Email delivery is attempted once; persisted outcome coverage lives in PostgreSQL integration tests.

Semua panggilan Gmail API di-mock — tidak ada panggilan jaringan nyata.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from app.services.notification_service import NotificationService

# =============================================================================
# Fixtures & Helpers
# =============================================================================


@pytest.fixture
def service():
    """NotificationService instance baru untuk setiap test."""
    return NotificationService()


@pytest.fixture
def mock_gmail_service():
    """Mock Gmail service yang sudah ter-build (users().messages().send())."""
    gmail = MagicMock()
    send_mock = MagicMock()
    send_mock.execute.return_value = {"id": "gmail_msg_123", "labelIds": ["SENT"]}
    gmail.users.return_value.messages.return_value.send.return_value = send_mock
    return gmail


# =============================================================================
# Test: _is_gmail_configured
# =============================================================================


class TestIsGmailConfigured:
    """Cek deteksi konfigurasi kredensial Gmail."""

    def test_tidak_dikonfigurasi_jika_kosong(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = ""
            assert service._is_gmail_configured() is False

    def test_tidak_dikonfigurasi_jika_hanya_spasi(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = "   "
            assert service._is_gmail_configured() is False

    def test_dikonfigurasi_jika_ada_isi(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = '{"type": "service_account"}'
            assert service._is_gmail_configured() is True


# =============================================================================
# Test: _get_gmail_service (lazy init)
# =============================================================================


class TestGmailServiceInit:
    """Test inisialisasi lazy Gmail service."""

    def test_credentials_kosong_raise_error(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = ""
            with pytest.raises(Exception, match="belum dikonfigurasi"):
                service._get_gmail_service()

    def test_credentials_json_invalid_raise_error(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = "bukan-json-valid"
            with pytest.raises(Exception, match="tidak valid"):
                service._get_gmail_service()


# =============================================================================
# Test: send_email — graceful fallback tanpa kredensial
# =============================================================================


class TestSendEmailFallback:
    """Tanpa kredensial Gmail, email di-skip tanpa raise (graceful fallback)."""

    @pytest.mark.asyncio
    async def test_return_false_tanpa_kredensial(self, service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = ""
            result = await service.send_email(
                to="user@company.com",
                subject="Tes",
                template="assignment",
                context={},
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_tidak_memanggil_gmail_tanpa_kredensial(self, service):
        """Tanpa kredensial, _get_gmail_service tidak boleh dipanggil."""
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = ""
            with patch.object(
                service, "_get_gmail_service"
            ) as mock_get_service:
                result = await service.send_email(
                    to="user@company.com",
                    subject="Tes",
                    template="assignment",
                    context={},
                )
        assert result is False
        mock_get_service.assert_not_called()


# =============================================================================
# Test: send_email — jalur sukses (Gmail API di-mock)
# =============================================================================


class TestSendEmailSuccess:
    """Email benar-benar dikirim via Gmail API (service di-mock)."""

    @pytest.mark.asyncio
    async def test_sukses_kirim_email(self, service, mock_gmail_service):
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = '{"type": "service_account"}'
            mock_settings.GMAIL_SENDER = "noreply@company.com"
            service._gmail_service = mock_gmail_service

            result = await service.send_email(
                to="user@company.com",
                subject="Anda ditugaskan",
                template="assignment",
                context={"reference_id": "PRJ-001"},
            )

        assert result is True
        # send() harus dipanggil tepat sekali
        send = mock_gmail_service.users.return_value.messages.return_value.send
        send.assert_called_once()

    @pytest.mark.asyncio
    async def test_payload_email_benar(self, service, mock_gmail_service):
        """Payload berisi userId=me, raw base64url dengan to/subject yang benar."""
        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = '{"type": "service_account"}'
            mock_settings.GMAIL_SENDER = "noreply@company.com"
            service._gmail_service = mock_gmail_service

            await service.send_email(
                to="user@company.com",
                subject="Subjek Uji",
                template="assignment",
                context={},
            )

        send = mock_gmail_service.users.return_value.messages.return_value.send
        _, kwargs = send.call_args
        assert kwargs["userId"] == "me"
        raw = kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8")
        assert "user@company.com" in decoded
        assert "Subjek Uji" in decoded

    @pytest.mark.asyncio
    async def test_return_false_jika_send_gagal(self, service, mock_gmail_service):
        """Jika Gmail API raise, send_email menangkap dan return False (tidak crash)."""
        send = mock_gmail_service.users.return_value.messages.return_value.send
        send.return_value.execute.side_effect = RuntimeError("API error")

        with patch("app.services.notification_service.settings") as mock_settings:
            mock_settings.GMAIL_CREDENTIALS = '{"type": "service_account"}'
            mock_settings.GMAIL_SENDER = "noreply@company.com"
            service._gmail_service = mock_gmail_service

            result = await service.send_email(
                to="user@company.com",
                subject="Tes",
                template="assignment",
                context={},
            )

        assert result is False


