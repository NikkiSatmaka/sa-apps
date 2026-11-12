"""
Konfigurasi dan keputusan seleksi suite Drive live (#27) — logika MURNI, tanpa jaringan.

Suite live memanggil Google Drive NYATA, jadi hanya berjalan bila operator menyalakannya secara
eksplisit dengan `GDRIVE_LIVE_TEST=1`. Selain itu test-nya DIDESELECT (bukan skip: CONSTRAINTS.md
bagian 2 melarang skip tanpa issue) sehingga CI (`-m integration`) tidak pernah menyentuhnya.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

ENV_AKTIF = "GDRIVE_LIVE_TEST"
ENV_KUNCI = "GDRIVE_SERVICE_ACCOUNT_KEY"
ENV_TIMEOUT = "DRIVE_LIVE_TEST_TIMEOUT"
TIMEOUT_DEFAULT = 120.0

# Semua wajib bila GDRIVE_LIVE_TEST=1 (email = akun Google nyata milik tim uji).
ENV_WAJIB = (
    ENV_KUNCI,
    "DRIVE_LIVE_LEAD_EMAIL",
    "DRIVE_LIVE_SA_EMAIL",
    "DRIVE_LIVE_SALES_EMAIL",
    "DRIVE_LIVE_PMO_EMAIL",
    "DRIVE_LIVE_DELIVERY_EMAIL",
)


class KonfigurasiLiveError(Exception):
    """Konfigurasi suite live tidak lengkap/tidak valid; pesan menyebut env yang bermasalah."""


@dataclass(frozen=True)
class KonfigurasiLive:
    kunci_json: str
    kunci: dict
    email_lead: str
    email_sa: str
    email_sales: str
    email_pmo: str
    email_delivery: str
    timeout: float


def live_aktif(env: Mapping[str, str]) -> bool:
    """Suite live hanya aktif bila `GDRIVE_LIVE_TEST` persis `1`."""
    return env.get(ENV_AKTIF) == "1"


def pilih_deselect(item_live: Sequence[T], env: Mapping[str, str]) -> list[T]:
    """Item live yang harus dideselect: semuanya bila live tidak aktif, tidak ada bila aktif."""
    return [] if live_aktif(env) else list(item_live)


def _timeout(env: Mapping[str, str]) -> float:
    mentah = env.get(ENV_TIMEOUT, "").strip()
    if not mentah:
        return TIMEOUT_DEFAULT
    try:
        nilai = float(mentah)
    except ValueError:
        nilai = math.nan
    if not math.isfinite(nilai) or nilai <= 0:
        raise KonfigurasiLiveError(
            f"{ENV_TIMEOUT} harus angka detik > 0 (nilai sekarang tidak valid)."
        )
    return nilai


def _parse_kunci(mentah: str) -> dict:
    """Parse key JSON service account. Isi key TIDAK pernah dimasukkan ke pesan error."""
    try:
        kunci = json.loads(mentah)
    except json.JSONDecodeError:
        raise KonfigurasiLiveError(
            f"{ENV_KUNCI} bukan JSON valid. Isi dengan key service account dalam satu baris."
        ) from None
    if (
        not isinstance(kunci, dict)
        or kunci.get("type") != "service_account"
        or not kunci.get("client_email")
        or not kunci.get("private_key")
    ):
        raise KonfigurasiLiveError(
            f"{ENV_KUNCI} bukan key service account Google "
            "(wajib type=service_account, client_email, private_key)."
        )
    return kunci


def muat_konfigurasi(env: Mapping[str, str]) -> KonfigurasiLive:
    """Baca & validasi env suite live. Semua env kurang dilaporkan sekaligus."""
    kurang = [nama for nama in ENV_WAJIB if not env.get(nama, "").strip()]
    if kurang:
        raise KonfigurasiLiveError(
            f"{ENV_AKTIF}=1 tetapi env wajib belum di-set: {', '.join(kurang)}. "
            "Jalankan scripts/wizard-google-drive.sh atau lihat backend/README.md "
            "(bagian Verifikasi Drive live)."
        )
    mentah = env[ENV_KUNCI].strip()
    kunci = _parse_kunci(mentah)
    email = {nama: env[nama].strip() for nama in ENV_WAJIB if nama != ENV_KUNCI}
    _periksa_email_berbeda(email, kunci["client_email"])
    return KonfigurasiLive(
        kunci_json=mentah,
        kunci=kunci,
        email_lead=email["DRIVE_LIVE_LEAD_EMAIL"],
        email_sa=email["DRIVE_LIVE_SA_EMAIL"],
        email_sales=email["DRIVE_LIVE_SALES_EMAIL"],
        email_pmo=email["DRIVE_LIVE_PMO_EMAIL"],
        email_delivery=email["DRIVE_LIVE_DELIVERY_EMAIL"],
        timeout=_timeout(env),
    )


def _periksa_email_berbeda(email: Mapping[str, str], email_service_account: str) -> None:
    """
    Tiap peran harus akun berbeda dan bukan service account itu sendiri: bila dua peran memakai
    satu email, izin 'Sales tidak punya akses' tak bisa dibedakan dari izin peran lain.
    """
    terlihat: dict[str, str] = {}
    for nama, nilai in email.items():
        kunci = nilai.lower()
        if kunci == email_service_account.lower():
            raise KonfigurasiLiveError(
                f"{nama} tidak boleh sama dengan email service account itu sendiri."
            )
        if kunci in terlihat:
            raise KonfigurasiLiveError(
                f"Email tiap peran harus berbeda: {terlihat[kunci]} dan {nama} memakai email sama."
            )
        terlihat[kunci] = nama
