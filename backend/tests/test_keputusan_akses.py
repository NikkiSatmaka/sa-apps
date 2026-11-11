"""
Unit test tabel-kasus untuk titik keputusan akses proyek (tiket #88, spec #87).

Dua lapis yang diuji lewat antarmuka publik `app.core.dependencies`:
- `izinkan(hubungan, tingkat)` — fungsi murni: hubungan user ke proyek × tingkat → boleh/tidak.
- `hubungan_proyek` / `ensure_project_access` — membaca relasi dari DB (sesi palsu) lalu memutuskan.

Matriks yang dikunci mengikuti spec #87 ("akses proyek" = Lead_SA, Admin, Sales PIC,
SA ditugaskan, collaborator; `viewer` hanya baca).
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.dependencies import (
    HubunganProyek,
    TingkatAkses,
    ensure_project_access,
    hubungan_proyek,
    izinkan,
)
from tests._auth_support import SesiPalsu, user_palsu

PESAN_403 = "Anda tidak memiliki akses ke proyek ini."

LEAD = HubunganProyek(privileged=True)
ADMIN = HubunganProyek(privileged=True)
SALES_PIC = HubunganProyek(sales_pic=True)
SA_DITUGASKAN = HubunganProyek(sa_ditugaskan=True)
KOLAB_VIEWER = HubunganProyek(kolaborator="viewer")
KOLAB_CONTRIB = HubunganProyek(kolaborator="contributor")
PIHAK_LUAR = HubunganProyek()

# (nama hubungan, hubungan) — baris tabel
HUBUNGAN = {
    "privileged": LEAD,
    "sales_pic": SALES_PIC,
    "sa_ditugaskan": SA_DITUGASKAN,
    "kolab_viewer": KOLAB_VIEWER,
    "kolab_contributor": KOLAB_CONTRIB,
    "pihak_luar": PIHAK_LUAR,
}

# tingkat → himpunan hubungan yang BOLEH (sumber kebenaran: matriks spec #87)
MATRIKS = {
    TingkatAkses.BACA: {
        "privileged",
        "sales_pic",
        "sa_ditugaskan",
        "kolab_viewer",
        "kolab_contributor",
    },
    # Story/ringkasan AI: Sales PIC tidak boleh
    TingkatAkses.STORY: {
        "privileged",
        "sa_ditugaskan",
        "kolab_viewer",
        "kolab_contributor",
    },
    # Tulis activity log / map kalender / unggah dokumen: viewer & Sales PIC tidak
    TingkatAkses.TULIS: {"privileged", "sa_ditugaskan", "kolab_contributor"},
    # PATCH proyek: seperti sekarang + viewer ditolak
    TingkatAkses.UBAH_PROYEK: {
        "privileged",
        "sales_pic",
        "sa_ditugaskan",
        "kolab_contributor",
    },
    # Majukan status dokumen: Lead_SA, Admin, SA ditugaskan
    TingkatAkses.KELOLA: {"privileged", "sa_ditugaskan"},
    # Isi DQ Number: Sales PIC, Lead_SA, Admin
    TingkatAkses.ISI_DQ: {"privileged", "sales_pic"},
    # Tambah collaborator: Lead_SA, Admin, SA ditugaskan, Sales PIC
    TingkatAkses.TAMBAH_KOLABORATOR: {"privileged", "sales_pic", "sa_ditugaskan"},
}

KASUS = [
    pytest.param(nama, tingkat, nama in boleh, id=f"{nama}-{tingkat.value}")
    for tingkat, boleh in MATRIKS.items()
    for nama in HUBUNGAN
]


def test_setiap_tingkat_punya_baris_matriks():
    assert set(MATRIKS) == set(TingkatAkses)


@pytest.mark.parametrize(("nama", "tingkat", "diharapkan"), KASUS)
def test_izinkan_sesuai_matriks(nama, tingkat, diharapkan):
    assert izinkan(HUBUNGAN[nama], tingkat) is diharapkan


def test_tingkat_default_adalah_baca():
    assert izinkan(SALES_PIC) is True
    assert izinkan(PIHAK_LUAR) is False


def test_pertanyaan_khusus_pada_hubungan():
    assert SALES_PIC.sales_pic and not SALES_PIC.sa_ditugaskan
    assert SA_DITUGASKAN.sa_ditugaskan and not SA_DITUGASKAN.sales_pic
    assert KOLAB_VIEWER.adalah_viewer and not KOLAB_VIEWER.adalah_contributor
    assert KOLAB_CONTRIB.adalah_contributor and not KOLAB_CONTRIB.adalah_viewer
    assert not PIHAK_LUAR.adalah_viewer and not PIHAK_LUAR.adalah_contributor


# --------------------------------------------------------------------------- hubungan_proyek


def _proyek(sales_pic=None, assigned_sa=None) -> SimpleNamespace:
    return SimpleNamespace(
        id_project="PRJ-1", sales_pic=sales_pic or uuid.uuid4(), assigned_sa=assigned_sa
    )


@pytest.mark.parametrize("role", ["Lead_SA", "Admin"])
async def test_hubungan_privileged_menurut_peran(role):
    h = await hubungan_proyek(SesiPalsu(None), _proyek(), user_palsu(role))
    assert h.privileged is True


@pytest.mark.parametrize("role", ["Sales", "SA"])
async def test_peran_non_privileged_tidak_privileged(role):
    h = await hubungan_proyek(SesiPalsu(None), _proyek(), user_palsu(role))
    assert h == PIHAK_LUAR


async def test_hubungan_dicocokkan_lewat_id_bukan_peran():
    """User ber-peran Sales yang kebetulan `assigned_sa` tetap dihitung SA ditugaskan."""
    user = user_palsu("Sales")
    h = await hubungan_proyek(SesiPalsu(None), _proyek(assigned_sa=user.id), user)
    assert h.sa_ditugaskan is True and h.sales_pic is False


async def test_hubungan_sales_pic():
    user = user_palsu("Sales")
    h = await hubungan_proyek(SesiPalsu(None), _proyek(sales_pic=user.id), user)
    assert h.sales_pic is True


@pytest.mark.parametrize("peran", ["viewer", "contributor"])
async def test_hubungan_membaca_peran_collaborator(peran):
    user = user_palsu("SA")
    kolab = SimpleNamespace(user_id=user.id, role=peran)
    h = await hubungan_proyek(SesiPalsu(kolab), _proyek(), user)
    assert h.kolaborator == peran


async def test_assigned_sa_kosong_tidak_cocok_dengan_user_mana_pun():
    h = await hubungan_proyek(SesiPalsu(None), _proyek(assigned_sa=None), user_palsu("SA"))
    assert h.sa_ditugaskan is False


# --------------------------------------------------------------------------- ensure_project_access


async def test_ensure_default_baca_menolak_pihak_luar():
    with pytest.raises(HTTPException) as exc:
        await ensure_project_access(SesiPalsu(None), _proyek(), user_palsu("SA"))
    assert exc.value.status_code == 403
    assert exc.value.detail == PESAN_403


@pytest.mark.parametrize("tingkat", list(TingkatAkses))
async def test_ensure_pesan_403_generik_untuk_semua_tingkat(tingkat):
    """Pesan sama di semua tingkat agar alasan penolakan tidak bocor."""
    with pytest.raises(HTTPException) as exc:
        await ensure_project_access(SesiPalsu(None), _proyek(), user_palsu("SA"), tingkat=tingkat)
    assert exc.value.status_code == 403
    assert exc.value.detail == PESAN_403


async def test_ensure_viewer_boleh_baca_tapi_ditolak_tulis():
    user = user_palsu("SA")
    kolab = SimpleNamespace(user_id=user.id, role="viewer")
    await ensure_project_access(SesiPalsu(kolab), _proyek(), user)
    await ensure_project_access(SesiPalsu(kolab), _proyek(), user, tingkat=TingkatAkses.STORY)
    with pytest.raises(HTTPException) as exc:
        await ensure_project_access(SesiPalsu(kolab), _proyek(), user, tingkat=TingkatAkses.TULIS)
    assert exc.value.status_code == 403
    assert exc.value.detail == PESAN_403


async def test_ensure_contributor_boleh_tulis():
    user = user_palsu("SA")
    kolab = SimpleNamespace(user_id=user.id, role="contributor")
    await ensure_project_access(SesiPalsu(kolab), _proyek(), user, tingkat=TingkatAkses.TULIS)


async def test_ensure_sales_pic_ditolak_story_tapi_boleh_baca():
    user = user_palsu("Sales")
    proyek = _proyek(sales_pic=user.id)
    await ensure_project_access(SesiPalsu(None), proyek, user)
    with pytest.raises(HTTPException):
        await ensure_project_access(SesiPalsu(None), proyek, user, tingkat=TingkatAkses.STORY)
