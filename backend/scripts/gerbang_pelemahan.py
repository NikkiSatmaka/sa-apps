"""Gerbang anti-pelemahan berbasis diff (CONSTRAINTS.md bagian 2, butir 1, 2, dan 4).

Memeriksa HANYA perubahan sebuah PR (``git diff <base>...HEAD``); kode lama yang sudah memuat
skip/pragma tidak dinilai. Yang dideteksi:

* ``ambang-cakupan``: ambang cakupan turun atau dihapus (``fail_under``, ``--cov-fail-under``,
  ``coverage.thresholds`` vitest, konstanta ``AMBANG_*`` di ``cakupan_gerbang.py``).
* ``skip-tanpa-issue``: skip/skipif/xfail (pytest) atau skip/todo/fails/skipIf (vitest) yang
  ditambah di berkas test tanpa referensi issue ``#<angka>`` (baris itu atau komentar di atasnya).
* ``pragma-tanpa-alasan``: pragma "no cover" (coverage.py) atau ignore v8/c8 tanpa alasan
  (teks sesudahnya atau komentar di baris sebelumnya).
* ``pengecualian-cakupan``: entri baru di ``omit`` (backend) atau ``coverage.exclude`` (frontend).

Melemahkan assertion TIDAK dideteksi: itu penilaian, tetap lewat review manual.

Pemakaian (dari ``backend/``)::

    uv run python scripts/gerbang_pelemahan.py --base origin/main

Kode keluar 0 bila lolos, 1 bila ada pelanggaran, 2 bila git/masukan gagal. Hanya perubahan
yang SUDAH di-commit (``base...HEAD``) yang dinilai.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass

# Berkas yang diperiksa untuk aturan ambang/pengecualian (nama dasar berkas).
BERKAS_KONFIG = ("pyproject.toml", "vitest.config.mts", "ci.yml", "cakupan_gerbang.py")

_RE_ISSUE = re.compile(r"#\d+")
_RE_SKIP_PY = re.compile(r"pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.(?:skip|xfail)\(")
_RE_SKIP_TS = re.compile(r"\b(?:it|describe|test)\.(?:skip|todo|fails|skipIf)\b")
_RE_PRAGMA = re.compile(r"#\s*pragma:\s*no\s+cover\b(.*)")
_RE_V8 = re.compile(r"(?:/\*|//)\s*[vc]8\s+ignore\b(.*)")
_RE_V8_KATA = re.compile(r"^\s*(?:next|start|stop|if|else|file)\b(?:\s+\d+)?")
_RE_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_RE_FAIL_UNDER = re.compile(r"fail[-_]under\s*[=:]?\s*(\d+(?:\.\d+)?)")
_RE_AMBANG_KONSTANTA = re.compile(r"^(AMBANG_\w+)\s*=\s*(\d+(?:\.\d+)?)", re.MULTILINE)
_RE_THRESHOLDS = re.compile(r"thresholds\s*:\s*\{([^}]*)\}")
_RE_THRESHOLD_KUNCI = re.compile(r"(\w+)\s*:\s*(\d+(?:\.\d+)?)")
_RE_EXCLUDE = re.compile(r"exclude\s*:\s*\[([^\]]*)\]")
_RE_STRING = re.compile(r"""["']([^"']+)["']""")


@dataclass(frozen=True)
class BarisTambah:
    berkas: str
    nomor: int
    teks: str
    sebelumnya: str | None  # baris tepat di atasnya pada berkas baru (konteks/tambahan)


def _baris_tambah(diff: str) -> Iterator[BarisTambah]:
    """Urai unified diff; hasilkan hanya baris yang DITAMBAH beserta baris di atasnya."""
    berkas: str | None = None
    di_hunk = False
    nomor = 0
    sebelumnya: str | None = None
    for mentah in diff.splitlines():
        if mentah.startswith("diff --git "):
            berkas, di_hunk = None, False
            continue
        if not di_hunk:
            if mentah.startswith("+++ "):
                tujuan = mentah[4:]
                berkas = None if tujuan == "/dev/null" else tujuan.removeprefix("b/")
                continue
        if (m := _RE_HUNK.match(mentah)) is not None:
            di_hunk, nomor, sebelumnya = True, int(m.group(1)), None
            continue
        if not di_hunk or berkas is None:
            continue
        if mentah.startswith("+"):
            yield BarisTambah(berkas, nomor, mentah[1:], sebelumnya)
            sebelumnya = mentah[1:]
            nomor += 1
        elif mentah.startswith(" "):
            sebelumnya = mentah[1:]
            nomor += 1
        # Baris "-" (dihapus) dan "\ No newline" tidak menggeser nomor baris baru.


def _berkas_test(path: str) -> str | None:
    """Kembalikan 'py'/'ts' bila ``path`` berkas test, selain itu None."""
    if path.endswith(".py") and re.search(r"(?:^|/)tests?/", path):
        return "py"
    if re.search(r"\.(?:test|spec)\.[mc]?[jt]sx?$", path) or re.search(
        r"(?:^|/)(?:test|tests|__tests__)/.*\.[mc]?[jt]sx?$", path
    ):
        return "ts"
    return None


def _komentar(baris: str | None) -> bool:
    return baris is not None and baris.lstrip().startswith(("#", "//", "/*", "*"))


def _punya_alasan(sisa: str, sebelumnya: str | None) -> bool:
    return bool(sisa.strip(" \t-—–:#*/")) or _komentar(sebelumnya)


def _periksa_baris(b: BarisTambah) -> Iterator[str]:
    awal = f"{b.berkas}:{b.nomor}:"
    jenis = _berkas_test(b.berkas)
    pola = {"py": _RE_SKIP_PY, "ts": _RE_SKIP_TS}.get(jenis or "")
    if pola is not None and pola.search(b.teks):
        ada_issue = _RE_ISSUE.search(b.teks) or (
            _komentar(b.sebelumnya) and _RE_ISSUE.search(b.sebelumnya or "")
        )
        if not ada_issue:
            yield (
                f"{awal} skip-tanpa-issue — skip/xfail/todo baru wajib menautkan issue "
                "terbuka (#<nomor>) di baris itu atau komentar di atasnya"
            )
    if (m := _RE_PRAGMA.search(b.teks)) is not None and not _punya_alasan(m.group(1), b.sebelumnya):
        yield f"{awal} pragma-tanpa-alasan — pragma 'no cover' wajib disertai alasan"
    if (m := _RE_V8.search(b.teks)) is not None:
        sisa = _RE_V8_KATA.sub("", m.group(1), count=1).replace("@preserve", "")
        if not _punya_alasan(sisa, b.sebelumnya):
            yield f"{awal} pragma-tanpa-alasan — ignore v8/c8 wajib disertai alasan"


def periksa_diff(diff: str) -> list[str]:
    """Pelanggaran aturan berbasis baris pada baris yang ditambah (``berkas:baris: aturan — …``)."""
    return [v for b in _baris_tambah(diff) for v in _periksa_baris(b)]


def _nomor_baris(teks: str, posisi: int) -> int:
    return teks.count("\n", 0, posisi) + 1


def _ambang(nama: str, teks: str) -> dict[str, tuple[float, int]]:
    """Peta kunci -> (nilai, nomor baris) untuk setiap ambang cakupan yang dikenali."""
    hasil: dict[str, tuple[float, int]] = {}
    if nama in ("pyproject.toml", "ci.yml"):
        for i, m in enumerate(_RE_FAIL_UNDER.finditer(teks)):
            hasil[f"fail_under[{i}]"] = (float(m.group(1)), _nomor_baris(teks, m.start(1)))
    elif nama == "vitest.config.mts":
        for blok in _RE_THRESHOLDS.finditer(teks):
            for k in _RE_THRESHOLD_KUNCI.finditer(blok.group(1)):
                pos = blok.start(1) + k.start(2)
                hasil[f"thresholds.{k.group(1)}"] = (float(k.group(2)), _nomor_baris(teks, pos))
    elif nama == "cakupan_gerbang.py":
        for m in _RE_AMBANG_KONSTANTA.finditer(teks):
            hasil[m.group(1)] = (float(m.group(2)), _nomor_baris(teks, m.start(2)))
    return hasil


def _pengecualian(nama: str, teks: str) -> dict[str, int]:
    """Peta entri omit/exclude -> nomor baris (kosong bila tak berlaku atau TOML rusak)."""
    if nama == "pyproject.toml":
        try:
            data = tomllib.loads(teks)
        except tomllib.TOMLDecodeError:
            return {}
        cov = data.get("tool", {}).get("coverage", {})
        entri = [*cov.get("run", {}).get("omit", []), *cov.get("report", {}).get("omit", [])]
        return {e: _nomor_baris(teks, max(teks.find(f'"{e}"'), 0)) for e in entri}
    if nama == "vitest.config.mts":
        awal = teks.find("coverage")
        hasil: dict[str, int] = {}
        for blok in _RE_EXCLUDE.finditer(teks, max(awal, 0)):
            for s in _RE_STRING.finditer(blok.group(1)):
                hasil[s.group(1)] = _nomor_baris(teks, blok.start(1) + s.start(1))
        return hasil
    return {}


def periksa_ambang(berkas: str, base: str | None, head: str | None) -> list[str]:
    """Bandingkan ambang dan pengecualian cakupan di ``berkas`` antara base dan head.

    ``base``/``head`` None (berkas baru/dihapus) atau nama berkas tak dikenal = tidak dinilai.
    """
    nama = berkas.rsplit("/", 1)[-1]
    if base is None or head is None or nama not in BERKAS_KONFIG:
        return []
    hasil: list[str] = []
    ambang_head = _ambang(nama, head)
    for kunci, (nilai_base, _) in _ambang(nama, base).items():
        if kunci not in ambang_head:
            hasil.append(f"{berkas}:1: ambang-cakupan — ambang {kunci} ({nilai_base:g}) dihapus")
            continue
        nilai_head, baris = ambang_head[kunci]
        if nilai_head < nilai_base:
            hasil.append(
                f"{berkas}:{baris}: ambang-cakupan — ambang {kunci} turun dari "
                f"{nilai_base:g} ke {nilai_head:g}"
            )
    entri_base = _pengecualian(nama, base)
    for entri, baris in _pengecualian(nama, head).items():
        if entri not in entri_base:
            hasil.append(
                f"{berkas}:{baris}: pengecualian-cakupan — entri baru '{entri}' di daftar "
                "omit/exclude cakupan (perlu persetujuan, CONSTRAINTS.md bagian 4)"
            )
    return hasil


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _isi(ref: str, path: str) -> str | None:
    try:
        return _git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerbang anti-pelemahan berbasis diff.")
    parser.add_argument("--base", default="origin/main", help="ref dasar (default origin/main)")
    args = parser.parse_args(argv)
    try:
        akar = _git("rev-parse", "--show-toplevel").strip()
        titik = _git("merge-base", args.base, "HEAD").strip()
        diff = _git("-C", akar, "diff", "--unified=1", "--no-color", "--no-ext-diff", titik, "HEAD")
        berubah = _git("-C", akar, "diff", "--name-only", titik, "HEAD").splitlines()
        pelanggaran = periksa_diff(diff)
        for path in berubah:
            if path.rsplit("/", 1)[-1] in BERKAS_KONFIG:
                pelanggaran += periksa_ambang(path, _isi(titik, path), _isi("HEAD", path))
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        print(
            f"GERBANG PELEMAHAN: git gagal terhadap base '{args.base}': {detail}", file=sys.stderr
        )
        return 2

    if pelanggaran:
        print("GERBANG PELEMAHAN GAGAL — perubahan melemahkan kontrak kualitas:", file=sys.stderr)
        for p in pelanggaran:
            print(f"  - {p}", file=sys.stderr)
        print(
            "Perbaiki (tautkan issue / beri alasan / pertahankan ambang) atau minta persetujuan "
            "pemilik produk — CONSTRAINTS.md bagian 2 dan 4.",
            file=sys.stderr,
        )
        return 1
    print("GERBANG PELEMAHAN LOLOS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
