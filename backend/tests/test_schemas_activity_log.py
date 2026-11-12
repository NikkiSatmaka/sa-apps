"""
Skema Activity Log (SA Spec Flow 3): konsistensi work_type, durasi 0.25–24.00 kelipatan 0.25,
raw_notes wajib ≤ 5000 karakter. Validator murni → contoh batas + properti Hypothesis.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.activity_log import (
    NON_PROJECT_SUBTASK_CATEGORIES,
    PROJECT_SUBTASK_CATEGORIES,
    VALID_PROJECT_PHASES,
    VALID_SUBTASK_CATEGORIES,
    VALID_WORK_TYPES,
    ActionItem,
    ActivityLogCreate,
    ActivityLogResponse,
    AiPolishedNotes,
    ProjectStoryResponse,
    default_phase_for_status,
    subtask_categories_for,
)


def _project(**o):
    d = {
        "work_type": "Project",
        "id_project": "PRJ-1",
        "project_phase": "Implementation",
        "subtask_category": "Assessment",
        "duration_hours": "1.5",
        "raw_notes": "rapat",
    }
    d.update(o)
    return d


def _non_project(**o):
    d = {
        "work_type": "Non-Project",
        "subtask_category": "Training",
        "duration_hours": "2",
        "raw_notes": "belajar",
    }
    d.update(o)
    return d


def _ditolak(**data) -> ValidationError:
    with pytest.raises(ValidationError) as exc:
        ActivityLogCreate(**data)
    return exc.value


class TestHelperMurni:
    def test_kategori_per_work_type(self):
        assert subtask_categories_for("Project") == PROJECT_SUBTASK_CATEGORIES
        assert subtask_categories_for("Non-Project") == NON_PROJECT_SUBTASK_CATEGORIES

    def test_work_type_tak_dikenal_jatuh_ke_set_project(self):
        assert subtask_categories_for("apa-saja") == PROJECT_SUBTASK_CATEGORIES

    def test_union_kategori_terurut_dan_tanpa_duplikat(self):
        assert VALID_SUBTASK_CATEGORIES == sorted(set(VALID_SUBTASK_CATEGORIES))
        assert set(VALID_SUBTASK_CATEGORIES) == set(PROJECT_SUBTASK_CATEGORIES) | set(
            NON_PROJECT_SUBTASK_CATEGORIES
        )

    def test_default_phase_handover_complete_adalah_implementation(self):
        assert default_phase_for_status("Handover Complete") == "Implementation"

    @pytest.mark.parametrize(
        "status",
        ["New", "Assigned", "Ready", "Closed-Win", "Lost", "", "handover complete"],
    )
    def test_default_phase_selainnya_pre_implementation(self, status):
        assert default_phase_for_status(status) == "Pre-Implementation"

    @given(st.text(max_size=40))
    def test_properti_default_phase_tidak_pernah_post_implementation(self, status):
        assert default_phase_for_status(status) in {"Pre-Implementation", "Implementation"}
        assert default_phase_for_status(status) in VALID_PROJECT_PHASES


class TestActivityLogCreateValid:
    def test_project_valid(self):
        a = ActivityLogCreate(**_project())
        assert a.duration_hours == Decimal("1.5")
        assert a.gcal_event_id is None and a.id_subtask is None

    def test_non_project_valid(self):
        a = ActivityLogCreate(**_non_project())
        assert a.id_project is None and a.project_phase is None

    def test_work_type_default_project(self):
        d = _project()
        del d["work_type"]
        assert ActivityLogCreate(**d).work_type == "Project"

    @pytest.mark.parametrize("fase", VALID_PROJECT_PHASES)
    def test_semua_fase_proyek_diterima(self, fase):
        assert ActivityLogCreate(**_project(project_phase=fase)).project_phase == fase

    @pytest.mark.parametrize("kat", PROJECT_SUBTASK_CATEGORIES)
    def test_semua_kategori_project_diterima(self, kat):
        assert ActivityLogCreate(**_project(subtask_category=kat))

    @pytest.mark.parametrize("kat", NON_PROJECT_SUBTASK_CATEGORIES)
    def test_semua_kategori_non_project_diterima(self, kat):
        assert ActivityLogCreate(**_non_project(subtask_category=kat))

    def test_raw_notes_di_trim(self):
        assert ActivityLogCreate(**_project(raw_notes="  halo \n")).raw_notes == "halo"

    def test_raw_notes_tepat_5000_diterima_dan_5001_ditolak(self):
        assert len(ActivityLogCreate(**_project(raw_notes="a" * 5000)).raw_notes) == 5000
        _ditolak(**_project(raw_notes="a" * 5001))

    def test_gcal_event_id_batas_255(self):
        assert ActivityLogCreate(**_project(gcal_event_id="g" * 255)).gcal_event_id == "g" * 255
        _ditolak(**_project(gcal_event_id="g" * 256))


class TestActivityLogCreateDitolak:
    def test_work_type_tidak_valid(self):
        _ditolak(**_project(work_type="Lainnya"))

    def test_project_tanpa_id_project(self):
        err = _ditolak(**_project(id_project=None))
        assert "id_project wajib" in str(err)

    def test_project_dengan_id_project_kosong(self):
        _ditolak(**_project(id_project=""))

    def test_project_tanpa_fase(self):
        assert "project_phase wajib" in str(_ditolak(**_project(project_phase=None)))

    def test_project_fase_tidak_valid(self):
        assert "project_phase tidak valid" in str(_ditolak(**_project(project_phase="Selesai")))

    def test_non_project_tidak_boleh_punya_proyek(self):
        assert "tidak boleh terkait proyek" in str(_ditolak(**_non_project(id_project="PRJ-1")))

    def test_non_project_tidak_boleh_punya_fase(self):
        assert "tidak boleh punya project_phase" in str(
            _ditolak(**_non_project(project_phase="Implementation"))
        )

    def test_kategori_non_project_dipakai_di_project(self):
        assert "tidak valid untuk work_type 'Project'" in str(
            _ditolak(**_project(subtask_category="Training"))
        )

    def test_kategori_project_dipakai_di_non_project(self):
        assert "tidak valid untuk work_type 'Non-Project'" in str(
            _ditolak(**_non_project(subtask_category="Assessment"))
        )

    def test_kategori_acak_ditolak(self):
        _ditolak(**_project(subtask_category="Ngopi"))

    @pytest.mark.parametrize("notes", ["", " ", "   \n\t "])
    def test_raw_notes_kosong_atau_hanya_spasi_ditolak(self, notes):
        """Regresi: catatan hanya-spasi dulu lolos min_length lalu ter-trim jadi string kosong."""
        _ditolak(**_project(raw_notes=notes))

    @pytest.mark.parametrize(
        "field", ["raw_notes", "gcal_event_id", "id_subtask", "id_project"]
    )
    def test_karakter_nul_ditolak(self, field):
        """#78: `\\x00` tidak bisa disimpan Postgres; tolak di skema agar tidak jadi 500 dari DB."""
        galat = _ditolak(**_project(**{field: "abc\x00def"}))
        assert "NUL" in str(galat)

    def test_field_wajib_hilang(self):
        for hilang in ("subtask_category", "duration_hours", "raw_notes"):
            d = _project()
            del d[hilang]
            assert hilang in str(_ditolak(**d))


