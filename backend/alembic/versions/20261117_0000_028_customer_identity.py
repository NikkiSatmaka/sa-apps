"""Add persistent Customer identities and link existing projects."""

import uuid

from alembic import op
import sqlalchemy as sa

revision = "20261117_0000_028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("normalized_name", sa.String(450), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_customers_normalized_name"),
    )
    op.add_column("projects", sa.Column("customer_id", sa.UUID(), nullable=True))
    conn = op.get_bind()
    projects = conn.execute(sa.text("SELECT id_project, customer_name FROM projects ORDER BY id_project")).all()
    identities: dict[str, tuple[str, list[str]]] = {}
    for project_id, raw_name in projects:
        normalized = (raw_name or "").strip().casefold()
        if normalized not in identities:
            identities[normalized] = ((raw_name or "").strip(), [])
        identities[normalized][1].append(project_id)
    for normalized, (name, project_ids) in identities.items():
        customer_id = uuid.uuid4()
        conn.execute(
            sa.text("INSERT INTO customers (id, name, normalized_name) VALUES (:id, :name, :normalized)"),
            {"id": customer_id, "name": name, "normalized": normalized},
        )
        conn.execute(
            sa.text("UPDATE projects SET customer_id = :id WHERE id_project = ANY(:project_ids)"),
            {"id": customer_id, "project_ids": project_ids},
        )
    op.create_foreign_key("fk_projects_customer_id", "projects", "customers", ["customer_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_projects_customer_id", "projects", type_="foreignkey")
    op.drop_column("projects", "customer_id")
    op.drop_table("customers")
