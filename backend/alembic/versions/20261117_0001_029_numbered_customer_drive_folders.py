"""Persist Customer Drive identity and per-Customer project folder numbers."""

from alembic import op
import sqlalchemy as sa

revision = "20261117_0001_029"
down_revision = "20261117_0000_028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("gdrive_folder_id", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        "uq_customers_gdrive_folder_id", "customers", ["gdrive_folder_id"]
    )
    op.add_column(
        "projects", sa.Column("gdrive_folder_number", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint(
        "chk_projects_gdrive_folder_number_positive",
        "projects",
        "gdrive_folder_number IS NULL OR gdrive_folder_number > 0",
    )
    op.create_unique_constraint(
        "uq_projects_customer_gdrive_folder_number",
        "projects",
        ["customer_id", "gdrive_folder_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_projects_customer_gdrive_folder_number", "projects", type_="unique"
    )
    op.drop_constraint(
        "chk_projects_gdrive_folder_number_positive", "projects", type_="check"
    )
    op.drop_column("projects", "gdrive_folder_number")
    op.drop_constraint("uq_customers_gdrive_folder_id", "customers", type_="unique")
    op.drop_column("customers", "gdrive_folder_id")
