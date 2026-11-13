"""
API endpoints untuk Admin — User management dan konfigurasi.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import VALID_ROLES
from app.core.database import get_db
from app.core.dependencies import adalah_admin, get_current_user
from app.models.user import User
from app.schemas.response import success_response

router = APIRouter(prefix="/admin", tags=["Admin"])



def _require_admin(current_user: User) -> None:
    """Validasi bahwa user saat ini memiliki flag `is_admin`."""
    if not adalah_admin(current_user):
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
            "is_admin": u.is_admin,
        }
        for u in users
    ]

    return success_response(data=data, message=f"{len(data)} users ditemukan.")


@router.patch(
    "/users/{user_id}/role",
    summary="Ubah role user",
    description="Mengubah role fungsional user (Sales, Product, SA, Lead_SA). Hanya Admin.",
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
    user.role = body.role
    await db.commit()

    return success_response(
        data={
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_admin": user.is_admin,
            "old_role": old_role,
        },
        message=f"Role {user.name} diubah dari {old_role} ke {body.role}.",
    )


class ChangeAdminRequest(BaseModel):
    """Request body untuk menetapkan atau mencabut flag admin."""

    is_admin: bool


@router.patch(
    "/users/{user_id}/admin",
    summary="Tetapkan atau cabut flag admin",
    description=(
        "Menetapkan atau mencabut flag `is_admin` user (kemampuan administrasi yang menempel "
        "pada satu role fungsional). Mencabut flag admin terakhir ditolak (409). Hanya Admin."
    ),
)
async def change_user_admin(
    user_id: str,
    body: ChangeAdminRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tetapkan atau cabut flag `is_admin` user."""
    _require_admin(current_user)

    import uuid as uuid_mod

    try:
        uid = uuid_mod.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format user ID tidak valid.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    old_is_admin = user.is_admin

    # Failsafe: sistem harus selalu punya minimal satu admin agar akses admin tidak hilang.
    if old_is_admin is True and not body.is_admin:
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
        if admin_count is not None and admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Admin terakhir tidak dapat dicabut. "
                    "Sistem harus selalu memiliki minimal satu Admin."
                ),
            )

    user.is_admin = body.is_admin
    await db.commit()

    return success_response(
        data={
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_admin": user.is_admin,
            "old_is_admin": old_is_admin,
        },
        message=f"Flag admin {user.name} diubah dari {old_is_admin} ke {body.is_admin}.",
    )
