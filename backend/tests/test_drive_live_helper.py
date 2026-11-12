"""
Unit test helper murni suite Drive live (#27): keputusan deselect, pemuatan konfigurasi env,
perhitungan peran efektif, penamaan folder uji, dan klien verifikasi (dengan service palsu).

Test ini TIDAK memanggil jaringan/Drive. Isi suite live itu sendiri (`tests/integration/drive_live/`)
hanya berjalan dengan `GDRIVE_LIVE_TEST=1` dan kredensial uji; helper-nya diuji di sini.
"""

import json

import pytest

from tests.integration.drive_live.izin import (
    AWALAN_SAPUAN,
    awalan_uji,
    milik_sapuan,
    nama_uji,
    peran_efektif,
    peran_tertinggi,
)
from tests.integration.drive_live.konfigurasi import (
    ENV_WAJIB,
    KonfigurasiLiveError,
    live_aktif,
    muat_konfigurasi,
    pilih_deselect,
)
from tests.integration.drive_live.verifikator import Verifikator

KUNCI = json.dumps(
    {"type": "service_account", "client_email": "uji@proyek.iam.gserviceaccount.com",
     "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n"}
)


def env_lengkap(**ubah: str) -> dict[str, str]:
    env = {
        "GDRIVE_LIVE_TEST": "1",
        "GDRIVE_SERVICE_ACCOUNT_KEY": KUNCI,
        "DRIVE_LIVE_LEAD_EMAIL": "lead@uji.test",
        "DRIVE_LIVE_SA_EMAIL": "sa@uji.test",
        "DRIVE_LIVE_SALES_EMAIL": "sales@uji.test",
        "DRIVE_LIVE_PMO_EMAIL": "pmo@uji.test",
        "DRIVE_LIVE_DELIVERY_EMAIL": "delivery@uji.test",
    }
    env.update(ubah)
    return env


# ----------------------------------------------------------------------------- keputusan deselect


@pytest.mark.parametrize("env", [{}, {"GDRIVE_LIVE_TEST": ""}, {"GDRIVE_LIVE_TEST": "0"},
                                 {"GDRIVE_LIVE_TEST": "true"}, {"GDRIVE_LIVE_TEST": " 1 x"}])
def test_live_tidak_aktif_kecuali_persis_satu(env):
    assert live_aktif(env) is False


def test_live_aktif_bila_persis_satu():
    assert live_aktif({"GDRIVE_LIVE_TEST": "1"}) is True


def test_tanpa_env_semua_item_live_dideselect():
    assert pilih_deselect(["a", "b"], {}) == ["a", "b"]


def test_dengan_env_tidak_ada_yang_dideselect():
    assert pilih_deselect(["a", "b"], {"GDRIVE_LIVE_TEST": "1"}) == []


def test_tanpa_item_live_tidak_ada_yang_dideselect():
    assert pilih_deselect([], {}) == []


# ----------------------------------------------------------------------------- konfigurasi env


def test_konfigurasi_lengkap_dimuat():
    cfg = muat_konfigurasi(env_lengkap())

    assert cfg.email_lead == "lead@uji.test"
    assert cfg.email_sa == "sa@uji.test"
    assert cfg.email_sales == "sales@uji.test"
    assert cfg.email_pmo == "pmo@uji.test"
    assert cfg.email_delivery == "delivery@uji.test"
    assert cfg.kunci["client_email"] == "uji@proyek.iam.gserviceaccount.com"
    assert cfg.kunci_json == KUNCI
    assert cfg.timeout == 120.0


def test_timeout_opsional_dibaca_dari_env():
    assert muat_konfigurasi(env_lengkap(DRIVE_LIVE_TEST_TIMEOUT="45")).timeout == 45.0


@pytest.mark.parametrize("nilai", ["abc", "0", "-5", "nan"])
def test_timeout_tidak_valid_ditolak_dengan_pesan_jelas(nilai):
    with pytest.raises(KonfigurasiLiveError, match="DRIVE_LIVE_TEST_TIMEOUT"):
        muat_konfigurasi(env_lengkap(DRIVE_LIVE_TEST_TIMEOUT=nilai))


