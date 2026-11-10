"""
Seam tiket 5A-7 (#40): satu sumber definisi Kuesioner kualifikasi.

Dua seam:
- GET /api/v1/qualification/schema (terautentikasi) mengembalikan schema_version + definisi.
- Modul definisi (`app.schemas.qualification_definition`) yang dipakai bersama oleh
  validasi, pilihan rubrik, dan akses label.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.schemas import qualification_definition as qd
from app.schemas.qualification import QUESTIONNAIRE_FIELDS, validate_answers
from app.services import bant_rubric

URL = "/api/v1/qualification/schema"


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = "Sales"
    return u


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_endpoint_skema_butuh_autentikasi():
    app.dependency_overrides.clear()
    assert TestClient(app).get(URL).status_code in (401, 403)


def test_endpoint_skema_memuat_versi_dan_seluruh_pertanyaan(client):
    res = client.get(URL)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["schema_version"] == bant_rubric.QUESTIONNAIRE_SCHEMA_VERSION
    names = [q["name"] for q in data["questions"]]
    # target_submit (header, #11) + 14 field jawaban
    assert names[0] == "target_submit"
    assert names[1:] == list(QUESTIONNAIRE_FIELDS)
    wajib = {q["name"] for q in data["questions"] if q["required"]}
    assert wajib == {
        "budget_dialokasikan",
        "peran_pic",
        "masalah_bisnis",
        "jenis_workload",
        "lingkungan",
        "skala",
        "target_go_live",
    }
    q = {q["name"]: q for q in data["questions"]}
    assert q["lingkungan"]["choices"] == ["On-prem", "Cloud", "Hybrid"]
    assert q["target_go_live"]["choices"] == ["≤ 3 bulan", "≤ 6 bulan", "> 6 bulan", "Tidak tahu"]
    assert [g["key"] for g in data["groups"]] == ["budget", "authority", "need", "timeline"]
    # petunjuk tata letak: tiga PIC sebaris, lingkungan + skala berdampingan
    assert {q[n]["row"] for n in ("pic_nama", "pic_jabatan", "pic_email")} == {"pic"}
    assert q["lingkungan"]["row"] == q["skala"]["row"] is not None
    assert q["mrr"]["row"] is None


def test_pilihan_rubrik_berasal_dari_definisi():
    for q in qd.QUESTIONS:
        if q.choices:
            nilai = {
                "budget_dialokasikan": bant_rubric.BUDGET_DIALOKASIKAN_CHOICES,
                "peran_pic": bant_rubric.PERAN_PIC_CHOICES,
                "jenis_workload": bant_rubric.JENIS_WORKLOAD_CHOICES,
                "lingkungan": bant_rubric.LINGKUNGAN_CHOICES,
                "target_go_live": bant_rubric.TARGET_GO_LIVE_CHOICES,
            }[q.name]
            assert tuple(q.choices) == tuple(nilai)
    # setiap kunci poin rubrik adalah pilihan yang sah di definisi
    assert set(bant_rubric.POIN_BUDGET_DIALOKASIKAN) == set(qd.get_question("budget_dialokasikan").choices)
    assert set(bant_rubric.POIN_AUTHORITY_PERAN) == set(qd.get_question("peran_pic").choices)
    assert set(bant_rubric.POIN_TIMELINE_GO_LIVE) == set(qd.get_question("target_go_live").choices)


def test_validasi_mengikuti_definisi_pilihan_dan_batas_panjang():
    dasar = {
        "budget_dialokasikan": "Ya",
        "peran_pic": "Perantara",
        "masalah_bisnis": "x",
        "jenis_workload": "Keamanan",
        "lingkungan": "Cloud",
        "skala": "s",
        "target_go_live": "Tidak tahu",
    }
    for q in qd.QUESTIONS:
        if q.choices and q.name in dasar:
            for pilihan in q.choices:
                hasil, errs = validate_answers({**dasar, q.name: pilihan})
                assert errs == [], (q.name, pilihan)
            _, errs = validate_answers({**dasar, q.name: "bukan-pilihan"})
            assert [e["field"] for e in errs] == [f"qualification_answers.{q.name}"]
    for q in qd.QUESTIONS:
        if q.max_length and q.type in ("text", "short"):
            _, errs = validate_answers({**dasar, q.name: "a" * (q.max_length + 1)})
            assert any(e["field"].endswith(q.name) for e in errs), q.name


def test_validasi_wajib_mengikuti_definisi():
    _, errs = validate_answers({})
    assert {e["field"].split(".")[1] for e in errs} == {
        q.name for q in qd.QUESTIONS if q.required and not q.header
    }


def test_akses_label_pertanyaan():
    assert qd.get_question_label("mrr") == "MRR (IDR)"
    assert qd.get_question_label("target_submit") == "Target submit"
    labels = qd.question_labels()
    assert list(labels) == [q.name for q in qd.QUESTIONS]
    with pytest.raises(KeyError):
        qd.get_question_label("tidak_ada")


def test_hint_masalah_bisnis_selaras_dengan_rubrik():
    assert str(bant_rubric.MIN_PANJANG_MASALAH_BISNIS) in qd.get_question("masalah_bisnis").hint
