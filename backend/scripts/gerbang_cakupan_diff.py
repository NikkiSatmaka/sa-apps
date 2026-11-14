"""Gerbang cakupan diff: cakupan pada baris yang DIUBAH/DITAMBAH (tiket #98).

Gerbang total (``cakupan_gerbang.py`` dan ``coverage.thresholds`` vitest) bisa tetap hijau walau
sebuah PR menambah banyak baris tak teruji. Gerbang ini menilai hanya baris yang berubah terhadap
merge-base dengan branch dasar, memakai ``diff-cover``:

* **backend**: ``coverage.xml`` gabungan unit + integrasi (Cobertura). Baris >= 90% dan
  "cabang" >= 80%. Angka cabang memakai mode ``--branch-coverage`` diff-cover: persentase baris
  yang diubah yang dieksekusi DAN tidak memuat cabang parsial. Itu bukan rasio cabang murni
  (diff-cover berbasis baris), tetapi selalu <= cakupan baris sehingga tidak melonggarkan.
* **frontend**: ``coverage/lcov.info`` Vitest. Hanya baris >= 90%; diff-cover tidak mendukung
  mode cabang untuk lcov, jadi cabang TIDAK dinilai (dilaporkan apa adanya, tanpa angka palsu).

Lewati otomatis: sisi yang tidak punya perubahan kode produk (``backend/app/**/*.py``;
``frontend/src/**/*.{ts,tsx}`` selain test, ``src/test/**``, dan ``*.d.ts``, selaras
CONSTRAINTS.md bagian 3) tidak dinilai dan tidak butuh laporan. Label PR
``cakupan-dikecualikan`` (hanya dengan persetujuan pemilik, CONSTRAINTS.md bagian 4) melewati
gerbang ini, BUKAN gerbang total.

Pemakaian (dari ``backend/``)::

    uv run python -m scripts.gerbang_cakupan_diff --base origin/main \\
        --backend-xml coverage.xml --frontend-lcov ../frontend/coverage/lcov.info

Yang dibandingkan: merge-base(base, HEAD) terhadap working tree, termasuk berkas untracked
(lokal: perubahan belum di-commit ikut dinilai; di CI working tree bersih = isi PR).
Kode keluar 0 bila lolos/dilewati, 1 bila ambang dilanggar atau laporan tidak ada, 2 bila
git/diff-cover gagal.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from scripts.cakupan_gerbang import AMBANG_BARIS, AMBANG_CABANG

LABEL_PENGECUALIAN = "cakupan-dikecualikan"
SISI = ("backend", "frontend")


class GagalAlat(Exception):
    """git atau diff-cover gagal dijalankan."""


def _kode_backend(path: str) -> bool:
    return path.startswith("backend/app/") and path.endswith(".py")


def _kode_frontend(path: str) -> bool:
    if not path.startswith("frontend/src/") or not path.endswith((".ts", ".tsx")):
        return False
    if path.startswith("frontend/src/test/") or path.endswith(".d.ts"):
        return False
    return not path.endswith((".test.ts", ".test.tsx"))


def kode_berubah(paths: Iterable[str]) -> dict[str, list[str]]:
    """Kelompokkan path yang berubah menjadi kode produk per sisi (terurut, tanpa duplikat)."""
    unik = sorted(set(paths))
    return {
        "backend": [p for p in unik if _kode_backend(p)],
        "frontend": [p for p in unik if _kode_frontend(p)],
    }


def rentang(nomor: Iterable[int]) -> str:
    """``[3, 4, 5, 9]`` -> ``"3-5, 9"``."""
    bagian: list[str] = []
    urut = sorted(set(nomor))
    i = 0
    while i < len(urut):
        j = i
        while j + 1 < len(urut) and urut[j + 1] == urut[j] + 1:
            j += 1
        bagian.append(str(urut[i]) if i == j else f"{urut[i]}-{urut[j]}")
        i = j + 1
    return ", ".join(bagian)


@dataclass(frozen=True)
class Hasil:
    sisi: str
    baris_total: int
    baris: float
    cabang: float | None  # None = tidak didukung alat untuk sisi ini
    berkas_hilang: dict[str, list[int]] = field(default_factory=dict)
    pelanggaran: list[str] = field(default_factory=list)


def _persen(laporan: dict) -> float:
    if int(laporan.get("total_num_lines", 0)) == 0:
        return 100.0
    return float(laporan["total_percent_covered"])


def _hilang(laporan: dict) -> dict[str, list[int]]:
    return {
        berkas: list(stat.get("violation_lines", []))
        for berkas, stat in sorted(laporan.get("src_stats", {}).items())
        if stat.get("violation_lines")
    }


def nilai(sisi: str, laporan_baris: dict, laporan_cabang: dict | None) -> Hasil:
    """Nilai JSON diff-cover (mode baris, dan mode cabang bila ada) terhadap ambang."""
    total = int(laporan_baris.get("total_num_lines", 0))
    baris = _persen(laporan_baris)
    cabang = None if laporan_cabang is None else _persen(laporan_cabang)
    pelanggaran: list[str] = []
    if baris < AMBANG_BARIS:
        hilang = int(laporan_baris.get("total_num_violations", 0))
        pelanggaran.append(
            f"{sisi}: cakupan BARIS pada baris yang diubah {baris:.2f}% < {AMBANG_BARIS:g}% "
            f"({hilang} dari {total} baris tak dieksekusi)"
        )
    if laporan_cabang is not None and cabang is not None and cabang < AMBANG_CABANG:
        hilang = int(laporan_cabang.get("total_num_violations", 0))
        pelanggaran.append(
            f"{sisi}: cakupan CABANG pada baris yang diubah {cabang:.2f}% < {AMBANG_CABANG:g}% "
            f"({hilang} dari {total} baris dengan cabang parsial atau tak dieksekusi)"
        )
    hilang_berkas = _hilang(laporan_cabang if laporan_cabang is not None else laporan_baris)
    return Hasil(sisi, total, baris, cabang, hilang_berkas, pelanggaran)


_CATATAN_CABANG = "cabang tidak didukung diff-cover untuk lcov; hanya baris yang dinilai"


def format_teks(hasil: list[Hasil], tambahan_gagal: Iterable[str] = ()) -> str:
    gagal = [*tambahan_gagal, *(p for h in hasil for p in h.pelanggaran)]
    judul = "GERBANG CAKUPAN DIFF GAGAL:" if gagal else "GERBANG CAKUPAN DIFF LOLOS"
    baris = [judul, *(f"  - {p}" for p in gagal)]
    for h in hasil:
        cabang = f"{h.cabang:.2f}%" if h.cabang is not None else f"- ({_CATATAN_CABANG})"
        baris.append(
            f"  {h.sisi}: {h.baris_total} baris terukur, baris {h.baris:.2f}%, cabang {cabang}"
        )
        for berkas, nomor in h.berkas_hilang.items():
            baris.append(f"    {berkas}: {rentang(nomor)}")
    if gagal:
        baris.append(
            "Tambahkan test perilaku untuk baris di atas (CONSTRAINTS.md bagian 6). Pengecualian "
            f"hanya lewat label '{LABEL_PENGECUALIAN}' dengan persetujuan pemilik (bagian 4)."
        )
    return "\n".join(baris)


def format_markdown(hasil: list[Hasil], catatan: list[str]) -> str:
    gagal = any(h.pelanggaran for h in hasil)
    md = [
        "## Gerbang cakupan diff (baris yang diubah)",
        "",
        f"Ambang: baris >= {AMBANG_BARIS:g}%, cabang >= {AMBANG_CABANG:g}% (backend). "
        f"Status: **{'GAGAL' if gagal else 'LOLOS'}**.",
        "",
    ]
    md += [f"- {c}" for c in catatan]
    if hasil:
        md += [
            "",
            "| Sisi | Baris terukur | Baris | Cabang | Status |",
            "| --- | --- | --- | --- | --- |",
        ]
        for h in hasil:
            cabang = f"{h.cabang:.2f}%" if h.cabang is not None else "tidak didukung (lcov)"
            status = "GAGAL" if h.pelanggaran else "LOLOS"
            md.append(f"| {h.sisi} | {h.baris_total} | {h.baris:.2f}% | {cabang} | {status} |")
        hilang = [(h.sisi, b, n) for h in hasil for b, n in h.berkas_hilang.items()]
        if hilang:
            md += ["", "Baris yang diubah tetapi belum tercakup:", ""]
            md += [f"- {s}: `{b}`: {rentang(n)}" for s, b, n in hilang]
        pelanggaran = [p for h in hasil for p in h.pelanggaran]
        if pelanggaran:
            md += ["", "Pelanggaran:", ""]
            md += [f"- **{p}**" for p in pelanggaran]
    return "\n".join(md) + "\n"


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
        ).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        raise GagalAlat(f"git {' '.join(args)}: {getattr(exc, 'stderr', '') or exc}") from exc


def _berubah(akar: Path, base: str) -> list[str]:
    titik = _git("merge-base", base, "HEAD", cwd=akar).strip()
    berubah = _git("diff", "--name-only", "--no-renames", titik, cwd=akar).splitlines()
    baru = _git("ls-files", "--others", "--exclude-standard", cwd=akar).splitlines()
    return [p for p in (*berubah, *baru) if p]


def _lcov_relatif_akar(teks: str, awalan: str) -> str:
    """Jadikan path ``SF:`` relatif lcov (Vitest: relatif ``frontend/``) relatif akar repo.

    diff-cover menafsirkan path SF relatif terhadap akar git, sedangkan Vitest menulisnya
    relatif terhadap direktori proyek frontend.
    """
    hasil = []
    for baris in teks.splitlines():
        if baris.startswith("SF:") and not Path(baris[3:]).is_absolute():
            baris = f"SF:{awalan}{baris[3:]}"
        hasil.append(baris)
    return "\n".join(hasil) + "\n"


def _diff_cover(laporan: Path, akar: Path, base: str, cabang: bool) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        keluaran = Path(tmp) / "diff-cover.json"
        if laporan.suffix == ".info":
            salinan = Path(tmp) / "lcov.info"
            teks = laporan.read_text(encoding="utf-8")
            salinan.write_text(_lcov_relatif_akar(teks, "frontend/"), encoding="utf-8")
            laporan = salinan
        perintah = [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            str(laporan),
            f"--compare-branch={base}",
            "--include-untracked",
            f"--format=json:{keluaran}",
            "--quiet",
        ]
        if cabang:
            perintah.append("--branch-coverage")
        proses = subprocess.run(perintah, cwd=akar, capture_output=True, text=True)
        if not keluaran.exists():
            raise GagalAlat(f"diff-cover gagal (exit {proses.returncode}): {proses.stderr.strip()}")
        return json.loads(keluaran.read_text(encoding="utf-8"))


def _tulis(path: str | None, teks: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(teks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerbang cakupan pada baris yang diubah.")
    parser.add_argument("--base", default="origin/main", help="ref dasar (default origin/main)")
    parser.add_argument("--sisi", nargs="+", choices=SISI, default=list(SISI))
    parser.add_argument("--backend-xml", default="coverage.xml", help="coverage.xml gabungan")
    parser.add_argument("--frontend-lcov", default="../frontend/coverage/lcov.info")
    parser.add_argument("--label", action="append", default=[], help="label PR (berulang)")
    parser.add_argument("--ringkasan", help="tambahkan ringkasan Markdown ke berkas ini")
    args = parser.parse_args(argv)

    laporan = {
        "backend": Path(args.backend_xml).resolve(),
        "frontend": Path(args.frontend_lcov).resolve(),
    }
    try:
        akar = Path(_git("rev-parse", "--show-toplevel").strip())
        kode = {s: f for s, f in kode_berubah(_berubah(akar, args.base)).items() if s in args.sisi}
        if not any(kode.values()):
            pesan = (
                "GERBANG CAKUPAN DIFF LOLOS — tidak ada perubahan kode produk "
                f"({', '.join(args.sisi)}); gerbang dilewati (dokumentasi/konfigurasi/test saja)."
            )
            print(pesan)
            _tulis(args.ringkasan, f"## Gerbang cakupan diff (baris yang diubah)\n\n{pesan}\n")
            return 0
        if LABEL_PENGECUALIAN in args.label:
            pesan = (
                f"GERBANG CAKUPAN DIFF DILEWATI — label PR '{LABEL_PENGECUALIAN}' "
                "(pengecualian disetujui pemilik, CONSTRAINTS.md bagian 4). "
                "Gerbang total tetap berlaku."
            )
            print(pesan)
            _tulis(args.ringkasan, f"## Gerbang cakupan diff (baris yang diubah)\n\n{pesan}\n")
            return 0

        hasil: list[Hasil] = []
        catatan: list[str] = []
        tidak_ada: list[str] = []
        for sisi, berkas in kode.items():
            if not berkas:
                catatan.append(f"{sisi}: tidak ada perubahan kode produk, dilewati.")
                continue
            if not laporan[sisi].is_file():
                tidak_ada.append(
                    f"laporan cakupan {sisi} tidak ditemukan ({laporan[sisi]}); job test/cakupan "
                    f"{sisi} gagal sebelum menghasilkan laporan? "
                    f"({len(berkas)} berkas kode berubah)"
                )
                continue
            json_baris = _diff_cover(laporan[sisi], akar, args.base, cabang=False)
            json_cabang = (
                _diff_cover(laporan[sisi], akar, args.base, cabang=True)
                if sisi == "backend"
                else None
            )
            if sisi == "frontend":
                catatan.append(f"frontend: {_CATATAN_CABANG}.")
            hasil.append(nilai(sisi, json_baris, json_cabang))
    except GagalAlat as exc:
        print(f"GERBANG CAKUPAN DIFF: gagal terhadap base '{args.base}': {exc}", file=sys.stderr)
        return 2

    print(format_teks(hasil, tidak_ada))
    _tulis(args.ringkasan, format_markdown(hasil, catatan + [f"**{t}**" for t in tidak_ada]))
    return 1 if tidak_ada or any(h.pelanggaran for h in hasil) else 0


if __name__ == "__main__":
    sys.exit(main())
