"""check runs and stable demo anchor"""

import sqlalchemy as sa
from alembic import op

revision = "4b9a05587d84"
down_revision = "8273404bd817"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "check_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("scenario", sa.String(length=30), nullable=False),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entities_checked", sa.Integer(), nullable=False),
        sa.Column("incidents_created", sa.Integer(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.CheckConstraint("status IN ('UNKNOWN','HEALTHY','DELAYED','BROKEN')"),
        sa.CheckConstraint("transport IN ('memory','http')"),
        sa.ForeignKeyConstraint(
            ["organization_id", "integration_id"],
            ["integrations.organization_id", "integrations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_check_runs_completed_at"), "check_runs", ["completed_at"], unique=False)
    op.add_column("integrations", sa.Column("demo_anchor", sa.DateTime(timezone=True), nullable=True))
    op.add_column("observations", sa.Column("run_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_observations_run_id"), "observations", ["run_id"], unique=False)
    op.create_foreign_key("observations_run_id_fkey", "observations", "check_runs", ["run_id"], ["id"])


def downgrade():
    op.drop_constraint("observations_run_id_fkey", "observations", type_="foreignkey")
    op.drop_index(op.f("ix_observations_run_id"), table_name="observations")
    op.drop_column("observations", "run_id")
    op.drop_column("integrations", "demo_anchor")
    op.drop_index(op.f("ix_check_runs_completed_at"), table_name="check_runs")
    op.drop_table("check_runs")
