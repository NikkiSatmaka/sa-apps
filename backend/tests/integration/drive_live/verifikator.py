"""
Klien verifikasi Drive untuk suite live (#27): TERPISAH dari kode produksi.

Test live tidak boleh mempercayai nilai kembalian `folder_provisioner`; hasilnya dibaca ulang lewat
klien `googleapiclient` milik test sendiri (key yang sama). Kelas ini menerima objek `service`
(hasil `build("drive", "v3", ...)`) sehingga logikanya bisa diuji dengan service palsu.
"""

from __future__ import annotations

from typing import Any

from googleapiclient.errors import HttpError

from tests.integration.drive_live import izin as modul_izin

MIME_FOLDER = "application/vnd.google-apps.folder"
FIELD_BERKAS = "id,name,mimeType,parents,trashed"
FIELD_IZIN = "nextPageToken,permissions(id,type,role,emailAddress,permissionDetails)"


def bangun_service(kunci: dict):
    """Service Drive v3 dari key service account (import malas)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    kredensial = service_account.Credentials.from_service_account_info(
        kunci, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=kredensial, cache_discovery=False)


class Verifikator:
    def __init__(self, service: Any) -> None:
        self._s = service

    # ------------------------------------------------------------------ baca
    def ambil(self, file_id: str) -> dict:
        return self._s.files().get(fileId=file_id, fields=FIELD_BERKAS).execute()

    def daftar_izin(self, file_id: str) -> list[dict]:
        """Semua permission yang dikembalikan Drive untuk `file_id` (semua halaman)."""
        hasil: list[dict] = []
        token = None
        while True:
            resp = (
                self._s.permissions()
                .list(fileId=file_id, fields=FIELD_IZIN, pageToken=token)
                .execute()
            )
            hasil.extend(resp.get("permissions", []))
            token = resp.get("nextPageToken")
            if not token:
                return hasil

    def anak(self, parent_id: str) -> list[dict]:
        """Subfolder langsung (tidak di-trash) dari `parent_id`."""
        q = f"'{parent_id}' in parents and mimeType='{MIME_FOLDER}' and trashed=false"
        return self._s.files().list(q=q, fields=f"files({FIELD_BERKAS})").execute()["files"]

    def rantai_ke_atas(self, file_id: str) -> list[str]:
        """[file_id, induk, kakek, ...] sampai folder tanpa induk yang terlihat."""
        rantai: list[str] = []
        sekarang: str | None = file_id
        while sekarang and sekarang not in rantai:
            rantai.append(sekarang)
            induk = self.ambil(sekarang).get("parents") or []
            sekarang = induk[0] if induk else None
        return rantai

    def peran_efektif(self, file_id: str, email: str) -> str | None:
        """Peran efektif `email` pada `file_id` (definisi di `izin.py`)."""
        izin = [self.daftar_izin(f) for f in self.rantai_ke_atas(file_id)]
        return modul_izin.peran_efektif(izin, email, hitung_publik=True)

    # ------------------------------------------------------------------ sapuan & hapus
    def folder_milik_service_account(self) -> list[dict]:
        hasil: list[dict] = []
        token = None
        q = f"'me' in owners and mimeType='{MIME_FOLDER}' and trashed=false"
        while True:
            resp = (
                self._s.files()
                .list(
                    q=q,
                    fields=f"nextPageToken,files({FIELD_BERKAS})",
                    pageToken=token,
                    pageSize=200,
                )
                .execute()
            )
            hasil.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return hasil

    def hapus(self, file_id: str) -> None:
        """Hapus permanen (beserta isinya). Folder yang sudah tidak ada bukan error."""
        try:
            self._s.files().delete(fileId=file_id).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise

    def hapus_berprefiks(self, awalan: str) -> list[str]:
        """Hapus folder milik service account yang namanya berawalan `awalan`; kembalikan id-nya."""
        terhapus: list[str] = []
        for folder in self.folder_milik_service_account():
            if folder["name"].startswith(awalan):
                self.hapus(folder["id"])
                terhapus.append(folder["id"])
        return terhapus
