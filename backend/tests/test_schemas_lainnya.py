"""
Skema lain di bawah tiket B10: handover (email PMO/Delivery), project (header intake),
scoring (batas sub-skor), qualification (parse JSON), workflow/subtask/collaborator/assignment/auth.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.assignment import AssignmentResponse, AssignRequest, ProjectBrief, SAAvailability
from app.schemas.auth import GoogleProfile, LoginResponse, RefreshRequest, TokenPair, UserResponse
from app.schemas.collaborator import CollaboratorAddRequest, CollaboratorListResponse
from app.schemas.handover import (
    HandoverConfigInput,
    HandoverReadiness,
    HandoverResponse,
)
from app.schemas.project import FileUploadResult, ProjectCreate, ProjectResponse
from app.schemas.qualification import parse_answers, validate_answers
from app.schemas.qualification_definition import (
    answer_questions,
    get_choices,
    get_question,
    get_question_label,
    question_labels,
    schema_payload,
)
from app.schemas.response import StandardResponse
from app.schemas.scoring import BANTOverrideInput, BANTResult, BANTSubScores
from app.schemas.subtask import SubtaskCreateRequest, SubtaskResponse
from app.schemas.workflow import StatusUpdateRequest

SEKARANG = datetime(2025, 1, 1, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------ handover
class TestHandoverConfigInput:
    def test_email_valid_dinormalisasi_lowercase(self):
        c = HandoverConfigInput(pmo_email="PMO.Lead+x@Contoh.CO.ID", delivery_email="d@x.io")
        assert c.pmo_email == "pmo.lead+x@contoh.co.id"
        assert c.delivery_email == "d@x.io"

    @pytest.mark.parametrize(
        "email",
        [
            "",
            "tanpa-at.com",
            "a@b",
            "a@b.c",
            "@x.com",
            "a b@x.com",
            "a@@x.com",
            " a@x.com",
            "a@x.com ",
            "a@x.123",
        ],
    )
    @pytest.mark.parametrize("kolom", ["pmo_email", "delivery_email"])
    def test_email_tidak_valid_ditolak_di_kedua_kolom(self, email, kolom):
        data = {"pmo_email": "p@x.com", "delivery_email": "d@x.com", kolom: email}
        with pytest.raises(ValidationError) as exc:
            HandoverConfigInput(**data)
        assert exc.value.errors()[0]["loc"] == (kolom,)

    def test_batas_tld_dua_huruf(self):
        assert HandoverConfigInput(pmo_email="a@b.co", delivery_email="a@b.co")

    def test_kedua_field_wajib(self):
        with pytest.raises(ValidationError) as exc:
            HandoverConfigInput()
        assert {e["loc"][0] for e in exc.value.errors()} == {"pmo_email", "delivery_email"}

    @given(
        st.from_regex(r"[a-zA-Z0-9._%+-]{1,20}@[a-zA-Z0-9-]{1,15}\.[a-zA-Z]{2,6}", fullmatch=True)
    )
    def test_properti_email_berformat_valid_diterima_dan_hasil_lowercase(self, email):
        c = HandoverConfigInput(pmo_email=email, delivery_email=email)
        assert c.pmo_email == email.lower()


class TestHandoverResponse:
    def test_readiness_default(self):
        r = HandoverReadiness(ready=False)
        assert r.missing_items == [] and r.pmo_email is None and r.hld_status is None

    def test_readiness_wajib_ready(self):
        with pytest.raises(ValidationError):
            HandoverReadiness()

    def test_handover_response_default_dan_wajib(self):
        r = HandoverResponse(
            id_project="P",
            project_name="N",
            customer_name="C",
            old_status="Won",
            new_status="Handed Over",
            pmo_email="p@x.com",
            delivery_email="d@x.com",
            handover_at=SEKARANG,
        )
        assert r.documents_handed_over == [] and r.final_deliverables_folder_id is None
        with pytest.raises(ValidationError):
            HandoverResponse(id_project="P")


# ------------------------------------------------------------------------------------ project
def _proj(**o):
    d = {
        "project_name": "Proyek",
        "customer_name": "Cust",
        "target_submit": date.today(),
        "estimasi_nilai": "1000",
    }
    d.update(o)
    return d


class TestProjectCreate:
    def test_valid_dan_nama_di_trim(self):
        p = ProjectCreate(**_proj(project_name="  A  ", customer_name=" B "))
        assert (p.project_name, p.customer_name) == ("A", "B")

    def test_target_submit_hari_ini_dan_besok_diterima_kemarin_ditolak(self):
        assert ProjectCreate(**_proj(target_submit=date.today()))
        assert ProjectCreate(**_proj(target_submit=date.today() + timedelta(days=1)))
        with pytest.raises(ValidationError) as exc:
            ProjectCreate(**_proj(target_submit=date.today() - timedelta(days=1)))
        assert "masa lalu" in str(exc.value)

    @pytest.mark.parametrize("nilai", ["0.01", "1", "999999999999.00", "999999999999"])
    def test_estimasi_nilai_valid_termasuk_batas(self, nilai):
        assert ProjectCreate(**_proj(estimasi_nilai=nilai)).estimasi_nilai == Decimal(nilai)

    @pytest.mark.parametrize(
        "nilai", ["0", "0.00", "0.009", "-5", "999999999999.01", "1000000000000"]
    )
    def test_estimasi_nilai_di_luar_rentang_ditolak(self, nilai):
        with pytest.raises(ValidationError):
            ProjectCreate(**_proj(estimasi_nilai=nilai))

    @pytest.mark.parametrize("kolom", ["project_name", "customer_name"])
    def test_nama_batas_150_dan_kosong(self, kolom):
        assert ProjectCreate(**_proj(**{kolom: "a" * 150}))
        with pytest.raises(ValidationError):
            ProjectCreate(**_proj(**{kolom: "a" * 151}))
        with pytest.raises(ValidationError):
            ProjectCreate(**_proj(**{kolom: ""}))

    @pytest.mark.parametrize("kolom", ["project_name", "customer_name"])
    def test_nama_hanya_spasi_ditolak(self, kolom):
        """Regresi: trim dilakukan setelah min_length sehingga '   ' dulu lolos jadi ''."""
        with pytest.raises(ValidationError):
            ProjectCreate(**_proj(**{kolom: "   "}))

    def test_field_wajib(self):
        with pytest.raises(ValidationError) as exc:
            ProjectCreate()
        assert {e["loc"][0] for e in exc.value.errors()} == {
            "project_name",
            "customer_name",
            "target_submit",
            "estimasi_nilai",
        }

    def test_tanggal_format_tidak_valid(self):
        with pytest.raises(ValidationError):
            ProjectCreate(**_proj(target_submit="31-12-2025x"))


def _orang() -> dict:
    return {"id": uuid.uuid4(), "name": "Orang", "email": "orang@example.com"}


class TestProjectResponse:
    def test_default_dan_hasil_upload(self):
        r = ProjectResponse(
            id_project="P",
            project_name="N",
            customer_name="C",
            target_submit=date.today(),
            estimasi_nilai="5",
            created_by=_orang(),
            product_pic=_orang(),
            created_at=SEKARANG,
            files=[FileUploadResult(filename="a.pdf", success=True, size_bytes=10)],
        )
        assert r.status == "Intake" and r.scoring_triggered is False and r.bant_score is None
        assert r.sales_pic is None  # Sales opsional
        assert r.files[0].error is None

    def test_id_orang_harus_uuid(self):
        with pytest.raises(ValidationError):
            ProjectResponse(
                id_project="P",
                project_name="N",
                customer_name="C",
                target_submit=date.today(),
                estimasi_nilai=1,
                created_by=_orang(),
                product_pic={"id": "bukan-uuid"},
                created_at=SEKARANG,
            )

    def test_sub_scores_harus_int(self):
        with pytest.raises(ValidationError):
            ProjectResponse(
                id_project="P",
                project_name="N",
                customer_name="C",
                target_submit=date.today(),
                estimasi_nilai=1,
                created_by=_orang(),
                product_pic=_orang(),
                created_at=SEKARANG,
                sub_scores={"budget": "banyak"},
            )


# ------------------------------------------------------------------------------------ scoring
class TestScoring:
    @pytest.mark.parametrize("nilai", [0, 1, 24, 25])
    def test_sub_skor_valid_termasuk_batas(self, nilai):
        assert BANTSubScores(budget=nilai, authority=nilai, need=nilai, timeline=nilai)

    @pytest.mark.parametrize("nilai", [-1, 26, 100])
    @pytest.mark.parametrize("kolom", ["budget", "authority", "need", "timeline"])
    def test_sub_skor_di_luar_batas_ditolak(self, nilai, kolom):
        data = {"budget": 0, "authority": 0, "need": 0, "timeline": 0, kolom: nilai}
        with pytest.raises(ValidationError):
            BANTSubScores(**data)

    @pytest.mark.parametrize("total,ok", [(0, True), (100, True), (-1, False), (101, False)])
    def test_total_skor_batas(self, total, ok):
        sub = BANTSubScores(budget=1, authority=1, need=1, timeline=1)
        if ok:
            assert BANTResult(total_score=total, sub_scores=sub, status="Intake").total_score == total
        else:
            with pytest.raises(ValidationError):
                BANTResult(total_score=total, sub_scores=sub, status="Intake")

    def test_use_case_tags_maksimal_5(self):
        sub = BANTSubScores(budget=1, authority=1, need=1, timeline=1)
        assert BANTResult(total_score=4, sub_scores=sub, status="x", use_case_tags=list("abcde"))
        with pytest.raises(ValidationError):
            BANTResult(total_score=4, sub_scores=sub, status="x", use_case_tags=list("abcdef"))

    def test_override_alasan_di_trim_dan_wajib(self):
        base = {"budget": 1, "authority": 2, "need": 3, "timeline": 4}
        assert BANTOverrideInput(**base, reason="  karena  ").reason == "karena"
        for kosong in ("", "   ", "\n\t"):
            with pytest.raises(ValidationError):
                BANTOverrideInput(**base, reason=kosong)

    @pytest.mark.parametrize("kolom", ["budget", "authority", "need", "timeline"])
    @pytest.mark.parametrize("nilai,ok", [(-1, False), (0, True), (25, True), (26, False)])
    def test_override_batas_sub_skor_per_kolom(self, kolom, nilai, ok):
        data = {"budget": 1, "authority": 1, "need": 1, "timeline": 1, "reason": "alasan"}
        data[kolom] = nilai
        if ok:
            assert getattr(BANTOverrideInput(**data), kolom) == nilai
        else:
            with pytest.raises(ValidationError):
                BANTOverrideInput(**data)

    @given(st.integers(min_value=-50, max_value=80))
    def test_properti_sub_skor_valid_jika_dan_hanya_jika_0_sampai_25(self, n):
        try:
            BANTSubScores(budget=n, authority=0, need=0, timeline=0)
            ok = True
        except ValidationError:
            ok = False
        assert ok is (0 <= n <= 25)


# ------------------------------------------------------------------------------------ kualifikasi
class TestQualificationParse:
    def test_parse_none_atau_kosong_ditolak(self):
        for raw in (None, "", "   "):
            jawaban, errors = parse_answers(raw)
            assert jawaban is None
            assert errors == [
                {
                    "field": "qualification_answers",
                    "reason": "Jawaban kuesioner kualifikasi wajib diisi.",
                }
            ]

    def test_parse_json_rusak_ditolak(self):
        jawaban, errors = parse_answers("{bukan json")
        assert jawaban is None
        assert errors[0]["field"] == "qualification_answers"
        assert "bukan JSON" in errors[0]["reason"]

    @pytest.mark.parametrize("raw", ["[]", '"teks"', "123", "null"])
    def test_parse_json_bukan_objek_ditolak(self, raw):
        jawaban, errors = parse_answers(raw)
        assert jawaban is None
        assert "objek JSON" in errors[0]["reason"]

    def test_parse_objek_kosong_menghasilkan_error_field_wajib(self):
        jawaban, errors = parse_answers("{}")
        assert jawaban is None
        wajib = {q.name for q in answer_questions() if q.required}
        assert {e["field"].split(".")[-1] for e in errors} == wajib

    def test_parse_jawaban_valid_lengkap(self):
        jawaban, errors = parse_answers(json.dumps(_jawaban_valid()))
        assert errors == []
        assert set(jawaban) == {q.name for q in answer_questions()}
        assert jawaban["mrr"] == 5_000_000

    def test_validate_menolak_kunci_tak_dikenal(self):
        jawaban, errors = validate_answers({**_jawaban_valid(), "skor": 100})
        assert jawaban is None
        assert {
            "field": "qualification_answers.skor",
            "reason": "Field tidak dikenal pada kuesioner.",
        } in errors

    def test_batas_mrr(self):
        for nilai, ok in [
            (0, True),
            (999_999_999_999, True),
            (-1, False),
            (1_000_000_000_000, False),
        ]:
            jawaban, errors = validate_answers({**_jawaban_valid(), "mrr": nilai})
            assert (jawaban is not None) is ok, nilai

    @pytest.mark.parametrize("nilai", [True, "5", float("nan"), float("inf"), [1]])
    def test_mrr_bukan_angka_valid_ditolak(self, nilai):
        jawaban, errors = validate_answers({**_jawaban_valid(), "mrr": nilai})
        assert jawaban is None
        assert errors[0]["field"] == "qualification_answers.mrr"

    def test_choice_tidak_valid_dan_email_tidak_valid(self):
        _, errors = validate_answers(
            {**_jawaban_valid(), "lingkungan": "Bulan", "pic_email": "bukan-email"}
        )
        assert {e["field"] for e in errors} == {
            "qualification_answers.lingkungan",
            "qualification_answers.pic_email",
        }

    def test_teks_melebihi_batas_ditolak_dan_tepat_batas_diterima(self):
        batas = get_question("masalah_bisnis").max_length
        ok, _ = validate_answers({**_jawaban_valid(), "masalah_bisnis": "a" * batas})
        assert ok is not None
        gagal, errors = validate_answers({**_jawaban_valid(), "masalah_bisnis": "a" * (batas + 1)})
        assert gagal is None and "Maksimal" in errors[0]["reason"]

    def test_teks_non_string_ditolak(self):
        gagal, errors = validate_answers({**_jawaban_valid(), "skala": 5})
        assert gagal is None and errors[0]["reason"] == "Harus berupa teks."

    def test_spasi_di_trim_dan_opsional_kosong_menjadi_none(self):
        hasil, _ = validate_answers(
            {**_jawaban_valid(), "skala": "  40 server  ", "kompetitor": "   "}
        )
        assert hasil["skala"] == "40 server" and hasil["kompetitor"] is None


def _jawaban_valid():
    jawaban = {}
    for q in answer_questions():
        if q.type == "choice":
            jawaban[q.name] = q.choices[0]
        elif q.type == "number":
            jawaban[q.name] = 5_000_000
        elif q.type == "email":
            jawaban[q.name] = "pic@contoh.com"
        else:
            jawaban[q.name] = "isi"
    return jawaban


class TestDefinisiKuesioner:
    def test_akses_definisi(self):
        assert get_question("mrr").type == "number"
        assert get_question_label("mrr") == "MRR (IDR)"
        assert question_labels()["mrr"] == "MRR (IDR)"
        assert "Ya" in get_choices("budget_dialokasikan")

    def test_pertanyaan_tak_dikenal_atau_tanpa_pilihan(self):
        with pytest.raises(KeyError):
            get_question("tidak-ada")
        with pytest.raises(KeyError):
            get_choices("mrr")

    def test_schema_payload_dapat_diserialisasi_json(self):
        payload = schema_payload()
        assert payload["schema_version"] == 1
        assert [g["key"] for g in payload["groups"]] == ["budget", "authority", "need", "timeline"]
        json.dumps(payload)


# ------------------------------------------------------------------------------------ lain-lain
class TestSkemaRingan:
    def test_status_update_reason_maks_500(self):
        assert StatusUpdateRequest(new_status="Lost", reason="a" * 500)
        with pytest.raises(ValidationError):
            StatusUpdateRequest(new_status="Lost", reason="a" * 501)
        with pytest.raises(ValidationError):
            StatusUpdateRequest()

    def test_subtask_judul_batas(self):
        assert SubtaskCreateRequest(title="a" * 150)
        for judul in ("", "a" * 151):
            with pytest.raises(ValidationError):
                SubtaskCreateRequest(title=judul)

    def test_subtask_response_assigned_opsional(self):
        r = SubtaskResponse(
            id_subtask="S",
            id_project="P",
            title="t",
            status="open",
            created_at=SEKARANG,
            updated_at=SEKARANG,
        )
        assert r.assigned_sa is None

    def test_collaborator_default_viewer_dan_uuid_wajib(self):
        assert CollaboratorAddRequest(user_id=uuid.uuid4()).role == "viewer"
        with pytest.raises(ValidationError):
            CollaboratorAddRequest(user_id="bukan-uuid")
        assert CollaboratorListResponse(items=[], total=0).total == 0

    def test_assign_request_uuid(self):
        assert AssignRequest(sa_id=str(uuid.uuid4()))
        with pytest.raises(ValidationError):
            AssignRequest(sa_id="x")

    def test_assignment_response(self):
        brief = ProjectBrief(
            id_project="P",
            project_name="N",
            customer_name="C",
            status="Assigned",
            target_submit=date.today(),
        )
        r = AssignmentResponse(
            project=brief,
            assigned_sa_name="Budi",
            notification_sent=True,
            folder_provisioning_triggered=False,
        )
        assert r.project.assigned_sa is None
        assert SAAvailability(id=uuid.uuid4(), name="A", email="a@x.com", role="SA", active_project_count=0)

    def test_auth_skema(self):
        pasangan = TokenPair(access_token="a", refresh_token="r", expires_in=60)
        assert pasangan.token_type == "bearer"
        user = UserResponse(
            id=uuid.uuid4(),
            email="a@x.com",
            name="A",
            role="SA",
            is_admin=False,
            created_at=SEKARANG,
            updated_at=SEKARANG,
        )
        assert user.avatar_url is None
        assert LoginResponse(user=user, tokens=pasangan).tokens.expires_in == 60
        assert GoogleProfile(google_id="g", email="a@x.com", name="A").avatar_url is None
        with pytest.raises(ValidationError):
            RefreshRequest()

    def test_standard_response(self):
        assert StandardResponse(status="success", data={"a": 1}, message="ok")
