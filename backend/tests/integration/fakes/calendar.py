"""
Fake Calendar: pengganti `calendar_service.fetch_events` dengan event terprogram.

Event diberikan sebagai item mentah gaya Google Calendar API (`id`, `summary`, `start`, `end`,
`description`) dan di-parse oleh `calendar_service._parse_event` ASLI, sehingga deteksi all-day dan
perhitungan durasi tetap logika produksi. Kegagalan mengangkat exception produksi yang sama.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.calendar_service import (
    CalendarAPIError,
    CalendarTimeoutError,
    calendar_service,
)


def event_berjadwal(
    event_id: str, judul: str, mulai: str, selesai: str, deskripsi: str | None = None
) -> dict[str, Any]:
    """Item event berjam (`dateTime` ISO 8601 dengan zona)."""
    item: dict[str, Any] = {
        "id": event_id,
        "summary": judul,
        "start": {"dateTime": mulai},
        "end": {"dateTime": selesai},
    }
    if deskripsi is not None:
        item["description"] = deskripsi
    return item


def event_seharian(event_id: str, judul: str, tanggal: str, tanggal_akhir: str) -> dict[str, Any]:
    """Item event all-day (`date` saja, durasi 8 jam di produksi)."""
    return {
        "id": event_id,
        "summary": judul,
        "start": {"date": tanggal},
        "end": {"date": tanggal_akhir},
    }


@dataclass
class FakeCalendar:
    """Pengendali fake Calendar. Gunakan lewat fixture `fake_calendar`."""

    items: list[dict[str, Any]] = field(default_factory=list)
    access_token_diterima: list[str] = field(default_factory=list)
    _galat_berikutnya: list[Exception] = field(default_factory=list)
    _galat_selalu: Exception | None = None

    # ------------------------------------------------------------------ pemrograman
    def set_events(self, *items: dict[str, Any]) -> None:
        """Ganti event yang dikembalikan sync (item mentah gaya Google)."""
        self.items = list(items)

    def fail_next(self, jenis: str = "api", pesan: str = "fake Calendar gagal") -> None:
        """Sync berikutnya gagal: "timeout" (CalendarTimeoutError) atau "api" (CalendarAPIError)."""
        self._galat_berikutnya.append(self._galat(jenis, pesan))

    def fail_always(self, jenis: str = "api", pesan: str = "fake Calendar gagal") -> None:
        self._galat_selalu = self._galat(jenis, pesan)

    @staticmethod
    def _galat(jenis: str, pesan: str) -> Exception:
        assert jenis in ("timeout", "api"), f"jenis galat tidak dikenal: {jenis!r}"
        return CalendarTimeoutError() if jenis == "timeout" else CalendarAPIError(pesan)

    # ------------------------------------------------------------------ pengganti
    async def fetch_events(self, access_token: str):
        self.access_token_diterima.append(access_token)
        if self._galat_berikutnya:
            raise self._galat_berikutnya.pop(0)
        if self._galat_selalu is not None:
            raise self._galat_selalu
        hasil = (calendar_service._parse_event(item) for item in self.items)
        return [e for e in hasil if e is not None]

    def pasang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(calendar_service, "fetch_events", self.fetch_events)
