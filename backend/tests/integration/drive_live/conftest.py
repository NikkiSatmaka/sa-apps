"""
Fixture & seleksi suite Drive LIVE (#27). Test di folder ini memanggil Google Drive NYATA.

Keamanan:
- Hanya berjalan bila `GDRIVE_LIVE_TEST=1`; selain itu semua test di folder ini DIDESELECT
  (bukan skip) oleh hook di bawah — termasuk saat CI memakai `-m integration`.
- Bila `GDRIVE_LIVE_TEST=1` tetapi env kurang/tidak valid, pengumpulan berhenti dengan error
  konfigurasi yang menyebut env yang kurang (tanpa membocorkan isi key).
- Semua folder uji berawalan `[LIVE-TEST <uuid>] `, dihapus di teardown meski test gagal, dan
  sisa sesi sebelumnya disapu di awal sesi.

Cara menjalankan: backend/README.md, bagian "Verifikasi Drive live".
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.drive_live.izin import AWALAN_SAPUAN, awalan_uji
from tests.integration.drive_live.konfigurasi import (
    KonfigurasiLive,
    KonfigurasiLiveError,
    live_aktif,
    muat_konfigurasi,
    pilih_deselect,
)
from tests.integration.drive_live.verifikator import Verifikator, bangun_service

FOLDER_INI = Path(__file__).parent


# trylast: jalan SETELAH seleksi `-m` bawaan, sehingga hanya test live yang benar-benar terpilih
# yang memicu validasi env; operator yang meng-export GDRIVE_LIVE_TEST=1 tetap bisa menjalankan
# test lain tanpa kredensial.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = [i for i in items if Path(str(i.path)).is_relative_to(FOLDER_INI)]
    dibuang = pilih_deselect(live, os.environ)
    if dibuang:
        items[:] = [i for i in items if i not in dibuang]
        config.hook.pytest_deselected(items=dibuang)
        return
    if live and live_aktif(os.environ):
        try:
            muat_konfigurasi(os.environ)
        except KonfigurasiLiveError as e:
            raise pytest.UsageError(f"Konfigurasi suite Drive live: {e}") from None


# --------------------------------------------------------------------------- konfigurasi & klien


@pytest.fixture(scope="session")
def konfigurasi_live() -> KonfigurasiLive:
    try:
        return muat_konfigurasi(os.environ)
    except KonfigurasiLiveError as e:
        pytest.fail(f"Konfigurasi suite Drive live: {e}", pytrace=False)


@pytest.fixture(scope="session")
def verifikator(konfigurasi_live: KonfigurasiLive) -> Verifikator:
    """Klien Drive MILIK TEST (terpisah dari kode produksi) untuk membaca hasil sebenarnya."""
    return Verifikator(bangun_service(konfigurasi_live.kunci))


@pytest.fixture(scope="session", autouse=True)
def _sapu_sisa_uji_sebelumnya(verifikator: Verifikator) -> None:
    """Awal sesi: hapus folder `[LIVE-TEST...` milik service account sisa sesi yang terputus."""
    verifikator.hapus_berprefiks(AWALAN_SAPUAN)


# --------------------------------------------------------------------------- per test


@pytest.fixture
def uid_uji() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def awalan(uid_uji: str) -> str:
    return awalan_uji(uid_uji)


@pytest.fixture
def pembersih(verifikator: Verifikator, awalan: str) -> Iterator[list[str]]:
    """
    Daftar id folder yang harus dihapus. Teardown SELALU berjalan (juga saat test gagal) dan
    menyapu semua folder berawalan unik test ini, termasuk sisa provisioning yang gagal sebagian.
    """
    ids: list[str] = []
    yield ids
    galat: list[str] = []
    for file_id in ids:
        try:
            verifikator.hapus(file_id)
        except Exception as e:  # noqa: BLE001 - coba semua dulu, laporkan di akhir
            galat.append(f"{file_id}: {e}")
    try:
        verifikator.hapus_berprefiks(awalan)
    except Exception as e:  # noqa: BLE001
        galat.append(f"sapuan {awalan!r}: {e}")
    if galat:
        pytest.fail("Pembersihan folder uji Drive gagal: " + "; ".join(galat), pytrace=False)


@pytest.fixture
def provisioner(konfigurasi_live: KonfigurasiLive, monkeypatch: pytest.MonkeyPatch):
    """`folder_provisioner` ASLI (bukan fake) dengan key uji; klien Drive-nya dibangun ulang."""
    from app.core.config import settings
    from app.services.folder_provisioner import folder_provisioner

    monkeypatch.setattr(settings, "GDRIVE_SERVICE_ACCOUNT_KEY", konfigurasi_live.kunci_json)
    monkeypatch.setattr(folder_provisioner, "_drive_service", None)
    return folder_provisioner
