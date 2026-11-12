"""
Bukti end-to-end (proses pytest terpisah, TANPA jaringan) bahwa suite Drive live aman:

- tanpa `GDRIVE_LIVE_TEST=1`, test live DIDESELECT (bukan skip/error), termasuk saat CI memakai
  `-m integration`;
- dengan `GDRIVE_LIVE_TEST=1` namun kredensial kurang, pengumpulan berhenti dengan error konfigurasi
  yang menyebut env yang kurang;
- dengan env lengkap, `--collect-only -m drive_live` menampilkan skenario.

Hanya `--collect-only` yang dijalankan sehingga tidak ada panggilan Drive/DB.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DIR_LIVE = "tests/integration/drive_live"

KUNCI = json.dumps(
    {
        "type": "service_account",
        "client_email": "uji@p.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
    }
)
ENV_LENGKAP = {
    "GDRIVE_LIVE_TEST": "1",
    "GDRIVE_SERVICE_ACCOUNT_KEY": KUNCI,
    "DRIVE_LIVE_LEAD_EMAIL": "lead@uji.test",
    "DRIVE_LIVE_SA_EMAIL": "sa@uji.test",
    "DRIVE_LIVE_SALES_EMAIL": "sales@uji.test",
    "DRIVE_LIVE_PMO_EMAIL": "pmo@uji.test",
    "DRIVE_LIVE_DELIVERY_EMAIL": "delivery@uji.test",
}


def _pytest(*args: str, env_tambahan: dict[str, str] | None = None):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GDRIVE_", "DRIVE_LIVE_", "COV_CORE", "COVERAGE", "PYTEST_ADDOPTS"))
    }
    env.update(env_tambahan or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--no-cov", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _node_live(keluaran: str) -> list[str]:
    return [b for b in keluaran.splitlines() if "drive_live/" in b and "::" in b]


def test_tanpa_env_default_test_live_dideselect_bukan_skip_atau_error():
    hasil = _pytest("-q", "-W", "ignore", DIR_LIVE)

    assert hasil.returncode == 5, hasil.stdout + hasil.stderr  # tidak ada test terpilih
    assert "deselected" in hasil.stdout
    assert "skipped" not in hasil.stdout and "error" not in hasil.stdout.lower()


def test_tanpa_env_marker_integration_di_ci_tidak_menjalankan_test_live():
    hasil = _pytest("-q", "-W", "ignore", "--collect-only", "-m", "integration", DIR_LIVE)

    assert _node_live(hasil.stdout) == [], hasil.stdout
    assert "deselected" in hasil.stdout


def test_tanpa_env_marker_drive_live_eksplisit_tetap_dideselect():
    hasil = _pytest("-q", "-W", "ignore", "--collect-only", "-m", "drive_live", DIR_LIVE)

    assert _node_live(hasil.stdout) == [], hasil.stdout
    assert "deselected" in hasil.stdout


def test_env_aktif_tanpa_kredensial_error_konfigurasi_jelas():
    hasil = _pytest(
        "-q",
        "-W",
        "ignore",
        "--collect-only",
        "-m",
        "drive_live",
        DIR_LIVE,
        env_tambahan={"GDRIVE_LIVE_TEST": "1"},
    )

    keluaran = hasil.stdout + hasil.stderr
    assert hasil.returncode != 0
    assert "GDRIVE_SERVICE_ACCOUNT_KEY" in keluaran
    assert "DRIVE_LIVE_SALES_EMAIL" in keluaran
    assert "Traceback" not in keluaran


def test_env_aktif_namun_marker_lain_tidak_memaksa_kredensial():
    # Operator yang meng-export GDRIVE_LIVE_TEST=1 tetap bisa menjalankan test unit biasa.
    hasil = _pytest(
        "-q",
        "-W",
        "ignore",
        "tests/test_drive_live_helper.py",
        env_tambahan={"GDRIVE_LIVE_TEST": "1"},
    )

    assert hasil.returncode == 0, hasil.stdout + hasil.stderr


def test_env_lengkap_collect_only_menampilkan_semua_skenario():
    hasil = _pytest(
        "-q",
        "-W",
        "ignore",
        "--collect-only",
        "-m",
        "drive_live",
        DIR_LIVE,
        env_tambahan=ENV_LENGKAP,
    )

    assert hasil.returncode == 0, hasil.stdout + hasil.stderr
    nodes = _node_live(hasil.stdout)
    for fragmen in (
        "test_provisioning_live.py::test_struktur_master_dan_izin_awal",
        "test_provisioning_live.py::test_unlock_lalu_lock_solutions_untuk_sales",
        "test_provisioning_live.py::test_lock_tanpa_akses_sales_adalah_noop",
        "test_provisioning_live.py::test_handover_final_deliverables_di_solutions",
        "test_provisioning_live.py::test_email_tidak_valid_gagal_setelah_retry",
        "test_api_live.py::test_assign_membuat_tree_asli_dan_menyimpan_id",
        "test_api_live.py::test_sla_lock_lalu_dq_membuka_solutions",
        "test_api_live.py::test_doc_reviewed_dengan_dq_membuka_solutions_untuk_sales",
        "test_api_live.py::test_doc_reviewed_tanpa_dq_solutions_tetap_tertutup",
    ):
        assert any(fragmen in n for n in nodes), (fragmen, hasil.stdout)
