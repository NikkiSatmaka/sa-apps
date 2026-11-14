"""Test skrip gerbang cakupan diff (scripts/gerbang_cakupan_diff.py), tiket #98.

Fungsi inti (klasifikasi path, penilaian ambang) diuji dengan data sintetis. ``main()`` diuji
di repo git sementara dengan laporan cakupan sintetis (Cobertura XML untuk backend, lcov untuk
frontend) dan ``diff-cover`` sungguhan, sehingga pencocokan path laporan <-> diff ikut teruji.
"""

import os
import subprocess

import pytest

from scripts import cakupan_gerbang
from scripts import gerbang_cakupan_diff as g

# ---------------------------------------------------------------------------
# kode_berubah: lewati otomatis berdasarkan path
# ---------------------------------------------------------------------------


def test_kode_berubah_hanya_menghitung_kode_produk():
    hasil = g.kode_berubah(
        [
            "backend/app/core/status.py",
            "backend/app/api/v1/x.py",
            "backend/app/README.md",  # bukan .py
            "backend/tests/test_x.py",
            "backend/alembic/versions/001_x.py",  # omit cakupan (CONSTRAINTS.md bagian 3)
            "backend/scripts/seed_demo_data.py",  # omit cakupan
            "backend/pyproject.toml",
            "frontend/src/lib/x.ts",
            "frontend/src/components/y.tsx",
            "frontend/src/lib/x.test.ts",  # berkas test
            "frontend/src/components/y.test.tsx",
            "frontend/src/test/setup.ts",  # utilitas test
            "frontend/src/types/z.d.ts",  # deklarasi tipe
            "frontend/src/app/globals.css",
            "frontend/scripts/cakupan-ringkasan.mjs",
            "frontend/vitest.config.mts",
            "docs/ROADMAP.md",
            ".github/workflows/ci.yml",
        ]
    )
    assert hasil == {
        "backend": ["backend/app/api/v1/x.py", "backend/app/core/status.py"],
        "frontend": ["frontend/src/components/y.tsx", "frontend/src/lib/x.ts"],
    }


def test_kode_berubah_kosong_untuk_dokumentasi_dan_konfigurasi():
    assert g.kode_berubah(["README.md", "CONSTRAINTS.md", "mise.toml"]) == {
        "backend": [],
        "frontend": [],
    }


# ---------------------------------------------------------------------------
# nilai: penilaian ambang dari JSON diff-cover
# ---------------------------------------------------------------------------


def _laporan(total, hilang, berkas=None):
    persen = 100 if total == 0 else 100 * (total - hilang) / total
    return {
        "total_num_lines": total,
        "total_num_violations": hilang,
        "total_percent_covered": persen,
        "src_stats": berkas or {},
    }


def test_ambang_sama_dengan_gerbang_total():
    assert g.AMBANG_BARIS == cakupan_gerbang.AMBANG_BARIS == 90.0
    assert g.AMBANG_CABANG == cakupan_gerbang.AMBANG_CABANG == 80.0


def test_nilai_lolos_tepat_di_ambang():
    h = g.nilai("backend", _laporan(10, 1), _laporan(10, 2))
    assert h.baris == pytest.approx(90.0)
    assert h.cabang == pytest.approx(80.0)
    assert h.pelanggaran == []


def test_nilai_gagal_bila_baris_di_bawah_ambang():
    berkas = {"app/x.py": {"percent_covered": 50.0, "violation_lines": [3, 4]}}
    h = g.nilai("backend", _laporan(4, 2, berkas), _laporan(4, 2, berkas))
    assert len(h.pelanggaran) == 2
    assert "BARIS" in h.pelanggaran[0] and "50.00% < 90%" in h.pelanggaran[0]
    assert "CABANG" in h.pelanggaran[1]
    assert h.berkas_hilang == {"app/x.py": [3, 4]}


def test_nilai_gagal_bila_hanya_cabang_di_bawah_ambang():
    h = g.nilai("backend", _laporan(10, 0), _laporan(10, 3))
    assert h.pelanggaran == [
        "backend: cakupan CABANG pada baris yang diubah 70.00% < 80% (3 dari 10 baris "
        "dengan cabang parsial atau tak dieksekusi)"
    ]


def test_nilai_tanpa_baris_terukur_dianggap_lolos():
    h = g.nilai("frontend", _laporan(0, 0), None)
    assert h.baris == 100.0
    assert h.cabang is None
    assert h.pelanggaran == []


def test_nilai_frontend_tanpa_cabang_tidak_memalsukan_angka():
    h = g.nilai("frontend", _laporan(10, 0), None)
    assert h.cabang is None
    assert "tidak didukung" in g.format_teks([h]).lower()


def test_format_markdown_memuat_tabel_dan_baris_hilang():
    berkas = {"src/lib/x.ts": {"percent_covered": 0.0, "violation_lines": [7]}}
    md = g.format_markdown([g.nilai("frontend", _laporan(1, 1, berkas), None)], catatan=[])
    assert "## Gerbang cakupan diff" in md
    assert "| frontend |" in md
    assert "`src/lib/x.ts`: 7" in md
    assert "GAGAL" in md


def test_rentang_baris_diringkas():
    assert g.rentang([3, 4, 5, 9, 11, 12]) == "3-5, 9, 11-12"


# ---------------------------------------------------------------------------
# main: repo git sementara + diff-cover sungguhan
# ---------------------------------------------------------------------------


def _git(cwd, *args):
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(cwd),
        "PATH": os.environ["PATH"],
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


BASE_PY = "A = 1\n"
FITUR_PY = "A = 1\n\n\ndef f(x):\n    if x:\n        return 1\n    return 2\n"


