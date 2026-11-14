"""
Konstanta model status proyek dua field (ADR 0013, spec §2.0 "Siklus status").

- `Projects.status`: siklus kerja (`Intake` ... `Closed`) ditambah status samping `Lost`
  dan `On Hold`.
- `Projects.qualification_state`: gate kualifikasi. Hanya bermakna saat `status = Intake`;
  setelah lolos gate tetap `Qualified`.

Satu sumber nama supaya CheckConstraint, state machine, scoring, dan notifikasi tidak
menulis literal sendiri-sendiri. Jangan "dirapikan" menjadi satu daftar campuran (ADR 0013).
"""

# --- status (siklus kerja) ---
INTAKE = "Intake"
AWAITING_ASSIGNMENT = "Awaiting Assignment"
ASSIGNED = "Assigned"
IN_PROGRESS = "In Progress"
SUBMITTED = "Submitted"
WON = "Won"
HANDED_OVER = "Handed Over"
CLOSED = "Closed"
LOST = "Lost"
ON_HOLD = "On Hold"

# Urutan siklus kerja utama (tanpa status samping).
SIKLUS_UTAMA = (
    INTAKE,
    AWAITING_ASSIGNMENT,
    ASSIGNED,
    IN_PROGRESS,
    SUBMITTED,
    WON,
    HANDED_OVER,
    CLOSED,
)
SEMUA_STATUS = (*SIKLUS_UTAMA, LOST, ON_HOLD)

# `previous_status` menyimpan status sebelum jeda/Lost: selalu salah satu siklus utama.
STATUS_SEBELUMNYA_VALID = SIKLUS_UTAMA

# --- qualification_state ---
QS_SCORING = "Scoring"
QS_NEED_CLARIFICATION = "Need Clarification"
QS_MANUAL_REVIEW = "Manual Review"
QS_QUALIFIED = "Qualified"
SEMUA_QUALIFICATION_STATE = (
    QS_SCORING,
    QS_NEED_CLARIFICATION,
    QS_MANUAL_REVIEW,
    QS_QUALIFIED,
)

# Hasil scoring hanya boleh mengubah proyek `Intake` dengan state ini. Status Awaiting
# Assignment dan sesudahnya tidak pernah ditimpa (mis. hasil AI yang selesai terlambat).
QS_SCORING_MUTABLE = frozenset({QS_SCORING, QS_NEED_CLARIFICATION})

# Override Lead_SA/Admin (#30) hanya untuk proyek `Intake` yang menunggu keputusan manual.
QS_OVERRIDE_ALLOWED = frozenset({QS_NEED_CLARIFICATION, QS_MANUAL_REVIEW})

# Status tempat DQ Number boleh diinput ("Assigned atau lebih tinggi" yang masih aktif).
STATUS_BOLEH_DQ = (ASSIGNED, IN_PROGRESS, SUBMITTED, WON, HANDED_OVER)

# Status proyek yang sudah selesai/berakhir (tidak lagi mendapat penugasan atau Requirement baru).
STATUS_AKHIR = (WON, HANDED_OVER, CLOSED, LOST)
