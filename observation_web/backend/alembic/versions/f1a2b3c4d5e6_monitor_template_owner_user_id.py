"""add owner_user_id to monitor_templates for multi-user Phase 2

Adds a nullable FK column ``owner_user_id`` to ``monitor_templates`` so custom
monitors have precise ownership (the existing ``created_by`` string keeps the
nickname for display/attribution; ``owner_user_id`` is the authoritative key for
owner permission checks). Builtin/legacy rows keep it NULL.

The migration is fault-tolerant/idempotent: the column and index are guarded by
existence checks so it is safe to run against databases that may already carry
the column (e.g. created by create_all on a fresh start).

Revision ID: f1a2b3c4d5e6
Revises: d5e8a7c3f912
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d5e8a7c3f912"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns_for(inspector: sa.Inspector, table: str) -> set:
    try:
        return {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        return set()


def _indexes_for(inspector: sa.Inspector, table: str) -> set:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "monitor_templates" not in tables:
        return

    if "owner_user_id" not in _columns_for(inspector, "monitor_templates"):
        # SQLite cannot add a column with an inline FK via ALTER TABLE, so add a
        # plain nullable Integer column; the ORM-level ForeignKey is advisory.
        op.add_column(
            "monitor_templates",
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
        )

    if "ix_monitor_templates_owner_user_id" not in _indexes_for(inspector, "monitor_templates"):
        op.create_index(
            "ix_monitor_templates_owner_user_id",
            "monitor_templates",
            ["owner_user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "monitor_templates" not in tables:
        return
    if "ix_monitor_templates_owner_user_id" in _indexes_for(inspector, "monitor_templates"):
        op.drop_index("ix_monitor_templates_owner_user_id", table_name="monitor_templates")
    if "owner_user_id" in _columns_for(inspector, "monitor_templates"):
        op.drop_column("monitor_templates", "owner_user_id")