class TestDurasi:
    @pytest.mark.parametrize("d", ["0.25", "0.50", "1", "7.75", "24", "24.00", "23.75"])
    def test_durasi_valid(self, d):
        assert ActivityLogCreate(**_project(duration_hours=d)).duration_hours == Decimal(d)

    @pytest.mark.parametrize("d", ["0", "0.24", "0.2", "24.01", "24.25", "-1", "25", "100"])
    def test_durasi_di_luar_rentang_ditolak(self, d):
        _ditolak(**_project(duration_hours=d))

    @pytest.mark.parametrize("d", ["0.3", "0.26", "1.1", "10.01", "23.99", "0.251"])
    def test_durasi_bukan_kelipatan_seperempat_ditolak(self, d):
        assert "kelipatan 0.25" in str(_ditolak(**_project(duration_hours=d)))

    def test_durasi_bukan_angka(self):
        _ditolak(**_project(duration_hours="sejam"))

    @settings(max_examples=200)
    @given(st.integers(min_value=1, max_value=96))
    def test_properti_semua_kelipatan_025_dalam_rentang_diterima(self, n):
        d = Decimal(n) * Decimal("0.25")
        assert ActivityLogCreate(**_project(duration_hours=d)).duration_hours == d

    @settings(max_examples=200)
    @given(st.decimals(min_value=Decimal("0.25"), max_value=Decimal("24"), places=2))
    def test_properti_diterima_jika_dan_hanya_jika_kelipatan_025(self, d):
        kelipatan = d % Decimal("0.25") == 0
        try:
            ActivityLogCreate(**_project(duration_hours=d))
            diterima = True
        except ValidationError:
            diterima = False
        assert diterima is kelipatan

    @settings(max_examples=100)
    @given(
        st.one_of(
            st.decimals(max_value=Decimal("0.24"), places=2, allow_nan=False, allow_infinity=False),
            st.decimals(
                min_value=Decimal("24.01"), places=2, allow_nan=False, allow_infinity=False
            ),
        )
    )
    def test_properti_di_luar_rentang_selalu_ditolak(self, d):
        with pytest.raises(ValidationError):
            ActivityLogCreate(**_project(duration_hours=d))


