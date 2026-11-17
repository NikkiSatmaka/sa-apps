"""Persist project Inventory and Diagram Drive folder IDs."""

from alembic import op
import sqlalchemy as sa

revision = "20261117_0002_030"
down_revision = "20261117_0001_029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("gdrive_inventory_folder_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("gdrive_diagram_folder_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "gdrive_diagram_folder_id")
    op.drop_column("projects", "gdrive_inventory_folder_id")
