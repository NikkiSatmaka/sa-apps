"""
Dependencies untuk FastAPI dependency injection.
Berisi auth middleware (JWT validation) dan dependencies lainnya.
"""

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


async def ensure_project_access(
    db: AsyncSession,
    project: Project,
    user: User,
) -> None:
    """
    Pastikan `user` boleh mengakses `project` di bawah general access set.

    Bukan dependency FastAPI — fungsi helper biasa yang menerima Project yang
    sudah di-load dan User. Mengizinkan akses jika user privileged
    (role Lead_SA/Admin), Sales PIC project, assigned SA, atau collaborator.
    Raise HTTP 403 (detail Indonesia) jika tidak satupun terpenuhi.

    Return None saat sukses.
    """
    is_privileged = user.role in ("Lead_SA", "Admin")
    is_sales_pic = project.sales_pic == user.id
    is_assigned_sa = project.assigned_sa == user.id

    # Cek keanggotaan collaborator (cocokkan cara get_project_detail query)
    collab_result = await db.execute(
        select(ProjectCollaborator).where(
            ProjectCollaborator.id_project == project.id_project,
            ProjectCollaborator.user_id == user.id,
        )
    )
    is_collaborator = collab_result.scalar_one_or_none() is not None

    if not (is_privileged or is_sales_pic or is_assigned_sa or is_collaborator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses ke proyek ini.",
        )
