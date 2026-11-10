"""
Fake Gmail: pengganti `notification_service.send_email` (dan penanda "Gmail terkonfigurasi").

Produksi `send_email` TIDAK pernah raise: gagal = return False (lalu `_send_email_with_retry`
mencoba ulang). Fake meniru kontrak itu. Interval retry dinolkan agar test tidak menunggu 30 detik.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services import notification_service as modul_notifikasi
from app.services.notification_service import notification_service


@dataclass
class SuratTerekam:
    to: str
    subject: str
    template: str
    context: dict[str, Any]
    berhasil: bool


@dataclass
class FakeGmail:
    """Pengendali fake Gmail. Gunakan lewat fixture `fake_gmail`."""

    terkonfigurasi: bool = True
    percobaan: list[SuratTerekam] = field(default_factory=list)
    _gagal_sisa: int = 0
    _gagal_selalu: bool = False
    _gerbang: asyncio.Event | None = None

    # ------------------------------------------------------------------ pemrograman
    def fail_next(self, times: int = 1) -> None:
        """`times` percobaan kirim berikutnya gagal (return False)."""
        self._gagal_sisa += times

    def fail_always(self) -> None:
        self._gagal_selalu = True

    def tahan_email(self) -> None:
        """
        Tahan pengiriman email background sampai `lepaskan_email()` dipanggil.

        Email dikirim lewat `asyncio.create_task` yang membuka sesi DB sendiri. Pada harness satu
        koneksi (B2), task itu dapat bertabrakan dengan sesi request yang masih berjalan
        ("savepoint does not exist"). Tahan dulu, selesaikan request, baru lepaskan.
        """
        self._gerbang_event().clear()

    def lepaskan_email(self) -> None:
        self._gerbang_event().set()

    def _gerbang_event(self) -> asyncio.Event:
        if self._gerbang is None:
            self._gerbang = asyncio.Event()
            self._gerbang.set()
        return self._gerbang

    # ------------------------------------------------------------------ perekaman
    @property
    def terkirim(self) -> list[SuratTerekam]:
        """Hanya pesan yang BERHASIL terkirim."""
        return [s for s in self.percobaan if s.berhasil]

    @property
    def gagal(self) -> list[SuratTerekam]:
        return [s for s in self.percobaan if not s.berhasil]

    async def tunggu_percobaan(self, jumlah: int, *, batas_detik: float = 2.0) -> None:
        """Tunggu sampai ada `jumlah` percobaan kirim (email dikirim di background)."""
        selesai_pada = asyncio.get_running_loop().time() + batas_detik
        while len(self.percobaan) < jumlah:
            if asyncio.get_running_loop().time() > selesai_pada:
                raise AssertionError(
                    f"hanya {len(self.percobaan)} percobaan kirim email, diharapkan {jumlah}"
                )
            await asyncio.sleep(0.01)

    # ------------------------------------------------------------------ pengganti
    async def send_email(self, to: str, subject: str, template: str, context: dict) -> bool:
        if not self.terkonfigurasi:
            return False
        berhasil = True
        if self._gagal_selalu:
            berhasil = False
        elif self._gagal_sisa > 0:
            self._gagal_sisa -= 1
            berhasil = False
        self.percobaan.append(SuratTerekam(to, subject, template, context, berhasil))
        return berhasil

    def pasang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(notification_service, "send_email", self.send_email)
        monkeypatch.setattr(
            notification_service, "_is_gmail_configured", lambda: self.terkonfigurasi
        )
        monkeypatch.setattr(modul_notifikasi, "EMAIL_RETRY_INTERVAL", 0)

        kirim_asli = notification_service._send_email_with_retry
        fake = self

        async def kirim_dengan_gerbang(event):
            await fake._gerbang_event().wait()
            await kirim_asli(event)

        monkeypatch.setattr(notification_service, "_send_email_with_retry", kirim_dengan_gerbang)