def _cobertura(root, hits, cabang=None):
    """Cobertura XML sintetis untuk ``backend/app/x.py``; ``hits`` = {nomor_baris: hit}."""
    baris = []
    for nomor, hit in sorted(hits.items()):
        attr = ""
        if cabang and nomor in cabang:
            attr = f' branch="true" condition-coverage="{cabang[nomor]}"'
        baris.append(f'<line number="{nomor}" hits="{hit}"{attr}/>')
    return (
        '<?xml version="1.0" ?>\n<coverage version="7" line-rate="1" branch-rate="1">'
        f"<sources><source>{root}/backend/app</source></sources><packages>"
        '<package name="." line-rate="1" branch-rate="1"><classes>'
        '<class name="x.py" filename="x.py" line-rate="1" branch-rate="1">'
        f"<methods/><lines>{''.join(baris)}</lines></class>"
        "</classes></package></packages></coverage>\n"
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/app/x.py").write_text(BASE_PY)
    (tmp_path / "frontend/src/lib").mkdir(parents=True)
    (tmp_path / "frontend/src/lib/y.ts").write_text("export const a = 1;\n")
    (tmp_path / ".gitignore").write_text("*.xml\n*.info\n*.md.out\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "fitur")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit_fitur_backend(repo):
    (repo / "backend/app/x.py").write_text(FITUR_PY)
    _git(repo, "commit", "-q", "-am", "fitur")


def test_main_docs_only_lolos_tanpa_laporan(repo, capsys):
    (repo / "README.md").write_text("dok\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "docs")
    assert g.main(["--base", "main"]) == 0
    out = capsys.readouterr().out
    assert "LOLOS" in out and "dilewati" in out


def test_main_gagal_pada_baris_baru_tak_teruji(repo, capsys):
    _commit_fitur_backend(repo)
    (repo / "cov.xml").write_text(_cobertura(repo, {1: 1, 4: 1, 5: 0, 6: 0, 7: 0}))
    assert g.main(["--base", "main", "--sisi", "backend", "--backend-xml", "cov.xml"]) == 1
    out = capsys.readouterr().out
    assert "GAGAL" in out
    assert "app/x.py: 5-7" in out
    assert "25.00% < 90%" in out


def test_main_gagal_pada_cabang_parsial(repo, capsys):
    _commit_fitur_backend(repo)
    xml = _cobertura(repo, {1: 1, 4: 1, 5: 1, 6: 1, 7: 1}, cabang={5: "50% (1/2)", 6: "0% (0/2)"})
    (repo / "cov.xml").write_text(xml)
    assert g.main(["--base", "main", "--sisi", "backend", "--backend-xml", "cov.xml"]) == 1
    out = capsys.readouterr().out
    assert "CABANG" in out and "50.00% < 80%" in out
    assert "BARIS pada baris yang diubah 100.00%" not in out  # baris lolos, tidak dilaporkan


def test_main_lolos_bila_tercakup_dan_menulis_ringkasan(repo, capsys):
    _commit_fitur_backend(repo)
    (repo / "cov.xml").write_text(_cobertura(repo, {1: 1, 4: 1, 5: 1, 6: 1, 7: 1}))
    argv = ["--base", "main", "--backend-xml", "cov.xml", "--ringkasan", "ringkas.md.out"]
    assert g.main(argv) == 0
    assert "LOLOS" in capsys.readouterr().out
    md = (repo / "ringkas.md.out").read_text()
    assert "| backend | 4 | 100.00% | 100.00% |" in md


def test_main_label_pengecualian_melewati_gerbang(repo, capsys):
    _commit_fitur_backend(repo)
    argv = ["--base", "main", "--label", "lain", "--label", g.LABEL_PENGECUALIAN]
    assert g.main(argv) == 0
    out = capsys.readouterr().out
    assert g.LABEL_PENGECUALIAN in out and "DILEWATI" in out


def test_main_gagal_bila_laporan_tidak_ada(repo, capsys):
    _commit_fitur_backend(repo)
    assert g.main(["--base", "main", "--backend-xml", "tidak-ada.xml"]) == 1
    assert "laporan cakupan backend tidak ditemukan" in capsys.readouterr().out


def test_main_sisi_lain_tidak_dinilai(repo, capsys):
    # Perubahan backend tidak menuntut laporan bila hanya sisi frontend yang diminta.
    _commit_fitur_backend(repo)
    assert g.main(["--base", "main", "--sisi", "frontend"]) == 0
    assert "dilewati" in capsys.readouterr().out


def test_main_frontend_lcov_tak_teruji_gagal(repo, capsys):
    (repo / "frontend/src/lib/y.ts").write_text(
        "export const a = 1;\nexport function b() {\n  return 2;\n}\n"
    )
    _git(repo, "commit", "-q", "-am", "fe")
    (repo / "lcov.info").write_text(
        "TN:\nSF:src/lib/y.ts\nDA:1,1\nDA:2,1\nDA:3,0\nLF:3\nLH:2\nend_of_record\n"
    )
    assert g.main(["--base", "main", "--frontend-lcov", "lcov.info"]) == 1
    out = capsys.readouterr().out
    assert "src/lib/y.ts: 3" in out
    assert "tidak didukung" in out.lower()


def test_main_menilai_perubahan_belum_di_commit(repo, capsys):
    # Lokal: perubahan working tree (termasuk berkas untracked) ikut dinilai.
    (repo / "backend/app/baru.py").write_text("def g():\n    return 1\n")
    assert g.main(["--base", "main", "--backend-xml", "tidak-ada.xml"]) == 1
    assert "tidak ditemukan" in capsys.readouterr().out


def test_main_base_tidak_dikenal_keluar_2(repo, capsys):
    assert g.main(["--base", "tidak-ada"]) == 2
    assert "GERBANG CAKUPAN DIFF" in capsys.readouterr().err
