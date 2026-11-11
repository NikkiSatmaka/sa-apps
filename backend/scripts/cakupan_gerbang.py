"""Gerbang cakupan backend: baris >= 90% DAN cabang >= 80% (CONSTRAINTS.md bagian 1).

Membaca keluaran ``coverage json`` (data gabungan unit + integrasi) dan memeriksa dua
ambang TERPISAH. ``--cov-fail-under`` pytest-cov hanya satu angka gabungan, jadi tidak
cukup. Yang MEMBLOK adalah cakupan TOTAL; modul (file) di bawah ambang hanya dilaporkan
sebagai peringatan (``::warning::`` di GitHub Actions) agar modul kecil dengan sedikit
cabang tidak memblok PR sendirian.

Pemakaian::

    coverage json -o coverage.json
    python scripts/cakupan_gerbang.py coverage.json

Kode keluar 0 bila lolos, 1 bila ada ambang yang dilanggar, 2 bila masukan tidak valid.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

AMBANG_BARIS = 90.0
AMBANG_CABANG = 80.0


@dataclass(frozen=True)
class Cakupan:
    nama: str
    baris_tercakup: int
    baris_total: int
    cabang_tercakup: int
    cabang_total: int

    @property
    def baris(self) -> float:
        # Tanpa statement = tidak ada yang bisa gagal.
        return 100.0 if self.baris_total == 0 else 100.0 * self.baris_tercakup / self.baris_total

    @property
    def cabang(self) -> float:
        return 100.0 if self.cabang_total == 0 else 100.0 * self.cabang_tercakup / self.cabang_total


def _dari_ringkasan(nama: str, ringkasan: dict) -> Cakupan:
    try:
        return Cakupan(
            nama,
            int(ringkasan["covered_lines"]),
            int(ringkasan["num_statements"]),
            int(ringkasan["covered_branches"]),
            int(ringkasan["num_branches"]),
        )
    except KeyError as exc:
        raise ValueError(
            f"Ringkasan '{nama}' tidak memuat {exc}; pastikan cakupan diukur dengan branch=true."
        ) from exc


def baca(data: dict) -> tuple[Cakupan, list[Cakupan]]:
    """Kembalikan (total, daftar per-file) dari struktur ``coverage json``."""
    if "totals" not in data or "files" not in data:
        raise ValueError("Bukan keluaran `coverage json` yang valid (tidak ada totals/files).")
    total = _dari_ringkasan("TOTAL", data["totals"])
    files = [_dari_ringkasan(n, f["summary"]) for n, f in sorted(data["files"].items())]
    return total, files


def periksa(
    total: Cakupan,
    files: list[Cakupan],
    ambang_baris: float = AMBANG_BARIS,
    ambang_cabang: float = AMBANG_CABANG,
) -> list[str]:
    """Daftar pelanggaran ambang (kosong = lolos). ``files`` dipertahankan agar
    pemanggil bisa memakai ``peringatan_modul``; hanya TOTAL yang memblok."""
    return _lanjut([total], ambang_baris, ambang_cabang)


def _lanjut(daftar: list[Cakupan], ambang_baris: float, ambang_cabang: float) -> list[str]:
    hasil: list[str] = []
    for c in daftar:
        if c.baris < ambang_baris:
            hasil.append(
                f"{c.nama}: cakupan BARIS {c.baris:.2f}% < {ambang_baris:g}% "
                f"({c.baris_tercakup}/{c.baris_total} statement)"
            )
        if c.cabang < ambang_cabang:
            hasil.append(
                f"{c.nama}: cakupan CABANG {c.cabang:.2f}% < {ambang_cabang:g}% "
                f"({c.cabang_tercakup}/{c.cabang_total} cabang)"
            )
    return hasil


def peringatan_modul(
    files: list[Cakupan],
    ambang_baris: float = AMBANG_BARIS,
    ambang_cabang: float = AMBANG_CABANG,
) -> list[str]:
    """Modul individual di bawah ambang (informatif, tidak memblok)."""
    return _lanjut(files, ambang_baris, ambang_cabang)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Pemakaian: {argv[0]} <coverage.json>", file=sys.stderr)
        return 2
    try:
        total, files = baca(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"GERBANG CAKUPAN: masukan tidak valid: {exc}", file=sys.stderr)
        return 2

    print(
        f"Total: baris {total.baris:.2f}% (ambang {AMBANG_BARIS:g}%), "
        f"cabang {total.cabang:.2f}% (ambang {AMBANG_CABANG:g}%); {len(files)} modul"
    )
    for w in peringatan_modul(files):
        print(f"::warning title=Modul di bawah ambang::{w}")
    pelanggaran = periksa(total, files)
    if pelanggaran:
        print("GERBANG CAKUPAN GAGAL — ambang dilanggar:", file=sys.stderr)
        for p in pelanggaran:
            print(f"  - {p}", file=sys.stderr)
        print(
            "Lihat kolom Missing pada `coverage report` untuk baris/cabang yang belum teruji; "
            "tambahkan test (jangan menurunkan ambang) — CONSTRAINTS.md bagian 6.",
            file=sys.stderr,
        )
        return 1
    print("GERBANG CAKUPAN LOLOS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
