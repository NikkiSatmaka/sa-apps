"""
Logika murni permission & penamaan folder uji untuk suite Drive live (#27).

Definisi "akses efektif" (dipakai semua assertion live):
    Peran efektif user U pada folder F = peran TERTINGGI di antara semua permission `type=user`
    dengan `emailAddress == U` pada F ATAU pada salah satu leluhur F (master, dst.).
    Alasannya: Drive mewarisi permission folder ke anak-anaknya, dan `permissions.list` pada
    folder anak tidak dijamin menampilkan permission turunan (permissionDetails hanya terisi
    untuk shared drive). Karena itu verifikasi TIDAK bergantung pada daftar izin satu folder,
    melainkan menggabungkan izin seluruh rantai leluhur. Permission `type=anyone` (link publik)
    dihitung sebagai akses terbuka (opsi `hitung_publik`) agar kebocoran lewat link tertangkap.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Urut naik menurut hak.
URUTAN_PERAN = ("reader", "commenter", "writer", "fileOrganizer", "organizer", "owner")

AWALAN_SAPUAN = "[LIVE-TEST"


def peran_tertinggi(peran: Iterable[str]) -> str | None:
    """Peran dengan hak terbesar, atau None bila kosong. Peran tak dikenal → ValueError."""
    tertinggi = -1
    for p in peran:
        if p not in URUTAN_PERAN:
            raise ValueError(f"peran Drive tidak dikenal: {p}")
        tertinggi = max(tertinggi, URUTAN_PERAN.index(p))
    return URUTAN_PERAN[tertinggi] if tertinggi >= 0 else None


def peran_efektif(
    izin_per_leluhur: Iterable[Iterable[Mapping[str, Any]]],
    email: str,
    *,
    hitung_publik: bool = False,
) -> str | None:
    """Peran efektif `email` dari izin folder + semua leluhurnya (lihat docstring modul)."""
    target = email.lower()
    cocok: list[str] = []
    for izin_folder in izin_per_leluhur:
        for izin in izin_folder:
            tipe = izin.get("type")
            if tipe == "user" and str(izin.get("emailAddress", "")).lower() == target:
                cocok.append(izin["role"])
            elif tipe == "anyone" and hitung_publik:
                cocok.append(izin["role"])
    return peran_tertinggi(cocok)


def awalan_uji(uid: str) -> str:
    """Awalan nama folder uji, mis. `[LIVE-TEST ab12] ` (mudah dikenali & disapu)."""
    return f"{AWALAN_SAPUAN} {uid}] "


def nama_uji(uid: str, nama: str) -> str:
    return f"{awalan_uji(uid)}{nama}"


def milik_sapuan(nama: str) -> bool:
    """Apakah nama folder berawalan `[LIVE-TEST` (sisa uji yang boleh disapu)."""
    return nama.startswith(AWALAN_SAPUAN)