def test_semua_env_wajib_dilaporkan_sekaligus_bila_kosong():
    with pytest.raises(KonfigurasiLiveError) as err:
        muat_konfigurasi({"GDRIVE_LIVE_TEST": "1"})

    for nama in ENV_WAJIB:
        assert nama in str(err.value)


@pytest.mark.parametrize("nama", ENV_WAJIB)
def test_satu_env_kurang_disebut_namanya(nama):
    env = env_lengkap()
    env[nama] = "   "

    with pytest.raises(KonfigurasiLiveError) as err:
        muat_konfigurasi(env)

    assert nama in str(err.value)
    assert [n for n in ENV_WAJIB if n != nama and n in str(err.value)] == []


def test_kunci_bukan_json_ditolak_tanpa_membocorkan_isi():
    with pytest.raises(KonfigurasiLiveError) as err:
        muat_konfigurasi(env_lengkap(GDRIVE_SERVICE_ACCOUNT_KEY="rahasia-bukan-json"))

    assert "GDRIVE_SERVICE_ACCOUNT_KEY" in str(err.value)
    assert "rahasia-bukan-json" not in str(err.value)


@pytest.mark.parametrize("kunci", ["[]", json.dumps({"type": "service_account"}),
                                   json.dumps({"type": "authorized_user", "client_email": "a",
                                               "private_key": "b"})])
def test_kunci_bukan_service_account_ditolak(kunci):
    with pytest.raises(KonfigurasiLiveError, match="service account"):
        muat_konfigurasi(env_lengkap(GDRIVE_SERVICE_ACCOUNT_KEY=kunci))


# ----------------------------------------------------------------------------- peran & penamaan


def test_peran_tertinggi_mengikuti_urutan_hak():
    assert peran_tertinggi(["reader", "writer"]) == "writer"
    assert peran_tertinggi(["writer", "owner", "reader"]) == "owner"
    assert peran_tertinggi(["reader"]) == "reader"
    assert peran_tertinggi([]) is None


def test_peran_tertinggi_menolak_peran_tak_dikenal():
    with pytest.raises(ValueError, match="aneh"):
        peran_tertinggi(["aneh"])


def test_peran_efektif_menggabungkan_izin_seluruh_leluhur_tanpa_beda_huruf_besar():
    inventory = [{"type": "user", "role": "reader", "emailAddress": "Sales@Uji.test"}]
    master = [
        {"type": "user", "role": "writer", "emailAddress": "sa@uji.test"},
        {"type": "user", "role": "writer", "emailAddress": "sales@uji.test"},
    ]

    assert peran_efektif([inventory, master], "sales@uji.test") == "writer"
    assert peran_efektif([inventory], "sales@UJI.test") == "reader"
    assert peran_efektif([inventory, master], "tidak-ada@uji.test") is None


def test_peran_efektif_hanya_menghitung_type_user_dan_mengabaikan_entri_tanpa_email():
    izin = [
        {"type": "anyone", "role": "reader"},
        {"type": "domain", "role": "reader", "emailAddress": "sales@uji.test"},
        {"type": "user", "role": "reader", "emailAddress": "sales@uji.test"},
    ]

    assert peran_efektif([izin], "sales@uji.test") == "reader"
    assert peran_efektif([[{"type": "anyone", "role": "reader"}]], "sales@uji.test") is None


def test_peran_efektif_menghitung_link_publik_sebagai_akses_terbuka_untuk_siapa_pun():
    # Folder yang dibagikan ke "anyone" memberi akses ke semua orang → harus tertangkap tes.
    izin = [{"type": "anyone", "role": "reader"}]

    assert peran_efektif([izin], "sales@uji.test", hitung_publik=True) == "reader"


def test_awalan_dan_nama_uji_dikenali_penyapu():
    awalan = awalan_uji("abc123")

    assert awalan == "[LIVE-TEST abc123] "
    assert nama_uji("abc123", "PT Uji") == "[LIVE-TEST abc123] PT Uji"
    assert awalan.startswith(AWALAN_SAPUAN)
    assert milik_sapuan(nama_uji("abc123", "PT Uji")) is True
    assert milik_sapuan("Inventory") is False
    assert milik_sapuan("PT Nyata - [LIVE-TEST x]") is False


