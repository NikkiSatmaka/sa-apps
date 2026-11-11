"""
Dependencies untuk FastAPI dependency injection.
Berisi auth middleware (JWT validation) dan dependencies lainnya.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.project import Project
from app.models.project_collaborator import ProjectCollaborator
from app.models.user import User

# Security scheme — mengambil Bearer token dari header Authorization
security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency untuk validasi JWT dan mendapatkan user saat ini.
    Return 401 jika token tidak ada, expired, atau invalid.
    Menyimpan user_id di request.state untuk digunakan rate limiter.
    """
    # Cek apakah token ada
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak ditemukan. Silakan login terlebih dahulu.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Decode dan validasi JWT
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        # Hanya access token yang sah sebagai kredensial API; refresh token (TTL lebih
        # panjang) hanya boleh ditukar di endpoint /auth/refresh.
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid: bukan access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid: payload tidak memiliki subject.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sudah expired. Silakan login ulang.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Query user dari database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Simpan user_id di request.state untuk rate limiter
    request.state.user_id = str(user.id)

    return user


def require_role(*allowed_roles: str):
    """
    Dependency factory untuk flat role gate.

    Mengembalikan dependency FastAPI yang depends pada `get_current_user` dan
    raise HTTP 403 jika `role` user saat ini tidak termasuk `allowed_roles`.
    Jika role diizinkan, user dikembalikan apa adanya.

    Contoh:
        @router.delete("/{id}", dependencies=[Depends(require_role("Lead_SA", "Admin"))])
    """

    async def _role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses untuk melakukan aksi ini.",
            )
        return current_user

    return _role_checker


class PeranUser(StrEnum):
    """Peran user portal (`User.role`)."""

    SALES = "Sales"
    SA = "SA"
    LEAD_SA = "Lead_SA"
    ADMIN = "Admin"


# Peran dengan hak penuh atas semua proyek (Admin = Lead_SA untuk semua aksi matriks).
PERAN_PRIVILEGED = (PeranUser.LEAD_SA, PeranUser.ADMIN)


class PeranKolaborator(StrEnum):
    """Peran collaborator per proyek (`ProjectCollaborator.role`)."""

    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"


class TingkatAkses(StrEnum):
    """Tingkat akses ke satu proyek.

    Siapa yang berhak pada tiap tingkat didefinisikan SATU kali di `_ATURAN` (spec #87); enum
    ini hanya daftar nama. Menambah tingkat = tambah anggota di sini + satu entri di `_ATURAN`.
    """

    BACA = "baca"
    STORY = "story"
    TULIS = "tulis"
    UBAH_PROYEK = "ubah_proyek"
    KELOLA = "kelola"
    ISI_DQ = "isi_dq"
    TAMBAH_KOLABORATOR = "tambah_kolaborator"
    HAPUS_KOLABORATOR = "hapus_kolaborator"
    UBAH_STATUS = "ubah_status"
    HANDOVER = "handover"
    KELOLA_REQUIREMENT = "kelola_requirement"
    EDIT_KUESIONER = "edit_kuesioner"

    @property
    def butuh_kolaborator(self) -> bool:
        """Apakah keputusan tingkat ini memakai data collaborator (perlu query ke DB)?"""
        return _ATURAN[self].butuh_kolaborator


@dataclass(frozen=True)
class HubunganProyek:
    """Hubungan satu user ke satu proyek (dicocokkan lewat id, bukan peran user).

    `privileged` = peran Lead_SA/Admin. `kolaborator` = peran collaborator
    (`PeranKolaborator`) atau None bila bukan collaborator.
    """

    privileged: bool = False
    sales_pic: bool = False
    sa_ditugaskan: bool = False
    kolaborator: str | None = None
    # Peran user. Hanya dipakai tingkat yang aturannya menggabungkan hubungan (id) DAN peran
    # (`Aturan.cocokkan_peran`).
    peran: str = field(default="", compare=False)

    @property
    def adalah_viewer(self) -> bool:
        return self.kolaborator == PeranKolaborator.VIEWER

    @property
    def adalah_contributor(self) -> bool:
        return self.kolaborator == PeranKolaborator.CONTRIBUTOR


