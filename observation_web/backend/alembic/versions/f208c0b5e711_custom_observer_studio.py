"""custom observer studio versions, assignments, and deployment state

Revision ID: f208c0b5e711
Revises: c7e9d2b4f81a
Create Date: 2026-07-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f208c0b5e711"
down_revision: Union[str, None] = "c7e9d2b4f81a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    # Historical partial schemas are completed by create_all during app startup.
    # A standalone catch-up migration must not invent dependent tables when the
    # parent monitor_templates table never existed.
    if "monitor_templates" not in tables:
        return
    columns = {
        item["name"] for item in inspector.get_columns("monitor_templates")
    }
    missing = [
        column for column in (
            sa.Column("template_key", sa.String(64), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("visibility", sa.String(16), nullable=False, server_default="team"),
            sa.Column("team_scope", sa.String(128), nullable=True, server_default=""),
            sa.Column("config_fingerprint", sa.String(80), nullable=True, server_default=""),
        ) if column.name not in columns
    ]
    if missing:
        with op.batch_alter_table("monitor_templates") as batch_op:
            for column in missing:
                batch_op.add_column(column)
    indexes = {
        item["name"] for item in inspector.get_indexes("monitor_templates")
    } if "monitor_templates" in tables else set()
    if "ix_monitor_templates_template_key" not in indexes:
        op.create_index(
            "ix_monitor_templates_template_key", "monitor_templates", ["template_key"], unique=True
        )

    if "monitor_template_versions" not in tables:
        _create_version_table()
    if "monitor_assignments" not in tables:
        _create_assignment_table()
    if "monitor_deployments" not in tables:
        _create_deployment_table()


def _create_version_table() -> None:
    op.create_table(
        "monitor_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("config_fingerprint", sa.String(80), nullable=False),
        sa.Column("created_by", sa.String(64), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "version", name="uq_monitor_template_version"),
    )
    op.create_index("ix_monitor_template_versions_template_id", "monitor_template_versions", ["template_id"])


def _create_assignment_table() -> None:
    op.create_table(
        "monitor_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("desired_version", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("status_message", sa.Text(), server_default=""),
        sa.Column("created_by", sa.String(64), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "target_type", "target_id", name="uq_monitor_assignment_target"),
    )
    op.create_index("ix_monitor_assignments_template_id", "monitor_assignments", ["template_id"])
    op.create_index("ix_monitor_assignment_target", "monitor_assignments", ["target_type", "target_id"])


def _create_deployment_table() -> None:
    op.create_table(
        "monitor_deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("monitor_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("array_id", sa.String(64), nullable=False),
        sa.Column("desired_version", sa.Integer(), nullable=False),
        sa.Column("desired_hash", sa.String(80), server_default=""),
        sa.Column("loaded_hash", sa.String(80), server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("status_message", sa.Text(), server_default=""),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("assignment_id", "array_id", name="uq_monitor_deployment_array"),
    )
    op.create_index("ix_monitor_deployments_assignment_id", "monitor_deployments", ["assignment_id"])
    op.create_index("ix_monitor_deployments_template_id", "monitor_deployments", ["template_id"])
    op.create_index("ix_monitor_deployments_array_id", "monitor_deployments", ["array_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in ("monitor_deployments", "monitor_assignments", "monitor_template_versions"):
        if table in tables:
            op.drop_table(table)
    if "monitor_templates" not in tables:
        return
    indexes = {item["name"] for item in inspector.get_indexes("monitor_templates")}
    columns = {item["name"] for item in inspector.get_columns("monitor_templates")}
    with op.batch_alter_table("monitor_templates") as batch_op:
        if "ix_monitor_templates_template_key" in indexes:
            batch_op.drop_index("ix_monitor_templates_template_key")
        for column in ("config_fingerprint", "team_scope", "visibility", "version", "template_key"):
            if column in columns:
                batch_op.drop_column(column)
