"""
Property test (Hypothesis) invarian skor BANT (tiket B8 #61, ADR 0010):
- skor total 0–100 dan tiap kriteria ≤ 25 untuk input apa pun,
- override sebagai batas bawah tidak pernah menurunkan skor,
- gabungan max(rubrik, AI, override) deterministik, komutatif, idempoten, dan monoton.

Fungsi murni saja: tanpa DB, jaringan, maupun waktu nyata.
"""

import json
from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.qualification import QUESTIONNAIRE_FIELDS, parse_answers, validate_answers
from app.schemas.qualification_definition import answer_questions
from app.schemas.scoring import BANTOverrideInput, BANTSubScores
from app.services import bant_rubric
from app.services.scoring_engine import ScoringEngine

KRITERIA = bant_rubric.SUB_SCORE_KEYS
RIBUAN = settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
SEDANG = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# Nilai skalar sembarang. Rubrik adalah fungsi murni atas jawaban TERNORMALISASI (kontrak
# docstring; jawaban selalu lewat `validate_answers` sebelum tersimpan), jadi nilai tak-hashable
# (list/dict) di field pilihan berada di luar kontraknya; validasi masukan diuji terpisah di bawah
# dengan nilai sembarang termasuk list.
nilai_skalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**15), max_value=10**15),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=120),
)
nilai_sembarang = st.one_of(nilai_skalar, st.lists(st.integers(), max_size=3))


def _pilihan(nama: str):
    return st.sampled_from(sorted(bant_rubric.get_choices(nama)))


@st.composite
def jawaban_acak(draw):
    """Jawaban semi-valid: tiap field diisi nilai valid, nilai sembarang, atau dihilangkan."""
    hasil = {}
    for q in answer_questions():
        if q.type == "choice":
            valid = _pilihan(q.name)
        elif q.type == "number":
            valid = st.integers(min_value=0, max_value=999_999_999_999)
        else:
            valid = st.text(max_size=300)
        pilihan = draw(st.one_of(valid, nilai_skalar, st.just("__hilang__")))
        if pilihan != "__hilang__":
            hasil[q.name] = pilihan
    return hasil


tanggal_opsional = st.one_of(
    st.none(), st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 1, 1))
)
sub_skor = st.builds(BANTSubScores, **{k: st.integers(min_value=0, max_value=25) for k in KRITERIA})
sub_skor_opsional = st.one_of(st.none(), sub_skor)


def _vektor(s: BANTSubScores) -> tuple[int, ...]:
    return tuple(getattr(s, k) for k in KRITERIA)


# --------------------------------------------------------------------------- rubrik


@RIBUAN
@given(jawaban_acak(), tanggal_opsional)
def test_rubrik_tiap_kriteria_0_25_dan_total_0_100(jawaban, target):
    skor = bant_rubric.compute_rubric_scores(jawaban, target)

    for k in KRITERIA:
        assert 0 <= getattr(skor, k) <= 25
    total = bant_rubric.total_score(skor)
    assert 0 <= total <= 100
    assert total == sum(_vektor(skor))


@SEDANG
@given(jawaban_acak(), tanggal_opsional)
def test_rubrik_deterministik_dan_tidak_memutasi_masukan(jawaban, target):
    salinan = json.loads(json.dumps(jawaban, default=str))

    a = bant_rubric.compute_rubric_scores(jawaban, target)
    b = bant_rubric.compute_rubric_scores(jawaban, target)

    assert a == b
    assert json.loads(json.dumps(jawaban, default=str)) == salinan


@SEDANG
@given(jawaban_acak(), tanggal_opsional)
def test_target_submit_hanya_menambah_skor_timeline(jawaban, target):
    tanpa = bant_rubric.compute_rubric_scores(jawaban, None)
    dengan = bant_rubric.compute_rubric_scores(jawaban, date(2030, 1, 1))

    assert dengan.timeline == tanpa.timeline + bant_rubric.POIN_TIMELINE_TARGET_SUBMIT
    assert (dengan.budget, dengan.authority, dengan.need) == (
        tanpa.budget,
        tanpa.authority,
        tanpa.need,
    )


@SEDANG
@given(jawaban_acak(), st.integers(min_value=1, max_value=999_999_999_999))
def test_mrr_positif_tidak_menurunkan_skor_budget(jawaban, mrr):
    tanpa = bant_rubric.compute_rubric_scores({**jawaban, "mrr": None}, None)
    dengan = bant_rubric.compute_rubric_scores({**jawaban, "mrr": mrr}, None)

    assert dengan.budget == tanpa.budget + bant_rubric.POIN_BUDGET_MRR


