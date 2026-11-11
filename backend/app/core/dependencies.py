"""
Dependencies untuk FastAPI dependency injection.
Berisi auth middleware (JWT validation) dan dependencies lainnya.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

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


class TingkatAkses(str, Enum):
    """Tingkat akses ke satu proyek. Matriks lengkap ada di `_IZIN` (spec #87)."""

    # Baca: Lead_SA, Admin, Sales PIC, SA ditugaskan, collaborator (viewer & contributor)
    BACA = "baca"
    # Baca Project Story + minta ringkasan AI: seperti BACA tetapi Sales PIC TIDAK
    STORY = "story"
    # Tulis activity log / map kalender / unggah dokumen: Lead_SA, Admin, SA ditugaskan,
    # collaborator contributor (viewer dan Sales PIC tidak)
    TULIS = "tulis"
    # Ubah proyek (PATCH): seperti BACA tetapi collaborator viewer ditolak
    UBAH_PROYEK = "ubah_proyek"
    # Majukan status dokumen: Lead_SA, Admin, SA ditugaskan
    KELOLA = "kelola"
    # Isi DQ Number: Lead_SA, Admin, Sales PIC proyek itu
    ISI_DQ = "isi_dq"
    # Tambah collaborator: Lead_SA, Admin, SA ditugaskan, Sales PIC
    TAMBAH_KOLABORATOR = "tambah_kolaborator"


@dataclass(frozen=True)
class HubunganProyek:
    """Hubungan satu user ke satu proyek (dicocokkan lewat id, bukan peran user).

    `privileged` = peran Lead_SA/Admin. `kolaborator` = peran collaborator
    (`"viewer"`/`"contributor"`) atau None bila bukan collaborator.
    """

    privileged: bool = False
    sales_pic: bool = False
    sa_ditugaskan: bool = False
    kolaborator: str | None = None

    @property
    def adalah_viewer(self) -> bool:
        return self.kolaborator == "viewer"

    @property
    def adalah_contributor(self) -> bool:
        return self.kolaborator == "contributor"


_IZIN: dict[TingkatAkses, Callable[[HubunganProyek], bool]] = {
    TingkatAkses.BACA: lambda h: (
        h.privileged or h.sales_pic or h.sa_ditugaskan or h.kolaborator is not None
    ),
    TingkatAkses.STORY: lambda h: h.privileged or h.sa_ditugaskan or h.kolaborator is not None,
    TingkatAkses.TULIS: lambda h: h.privileged or h.sa_ditugaskan or h.adalah_contributor,
    TingkatAkses.UBAH_PROYEK: lambda h: (
        h.privileged or h.sales_pic or h.sa_ditugaskan or h.adalah_contributor
    ),
    TingkatAkses.KELOLA: lambda h: h.privileged or h.sa_ditugaskan,
    TingkatAkses.ISI_DQ: lambda h: h.privileged or h.sales_pic,
    TingkatAkses.TAMBAH_KOLABORATOR: lambda h: h.privileged or h.sales_pic or h.sa_ditugaskan,
}


def izinkan(hubungan: HubunganProyek, tingkat: TingkatAkses = TingkatAkses.BACA) -> bool:
    """Fungsi keputusan murni: apakah `hubungan` boleh pada `tingkat`?"""
    return _IZIN[tingkat](hubungan)


async def hubungan_proyek(db: AsyncSession, project: Project, user: User) -> HubunganProyek:
    """Baca hubungan `user` ke `project` (satu query collaborator)."""
    collab_result = await db.execute(
        select(ProjectCollaborator).where(
            ProjectCollaborator.id_project == project.id_project,
            ProjectCollaborator.user_id == user.id,
        )
    )
    kolab = collab_result.scalar_one_or_none()
    return HubunganProyek(
        privileged=user.role in ("Lead_SA", "Admin"),
        sales_pic=project.sales_pic == user.id,
        sa_ditugaskan=project.assigned_sa == user.id,
        kolaborator=None if kolab is None else getattr(kolab, "role", None) or "viewer",
    )


async def ensure_project_access(
    db: AsyncSession,
    project: Project,
    user: User,
    tingkat: TingkatAkses = TingkatAkses.BACA,
) -> None:
    """
    TITIK KEPUTUSAN AKSES PROYEK — satu-satunya pintu yang boleh dipakai rute.

    Bukan dependency FastAPI — helper biasa yang menerima Project yang sudah
    di-load dan User. Raise HTTP 403 (pesan generik Indonesia, sama untuk semua
    `tingkat` agar alasan penolakan tidak bocor) bila `user` tidak berhak pada
    `tingkat`. Panggil SETELAH proyek dimuat (404 urusan pemanggil) dan SEBELUM
    efek samping apa pun (penulisan, notifikasi, LLM, Drive). Jangan panggil di
    dalam `try/except Exception` yang menelan HTTPException.

    Return None saat sukses. Test penjaga rute (`tests/test_penjaga_akses_rute.py`)
    menelusuri simbol ini; jangan ganti namanya tanpa memperbarui penjaga.
    """
    hubungan = await hubungan_proyek(db, project, user)
    if not izinkan(hubungan, tingkat):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses ke proyek ini.",
        )
