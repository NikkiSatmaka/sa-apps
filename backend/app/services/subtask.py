"""
Aturan domain subtask yang murni (tanpa DB).

- `subtask_terlambat`: penanda "terlambat" pada daftar subtask (issue #124).
"""

from datetime import date


def subtask_terlambat(
    due_date: date | None, status: str, hari_ini: date | None = None
) -> bool:
    """
    Subtask terlambat bila `due_date` sudah lewat (due_date < hari ini) dan status belum `done`.

    Jatuh tempo hari ini belum terlambat. Tanpa `due_date` tidak pernah terlambat. "Hari ini"
    memakai `date.today()` (tanggal lokal server), konsisten dengan validasi `target_submit`
    di `app/schemas/project.py` dan `app/api/projects.py`.
    """
    if due_date is None or status == "done":
        return False
    return due_date < (hari_ini or date.today())