class AksesKolaborator(StrEnum):
    """Collaborator mana yang diizinkan pada satu tingkat."""

    TIDAK = "tidak"
    SEMUA = "semua"  # viewer & contributor (baris collaborator apa pun)
    CONTRIBUTOR = "contributor"  # viewer ditolak


@dataclass(frozen=True)
class Aturan:
    """Siapa yang berhak pada satu tingkat. Lead_SA/Admin SELALU berhak, tidak dicantumkan.

    `sales_pic` / `sa_ditugaskan` / `kolaborator` = hubungan yang diizinkan. Bila
    `cocokkan_peran`, Sales PIC hanya berlaku untuk user berperan Sales dan SA ditugaskan hanya
    untuk berperan SA (dicocokkan lewat id DAN peran).
    """

    keterangan: str
    sales_pic: bool = False
    sa_ditugaskan: bool = False
    kolaborator: AksesKolaborator = AksesKolaborator.TIDAK
    cocokkan_peran: bool = False

    @property
    def butuh_kolaborator(self) -> bool:
        return self.kolaborator != AksesKolaborator.TIDAK

    def mengizinkan(self, h: HubunganProyek) -> bool:
        if h.privileged:
            return True
        if self.sales_pic and h.sales_pic and self._peran_cocok(h, PeranUser.SALES):
            return True
        if self.sa_ditugaskan and h.sa_ditugaskan and self._peran_cocok(h, PeranUser.SA):
            return True
        match self.kolaborator:
            case AksesKolaborator.SEMUA:
                return h.kolaborator is not None
            case AksesKolaborator.CONTRIBUTOR:
                return h.adalah_contributor
            case _:
                return False

    def _peran_cocok(self, h: HubunganProyek, peran: PeranUser) -> bool:
        return not self.cocokkan_peran or h.peran == peran


_ATURAN: dict[TingkatAkses, Aturan] = {
    TingkatAkses.BACA: Aturan(
        "Baca: Sales PIC, SA ditugaskan, collaborator (viewer & contributor)",
        sales_pic=True,
        sa_ditugaskan=True,
        kolaborator=AksesKolaborator.SEMUA,
    ),
    TingkatAkses.STORY: Aturan(
        "Baca Project Story + minta ringkasan AI: seperti BACA tetapi Sales PIC TIDAK",
        sa_ditugaskan=True,
        kolaborator=AksesKolaborator.SEMUA,
    ),
    TingkatAkses.TULIS: Aturan(
        "Tulis activity log / map kalender / unggah dokumen: SA ditugaskan, contributor "
        "(viewer dan Sales PIC tidak)",
        sa_ditugaskan=True,
        kolaborator=AksesKolaborator.CONTRIBUTOR,
    ),
    TingkatAkses.UBAH_PROYEK: Aturan(
        "Ubah proyek (PATCH): seperti BACA tetapi viewer ditolak",
        sales_pic=True,
        sa_ditugaskan=True,
        kolaborator=AksesKolaborator.CONTRIBUTOR,
    ),
    TingkatAkses.KELOLA: Aturan("Majukan status dokumen: SA ditugaskan", sa_ditugaskan=True),
    TingkatAkses.ISI_DQ: Aturan("Isi DQ Number: Sales PIC proyek itu", sales_pic=True),
    TingkatAkses.TAMBAH_KOLABORATOR: Aturan(
        "Tambah collaborator: SA ditugaskan, Sales PIC", sales_pic=True, sa_ditugaskan=True
    ),
    TingkatAkses.HAPUS_KOLABORATOR: Aturan(
        "Hapus collaborator: sama dengan TAMBAH_KOLABORATOR (collaborator tidak boleh menghapus)",
        sales_pic=True,
        sa_ditugaskan=True,
    ),
    TingkatAkses.UBAH_STATUS: Aturan(
        "Ubah status proyek (workflow): Sales PIC berperan Sales, SA ditugaskan berperan SA; "
        "collaborator tidak dihitung",
        sales_pic=True,
        sa_ditugaskan=True,
        cocokkan_peran=True,
    ),
    TingkatAkses.HANDOVER: Aturan(
        "Handover (cek kesiapan + eksekusi): SA ditugaskan berperan SA; Sales (termasuk PIC) "
        "dan collaborator ditolak",
        sa_ditugaskan=True,
        cocokkan_peran=True,
    ),
    TingkatAkses.KELOLA_REQUIREMENT: Aturan(
        "Kelola Requirement (edit butir, generate ulang, pertahankan versi): SA ditugaskan "
        "berperan SA; Sales PIC dan collaborator read-only",
        sa_ditugaskan=True,
        cocokkan_peran=True,
    ),
    TingkatAkses.EDIT_KUESIONER: Aturan(
        "Ubah jawaban Kuesioner kualifikasi: Sales PIC berperan Sales",
        sales_pic=True,
        cocokkan_peran=True,
    ),
}


