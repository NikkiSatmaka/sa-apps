"""Test skrip gerbang anti-pelemahan (scripts/gerbang_pelemahan.py), CONSTRAINTS.md bagian 2.

Fungsi inti diuji dengan diff sintetis (tanpa git); satu test integrasi kecil membuat repo git
sementara untuk ``main()``. Token yang dideteksi gerbang dirangkai dari potongan string agar
berkas test ini sendiri tidak memicu gerbang saat barisnya ditambahkan ke sebuah PR.
"""

import subprocess
import textwrap

import pytest

from scripts import gerbang_pelemahan as g

# Token terlarang dirangkai (lihat docstring modul).
SKIP = "pytest.mark." + "skip"
SKIPIF = "pytest.mark." + 'skipif(sys.platform == "win32", reason="x")'
XFAIL = "pytest.mark." + "xfail"
PYTEST_SKIP_CALL = "pytest." + 'skip("x")'
PYTEST_XFAIL_CALL = "pytest." + 'xfail("x")'
PRAGMA = "# prag" + "ma: no cover"
V8 = "/* v" + "8 ignore"
C8 = "/* c" + "8 ignore"


def _diff(path, baris_baru, *, sebelum=None, mulai=10):
    """Diff unified sintetis: satu hunk, ``sebelum`` = baris konteks tepat di atas."""
    konteks = [] if sebelum is None else [" " + sebelum]
    awal = mulai - len(konteks)
    isi = konteks + ["+" + b for b in baris_baru]
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -{awal},{len(konteks)} +{awal},{len(isi)} @@\n" + "\n".join(isi) + "\n"
    )


PY_TEST = "backend/tests/test_x.py"
TS_TEST = "frontend/src/lib/x.test.ts"


# --- Aturan 2: skip/xfail tanpa issue -------------------------------------------------


@pytest.mark.parametrize(
    "baris",
    [
        "@" + SKIP,
        "@" + SKIPIF,
        "@" + XFAIL,
        "    " + PYTEST_SKIP_CALL,
        "    " + PYTEST_XFAIL_CALL,
    ],
)
def test_skip_pytest_tanpa_issue_memicu(baris):
    v = g.periksa_diff(_diff(PY_TEST, [baris], mulai=7))
    assert len(v) == 1
    assert v[0].startswith(f"{PY_TEST}:7: skip-tanpa-issue — ")


@pytest.mark.parametrize(
    "baris",
    [
        "it." + 'skip("a", () => {});',
        "describe." + 'skip("a", () => {});',
        "test." + 'skip("a", () => {});',
        "it." + 'todo("a");',
        "it." + 'fails("a", () => {});',
        "it." + 'skipIf(cond)("a", () => {});',
    ],
)
def test_skip_vitest_tanpa_issue_memicu(baris):
    v = g.periksa_diff(_diff(TS_TEST, [baris], mulai=3))
    assert len(v) == 1
    assert v[0].startswith(f"{TS_TEST}:3: skip-tanpa-issue — ")


def test_skip_dengan_issue_di_baris_yang_sama_tidak_memicu():
    assert g.periksa_diff(_diff(PY_TEST, ["@" + SKIP + '(reason="tunggu #123")'])) == []
    assert g.periksa_diff(_diff(TS_TEST, ["it." + 'skip("a", () => {}); // #45'])) == []


def test_skip_dengan_issue_di_komentar_atasnya_tidak_memicu():
    assert g.periksa_diff(_diff(PY_TEST, ["@" + SKIP], sebelum="# Menunggu #77")) == []
    assert g.periksa_diff(_diff(TS_TEST, ["it." + 'todo("a");'], sebelum="// lihat #9")) == []


def test_issue_di_baris_kode_atasnya_bukan_komentar_tidak_menyelamatkan():
    v = g.periksa_diff(_diff(PY_TEST, ["@" + SKIP], sebelum='x = "#12"'))
    assert len(v) == 1


def test_skip_di_baris_lama_tidak_memicu():
    # Baris konteks / dihapus tidak dinilai; hanya baris yang ditambah.
    diff = (
        f"diff --git a/{PY_TEST} b/{PY_TEST}\n--- a/{PY_TEST}\n+++ b/{PY_TEST}\n"
        "@@ -5,3 +5,2 @@\n"
        f" @{SKIP}\n"
        f"-@{XFAIL}\n"
        "+def test_baru(): ...\n"
    )
    assert g.periksa_diff(diff) == []


def test_skip_di_berkas_non_test_diabaikan():
    assert g.periksa_diff(_diff("backend/app/x.py", ["@" + SKIP])) == []


