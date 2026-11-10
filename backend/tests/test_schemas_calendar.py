"""
Skema Calendar (SA Spec Flow 3): pemetaan event Google Calendar ke Activity Log. Validasi
konsistensi work_type selaras ActivityLogCreate; durasi override 0.25–24.00.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.activity_log import (
    NON_PROJECT_SUBTASK_CATEGORIES,
    PROJECT_SUBTASK_CATEGORIES,
    VALID_PROJECT_PHASES,
    ActivityLogCreate,
)
from app.schemas.calendar import (
    CalendarEventResponse,
    CalendarMapRequest,
    CalendarMapResponse,
    CalendarSyncRequest,
    CalendarSyncResponse,
)


def _project(**o):
    d = {
        "gcal_event_id": "evt-1",
        "work_type": "Project",
        "project_id": "PRJ-1",
        "project_phase": "Pre-Implementation",
        "subtask_category": "Customer Meeting",
        "event_title": "Rapat",
    }
    d.update(o)
    return d


def _non_project(**o):
    d = {
        "gcal_event_id": "evt-2",
        "work_type": "Non-Project",
        "subtask_category": "Training",
        "event_title": "Pelatihan",
    }
    d.update(o)
    return d


def _ditolak(**data) -> str:
    with pytest.raises(ValidationError) as exc:
        CalendarMapRequest(**data)
    return str(exc.value)


class TestCalendarSyncRequest:
    def test_access_token_wajib(self):
        assert CalendarSyncRequest(access_token="tok").access_token == "tok"
        with pytest.raises(ValidationError):
            CalendarSyncRequest()


class TestCalendarMapRequestValid:
    def test_project_valid_dengan_default(self):
        r = CalendarMapRequest(**_project())
        assert r.duration_hours is None and r.raw_notes is None
        assert r.is_all_day is False and r.event_start is None

    def test_work_type_default_project(self):
        d = _project()
        del d["work_type"]
        assert CalendarMapRequest(**d).work_type == "Project"

    def test_non_project_valid(self):
        r = CalendarMapRequest(**_non_project())
        assert r.project_id is None and r.project_phase is None

    def test_event_waktu_dan_all_day_diterima(self):
        mulai = datetime(2025, 1, 1, 9, tzinfo=timezone.utc)
        r = CalendarMapRequest(**_project(is_all_day=True, event_start=mulai, event_end=mulai))
        assert r.is_all_day is True and r.event_start == mulai

    @pytest.mark.parametrize("kat", PROJECT_SUBTASK_CATEGORIES)
    def test_kategori_project(self, kat):
        assert CalendarMapRequest(**_project(subtask_category=kat))

    @pytest.mark.parametrize("kat", NON_PROJECT_SUBTASK_CATEGORIES)
    def test_kategori_non_project(self, kat):
        assert CalendarMapRequest(**_non_project(subtask_category=kat))

    @pytest.mark.parametrize("d", ["0.25", "1", "24", "24.00"])
    def test_durasi_override_dalam_rentang(self, d):
        assert CalendarMapRequest(**_project(duration_hours=d)).duration_hours == Decimal(d)

    def test_batas_panjang_gcal_event_id_dan_project_id(self):
        assert CalendarMapRequest(**_project(gcal_event_id="e" * 255))
        assert CalendarMapRequest(**_project(project_id="p" * 50))


class TestCalendarMapRequestDitolak:
    @pytest.mark.parametrize("d", ["0", "0.24", "24.01", "-1"])
    def test_durasi_override_di_luar_rentang(self, d):
        _ditolak(**_project(duration_hours=d))

    def test_gcal_event_id_kosong_atau_terlalu_panjang(self):
        _ditolak(**_project(gcal_event_id=""))
        _ditolak(**_project(gcal_event_id="e" * 256))

    def test_project_id_terlalu_panjang(self):
        _ditolak(**_project(project_id="p" * 51))

    def test_work_type_tidak_valid(self):
        assert "work_type tidak valid" in _ditolak(**_project(work_type="X"))

    def test_project_tanpa_project_id(self):
        assert "project_id wajib" in _ditolak(**_project(project_id=None))

    def test_project_tanpa_fase(self):
        assert "project_phase wajib" in _ditolak(**_project(project_phase=None))

    def test_project_fase_tidak_valid(self):
        assert "project_phase tidak valid" in _ditolak(**_project(project_phase="Selesai"))

    def test_non_project_dengan_proyek(self):
        assert "tidak boleh terkait proyek" in _ditolak(**_non_project(project_id="PRJ-1"))

    def test_non_project_dengan_fase(self):
        assert "tidak boleh punya project_phase" in _ditolak(
            **_non_project(project_phase="Implementation")
        )

    def test_kategori_salah_set(self):
        assert "tidak valid untuk" in _ditolak(**_project(subtask_category="Training"))
        assert "tidak valid untuk" in _ditolak(**_non_project(subtask_category="Assessment"))

    def test_field_wajib_hilang(self):
        for hilang in ("gcal_event_id", "subtask_category", "event_title"):
            d = _project()
            del d[hilang]
            assert hilang in _ditolak(**d)


class TestSelarasDenganActivityLogCreate:
    """Spec kode: aturan konsistensi Calendar harus identik dengan ActivityLogCreate."""

    @given(
        st.sampled_from(["Project", "Non-Project", "Lain"]),
        st.sampled_from([None, "", "PRJ-1"]),
        st.sampled_from([None, "", *VALID_PROJECT_PHASES, "Basi"]),
        st.sampled_from([*PROJECT_SUBTASK_CATEGORIES, *NON_PROJECT_SUBTASK_CATEGORIES, "Ngopi"]),
    )
    def test_properti_keputusan_sama(self, wt, proj, fase, kat):
        def cal():
            CalendarMapRequest(
                gcal_event_id="e",
                work_type=wt,
                project_id=proj,
                project_phase=fase,
                subtask_category=kat,
                event_title="t",
            )

        def log():
            ActivityLogCreate(
                work_type=wt,
                id_project=proj,
                project_phase=fase,
                subtask_category=kat,
                duration_hours="1",
                raw_notes="x",
            )

        def ok(fn):
            try:
                fn()
                return True
            except ValidationError:
                return False

        assert ok(cal) is ok(log)


class TestSkemaResponse:
    def test_event_response(self):
        e = CalendarEventResponse(
            gcal_event_id="e", title="T", duration_hours="1.5", is_all_day=False
        )
        assert e.start is None and e.end is None and e.description is None
        assert e.duration_hours == Decimal("1.5")

    def test_event_response_field_wajib(self):
        with pytest.raises(ValidationError):
            CalendarEventResponse(gcal_event_id="e")

    def test_sync_response(self):
        r = CalendarSyncResponse(
            events=[
                CalendarEventResponse(
                    gcal_event_id="e", title="T", duration_hours=1, is_all_day=True
                )
            ],
            total_events=1,
        )
        assert r.total_events == 1 and r.events[0].is_all_day is True
        with pytest.raises(ValidationError):
            CalendarSyncResponse(events=[{"x": 1}], total_events=1)

    def test_map_response(self):
        r = CalendarMapResponse(
            id_log="L",
            work_type="Non-Project",
            gcal_event_id="e",
            subtask_category="Exam",
            duration_hours="2",
            raw_notes="n",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert r.id_project is None and r.project_phase is None
        with pytest.raises(ValidationError):
            CalendarMapResponse(id_log="L")
