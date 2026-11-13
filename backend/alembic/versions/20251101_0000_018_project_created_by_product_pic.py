"""project: created_by, product_pic (wajib), sales_pic opsional, lead_sa

Revision ID: 018
Revises: 017
Create Date: 2025-11-01 00:00:00.000000

Issue #117, ADR 0014.
- `projects.created_by` (FK users, NOT NULL): pembuat project.
- `projects.product_pic` (FK users, NOT NULL): Product penanggung jawab; selalu ada.
- `projects.sales_pic` menjadi NULLABLE: project boleh tanpa Sales.
- `projects.lead_sa` (FK users, NULLABLE): belum diisi sampai tiket Orang-2 (#118).
- Data (hanya data dev; tidak ada data produksi): `created_by` dan `product_pic` diisi dari
  `sales_pic` lama (satu-satunya orang yang tercatat pada project lama).

Downgrade (lossy): `created_by`, `product_pic`, dan `lead_sa` dibuang. Baris dengan `sales_pic`
NULL diisi dari `product_pic` sebelum NOT NULL dikembalikan, sehingga project tanpa Sales
tampak dimiliki Product-nya pada skema lama.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifikasi revisi
revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("created_by", sa.UUID(), nullable=True, comment="FK ke user pembuat project"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "product_pic", sa.UUID(), nullable=True, comment="FK ke user Product penanggung jawab"
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "lead_sa",
            sa.UUID(),
            nullable=True,
            comment="FK ke user Lead_SA penanggung jawab (wajib sejak Assigned; diisi di Orang-2)",
        ),
    )
    op.execute("UPDATE projects SET created_by = sales_pic, product_pic = sales_pic")
    op.alter_column("projects", "created_by", nullable=False)
    op.alter_column("projects", "product_pic", nullable=False)
    op.create_foreign_key("fk_projects_created_by", "projects", "users", ["created_by"], ["id"])
    op.create_foreign_key("fk_projects_product_pic", "projects", "users", ["product_pic"], ["id"])
    op.create_foreign_key("fk_projects_lead_sa", "projects", "users", ["lead_sa"], ["id"])
    op.alter_column(
        "projects",
        "sales_pic",
        existing_type=sa.UUID(),
        nullable=True,
        existing_comment="FK ke user requester yang membuat request (Sales/SA/Lead_SA)",
        comment="FK ke user Sales PIC (opsional; project boleh tanpa Sales)",
    )


def downgrade() -> None:
    op.execute("UPDATE projects SET sales_pic = product_pic WHERE sales_pic IS NULL")
    op.alter_column(
        "projects",
        "sales_pic",
        existing_type=sa.UUID(),
        nullable=False,
        existing_comment="FK ke user Sales PIC (opsional; project boleh tanpa Sales)",
        comment="FK ke user requester yang membuat request (Sales/SA/Lead_SA)",
    )
    op.drop_constraint("fk_projects_lead_sa", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_product_pic", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_created_by", "projects", type_="foreignkey")
    op.drop_column("projects", "lead_sa")
    op.drop_column("projects", "product_pic")
    op.drop_column("projects", "created_by")
