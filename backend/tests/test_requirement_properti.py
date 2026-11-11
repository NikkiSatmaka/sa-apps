"""
Property test fungsi murni Requirement: pembagian anggaran karakter (`allocate_budget`),
hash sumber (`compute_source_hash`), dan teks kuesioner (`build_questionnaire_text`).
Tiket B9, spec #49.
"""

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.schemas.qualification_definition import answer_questions, question_labels
from app.services.requirement_generator import (
    allocate_budget,
    build_questionnaire_text,
    compute_source_hash,
)

PROP = hyp_settings(max_examples=200, deadline=None)

PANJANG = st.lists(st.integers(min_value=0, max_value=5000), max_size=12)
TOTAL = st.integers(min_value=-10, max_value=20000)


# --- allocate_budget
@PROP
@given(PANJANG, TOTAL)
def test_property_alokasi_tak_melebihi_panjang_sumber_maupun_total(panjang, total):
    alok = allocate_budget(panjang, total)
    assert len(alok) == len(panjang)
    assert all(0 <= a <= p for a, p in zip(alok, panjang))
    assert sum(alok) <= max(0, total)


@PROP
@given(PANJANG, TOTAL)
def test_property_anggaran_terpakai_penuh_atau_semua_sumber_utuh(panjang, total):
    """Tidak ada anggaran menganggur bila masih ada sumber yang terpotong."""
    alok = allocate_budget(panjang, total)
    assert sum(alok) == min(max(0, total), sum(panjang))


@PROP
@given(PANJANG, TOTAL)
def test_property_adil_antar_sumber_yang_terpotong(panjang, total):
    """Sumber terpotong mendapat jatah sama (selisih maks 1) dan tak kalah dari sumber utuh."""
    alok = allocate_budget(panjang, total)
    terpotong = [a for a, p in zip(alok, panjang) if a < p]
    if terpotong:
        assert max(terpotong) - min(terpotong) <= 1
        # Sumber utuh tidak pernah mendapat lebih dari jatah sumber yang terpotong + 1.
        utuh = [a for a, p in zip(alok, panjang) if a == p]
        assert all(u <= max(terpotong) + 1 for u in utuh)


@PROP
@given(PANJANG, TOTAL, st.randoms(use_true_random=False))
def test_property_urutan_sumber_tidak_mengubah_multiset_alokasi(panjang, total, rnd):
    acak = list(panjang)
    rnd.shuffle(acak)
    assert sorted(allocate_budget(panjang, total)) == sorted(allocate_budget(acak, total))


@PROP
@given(PANJANG, TOTAL)
def test_property_total_lebih_besar_tidak_mengurangi_alokasi_siapa_pun(panjang, total):
    kecil = allocate_budget(panjang, total)
    besar = allocate_budget(panjang, total + 1)
    # Penambahan anggaran tidak pernah menjatuhkan total terpakai.
    assert sum(besar) >= sum(kecil)


def test_alokasi_tepi():
    assert allocate_budget([], 100) == []
    assert allocate_budget([5, 5], 0) == [0, 0]
    assert allocate_budget([5, 5], -3) == [0, 0]
    assert allocate_budget([0, 0, 0], 10) == [0, 0, 0]
    assert allocate_budget([10**9], 7) == [7]
    assert allocate_budget([3], 10**9) == [3]


# --- compute_source_hash
NAMA_JAWABAN = [q.name for q in answer_questions()]
NILAI = st.one_of(st.text(max_size=20), st.integers(), st.booleans(), st.none())
JAWABAN = st.dictionaries(st.sampled_from(NAMA_JAWABAN), NILAI, max_size=len(NAMA_JAWABAN))
SUMBER = st.lists(st.tuples(st.sampled_from(["MoM", "RFP"]), st.text(max_size=60)), max_size=6)


@PROP
@given(st.one_of(st.none(), JAWABAN), SUMBER)
def test_property_hash_deterministik_dan_berformat_sha256_hex(jawaban, sumber):
    h = compute_source_hash(jawaban, sumber)
    assert h == compute_source_hash(jawaban, list(sumber))
    assert len(h) == 64 and set(h) <= set("0123456789abcdef")


