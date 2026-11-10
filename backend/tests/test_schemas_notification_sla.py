"""
Skema response Notification dan SLA: bentuk data valid diterima, data tidak lengkap/bertipe
salah ditolak, default dan pemetaan dari objek ORM (`from_attributes`) benar.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.schemas.sla import SLAProcessingStats, SLAStatusResponse

WAKTU = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _notif(**override):
    data = {
        "id": "NOTIF-1",
        "event_type": "assignment",
        "channel": "in-app",
        "status": "sent",
        "created_at": WAKTU,
    }
    data.update(override)
    return data


class TestNotificationResponse:
    def test_data_minimal_valid_dengan_default_opsional_none(self):
        n = NotificationResponse(**_notif())
        assert n.reference_id is None
        assert n.metadata is None
        assert n.read_at is None

    def test_data_lengkap_diterima(self):
        n = NotificationResponse(
            **_notif(reference_id="PRJ-1", metadata={"k": 1}, read_at=WAKTU, status="read")
        )
        assert n.reference_id == "PRJ-1"
        assert n.metadata == {"k": 1}
        assert n.read_at == WAKTU

    @pytest.mark.parametrize("hilang", ["id", "event_type", "channel", "status", "created_at"])
    def test_field_wajib_hilang_ditolak(self, hilang):
        data = _notif()
        del data[hilang]
        with pytest.raises(ValidationError) as exc:
            NotificationResponse(**data)
        assert exc.value.errors()[0]["loc"] == (hilang,)

    def test_created_at_bukan_tanggal_ditolak(self):
        with pytest.raises(ValidationError):
            NotificationResponse(**_notif(created_at="bukan-tanggal"))

    def test_dipetakan_dari_objek_orm_lewat_from_attributes(self):
        # Atribut ORM bernama `notification_metadata`, jadi `metadata` tidak terisi lewat atribut.
        orm = SimpleNamespace(
            id="N-9",
            event_type="handover",
            channel="email",
            status="pending",
            reference_id="PRJ-9",
            metadata={"a": "b"},
            created_at=WAKTU,
            read_at=None,
        )
        n = NotificationResponse.model_validate(orm)
        assert (n.id, n.event_type, n.channel, n.status) == ("N-9", "handover", "email", "pending")
        assert n.metadata == {"a": "b"}

    def test_dipetakan_dari_model_orm_nyata_dengan_kolom_metadata(self):
        """Regresi: `NotificationLog.metadata` adalah MetaData SQLAlchemy, bukan isi kolom."""
        from app.models import NotificationLog

        orm = NotificationLog(
            id="N-1",
            event_type="assignment",
            channel="email",
            status="sent",
            notification_metadata={"proyek": "PRJ-1"},
            created_at=WAKTU,
        )
        n = NotificationResponse.model_validate(orm)
        assert n.metadata == {"proyek": "PRJ-1"}


class TestNotificationListResponse:
    def test_default_items_kosong_dan_per_page_20(self):
        r = NotificationListResponse(total=0, page=1)
        assert r.items == []
        assert r.per_page == 20

    def test_items_diparse_menjadi_notifikasi(self):
        r = NotificationListResponse(items=[_notif(), _notif(id="N2")], total=2, page=1, per_page=5)
        assert [i.id for i in r.items] == ["NOTIF-1", "N2"]
        assert r.per_page == 5

    @pytest.mark.parametrize("hilang", ["total", "page"])
    def test_total_dan_page_wajib(self, hilang):
        data = {"total": 1, "page": 1}
        del data[hilang]
        with pytest.raises(ValidationError):
            NotificationListResponse(**data)

    def test_item_tidak_valid_menggagalkan_seluruh_daftar(self):
        with pytest.raises(ValidationError):
            NotificationListResponse(items=[{"id": "x"}], total=1, page=1)

    def test_instance_default_items_tidak_dibagi_antar_objek(self):
        a = NotificationListResponse(total=0, page=1)
        a.items.append(NotificationResponse(**_notif()))
        b = NotificationListResponse(total=0, page=1)
        assert b.items == []


class TestUnreadCountResponse:
    def test_hitungan_valid(self):
        assert UnreadCountResponse(unread_count=0).unread_count == 0
        assert UnreadCountResponse(unread_count="7").unread_count == 7

    def test_wajib_dan_bertipe_integer(self):
        with pytest.raises(ValidationError):
            UnreadCountResponse()
        with pytest.raises(ValidationError):
            UnreadCountResponse(unread_count="banyak")


def _sla(**override):
    data = {
        "project_id": "PRJ-1",
        "status": "green",
        "days_elapsed": 0,
        "is_locked": False,
        "is_active": True,
        "started_at": "2025-01-01T00:00:00+00:00",
    }
    data.update(override)
    return data


class TestSLAStatusResponse:
    def test_valid_dengan_stopped_at_default_none(self):
        s = SLAStatusResponse(**_sla())
        assert s.stopped_at is None

    def test_stopped_at_diterima_bila_diisi(self):
        s = SLAStatusResponse(**_sla(stopped_at="2025-01-06T00:00:00+00:00", is_active=False))
        assert s.stopped_at == "2025-01-06T00:00:00+00:00"
        assert s.is_active is False

    @pytest.mark.parametrize(
        "hilang", ["project_id", "status", "days_elapsed", "is_locked", "is_active", "started_at"]
    )
    def test_field_wajib_hilang_ditolak(self, hilang):
        data = _sla()
        del data[hilang]
        with pytest.raises(ValidationError):
            SLAStatusResponse(**data)

    def test_days_elapsed_bukan_angka_ditolak(self):
        with pytest.raises(ValidationError):
            SLAStatusResponse(**_sla(days_elapsed="lima"))


class TestSLAProcessingStats:
    def test_errors_default_kosong_dan_tidak_dibagi_antar_instance(self):
        a = SLAProcessingStats(
            total_checked=1, reminders_sent=0, escalations_sent=0, locks_performed=0
        )
        a.errors.append("gagal")
        b = SLAProcessingStats(
            total_checked=1, reminders_sent=0, escalations_sent=0, locks_performed=0
        )
        assert b.errors == []

    def test_semua_penghitung_wajib(self):
        with pytest.raises(ValidationError) as exc:
            SLAProcessingStats()
        lokasi = {e["loc"][0] for e in exc.value.errors()}
        assert lokasi == {"total_checked", "reminders_sent", "escalations_sent", "locks_performed"}

    def test_errors_menerima_daftar_string_dan_menolak_non_string(self):
        s = SLAProcessingStats(
            total_checked=2, reminders_sent=1, escalations_sent=1, locks_performed=0, errors=["a"]
        )
        assert s.errors == ["a"]
        with pytest.raises(ValidationError):
            SLAProcessingStats(
                total_checked=2,
                reminders_sent=1,
                escalations_sent=1,
                locks_performed=0,
                errors=[{"x": 1}],
            )
