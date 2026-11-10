"""
Unit test `calendar_service` (tiket #60, spec #49; ADR 0007: Calendar read-only).

HTTP ke Google dipalsukan di boundary (`httpx.MockTransport`) sehingga kode produksi
(`fetch_events`, parsing, durasi) berjalan utuh tanpa jaringan. Pasangan integrasi:
`tests/integration/test_kalender_t60.py` (API + Postgres + fake Calendar).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services import calendar_service as modul
from app.services.calendar_service import (
    ALL_DAY_DURATION_HOURS,
    CalendarAPIError,
    CalendarService,
    CalendarTimeoutError,
    calendar_service,
)

KELAS_ASLI = httpx.AsyncClient


def _pasang_http(monkeypatch, handler) -> list[httpx.Request]:
    """Ganti `httpx.AsyncClient` di modul dengan klien ber-MockTransport; kembalikan request."""
    diterima: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        diterima.append(request)
        return handler(request)

    def _pabrik(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_handler)
        return KELAS_ASLI(*args, **kwargs)

    monkeypatch.setattr(modul.httpx, "AsyncClient", _pabrik)
    return diterima


def _item(event_id="e1", **o) -> dict:
    dasar = {
        "id": event_id,
        "summary": "Rapat",
        "start": {"dateTime": "2030-01-01T09:00:00+00:00"},
        "end": {"dateTime": "2030-01-01T10:00:00+00:00"},
    }
    dasar.update(o)
    return dasar


# ---  fetch_events


async def test_fetch_events_mengirim_token_dan_rentang_tujuh_hari_serta_parse_hasil(monkeypatch):
    diterima = _pasang_http(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "items": [
                    _item("e1", description="Agenda"),
                    _item("e2", start={"date": "2030-01-02"}, end={"date": "2030-01-03"}),
                    {"summary": "tanpa id"},
                ]
            },
        ),
    )
    sebelum = datetime.now(timezone.utc)

    events = await CalendarService().fetch_events("ya29.abc")

    req = diterima[0]
    assert req.headers["authorization"] == "Bearer ya29.abc"
    assert req.url.path == "/calendar/v3/calendars/primary/events"
    q = req.url.params
    assert q["maxResults"] == "200"
    assert q["singleEvents"] == "true" and q["orderBy"] == "startTime"
    awal = datetime.fromisoformat(q["timeMin"])
    akhir = datetime.fromisoformat(q["timeMax"])
    assert akhir - awal == timedelta(days=14)
    assert abs((awal + timedelta(days=7)) - sebelum) < timedelta(minutes=1)
    # Event tanpa id dilewati; all-day berdurasi 8 jam.
    assert [e.gcal_event_id for e in events] == ["e1", "e2"]
    assert events[0].duration_hours == Decimal("1.00") and events[0].description == "Agenda"
    assert events[1].is_all_day and events[1].duration_hours == ALL_DAY_DURATION_HOURS


async def test_fetch_events_tanpa_items_menghasilkan_daftar_kosong(monkeypatch):
    _pasang_http(monkeypatch, lambda r: httpx.Response(200, json={}))

    assert await CalendarService().fetch_events("t") == []


@pytest.mark.parametrize("kode", [400, 401, 403, 500])
async def test_fetch_events_status_bukan_200_menjadi_calendar_api_error(monkeypatch, kode):
    _pasang_http(monkeypatch, lambda r: httpx.Response(kode, text="x" * 500))

    with pytest.raises(CalendarAPIError) as exc:
        await CalendarService().fetch_events("t")

    assert f"({kode})" in exc.value.message
    assert len(exc.value.message) < 300  # detail error dipotong, tidak membocorkan seluruh body


async def test_fetch_events_timeout_menjadi_calendar_timeout_error(monkeypatch):
    def _habis_waktu(request):
        raise httpx.ReadTimeout("lambat", request=request)

    _pasang_http(monkeypatch, _habis_waktu)

    with pytest.raises(CalendarTimeoutError) as exc:
        await CalendarService().fetch_events("t")

    assert exc.value.message == "Google Calendar API timeout"


async def test_fetch_events_gagal_koneksi_menjadi_calendar_api_error(monkeypatch):
    def _putus(request):
        raise httpx.ConnectError("tidak ada rute", request=request)

    _pasang_http(monkeypatch, _putus)

    with pytest.raises(CalendarAPIError) as exc:
        await CalendarService().fetch_events("t")

    assert "Gagal menghubungi Google Calendar" in exc.value.message


def test_hierarki_exception_dan_singleton():
    assert issubclass(CalendarTimeoutError, modul.CalendarServiceError)
    assert issubclass(CalendarAPIError, modul.CalendarServiceError)
    assert isinstance(calendar_service, CalendarService)


# ---  _parse_event


def test_parse_event_tanpa_judul_memakai_placeholder():
    ev = CalendarService()._parse_event(
        {
            "id": "x",
            "start": {"dateTime": "2030-01-01T09:00:00+00:00"},
            "end": {"dateTime": "2030-01-01T09:30:00+00:00"},
        }
    )

    assert ev.title == "(No Title)"
    assert ev.duration_hours == Decimal("0.50")


def test_parse_event_tanpa_id_dikembalikan_none():
    assert CalendarService()._parse_event({"summary": "x"}) is None


def test_parse_event_all_day_mengabaikan_end_untuk_durasi():
    ev = CalendarService()._parse_event(
        {"id": "x", "start": {"date": "2030-01-02"}, "end": {"date": "2030-01-09"}}
    )

    assert ev.is_all_day is True
    assert ev.duration_hours == Decimal("8.00")
    assert (ev.start, ev.end) == ("2030-01-02", "2030-01-09")


def test_parse_event_tanpa_waktu_sama_sekali_fallback_satu_jam():
    ev = CalendarService()._parse_event({"id": "x"})

    assert ev.is_all_day is False
    assert ev.duration_hours == Decimal("1.00")
    assert ev.start is None


# ---  durasi


@pytest.mark.parametrize(
    ("mulai", "selesai", "diharapkan"),
    [
        ("2030-01-01T09:00:00+00:00", "2030-01-01T10:30:00+00:00", "1.50"),
        ("2030-01-01T09:00:00+00:00", "2030-01-01T09:05:00+00:00", "0.25"),  # dinaikkan ke minimum
        (
            "2030-01-01T09:00:00+00:00",
            "2030-01-03T09:00:00+00:00",
            "24.00",
        ),  # dipangkas ke maksimum
        ("2030-01-01T10:00:00+00:00", "2030-01-01T09:00:00+00:00", "0.25"),  # akhir < awal
        ("2030-01-01T09:00:00+07:00", "2030-01-01T09:00:00+00:00", "7.00"),  # beda zona waktu
        (None, "2030-01-01T10:00:00+00:00", "1.00"),
        ("2030-01-01T09:00:00+00:00", None, "1.00"),
        ("", "", "1.00"),
        ("bukan-tanggal", "2030-01-01T10:00:00+00:00", "1.00"),
        ("2030-01-01T09:00:00", "2030-01-01T10:00:00+00:00", "1.00"),  # naive vs aware → TypeError
    ],
)
def test_calculate_duration_kasus_batas(mulai, selesai, diharapkan):
    assert CalendarService()._calculate_duration(mulai, selesai) == Decimal(diharapkan)


@given(menit=st.integers(min_value=-3000, max_value=5000))
def test_property_durasi_selalu_di_rentang_valid_dan_dua_desimal(menit):
    awal = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    hasil = CalendarService()._calculate_duration(
        awal.isoformat(), (awal + timedelta(minutes=menit)).isoformat()
    )

    assert Decimal("0.25") <= hasil <= Decimal("24.00")
    assert hasil == hasil.quantize(Decimal("0.01"))


@given(menit=st.integers(min_value=15, max_value=24 * 60))
def test_property_durasi_dalam_rentang_sama_dengan_selisih_sebenarnya(menit):
    awal = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    hasil = CalendarService()._calculate_duration(
        awal.isoformat(), (awal + timedelta(minutes=menit)).isoformat()
    )

    assert abs(hasil - Decimal(menit) / Decimal(60)) <= Decimal("0.005")


# ---  generate_notes


def test_generate_notes_tanpa_deskripsi():
    assert CalendarService.generate_notes("Rapat") == "[Calendar] Rapat"


def test_generate_notes_dengan_deskripsi():
    assert CalendarService.generate_notes("Rapat", "Bahas BOQ") == "[Calendar] Rapat — Bahas BOQ"


def test_generate_notes_deskripsi_kosong_dianggap_tanpa_deskripsi():
    assert CalendarService.generate_notes("Rapat", "") == "[Calendar] Rapat"


def test_generate_notes_deskripsi_dipotong_500_karakter():
    hasil = CalendarService.generate_notes("R", "a" * 900)

    assert hasil == "[Calendar] R — " + "a" * 500


@given(judul=st.text(max_size=50), deskripsi=st.text(max_size=1000))
def test_property_generate_notes_selalu_berawalan_calendar_dan_deskripsi_maks_500(judul, deskripsi):
    hasil = CalendarService.generate_notes(judul, deskripsi)

    assert hasil.startswith(f"[Calendar] {judul}")
    assert len(hasil) <= len(f"[Calendar] {judul} — ") + 500