class TestPropertiKonsistensiWorkType:
    @given(
        st.sampled_from(VALID_WORK_TYPES),
        st.sampled_from([None, "", "PRJ-1"]),
        st.sampled_from([None, "", *VALID_PROJECT_PHASES]),
        st.sampled_from(VALID_SUBTASK_CATEGORIES),
    )
    def test_properti_diterima_jika_dan_hanya_jika_konsisten(self, wt, proj, fase, kat):
        if wt == "Project":
            seharusnya = (
                bool(proj) and fase in VALID_PROJECT_PHASES and kat in PROJECT_SUBTASK_CATEGORIES
            )
        else:
            seharusnya = not proj and not fase and kat in NON_PROJECT_SUBTASK_CATEGORIES
        try:
            ActivityLogCreate(
                work_type=wt,
                id_project=proj,
                project_phase=fase,
                subtask_category=kat,
                duration_hours="1",
                raw_notes="x",
            )
            diterima = True
        except ValidationError:
            diterima = False
        assert diterima is seharusnya

    @given(st.text(min_size=1, max_size=5000).filter(lambda s: s.strip()))
    def test_properti_raw_notes_tidak_kosong_selalu_hasil_trim(self, notes):
        a = ActivityLogCreate(**_project(raw_notes=notes))
        assert a.raw_notes == notes.strip()
        assert a.raw_notes != ""


class TestSkemaResponse:
    def test_polished_notes_default_kosong(self):
        n = AiPolishedNotes()
        assert n.discussion_points == [] and n.action_items == []

    def test_polished_notes_dengan_action_item(self):
        n = AiPolishedNotes(
            discussion_points=["a"], action_items=[ActionItem(description="kirim", pic="Budi")]
        )
        assert n.action_items[0].pic == "Budi"
        assert ActionItem(description="x").pic is None

    def test_action_item_wajib_deskripsi(self):
        with pytest.raises(ValidationError):
            ActionItem()

    def test_response_dari_atribut_orm_dan_default(self):
        from types import SimpleNamespace

        orm = SimpleNamespace(
            id_log="L1",
            work_type="Project",
            id_project="P",
            project_phase="Implementation",
            sa_id=uuid4(),
            subtask_category="Assessment",
            id_subtask=None,
            duration_hours=Decimal("1.50"),
            raw_notes="x",
            ai_polished_notes=None,
            gcal_event_id=None,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        r = ActivityLogResponse.model_validate(orm)
        assert r.needs_repolish is False
        assert r.duration_hours == Decimal("1.50")

    def test_response_sa_id_harus_uuid(self):
        with pytest.raises(ValidationError):
            ActivityLogResponse(
                id_log="L",
                work_type="Project",
                sa_id="bukan-uuid",
                subtask_category="Assessment",
                duration_hours=1,
                raw_notes="x",
                created_at=datetime.now(timezone.utc),
            )

    def test_project_story_page_size_default_20(self):
        s = ProjectStoryResponse(items=[], total=0, page=1, total_pages=0)
        assert s.page_size == 20
        with pytest.raises(ValidationError):
            ProjectStoryResponse(items=[], total=0, page=1)