def test_berkas_dihapus_diabaikan():
    diff = (
        f"diff --git a/{PY_TEST} b/{PY_TEST}\ndeleted file mode 100644\n"
        f"--- a/{PY_TEST}\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-@{SKIP}\n"
    )
    assert g.periksa_diff(diff) == []


# --- Aturan 3: pragma / v8 ignore tanpa alasan ----------------------------------------


def test_pragma_tanpa_alasan_memicu():
    v = g.periksa_diff(_diff("backend/app/x.py", ["    return 1  " + PRAGMA], mulai=4))
    assert len(v) == 1
    assert v[0].startswith("backend/app/x.py:4: pragma-tanpa-alasan — ")


def test_pragma_dengan_alasan_sesudahnya_tidak_memicu():
    assert (
        g.periksa_diff(_diff("backend/app/x.py", ["    x()  " + PRAGMA + " — jalur OS lain"])) == []
    )


def test_pragma_dengan_komentar_alasan_di_atasnya_tidak_memicu():
    d = _diff(
        "backend/app/x.py", ["    x()  " + PRAGMA], sebelum="    # Hanya dijalankan di Windows"
    )
    assert g.periksa_diff(d) == []


def test_pragma_dengan_baris_atas_bukan_komentar_memicu():
    d = _diff("backend/app/x.py", ["    x()  " + PRAGMA], sebelum="    y = 1")
    assert len(g.periksa_diff(d)) == 1


def test_pragma_lama_tidak_memicu():
    diff = (
        "diff --git a/backend/app/x.py b/backend/app/x.py\n--- a/backend/app/x.py\n"
        "+++ b/backend/app/x.py\n@@ -1,2 +1,3 @@\n"
        f" x()  {PRAGMA}\n+y = 2\n z = 3\n"
    )
    assert g.periksa_diff(diff) == []


@pytest.mark.parametrize("awal", [V8, C8])
def test_ignore_v8_c8_tanpa_alasan_memicu(awal):
    for isi in (f"{awal} next */", f"{awal} start */", f"{awal} file */"):
        v = g.periksa_diff(_diff("frontend/src/a.ts", [isi]))
        assert len(v) == 1, isi
        assert "pragma-tanpa-alasan" in v[0]


def test_ignore_v8_dengan_alasan_tidak_memicu():
    assert g.periksa_diff(_diff("frontend/src/a.ts", [V8 + " next -- cabang SSR */"])) == []
    d = _diff("frontend/src/a.ts", [V8 + " next */"], sebelum="// Hanya di server")
    assert g.periksa_diff(d) == []


# --- Aturan 1: ambang cakupan ---------------------------------------------------------

PYPROJECT = textwrap.dedent(
    """\
    [tool.coverage.report]
    fail_under = {n}
    show_missing = true
    """
)
VITEST = textwrap.dedent(
    """\
    export default {{
      test: {{ coverage: {{
        thresholds: {{ lines: {l}, branches: {b} }},
      }} }},
    }};
    """
)


def test_ambang_pyproject_turun_memicu():
    v = g.periksa_ambang("backend/pyproject.toml", PYPROJECT.format(n=90), PYPROJECT.format(n=85))
    assert len(v) == 1
    assert v[0].startswith("backend/pyproject.toml:2: ambang-cakupan — ")
    assert "90" in v[0] and "85" in v[0]


def test_ambang_pyproject_naik_atau_tetap_tidak_memicu():
    n90 = PYPROJECT.format(n=90)
    assert g.periksa_ambang("backend/pyproject.toml", n90, PYPROJECT.format(n=95)) == []
    assert g.periksa_ambang("backend/pyproject.toml", n90, n90) == []


def test_ambang_dihapus_memicu():
    v = g.periksa_ambang("backend/pyproject.toml", PYPROJECT.format(n=90), "[tool.x]\na = 1\n")
    assert len(v) == 1 and "dihapus" in v[0]


def test_ambang_vitest_turun_memicu_per_kunci():
    v = g.periksa_ambang(
        "frontend/vitest.config.mts", VITEST.format(l=90, b=80), VITEST.format(l=80, b=70)
    )
    assert len(v) == 2
    assert all("ambang-cakupan" in x for x in v)


def test_ambang_vitest_naik_tidak_memicu():
    assert (
        g.periksa_ambang(
            "frontend/vitest.config.mts", VITEST.format(l=90, b=80), VITEST.format(l=95, b=85)
        )
        == []
    )


def test_ambang_ci_fail_under_turun_memicu():
    base = "run: pytest --cov-fail-under=90\n"
    v = g.periksa_ambang(".github/workflows/ci.yml", base, "run: pytest --cov-fail-under=80\n")
    assert len(v) == 1 and v[0].startswith(".github/workflows/ci.yml:1: ambang-cakupan")