@PROP
@given(JAWABAN, SUMBER, st.randoms(use_true_random=False))
def test_property_hash_tak_sensitif_urutan_sumber_maupun_urutan_kunci_jawaban(jawaban, sumber, rnd):
    sumber_acak = list(sumber)
    rnd.shuffle(sumber_acak)
    kunci = list(jawaban.items())
    rnd.shuffle(kunci)
    assert compute_source_hash(jawaban, sumber) == compute_source_hash(dict(kunci), sumber_acak)


@PROP
@given(JAWABAN, SUMBER, st.sampled_from(["", " ", "\n", "  \t "]))
def test_property_spasi_ujung_teks_sumber_tidak_mengubah_hash(jawaban, sumber, spasi):
    dengan_spasi = [(t, spasi + x + spasi) for t, x in sumber]
    assert compute_source_hash(jawaban, sumber) == compute_source_hash(jawaban, dengan_spasi)


@PROP
@given(
    JAWABAN,
    SUMBER,
    st.dictionaries(
        st.text(min_size=1, max_size=15).filter(lambda k: k not in NAMA_JAWABAN),
        st.text(max_size=10),
        max_size=4,
    ),
)
def test_property_field_header_dan_kunci_asing_tidak_ikut_hash(jawaban, sumber, header):
    assert compute_source_hash(jawaban, sumber) == compute_source_hash(
        {**jawaban, **header}, sumber
    )


@PROP
@given(JAWABAN, SUMBER, st.text(min_size=1, max_size=20).filter(lambda s: s.strip()))
def test_property_teks_sumber_baru_mengubah_hash(jawaban, sumber, tambahan):
    assert compute_source_hash(jawaban, sumber) != compute_source_hash(
        jawaban, [*sumber, ("MoM", tambahan)]
    )


@PROP
@given(st.text(min_size=1, max_size=40).filter(lambda s: s.strip()))
def test_property_tipe_sumber_ikut_hash(teks):
    assert compute_source_hash({}, [("MoM", teks)]) != compute_source_hash({}, [("RFP", teks)])


def test_hash_perubahan_satu_jawaban_mengubah_hash():
    nama = NAMA_JAWABAN[0]
    assert compute_source_hash({nama: "Ya"}, []) != compute_source_hash({nama: "Tidak"}, [])


def test_hash_none_kosong_dan_tanpa_sumber_sama():
    assert compute_source_hash(None, []) == compute_source_hash({}, [])


def test_hash_unicode_stabil():
    a = compute_source_hash({}, [("MoM", "Kebutuhan 日本語 🙂 é")])
    assert a == compute_source_hash({}, [("MoM", "Kebutuhan 日本語 🙂 é")])


def test_hash_format_kanonik_tetap_agar_hash_tersimpan_di_database_tetap_valid():
    """Hash tersimpan di DB: mengubah algoritma/format membuat semua banner palsu muncul."""
    import hashlib

    kanonik = '{"answers": {}, "sources": [["MoM", "isi"], ["RFP", "lain"]]}'
    harapan = hashlib.sha256(kanonik.encode("utf-8")).hexdigest()
    assert compute_source_hash(None, [("RFP", " lain "), ("MoM", "isi")]) == harapan


# --- build_questionnaire_text
def test_teks_kuesioner_kosong_untuk_none_dan_jawaban_kosong_atau_hanya_spasi():
    assert build_questionnaire_text(None) == ""
    assert build_questionnaire_text({}) == ""
    nama = NAMA_JAWABAN[0]
    assert build_questionnaire_text({nama: "   "}) == ""
    assert build_questionnaire_text({nama: None}) == ""


JAWABAN_SATU_BARIS = st.dictionaries(
    st.sampled_from(NAMA_JAWABAN),
    st.one_of(
        st.text(alphabet=st.characters(blacklist_characters="\n"), max_size=20),
        st.integers(),
        st.none(),
    ),
    max_size=len(NAMA_JAWABAN),
)


@PROP
@given(JAWABAN_SATU_BARIS)
def test_property_teks_kuesioner_memuat_label_dan_nilai_hanya_untuk_jawaban_terisi(jawaban):
    teks = build_questionnaire_text(jawaban)
    label = question_labels()
    baris = teks.split("\n") if teks else []
    terisi = {
        n: v
        for n, v in jawaban.items()
        if v is not None and not (isinstance(v, str) and not v.strip())
    }
    assert len(baris) == len(terisi)
    for n, v in terisi.items():
        assert f"{label[n]}: {v}" in baris