def izinkan(hubungan: HubunganProyek, tingkat: TingkatAkses = TingkatAkses.BACA) -> bool:
    """Fungsi keputusan murni: apakah `hubungan` boleh pada `tingkat`?"""
    return _ATURAN[tingkat].mengizinkan(hubungan)


async def hubungan_proyek(
    db: AsyncSession, project: Project, user: User, *, baca_kolaborator: bool = True
) -> HubunganProyek:
    """Baca hubungan `user` ke `project` (satu query collaborator, kecuali `baca_kolaborator`
    dimatikan untuk tingkat yang keputusannya tidak memakai collaborator)."""
    kolab = None
    if baca_kolaborator:
        collab_result = await db.execute(
            select(ProjectCollaborator).where(
                ProjectCollaborator.id_project == project.id_project,
                ProjectCollaborator.user_id == user.id,
            )
        )
        kolab = collab_result.scalar_one_or_none()
    return HubunganProyek(
        privileged=user.role in PERAN_PRIVILEGED,
        sales_pic=project.sales_pic == user.id,
        sa_ditugaskan=project.assigned_sa == user.id,
        kolaborator=(
            None if kolab is None else getattr(kolab, "role", None) or PeranKolaborator.VIEWER
        ),
        peran=user.role,
    )


async def ensure_project_access(
    db: AsyncSession,
    project: Project,
    user: User,
    tingkat: TingkatAkses = TingkatAkses.BACA,
    pesan: str | None = None,
) -> None:
    """
    TITIK KEPUTUSAN AKSES PROYEK — satu-satunya pintu yang boleh dipakai rute.

    Bukan dependency FastAPI — helper biasa yang menerima Project yang sudah
    di-load dan User. Raise HTTP 403 (pesan generik Indonesia, sama untuk semua
    `tingkat` agar alasan penolakan tidak bocor) bila `user` tidak berhak pada
    `tingkat`. Panggil SETELAH proyek dimuat (404 urusan pemanggil) dan SEBELUM
    efek samping apa pun (penulisan, notifikasi, LLM, Drive). Jangan panggil di
    dalam `try/except Exception` yang menelan HTTPException.

    `pesan` (opsional) mengganti teks 403 default; dipakai rute lama yang kontrak pesannya sudah
    terkunci (tetap 403, aturan keputusan tidak berubah).

    Return None saat sukses. Test penjaga rute (`tests/test_penjaga_akses_rute.py`)
    menelusuri simbol ini; jangan ganti namanya tanpa memperbarui penjaga.
    """
    hubungan = await hubungan_proyek(db, project, user, baca_kolaborator=tingkat.butuh_kolaborator)
    if not izinkan(hubungan, tingkat):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=pesan or "Anda tidak memiliki akses ke proyek ini.",
        )