@RIBUAN
@given(st.integers(min_value=-1000, max_value=1000))
def test_gate_sesuai_ambang_untuk_semua_total(total):
    status_siklus, state = bant_rubric.decide_gate(total)

    assert (status_siklus, state) == (
        ("Awaiting Assignment", "Qualified") if total >= 60 else ("Intake", "Need Clarification")
    )


@SEDANG
@given(sub_skor)
def test_feedback_menyebut_tepat_kriteria_lemah(skor):
    teks = bant_rubric.generate_feedback(skor)

    for k in KRITERIA:
        lemah = getattr(skor, k) < bant_rubric.WEAK_CRITERION_THRESHOLD
        assert (f"- {k.capitalize()} (skor:" in teks) is lemah
    if bant_rubric.total_score(skor) < 60 and all(
        getattr(skor, k) >= bant_rubric.WEAK_CRITERION_THRESHOLD for k in KRITERIA
    ):
        assert "belum mencapai threshold" in teks


# --------------------------------------------------------------------------- gabungan max


@RIBUAN
@given(sub_skor_opsional, sub_skor_opsional, sub_skor_opsional)
def test_merge_max_dalam_batas_dan_total_0_100(rubrik, ai, override):
    if rubrik is None and ai is None and override is None:
        rubrik = BANTSubScores(budget=0, authority=0, need=0, timeline=0)

    hasil = ScoringEngine._merge_max(rubrik, ai, override)

    assert all(0 <= v <= 25 for v in _vektor(hasil))
    assert 0 <= bant_rubric.total_score(hasil) <= 100


@RIBUAN
@given(sub_skor, sub_skor_opsional, sub_skor_opsional)
def test_merge_max_tidak_pernah_di_bawah_komponen_mana_pun(rubrik, ai, override):
    hasil = _vektor(ScoringEngine._merge_max(rubrik, ai, override))

    for komponen in (rubrik, ai, override):
        if komponen is not None:
            assert all(h >= c for h, c in zip(hasil, _vektor(komponen)))
    # tiap kriteria sama persis dengan salah satu komponen (max, bukan jumlah)
    for i, h in enumerate(hasil):
        assert h in {_vektor(c)[i] for c in (rubrik, ai, override) if c is not None}


@RIBUAN
@given(sub_skor, sub_skor_opsional, sub_skor)
def test_override_sebagai_batas_bawah_tidak_pernah_menurunkan_skor(rubrik, ai, override):
    tanpa_override = ScoringEngine._merge_max(rubrik, ai, None)

    dengan_override = ScoringEngine._merge_max(rubrik, ai, override)

    assert bant_rubric.total_score(dengan_override) >= bant_rubric.total_score(tanpa_override)
    assert all(d >= t for d, t in zip(_vektor(dengan_override), _vektor(tanpa_override)))
    assert all(d >= o for d, o in zip(_vektor(dengan_override), _vektor(override)))


@RIBUAN
@given(sub_skor_opsional, sub_skor_opsional, sub_skor_opsional, sub_skor)
def test_merge_max_monoton_menambah_komponen_tidak_menurunkan(rubrik, ai, override, tambahan):
    dasar = ScoringEngine._merge_max(
        rubrik, ai, override, BANTSubScores(budget=0, authority=0, need=0, timeline=0)
    )

    lebih = ScoringEngine._merge_max(rubrik, ai, override, tambahan)

    assert all(lb >= d for lb, d in zip(_vektor(lebih), _vektor(dasar)))


@SEDANG
@given(sub_skor, sub_skor_opsional, sub_skor_opsional)
def test_merge_max_deterministik_komutatif_dan_idempoten(a, b, c):
    semua = [a, b, c]
    asal = ScoringEngine._merge_max(*semua)

    assert ScoringEngine._merge_max(*semua) == asal
    assert ScoringEngine._merge_max(c, b, a) == asal
    assert ScoringEngine._merge_max(asal, a, b, c) == asal
    assert ScoringEngine._merge_max(asal) == asal


@SEDANG
@given(sub_skor, sub_skor, sub_skor, sub_skor)
def test_override_lebih_tinggi_tidak_menurunkan_hasil(rubrik, ai, rendah, tinggi):
    naik = BANTSubScores(**{k: max(getattr(rendah, k), getattr(tinggi, k)) for k in KRITERIA})

    a = ScoringEngine._merge_max(rubrik, ai, rendah)
    b = ScoringEngine._merge_max(rubrik, ai, naik)

    assert all(y >= x for x, y in zip(_vektor(a), _vektor(b)))


