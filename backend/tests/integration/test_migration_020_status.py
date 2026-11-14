"""
Migration 020 (issue #121, ADR 0013): enum `status` baru + `qualification_state`,
`previous_status`, `lost_reason` pada `projects`.

Memakai database sementara per test (`database_kosong_url`) karena mengubah versi skema.
Yang diuji: pemetaan data lama ke baru (upgrade), pemetaan balik (downgrade, lossy),
dan constraint pada skema head.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _head, _sql, _versi

REVISI_BARU = "020"
REVISI_LAMA = "019"

# (status lama, status baru, qualification_state baru), sesuai tabel pemetaan ADR 0013.
PEMETAAN_UPGRADE = [
    ("New", "Intake", "Scoring"),
    ("Scoring Pending", "Intake", "Scoring"),
    ("Need Clarification", "Intake", "Need Clarification"),
    ("Manual Review Required", "Intake", "Manual Review"),
    ("Pending Assignment", "Awaiting Assignment", "Qualified"),
    ("Assigned", "Assigned", "Qualified"),
    ("Ready", "Submitted", "Qualified"),
    ("Closed-Win", "Won", "Qualified"),
    ("Handover Complete", "Handed Over", "Qualified"),
    ("Lost", "Lost", "Qualified"),
]

# (status baru, qualification_state, status lama hasil downgrade).
PEMETAAN_DOWNGRADE = [
    ("Intake", "Scoring", "Scoring Pending"),
    ("Intake", "Need Clarification", "Need Clarification"),
    ("Intake", "Manual Review", "Manual Review Required"),
    ("Awaiting Assignment", "Qualified", "Pending Assignment"),
    ("Assigned", "Qualified", "Assigned"),
    ("In Progress", "Qualified", "Assigned"),
    ("Submitted", "Qualified", "Ready"),
    ("Won", "Qualified", "Closed-Win"),
    ("Handed Over", "Qualified", "Handover Complete"),
    ("Closed", "Qualified", "Handover Complete"),
]


def _user(url: str) -> str:
    user_id = str(uuid.uuid4())
    _sql(
        url,
        "INSERT INTO users (id, email, name, role, google_id) "
        "VALUES (:id, :email, 'u', 'Product', :gid)",
        {"id": user_id, "email": f"{user_id}@mig.test", "gid": f"g-{user_id}"},
    )
    return user_id


def _proyek(url: str, user: str, id_project: str, status: str, **kolom) -> str:
    nama = ["id_project", "project_name", "customer_name", "created_by", "product_pic"]
    nama += ["target_submit", "status", *kolom]
    nilai = {
        "id_project": id_project,
        "project_name": "P",
        "customer_name": "C",
        "created_by": user,
        "product_pic": user,
        "target_submit": date(2030, 1, 1),
        "status": status,
        **kolom,
    }
    _sql(
        url,
        f"INSERT INTO projects ({', '.join(nama)}) VALUES ({', '.join(f':{n}' for n in nama)})",
        nilai,
    )
    return id_project


def _baris(url: str, id_project: str, *kolom: str):
    return _sql(
        url,
        f"SELECT {', '.join(kolom)} FROM projects WHERE id_project = :id",
        {"id": id_project},
    )[0]


def test_revisi_020_adalah_head(database_kosong_url):
    jalankan_alembic(database_kosong_url, "upgrade", "head")

    assert _versi(database_kosong_url) == _head() == REVISI_BARU


@pytest.mark.parametrize(("lama", "baru", "state"), PEMETAAN_UPGRADE)
def test_upgrade_memetakan_status_lama_ke_status_dan_qualification_state(
    database_kosong_url, lama, baru, state
):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    user = _user(url)
    _proyek(url, user, "PRJ-MIG", lama)

    jalankan_alembic(url, "upgrade", "head")

    status, qualification_state, previous_status = _baris(
        url, "PRJ-MIG", "status", "qualification_state", "previous_status"
    )
    assert (status, qualification_state, previous_status) == (baru, state, None)


def test_upgrade_status_lost_lama_mendapat_lost_reason_pengganti(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    _proyek(url, _user(url), "PRJ-LOST", "Lost")

    jalankan_alembic(url, "upgrade", "head")

    (alasan,) = _baris(url, "PRJ-LOST", "lost_reason")
    assert alasan and alasan.strip()  # memenuhi constraint; alasan asli tidak pernah tercatat


def test_upgrade_status_non_lost_tidak_mengisi_lost_reason(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    _proyek(url, _user(url), "PRJ-A", "Assigned")

    jalankan_alembic(url, "upgrade", "head")

    assert _baris(url, "PRJ-A", "lost_reason") == (None,)


def test_upgrade_tanpa_data_dan_banyak_proyek_sekaligus(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    user = _user(url)
    for i, (lama, _, _) in enumerate(PEMETAAN_UPGRADE):
        _proyek(url, user, f"PRJ-{i}", lama)

    jalankan_alembic(url, "upgrade", "head")

    hasil = [
        _baris(url, f"PRJ-{i}", "status", "qualification_state")
        for i in range(len(PEMETAAN_UPGRADE))
    ]
    assert hasil == [(baru, state) for _, baru, state in PEMETAAN_UPGRADE]


def test_head_kolom_baru_default_dan_nullable(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    user = _user(url)

    _sql(
        url,
        "INSERT INTO projects (id_project, project_name, customer_name, created_by, "
        "product_pic, target_submit) VALUES ('PRJ-DEF', 'P', 'C', :u, :u, :t)",
        {"u": user, "t": date(2030, 1, 1)},
    )

    assert _baris(
        url, "PRJ-DEF", "status", "qualification_state", "previous_status", "lost_reason"
    ) == ("Intake", "Scoring", None, None)


@pytest.mark.parametrize("lama", [p[0] for p in PEMETAAN_UPGRADE])
def test_head_menolak_nama_status_lama(database_kosong_url, lama):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    with pytest.raises(DBAPIError, match="chk_projects_status"):
        _proyek(url, _user(url), "PRJ-LAMA", lama)


@pytest.mark.parametrize(
    "baru",
    [
        "Intake",
        "Awaiting Assignment",
        "Assigned",
        "In Progress",
        "Submitted",
        "Won",
        "Handed Over",
        "Closed",
        "On Hold",
    ],
)
def test_head_menerima_status_baru(database_kosong_url, baru):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    _proyek(url, _user(url), "PRJ-BARU", baru)

    assert _baris(url, "PRJ-BARU", "status") == (baru,)


@pytest.mark.parametrize("alasan", [None, "", "   "])
def test_head_lost_tanpa_lost_reason_ditolak(database_kosong_url, alasan):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    with pytest.raises(DBAPIError, match="chk_projects_lost_reason"):
        _proyek(url, _user(url), "PRJ-L", "Lost", lost_reason=alasan)


def test_head_lost_dengan_lost_reason_dan_previous_status_diterima(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    _proyek(
        url, _user(url), "PRJ-L", "Lost", lost_reason="Kalah tender", previous_status="Submitted"
    )

    assert _baris(url, "PRJ-L", "status", "lost_reason", "previous_status") == (
        "Lost",
        "Kalah tender",
        "Submitted",
    )


def test_head_qualification_state_tidak_valid_ditolak(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    with pytest.raises(DBAPIError, match="chk_projects_qualification_state"):
        _proyek(url, _user(url), "PRJ-Q", "Intake", qualification_state="Manual Review Required")


@pytest.mark.parametrize("nilai", ["On Hold", "Lost", "Ready", ""])
def test_head_previous_status_tidak_valid_ditolak(database_kosong_url, nilai):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    with pytest.raises(DBAPIError, match="chk_projects_previous_status"):
        _proyek(url, _user(url), "PRJ-P", "Assigned", previous_status=nilai)


@pytest.mark.parametrize(("baru", "state", "lama"), PEMETAAN_DOWNGRADE)
def test_downgrade_memetakan_balik_ke_status_lama(database_kosong_url, baru, state, lama):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    _proyek(url, _user(url), "PRJ-D", baru, qualification_state=state)

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _versi(url) == REVISI_LAMA
    assert _baris(url, "PRJ-D", "status") == (lama,)


def test_downgrade_lost_tetap_lost_dan_on_hold_kembali_ke_status_sebelumnya(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    user = _user(url)
    _proyek(url, user, "PRJ-L", "Lost", lost_reason="x", qualification_state="Qualified")
    _proyek(
        url,
        user,
        "PRJ-H",
        "On Hold",
        previous_status="Submitted",
        qualification_state="Qualified",
    )
    _proyek(url, user, "PRJ-H2", "On Hold", qualification_state="Qualified")  # tanpa riwayat

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _baris(url, "PRJ-L", "status") == ("Lost",)
    assert _baris(url, "PRJ-H", "status") == ("Ready",)
    assert _baris(url, "PRJ-H2", "status") == ("Pending Assignment",)


def test_downgrade_membuang_kolom_baru_memulihkan_constraint_dan_default_lama(
    database_kosong_url,
):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")

    jalankan_alembic(url, "downgrade", REVISI_LAMA)

    assert _sql(
        url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'projects' "
        "AND column_name IN ('qualification_state', 'previous_status', 'lost_reason')",
    ) == []
    user = _user(url)
    with pytest.raises(DBAPIError, match="chk_projects_status"):
        _proyek(url, user, "PRJ-X", "Intake")
    _proyek(url, user, "PRJ-OK", "Ready")
    _sql(
        url,
        "INSERT INTO projects (id_project, project_name, customer_name, created_by, "
        "product_pic, target_submit) VALUES ('PRJ-DEF', 'P', 'C', :u, :u, :t)",
        {"u": user, "t": date(2030, 1, 1)},
    )
    assert _baris(url, "PRJ-DEF", "status") == ("New",)


def test_upgrade_downgrade_upgrade_menjaga_data_yang_dapat_dipetakan(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", REVISI_LAMA)
    user = _user(url)
    for i, (lama, _, _) in enumerate(PEMETAAN_UPGRADE):
        _proyek(url, user, f"PRJ-{i}", lama)

    jalankan_alembic(url, "upgrade", "head")
    jalankan_alembic(url, "downgrade", REVISI_LAMA)
    jalankan_alembic(url, "upgrade", "head")

    hasil = [
        _baris(url, f"PRJ-{i}", "status", "qualification_state")
        for i in range(len(PEMETAAN_UPGRADE))
    ]
    assert hasil == [(baru, state) for _, baru, state in PEMETAAN_UPGRADE]
    assert _versi(url) == _head()
