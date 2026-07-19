"""drop redundant single-column and primary-key indexes

Removes indexes that add write/storage cost without helping any real query:

* ``alerts.array_id`` / ``alerts.observer_name`` / ``alerts.level`` single-column
  indexes — fully covered by the composite indexes ``ix_alerts_array_timestamp``,
  ``ix_alerts_array_observer_ts`` and ``ix_alerts_level_timestamp`` (leftmost
  prefix rule).
* ``ix_alerts_is_expected`` — a three-value low-selectivity column; the index is
  never selective enough to be chosen by the planner.
* ``ix_<table>_id`` on every table — the integer primary key is the SQLite rowid,
  so a secondary index on it is pure overhead.

The migration is fault-tolerant: every drop is guarded by an existence check, so
it is safe to run against databases created before or after these ORM changes.

Revision ID: b4d1f7a2c9e3
Revises: e31b7a9c204d
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4d1f7a2c9e3"
down_revision: Union[str, None] = "e31b7a9c204d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit single-column indexes on the alerts table that are now redundant.
_ALERTS_REDUNDANT_INDEXES = (
    "ix_alerts_array_id",
    "ix_alerts_observer_name",
    "ix_alerts_level",
    "ix_alerts_is_expected",
)


def _indexes_for(inspector: sa.Inspector, table: str) -> set:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Drop redundant single-column alert indexes.
    if "alerts" in tables:
        existing = _indexes_for(inspector, "alerts")
        for name in _ALERTS_REDUNDANT_INDEXES:
            if name in existing:
                op.drop_index(name, table_name="alerts")

    # 2. Drop the redundant ix_<table>_id primary-key indexes everywhere.
    for table in tables:
        idx_name = f"ix_{table}_id"
        if idx_name in _indexes_for(inspector, table):
            op.drop_index(idx_name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # Recreate the single-column alert indexes (best-effort).
    if "alerts" in tables:
        existing = _indexes_for(inspector, "alerts")
        alert_cols = {c["name"] for c in inspector.get_columns("alerts")}
        recreate = {
            "ix_alerts_array_id": "array_id",
            "ix_alerts_observer_name": "observer_name",
            "ix_alerts_level": "level",
            "ix_alerts_is_expected": "is_expected",
        }
        for name, col in recreate.items():
            if name not in existing and col in alert_cols:
                op.create_index(name, "alerts", [col])

    # Recreate ix_<table>_id for tables that have an integer id column.
    for table in tables:
        idx_name = f"ix_{table}_id"
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "id" in cols and idx_name not in _indexes_for(inspector, table):
            op.create_index(idx_name, table, ["id"])
