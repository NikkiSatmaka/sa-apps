"""
Definisi Kuesioner kualifikasi — SATU-SATUNYA sumber (nama field, label, tipe, wajib/opsional,
pilihan, petunjuk isian, kelompok BANT, petunjuk tata letak, batas panjang).

Dipakai oleh:
- validasi jawaban (app.schemas.qualification),
- pilihan jawaban rubrik (app.services.bant_rubric),
- endpoint skema GET /qualification/schema (frontend merender form & tampilan baca-saja darinya),
- akses label pertanyaan (get_question_label / question_labels), mis. untuk prompt 5B.

Kuesioner adalah set tetap di kode (keputusan 5.1). Mengubah isi definisi berarti mengubah
kontrak produk: naikkan QUESTIONNAIRE_SCHEMA_VERSION bila semantik jawaban berubah.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

QUESTIONNAIRE_SCHEMA_VERSION = 1

MAX_MRR = 999_999_999_999
MAX_TEXT_LENGTH = 2000
MAX_SHORT_LENGTH = 200
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# --- Pilihan jawaban (nilai persis yang dikirim klien) ---
YA, BELUM, TIDAK_TAHU = "Ya", "Belum", "Tidak tahu"
PERAN_PENGAMBIL_KEPUTUSAN, PERAN_PERANTARA = "Pengambil keputusan", "Perantara"
GO_LIVE_3_BULAN, GO_LIVE_6_BULAN, GO_LIVE_LEBIH_6_BULAN = "≤ 3 bulan", "≤ 6 bulan", "> 6 bulan"

# Tipe: "number", "choice", "text" (area teks), "short" (teks satu baris), "email", "date" (header).
TYPES = ("number", "choice", "text", "short", "email", "date")


@dataclass(frozen=True)
class Group:
    """Kelompok BANT (judul seksi di form)."""

    key: str
    title: str


@dataclass(frozen=True)
class Question:
    name: str
    group: str  # key Group
    type: str
    label: str  # label di form
    short_label: str  # label di tampilan baca-saja / prompt
    required: bool = False
    choices: Optional[tuple[str, ...]] = None
    hint: Optional[str] = None  # petunjuk isian di bawah input
    placeholder: Optional[str] = None
    max_length: Optional[int] = None  # tipe teks
    min_value: Optional[float] = None  # tipe number
    max_value: Optional[float] = None
    pattern: Optional[str] = None  # regex (tipe email)
    row: Optional[str] = None  # pertanyaan berurutan dengan row sama dirender sebaris
    row_hint: Optional[str] = None  # petunjuk untuk seluruh baris (di pertanyaan pertama baris)
    display: Optional[str] = None  # "currency_idr" | "date" untuk tampilan baca-saja
    show_char_count: bool = False
    header: bool = False  # True: field header proyek, bukan bagian qualification_answers

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["choices"] = list(self.choices) if self.choices is not None else None
        return d


GROUPS: tuple[Group, ...] = (
    Group("budget", "Budget"),
    Group("authority", "Authority"),
    Group("need", "Need"),
    Group("timeline", "Timeline & Kompetisi"),
)

QUESTIONS: tuple[Question, ...] = (
    # Pertanyaan #11 — field header proyek (diisi di langkah 1), hanya tampil di baca-saja.
    Question(
        "target_submit", "timeline", "date", "Target submit", "Target submit",
        header=True, display="date",
    ),
    Question(
        "mrr", "budget", "number", "MRR (estimasi pendapatan bulanan, IDR)", "MRR (IDR)",
        placeholder="Contoh: 5000000", min_value=0, max_value=MAX_MRR, display="currency_idr",
    ),
    Question(
        "budget_dialokasikan", "budget", "choice",
        "Budget sudah dialokasikan/disetujui?", "Budget sudah dialokasikan/disetujui?",
        required=True, choices=(YA, BELUM, TIDAK_TAHU),
    ),
    Question(
        "pic_nama", "authority", "short", "Nama PIC", "Nama PIC",
        max_length=MAX_SHORT_LENGTH, row="pic",
        row_hint="Nama, jabatan, dan email PIC dinilai bila ketiganya diisi.",
    ),
    Question(
        "pic_jabatan", "authority", "short", "Jabatan PIC", "Jabatan PIC",
        max_length=MAX_SHORT_LENGTH, row="pic",
    ),
    Question(
        "pic_email", "authority", "email", "Email PIC", "Email PIC",
        max_length=MAX_SHORT_LENGTH, pattern=EMAIL_PATTERN, row="pic",
    ),
    Question(
        "peran_pic", "authority", "choice",
        "Peran PIC dalam keputusan", "Peran PIC dalam keputusan",
        required=True, choices=(PERAN_PENGAMBIL_KEPUTUSAN, PERAN_PERANTARA, TIDAK_TAHU),
    ),
    Question(
        "stakeholder_lain", "authority", "text",
        "Stakeholder lain dalam keputusan", "Stakeholder lain dalam keputusan",
        max_length=MAX_TEXT_LENGTH,
    ),
    Question(
        "masalah_bisnis", "need", "text",
        "Masalah bisnis yang ingin diselesaikan", "Masalah bisnis yang ingin diselesaikan",
        required=True, max_length=MAX_TEXT_LENGTH,
        placeholder="Jelaskan masalah bisnis customer secara faktual",
        hint="Uraian yang lebih rinci (≥ 50 karakter) menambah skor.",
        show_char_count=True,
    ),
    Question(
        "jenis_workload", "need", "choice", "Jenis workload", "Jenis workload",
        required=True,
        choices=(
            "Migrasi ke cloud",
            "Data warehouse/analytics",
            "Disaster recovery/backup",
            "Aplikasi baru/modernisasi",
            "Keamanan",
            "Lainnya",
        ),
    ),
    Question(
        "lingkungan", "need", "choice", "Lingkungan saat ini", "Lingkungan saat ini",
        required=True, choices=("On-prem", "Cloud", "Hybrid"), row="lingkungan_skala",
    ),
    Question(
        "skala", "need", "short",
        "Skala (jumlah server, volume data)", "Skala (jumlah server, volume data)",
        required=True, max_length=MAX_SHORT_LENGTH, placeholder="Contoh: 40 server, 20 TB",
        row="lingkungan_skala",
    ),
    Question(
        "persyaratan_khusus", "need", "text",
        "Persyaratan khusus (kepatuhan, SLA, integrasi, data residency)", "Persyaratan khusus",
        max_length=MAX_TEXT_LENGTH,
    ),
    Question(
        "target_go_live", "timeline", "choice",
        "Target go-live / keputusan beli", "Target go-live / keputusan beli",
        required=True, choices=(GO_LIVE_3_BULAN, GO_LIVE_6_BULAN, GO_LIVE_LEBIH_6_BULAN, TIDAK_TAHU),
    ),
    Question(
        "kompetitor", "timeline", "text", "Kompetitor/vendor lain", "Kompetitor/vendor lain",
        max_length=MAX_TEXT_LENGTH,
    ),
)

_BY_NAME = {q.name: q for q in QUESTIONS}


def get_question(name: str) -> Question:
    """Definisi satu pertanyaan; KeyError bila nama tidak dikenal."""
    return _BY_NAME[name]


def answer_questions() -> tuple[Question, ...]:
    """Pertanyaan yang jawabannya masuk qualification_answers (tanpa field header)."""
    return tuple(q for q in QUESTIONS if not q.header)


def get_choices(name: str) -> tuple[str, ...]:
    """Pilihan jawaban sebuah pertanyaan bertipe choice."""
    choices = get_question(name).choices
    if choices is None:
        raise KeyError(f"Pertanyaan '{name}' tidak memiliki pilihan.")
    return choices


def get_question_label(name: str) -> str:
    """Label pertanyaan (versi ringkas, untuk tampilan baca-saja dan prompt dokumen)."""
    return get_question(name).short_label


def question_labels() -> dict[str, str]:
    """Peta nama pertanyaan → label ringkas, berurutan sesuai urutan tampil."""
    return {q.name: q.short_label for q in QUESTIONS}


def schema_payload() -> dict[str, Any]:
    """Bentuk yang disajikan endpoint skema."""
    return {
        "schema_version": QUESTIONNAIRE_SCHEMA_VERSION,
        "groups": [asdict(g) for g in GROUPS],
        "questions": [q.to_dict() for q in QUESTIONS],
    }
