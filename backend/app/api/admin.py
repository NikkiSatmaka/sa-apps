"""
API endpoints untuk Admin — User management dan konfigurasi.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import VALID_ROLES
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.response import success_response

router = APIRouter(prefix="/admin", tags=["Admin"])



def _require_admin(current_user: User) -> None:
    """Validasi bahwa user saat ini memiliki role Admin."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Admin yang dapat mengakses fitur ini.",
        )


class ChangeRoleRequest(BaseModel):
    """Request body untuk mengubah role user."""

    role: str


@router.get(
    "/users",
    summary="Daftar semua users",
    description="Mengembalikan semua user yang terdaftar di sistem. Hanya Admin.",
)
async def list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ambil semua users untuk admin management."""
    _require_admin(current_user)

    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()

    data = [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "role": u.role,
        }
        for u in users
    ]

    return success_response(data=data, message=f"{len(data)} users ditemukan.")


@router.patch(
    "/users/{user_id}/role",
    summary="Ubah role user",
    description="Mengubah role user ke role baru (Sales, SA, Lead_SA, Admin). Hanya Admin.",
)
async def change_user_role(
    user_id: str,
    body: ChangeRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ubah role user."""
    _require_admin(current_user)

    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role tidak valid. Pilihan: {', '.join(VALID_ROLES)}",
        )

    # Cari user
    import uuid as uuid_mod

    try:
        uid = uuid_mod.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format user ID tidak valid.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    old_role = user.role

    # Failsafe: cegah demosi Admin terakhir. Jika user ini seorang Admin dan
    # role barunya bukan Admin, pastikan masih ada Admin lain yang tersisa.
    # Sistem harus selalu punya minimal satu Admin agar akses admin tidak hilang.
    if old_role == "Admin" and body.role != "Admin":
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role == "Admin")
        )
        if admin_count is not None and admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Admin terakhir tidak dapat di-demote. "
                    "Sistem harus selalu memiliki minimal satu Admin."
                ),
            )

    user.role = body.role
    await db.commit()

    return success_response(
        data={
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "old_role": old_role,
        },
        message=f"Role {user.name} diubah dari {old_role} ke {body.role}.",
    )
