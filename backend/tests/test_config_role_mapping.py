"""
Validasi `ROLE_MAPPING` saat `Settings()` dibuat (fail-fast; tiket #80).

Nilai peran di luar {Sales, Product, SA, Lead_SA} melanggar CHECK `chk_users_role` saat user baru
disimpan dan membuat login 500. Konfigurasi seperti itu harus menghentikan startup dengan pesan
jelas, bukan baru meledak saat login pertama user.
"""

import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(monkeypatch, nilai: str) -> Settings:
    monkeypatch.setenv("ROLE_MAPPING", nilai)
    return Settings(_env_file=None)


@pytest.mark.parametrize(
    "peran",
    ["Superuser", "admin", "Admin", "SALES", "Lead SA", "", " SA"],
    ids=["asing", "huruf-kecil", "admin-bukan-role", "kapital", "spasi", "kosong", "spasi-depan"],
)
def test_peran_tidak_valid_menghentikan_startup_dan_menyebut_entrinya(monkeypatch, peran):
    mapping = json.dumps({"a@b.com": "Lead_SA", "*@b.com": peran})

    with pytest.raises(ValidationError) as exc:
        _settings(monkeypatch, mapping)

    pesan = str(exc.value)
    assert "ROLE_MAPPING" in pesan
    assert "*@b.com" in pesan
    assert "Sales, Product, SA, Lead_SA" in pesan


def test_semua_entri_tidak_valid_dilaporkan_sekaligus(monkeypatch):
    mapping = json.dumps({"a@b.com": "Superuser", "c@d.com": "Root", "e@f.com": "SA"})

    with pytest.raises(ValidationError) as exc:
        _settings(monkeypatch, mapping)

    # `str(ValidationError)` ikut memuat nilai input mentah; periksa hanya pesan validator.
    pesan = exc.value.errors()[0]["msg"]
    assert "a@b.com" in pesan and "Superuser" in pesan
    assert "c@d.com" in pesan and "Root" in pesan
    assert "e@f.com" not in pesan


@pytest.mark.parametrize("nilai", [1, None, ["SA"], {"r": "SA"}, True])
def test_nilai_peran_bukan_string_ditolak(monkeypatch, nilai):
    with pytest.raises(ValidationError):
        _settings(monkeypatch, json.dumps({"a@b.com": nilai}))


@pytest.mark.parametrize("peran", ["Sales", "Product", "SA", "Lead_SA"])
def test_peran_valid_diterima_dan_nilai_mentah_tidak_diubah(monkeypatch, peran):
    mentah = json.dumps({"*@b.com": peran})

    assert _settings(monkeypatch, mentah).ROLE_MAPPING == mentah


@pytest.mark.parametrize("mentah", ["", "{}", "bukan json", "[1, 2]", '"teks"', "null"])
def test_kosong_rusak_atau_bukan_objek_tetap_diterima_seperti_sebelumnya(monkeypatch, mentah):
    """
    compose.yaml meneruskan `ROLE_MAPPING: ${ROLE_MAPPING:-}` (string kosong) dan
    `AuthService.role_mapping` sengaja menganggap JSON rusak/non-objek sebagai mapping kosong
    (lihat test_auth_service). Validasi baru hanya memeriksa NILAI PERAN pada objek.
    """
    assert _settings(monkeypatch, mentah).ROLE_MAPPING == mentah


def test_default_diterima():
    assert Settings(_env_file=None).ROLE_MAPPING == "{}"