def test_ambang_konstanta_skrip_gerbang_turun_memicu():
    base = "AMBANG_BARIS = 90.0\nAMBANG_CABANG = 80.0\n"
    head = "AMBANG_BARIS = 90.0\nAMBANG_CABANG = 70.0\n"
    v = g.periksa_ambang("backend/scripts/cakupan_gerbang.py", base, head)
    assert len(v) == 1 and "AMBANG_CABANG" in v[0]


def test_ambang_berkas_baru_atau_tak_dikenal_tidak_memicu():
    assert g.periksa_ambang("backend/pyproject.toml", None, PYPROJECT.format(n=10)) == []
    assert g.periksa_ambang("README.md", "fail_under = 90", "fail_under = 10") == []


# --- Aturan 3b: perluasan omit / exclude ----------------------------------------------

OMIT = textwrap.dedent(
    """\
    [tool.coverage.run]
    omit = [
        "alembic/*",
    {extra}]
    """
)
EXCLUDE = textwrap.dedent(
    """\
    export default {{
      test: {{ coverage: {{
        exclude: ["src/test/**"{extra}],
      }} }},
    }};
    """
)


def test_omit_entri_baru_memicu():
    head = OMIT.format(extra='    "app/besar.py",\n')
    v = g.periksa_ambang("backend/pyproject.toml", OMIT.format(extra=""), head)
    assert len(v) == 1
    assert "pengecualian-cakupan" in v[0] and "app/besar.py" in v[0]
    assert v[0].startswith("backend/pyproject.toml:4:")


def test_omit_tetap_atau_berkurang_tidak_memicu():
    base = OMIT.format(extra='    "app/besar.py",\n')
    assert g.periksa_ambang("backend/pyproject.toml", base, base) == []
    assert g.periksa_ambang("backend/pyproject.toml", base, OMIT.format(extra="")) == []


def test_omit_toml_rusak_tidak_meledak():
    assert g.periksa_ambang("backend/pyproject.toml", OMIT.format(extra=""), "bukan [toml") == []


def test_exclude_vitest_entri_baru_memicu():
    head = EXCLUDE.format(extra=', "src/app/**"')
    v = g.periksa_ambang("frontend/vitest.config.mts", EXCLUDE.format(extra=""), head)
    assert len(v) == 1
    assert "pengecualian-cakupan" in v[0] and "src/app/**" in v[0]


def test_exclude_vitest_tetap_tidak_memicu():
    base = EXCLUDE.format(extra="")
    assert g.periksa_ambang("frontend/vitest.config.mts", base, base) == []


# --- main() dengan repo git sementara -------------------------------------------------


def _git(cwd, *args):
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(cwd),
        "PATH": __import__("os").environ["PATH"],
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "backend/tests").mkdir(parents=True)
    (tmp_path / "backend/tests/test_a.py").write_text("def test_a():\n    assert 1\n")
    (tmp_path / "backend/pyproject.toml").write_text(PYPROJECT.format(n=90))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "fitur")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_lolos_pada_perubahan_sah(repo, capsys):
    (repo / "backend/tests/test_a.py").write_text(
        "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"
    )
    (repo / "backend/pyproject.toml").write_text(PYPROJECT.format(n=95))
    _git(repo, "commit", "-q", "-am", "ok")
    assert g.main(["--base", "main"]) == 0
    assert "GERBANG PELEMAHAN LOLOS" in capsys.readouterr().out


def test_main_gagal_pada_skip_dan_ambang_turun(repo, capsys):
    (repo / "backend/tests/test_a.py").write_text(f"@{SKIP}\ndef test_a():\n    assert 1\n")
    (repo / "backend/pyproject.toml").write_text(PYPROJECT.format(n=50))
    _git(repo, "commit", "-q", "-am", "lemah")
    assert g.main(["--base", "main"]) == 1
    err = capsys.readouterr().err
    assert "backend/tests/test_a.py:1: skip-tanpa-issue" in err
    assert "backend/pyproject.toml:2: ambang-cakupan" in err


def test_main_tidak_menilai_skip_lama(repo, capsys):
    # Skip sudah ada di base; PR hanya menambah test lain.
    (repo / "backend/tests/test_a.py").write_text(f"@{SKIP}\ndef test_a():\n    assert 1\n")
    _git(repo, "commit", "-q", "-am", "skip lama")
    _git(repo, "branch", "-f", "main", "HEAD")
    (repo / "backend/tests/test_a.py").write_text(
        f"@{SKIP}\ndef test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"
    )
    _git(repo, "commit", "-q", "-am", "tambah")
    assert g.main(["--base", "main"]) == 0


def test_main_base_tidak_dikenal_keluar_2(repo, capsys):
    assert g.main(["--base", "tidak-ada"]) == 2
    assert "GERBANG PELEMAHAN" in capsys.readouterr().err
