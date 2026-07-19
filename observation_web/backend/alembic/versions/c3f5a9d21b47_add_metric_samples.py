"""add metric_samples table for persistent metrics

Creates the ``metric_samples`` table used to persist downsampled performance
metrics (CPU / memory / extra JSON) so history survives restarts and is shared
across workers.  The in-memory deque in ``api/ingest.py`` is kept for fast
recent lookups; this table is written at most once per array per ~60s window.

The migration is fault-tolerant/idempotent: table and index creation are
guarded by existence checks so it is safe to run against databases that may
already carry the table (e.g. created by create_all on a fresh start).

Revision ID: c3f5a9d21b47
Revises: b4d1f7a2c9e3
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f5a9d21b47"
down_revision: Union[str, None] = "b4d1f7a2c9e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes_for(inspector: sa.Inspector, table: str) -> set:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "metric_samples" not in tables:
        op.create_table(
            "metric_samples",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("array_id", sa.String(length=64), nullable=False),
            sa.Column("ts", sa.DateTime(), nullable=False),
            sa.Column("cpu0", sa.Float(), nullable=True),
            sa.Column("mem_used_mb", sa.Float(), nullable=True),
            sa.Column("mem_total_mb", sa.Float(), nullable=True),
            sa.Column("extra", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )

    existing = _indexes_for(inspector, "metric_samples")
    if "ix_metric_samples_array_id" not in existing:
        op.create_index("ix_metric_samples_array_id", "metric_samples", ["array_id"])
    if "ix_metric_samples_ts" not in existing:
        op.create_index("ix_metric_samples_ts", "metric_samples", ["ts"])
    if "ix_metric_samples_array_ts" not in existing:
        op.create_index("ix_metric_samples_array_ts", "metric_samples", ["array_id", "ts"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "metric_samples" in set(inspector.get_table_names()):
        op.drop_table("metric_samples")
