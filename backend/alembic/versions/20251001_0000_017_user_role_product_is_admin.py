"""role Product + flag is_admin (role Admin dihapus dari enum)

Revision ID: 017
Revises: 016
Create Date: 2025-10-01 00:00:00.000000

Issue #114, ADR 0012.
- `users.role` menjadi tepat satu role fungsional: Sales, Product, SA, Lead_SA.
- `users.is_admin` (boolean NOT NULL default false) menggantikan role Admin: kemampuan, bukan
  pekerjaan.
- Data: user berrole `Admin` menjadi role `Lead_SA` dengan `is_admin = true` (role fungsional
  dapat diubah lewat endpoint admin sesudahnya).

Downgrade (lossy): user dengan `is_admin = true` kembali menjadi role `Admin` (role fungsional
semula hilang); role `Product` dipetakan ke `Sales` karena skema lama tidak mengenalnya.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifikasi revisi
revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_LAMA = "role IN ('Sales', 'SA', 'Lead_SA', 'Admin')"
_ROLE_BARU = "role IN ('Sales', 'Product', 'SA', 'Lead_SA')"


def upgrade() -> None:
    op.drop_constraint("chk_users_role", "users", type_="check")
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Flag kemampuan administrasi (menempel pada satu role fungsional)",
        ),
    )
    op.execute("UPDATE users SET is_admin = true, role = 'Lead_SA' WHERE role = 'Admin'")
    op.create_check_constraint("chk_users_role", "users", _ROLE_BARU)
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_comment="Role pengguna: Sales, SA, Lead_SA, Admin",
        comment="Role fungsional pengguna: Sales, Product, SA, Lead_SA",
    )


def downgrade() -> None:
    op.drop_constraint("chk_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = 'Sales' WHERE role = 'Product'")
    op.execute("UPDATE users SET role = 'Admin' WHERE is_admin")
    op.drop_column("users", "is_admin")
    op.create_check_constraint("chk_users_role", "users", _ROLE_LAMA)
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_comment="Role fungsional pengguna: Sales, Product, SA, Lead_SA",
        comment="Role pengguna: Sales, SA, Lead_SA, Admin",
    )
