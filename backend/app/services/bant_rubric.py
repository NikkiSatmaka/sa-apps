"""
Rubrik skor BANT deterministik dari Kuesioner kualifikasi (ADR 0010).

Satu-satunya tempat angka rubrik hidup. Perubahan angka di sini adalah perubahan
perilaku gate kualifikasi dan wajib disertai perubahan test (tests/test_bant_rubric.py).
Rubrik bersifat per `schema_version` kuesioner.

Catatan: `estimasi_nilai` sengaja TIDAK dinilai (field wajib sehingga komponen itu
akan selalu terpenuhi); MRR dinilai.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional

from app.schemas.scoring import BANTSubScores

QUESTIONNAIRE_SCHEMA_VERSION = 1

# Kunci sub-skor numerik di projects.bant_detail (dimiliki backend).
SUB_SCORE_KEYS = ("budget", "authority", "need", "timeline")

# Ambang gate kualifikasi: total >= GATE_THRESHOLD lolos.
GATE_THRESHOLD = 60
# Kriteria dengan sub-skor di bawah angka ini dianggap lemah di feedback.
WEAK_CRITERION_THRESHOLD = 15

# --- Pilihan jawaban (nilai persis yang dikirim klien) ---
YA, BELUM, TIDAK_TAHU = "Ya", "Belum", "Tidak tahu"
BUDGET_DIALOKASIKAN_CHOICES = (YA, BELUM, TIDAK_TAHU)

PERAN_PENGAMBIL_KEPUTUSAN, PERAN_PERANTARA = "Pengambil keputusan", "Perantara"
PERAN_PIC_CHOICES = (PERAN_PENGAMBIL_KEPUTUSAN, PERAN_PERANTARA, TIDAK_TAHU)

JENIS_WORKLOAD_CHOICES = (
    "Migrasi ke cloud",
    "Data warehouse/analytics",
    "Disaster recovery/backup",
    "Aplikasi baru/modernisasi",
    "Keamanan",
    "Lainnya",
)
LINGKUNGAN_CHOICES = ("On-prem", "Cloud", "Hybrid")

GO_LIVE_3_BULAN, GO_LIVE_6_BULAN, GO_LIVE_LEBIH_6_BULAN = "≤ 3 bulan", "≤ 6 bulan", "> 6 bulan"
TARGET_GO_LIVE_CHOICES = (GO_LIVE_3_BULAN, GO_LIVE_6_BULAN, GO_LIVE_LEBIH_6_BULAN, TIDAK_TAHU)

# --- Poin rubrik (maksimum 25 per kriteria) ---
# Budget: 10 + 15
POIN_BUDGET_MRR = 10
POIN_BUDGET_DIALOKASIKAN = {YA: 15, BELUM: 5, TIDAK_TAHU: 0}
# Authority: 10 + 15
POIN_AUTHORITY_PIC_LENGKAP = 10
POIN_AUTHORITY_PERAN = {PERAN_PENGAMBIL_KEPUTUSAN: 15, PERAN_PERANTARA: 6, TIDAK_TAHU: 0}
# Need: 8 + 5 + 7 + 5
MIN_PANJANG_MASALAH_BISNIS = 50
POIN_NEED_MASALAH_BISNIS = 8
POIN_NEED_WORKLOAD = 5
POIN_NEED_LINGKUNGAN_SKALA = 7
POIN_NEED_PERSYARATAN_KHUSUS = 5
# Timeline: 10 + 15
POIN_TIMELINE_TARGET_SUBMIT = 10
POIN_TIMELINE_GO_LIVE = {
    GO_LIVE_3_BULAN: 15,
    GO_LIVE_6_BULAN: 10,
    GO_LIVE_LEBIH_6_BULAN: 5,
    TIDAK_TAHU: 0,
}


def _terisi(value: Any) -> bool:
    """True bila nilai berupa teks tidak kosong (setelah trim)."""
    return isinstance(value, str) and value.strip() != ""


def compute_rubric_scores(
    answers: Mapping[str, Any], target_submit: Optional[date]
) -> BANTSubScores:
    """
    Hitung sub-skor BANT dari jawaban kuesioner (fungsi murni, tanpa I/O).

    Args:
        answers: Jawaban ter-normalisasi (lihat app.schemas.qualification).
        target_submit: Target submit header proyek (pertanyaan #11).
    """
    # Budget
    mrr = answers.get("mrr")
    budget = POIN_BUDGET_MRR if isinstance(mrr, (int, float)) and mrr > 0 else 0
    budget += POIN_BUDGET_DIALOKASIKAN.get(answers.get("budget_dialokasikan"), 0)

    # Authority: PIC lengkap = ketiga field terisi, selain itu 0
    pic_lengkap = all(_terisi(answers.get(k)) for k in ("pic_nama", "pic_jabatan", "pic_email"))
    authority = POIN_AUTHORITY_PIC_LENGKAP if pic_lengkap else 0
    authority += POIN_AUTHORITY_PERAN.get(answers.get("peran_pic"), 0)

    # Need
    need = 0
    masalah = answers.get("masalah_bisnis")
    if _terisi(masalah) and len(masalah.strip()) >= MIN_PANJANG_MASALAH_BISNIS:
        need += POIN_NEED_MASALAH_BISNIS
    if _terisi(answers.get("jenis_workload")):
        need += POIN_NEED_WORKLOAD
    if _terisi(answers.get("lingkungan")) and _terisi(answers.get("skala")):
        need += POIN_NEED_LINGKUNGAN_SKALA
    if _terisi(answers.get("persyaratan_khusus")):
        need += POIN_NEED_PERSYARATAN_KHUSUS

    # Timeline
    timeline = POIN_TIMELINE_TARGET_SUBMIT if target_submit is not None else 0
    timeline += POIN_TIMELINE_GO_LIVE.get(answers.get("target_go_live"), 0)

    return BANTSubScores(budget=budget, authority=authority, need=need, timeline=timeline)


def total_score(sub_scores: BANTSubScores) -> int:
    """Jumlah empat sub-skor (0-100)."""
    return sub_scores.budget + sub_scores.authority + sub_scores.need + sub_scores.timeline


def decide_status(total: int) -> str:
    """Gate kualifikasi: >= GATE_THRESHOLD → Pending Assignment, selain itu Need Clarification."""
    return "Pending Assignment" if total >= GATE_THRESHOLD else "Need Clarification"


def generate_feedback(sub_scores: BANTSubScores) -> str:
    """Feedback untuk Sales saat skor < GATE_THRESHOLD: kriteria yang lemah."""
    kriteria = (
        ("Budget", sub_scores.budget),
        ("Authority", sub_scores.authority),
        ("Need", sub_scores.need),
        ("Timeline", sub_scores.timeline),
    )
    lemah = [
        f"- {nama} (skor: {skor}/25): informasi kurang jelas"
        for nama, skor in kriteria
        if skor < WEAK_CRITERION_THRESHOLD
    ]
    if not lemah:
        return f"Skor total belum mencapai threshold {GATE_THRESHOLD}. Lengkapi informasi proyek."
    return "Kriteria berikut perlu dilengkapi:\n" + "\n".join(lemah)
