"""Add persistent Customer identities and link existing projects."""

from alembic import op
import sqlalchemy as sa

revision = "20261117_0000_028"
down_revision = "20261116_0002_027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("normalized_name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_customers_normalized_name"),
    )
    op.add_column("projects", sa.Column("customer_id", sa.UUID(), nullable=True))
    conn = op.get_bind()
    names = conn.execute(sa.text("SELECT DISTINCT lower(trim(customer_name)) AS normalized FROM projects ORDER BY normalized")).scalars()
    for normalized in names:
        if not normalized:
            continue
        ids = conn.execute(sa.text("SELECT id_project, customer_name FROM projects WHERE lower(trim(customer_name)) = :normalized"), {"normalized": normalized}).all()
        customer_id = conn.execute(sa.text("INSERT INTO customers (id, name, normalized_name) VALUES (gen_random_uuid(), :name, :normalized) RETURNING id"), {"name": ids[0].customer_name.strip(), "normalized": normalized}).scalar_one()
        conn.execute(sa.text("UPDATE projects SET customer_id = :id WHERE lower(trim(customer_name)) = :normalized"), {"id": customer_id, "normalized": normalized})
    op.create_foreign_key("fk_projects_customer_id", "projects", "customers", ["customer_id"], ["id"])
    op.alter_column("projects", "customer_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_projects_customer_id", "projects", type_="foreignkey")
    op.drop_column("projects", "customer_id")
    op.drop_table("customers")