@SEDANG
@given(sub_skor, sub_skor_opsional, sub_skor_opsional)
def test_build_result_konsisten_dengan_gate(rubrik, ai, override):
    skor = ScoringEngine._merge_max(rubrik, ai, override)

    hasil = ScoringEngine._build_result(skor, None)

    assert hasil.total_score == bant_rubric.total_score(skor)
    assert (hasil.status, hasil.qualification_state) == bant_rubric.decide_gate(hasil.total_score)
    assert (hasil.feedback is None) == (hasil.total_score >= 60)


# --------------------------------------------------------------------------- agregasi AI


nilai_skor_ai = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.text(max_size=5),
    st.none(),
    st.booleans(),
)
kriteria_ai = st.one_of(
    st.dictionaries(st.sampled_from(["score", "evidence"]), nilai_skor_ai, max_size=2),
    nilai_skor_ai,
)
ekstraksi_ai = st.dictionaries(
    st.sampled_from([*KRITERIA, "use_case_tags", "lain"]),
    st.one_of(kriteria_ai, st.lists(st.one_of(st.text(max_size=8), st.integers()), max_size=9)),
    max_size=6,
)


@RIBUAN
@given(st.lists(ekstraksi_ai, max_size=4))
def test_agregasi_ai_apa_pun_tetap_dalam_0_25(ekstraksi):
    hasil = ScoringEngine()._aggregate_scores(ekstraksi)

    assert all(0 <= v <= 25 for v in _vektor(hasil))


@SEDANG
@given(st.lists(sub_skor, min_size=1, max_size=4))
def test_agregasi_ai_best_evidence_wins(daftar):
    ekstraksi = [{k: {"score": getattr(s, k), "evidence": "x"} for k in KRITERIA} for s in daftar]

    hasil = ScoringEngine()._aggregate_scores(ekstraksi)

    for k in KRITERIA:
        assert getattr(hasil, k) == max(getattr(s, k) for s in daftar)


@SEDANG
@given(st.lists(ekstraksi_ai, max_size=4))
def test_tag_ai_unik_tanpa_beda_huruf_dan_maks_lima(ekstraksi):
    tag = ScoringEngine()._aggregate_tags(ekstraksi)

    assert len(tag) <= 5
    assert len({t.lower() for t in tag}) == len(tag)


@RIBUAN
@given(nilai_skor_ai)
def test_safe_score_selalu_di_rentang(nilai):
    assert 0 <= ScoringEngine()._safe_score({"score": nilai}) <= 25
    assert ScoringEngine()._safe_score(nilai) == 0 or isinstance(nilai, dict)


# --------------------------------------------------------------------------- validasi masukan


@SEDANG
@given(st.dictionaries(st.text(min_size=1, max_size=15), nilai_sembarang, max_size=8))
def test_validasi_jawaban_tidak_pernah_melempar_dan_kunci_asing_selalu_ditolak(mentah):
    hasil, error = validate_answers(mentah)

    asing = [k for k in mentah if k not in QUESTIONNAIRE_FIELDS]
    if asing:
        assert hasil is None
        assert {e["field"] for e in error} >= {f"qualification_answers.{k}" for k in asing}
    assert (hasil is None) == bool(error)


@SEDANG
@given(jawaban_acak())
def test_jawaban_valid_menghasilkan_semua_field_dan_skor_dalam_batas(jawaban):
    hasil, error = validate_answers(jawaban)

    if hasil is not None:
        assert set(hasil) == set(QUESTIONNAIRE_FIELDS)
        skor = bant_rubric.compute_rubric_scores(hasil, None)
        assert 0 <= bant_rubric.total_score(skor) <= 100


@SEDANG
@given(st.one_of(st.none(), st.text(max_size=80), st.just("[]"), st.just("123")))
def test_parse_answers_string_apa_pun_tidak_melempar(teks):
    hasil, error = parse_answers(teks)

    assert (hasil is None) == bool(error)


@RIBUAN
@given(
    st.integers(min_value=-100, max_value=100),
    st.integers(min_value=-100, max_value=100),
    st.integers(min_value=-100, max_value=100),
    st.integers(min_value=-100, max_value=100),
    st.text(max_size=20),
)
def test_input_override_hanya_menerima_0_25_dan_alasan_tak_kosong(b, a, n, t, alasan):
    valid = all(0 <= x <= 25 for x in (b, a, n, t)) and alasan.strip() != ""
    try:
        masuk = BANTOverrideInput(budget=b, authority=a, need=n, timeline=t, reason=alasan)
    except ValidationError:
        assert not valid
    else:
        assert valid
        assert masuk.reason == alasan.strip()


@pytest.mark.parametrize("kunci", KRITERIA)
def test_subskor_di_luar_rentang_ditolak_skema(kunci):
    dasar = {k: 0 for k in KRITERIA}
    for buruk in (-1, 26):
        with pytest.raises(ValidationError):
            BANTSubScores(**{**dasar, kunci: buruk})