# ----------------------------------------------------------------------------- klien verifikasi


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class ServiceDrivePalsu:
    """Meniru bagian `googleapiclient` Drive v3 yang dipakai `Verifikator`."""

    def __init__(self, berkas: dict[str, dict], izin: dict[str, list[dict]]):
        self.berkas = berkas
        self.izin = izin
        self.dihapus: list[str] = []

    def files(self):
        return self

    def permissions(self):
        return _Izin(self)

    def get(self, fileId, fields):  # noqa: N803 - nama argumen API Google
        return _Req(lambda: self.berkas[fileId])

    def delete(self, fileId):  # noqa: N803
        def _hapus():
            if fileId not in self.berkas:
                from googleapiclient.errors import HttpError
                from httplib2 import Response

                raise HttpError(Response({"status": "404"}), b"tidak ada")
            self.dihapus.append(fileId)

        return _Req(_hapus)

    def list(self, q, fields, pageToken=None, pageSize=None):  # noqa: N803
        halaman = {None: 0, "t2": 1}[pageToken]
        if "in parents" in q:
            induk = q.split("'")[1]
            anak = [b for b in self.berkas.values() if induk in b.get("parents", [])]
            return _Req(lambda: {"files": anak})
        semua = [b for b in self.berkas.values() if b.get("owned")]
        potongan = [semua[:1], semua[1:]][halaman]
        return _Req(
            lambda: {"files": potongan, **({"nextPageToken": "t2"} if halaman == 0 else {})}
        )


class _Izin:
    def __init__(self, induk):
        self._induk = induk

    def list(self, fileId, fields, pageToken=None):  # noqa: N803
        return _Req(lambda: {"permissions": self._induk.izin.get(fileId, [])})


def _pohon() -> ServiceDrivePalsu:
    folder = "application/vnd.google-apps.folder"
    berkas = {
        "m": {"id": "m", "name": "[LIVE-TEST a] PT - P", "mimeType": folder, "owned": True},
        "i": {"id": "i", "name": "Inventory", "mimeType": folder, "parents": ["m"]},
        "d": {"id": "d", "name": "Diagram", "mimeType": folder, "parents": ["m"]},
        "x": {"id": "x", "name": "Punya Orang", "mimeType": folder, "owned": True},
    }
    izin = {
        "m": [{"type": "user", "role": "writer", "emailAddress": "sa@uji.test"}],
        "i": [{"type": "user", "role": "reader", "emailAddress": "sales@uji.test"}],
    }
    return ServiceDrivePalsu(berkas, izin)


def test_rantai_ke_atas_dari_anak_sampai_akar():
    v = Verifikator(_pohon())

    assert v.rantai_ke_atas("i") == ["i", "m"]
    assert v.rantai_ke_atas("m") == ["m"]


def test_peran_efektif_memperhitungkan_leluhur_dan_tidak_bocor_ke_saudara():
    v = Verifikator(_pohon())

    assert v.peran_efektif("i", "sales@uji.test") == "reader"
    assert v.peran_efektif("d", "sales@uji.test") is None
    assert v.peran_efektif("m", "sales@uji.test") is None
    assert v.peran_efektif("d", "sa@uji.test") == "writer"  # diwarisi dari master


def test_anak_mengembalikan_nama_subfolder():
    assert sorted(f["name"] for f in Verifikator(_pohon()).anak("m")) == ["Diagram", "Inventory"]


def test_folder_milik_service_account_menelusuri_semua_halaman():
    nama = sorted(f["name"] for f in Verifikator(_pohon()).folder_milik_service_account())

    assert nama == ["Punya Orang", "[LIVE-TEST a] PT - P"]


def test_hapus_berprefiks_hanya_menghapus_folder_dengan_awalan_dan_melaporkannya():
    service = _pohon()

    terhapus = Verifikator(service).hapus_berprefiks("[LIVE-TEST")

    assert terhapus == ["m"]
    assert service.dihapus == ["m"]


def test_hapus_folder_yang_sudah_tidak_ada_bukan_error():
    service = _pohon()

    Verifikator(service).hapus("tidak-ada")

    assert service.dihapus == []
