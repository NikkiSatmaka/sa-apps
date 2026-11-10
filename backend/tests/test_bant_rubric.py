"""
Test fungsi rubrik BANT murni (seam kecil): jawaban kuesioner → sub-skor.
Nilai harapan berasal dari spesifikasi #24 / ADR 0010, bukan dihitung ulang dari kode.
"""

from datetime import date

import pytest

from app.services import bant_rubric
from app.services.bant_rubric import compute_rubric_scores

TARGET = date(2030, 1, 1)


def _jawaban(**override):
    """Jawaban 'kosong' yang valid: hanya field wajib, semua pilihan 'Tidak tahu'."""
    dasar = {
        "mrr": None,
        "budget_dialokasikan": "Tidak tahu",
        "pic_nama": None,
        "pic_jabatan": None,
        "pic_email": None,
        "peran_pic": "Tidak tahu",
        "stakeholder_lain": None,
        "masalah_bisnis": "x" * 10,
        "jenis_workload": "Lainnya",
        "lingkungan": "Cloud",
        "skala": "10 server",
        "persyaratan_khusus": None,
        "kompetitor": None,
        "target_go_live": "Tidak tahu",
    }
    dasar.update(override)
    return dasar


def _jawaban_penuh():
    return _jawaban(
        mrr=5_000_000,
        budget_dialokasikan="Ya",
        pic_nama="Budi",
        pic_jabatan="CTO",
        pic_email="budi@contoh.co.id",
        peran_pic="Pengambil keputusan",
        masalah_bisnis="x" * 50,
        persyaratan_khusus="Data residency Indonesia",
        target_go_live="≤ 3 bulan",
    )


def test_semua_terisi_penuh_adalah_100():
    s = compute_rubric_scores(_jawaban_penuh(), TARGET)
    assert (s.budget, s.authority, s.need, s.timeline) == (25, 25, 25, 25)


def test_semua_tidak_tahu_tidak_lolos_gate_60():
    s = compute_rubric_scores(_jawaban(), TARGET)
    total = s.budget + s.authority + s.need + s.timeline
    # Need: 0 (masalah <50) + 5 (workload) + 7 (env+skala) + 0; Timeline: 10 dari target submit
    assert (s.budget, s.authority, s.need, s.timeline) == (0, 0, 12, 10)
    assert total < 60


@pytest.mark.parametrize(
    "mrr,diharapkan",
    [(None, 0), (0, 0), (1, 10), (5_000_000, 10)],
)
def test_budget_mrr_hanya_dinilai_bila_lebih_dari_nol(mrr, diharapkan):
    assert compute_rubric_scores(_jawaban(mrr=mrr), TARGET).budget == diharapkan


@pytest.mark.parametrize(
    "pilihan,diharapkan", [("Ya", 15), ("Belum", 5), ("Tidak tahu", 0)]
)
def test_budget_dialokasikan(pilihan, diharapkan):
    assert compute_rubric_scores(_jawaban(budget_dialokasikan=pilihan), TARGET).budget == diharapkan


@pytest.mark.parametrize(
    "pilihan,diharapkan",
    [("Pengambil keputusan", 15), ("Perantara", 6), ("Tidak tahu", 0)],
)
def test_authority_peran_pic(pilihan, diharapkan):
    assert compute_rubric_scores(_jawaban(peran_pic=pilihan), TARGET).authority == diharapkan


@pytest.mark.parametrize(
    "nama,jabatan,email,diharapkan",
    [
        ("Budi", "CTO", "b@c.id", 10),
        ("Budi", "CTO", None, 0),
        ("Budi", None, "b@c.id", 0),
        (None, "CTO", "b@c.id", 0),
        ("Budi", "   ", "b@c.id", 0),
        (None, None, None, 0),
    ],
)
def test_authority_pic_lengkap_hanya_bila_ketiganya_terisi(nama, jabatan, email, diharapkan):
    s = compute_rubric_scores(
        _jawaban(pic_nama=nama, pic_jabatan=jabatan, pic_email=email), TARGET
    )
    assert s.authority == diharapkan


@pytest.mark.parametrize("panjang,diharapkan", [(0, 0), (49, 0), (50, 8), (51, 8)])
def test_need_batas_50_karakter_masalah_bisnis(panjang, diharapkan):
    s = compute_rubric_scores(_jawaban(masalah_bisnis="x" * panjang), TARGET)
    # komponen lain tetap: workload 5 + env/skala 7
    assert s.need == diharapkan + 12


def test_need_masalah_bisnis_spasi_tidak_dihitung():
    s = compute_rubric_scores(_jawaban(masalah_bisnis=" " * 60), TARGET)
    assert s.need == 12


def test_need_lingkungan_dan_skala_harus_keduanya_terisi():
    assert compute_rubric_scores(_jawaban(skala=None), TARGET).need == 5
    assert compute_rubric_scores(_jawaban(lingkungan=None), TARGET).need == 5


def test_need_persyaratan_khusus_menambah_5():
    assert compute_rubric_scores(_jawaban(persyaratan_khusus="SLA 99.9%"), TARGET).need == 17


@pytest.mark.parametrize(
    "go_live,diharapkan",
    [("≤ 3 bulan", 25), ("≤ 6 bulan", 20), ("> 6 bulan", 15), ("Tidak tahu", 10)],
)
def test_timeline_bucket_go_live(go_live, diharapkan):
    assert compute_rubric_scores(_jawaban(target_go_live=go_live), TARGET).timeline == diharapkan


def test_timeline_tanpa_target_submit_kehilangan_10():
    assert compute_rubric_scores(_jawaban(target_go_live="≤ 3 bulan"), None).timeline == 15


def test_estimasi_nilai_tidak_ikut_dinilai():
    # estimasi_nilai bukan bagian jawaban; menyelipkannya tidak mengubah skor
    a = compute_rubric_scores(_jawaban(), TARGET)
    b = compute_rubric_scores(_jawaban(estimasi_nilai=10**12), TARGET)
    assert a == b


def test_rubrik_satu_tempat_maksimum_25_per_kriteria():
    assert bant_rubric.GATE_THRESHOLD == 60
    assert bant_rubric.QUESTIONNAIRE_SCHEMA_VERSION == 1
