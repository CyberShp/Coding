"""add observer_config_overrides for per-tag/array observer overlays (Phase 3)

Introduces the ``observer_config_overrides`` table so built-in observer config
becomes a layered model: the existing ``observer_configs`` row is the global
default, and rows here overlay it per L1 tag or per array (most specific wins).

The migration is fault-tolerant/idempotent, mirroring f1a2b3c4d5e6:
- SQLite fresh databases already get the table from create_all, so a table
  existence check makes the create a no-op there.
- The unique index is guarded by an existence check.

Revision ID: a3b7c1e4f209
Revises: f1a2b3c4d5e6
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3b7c1e4f209"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
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

    if "observer_config_overrides" not in tables:
        op.create_table(
            "observer_config_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("observer_name", sa.String(length=64), nullable=False),
            sa.Column("scope_type", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.String(length=64), nullable=False),
            sa.Column("params_json", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "observer_name", "scope_type", "scope_id",
                name="uq_observer_override_scope",
            ),
        )

    # Re-inspect: index set may only exist after the create above.
    inspector = sa.inspect(bind)
    existing_idx = _indexes_for(inspector, "observer_config_overrides")
    if "ix_observer_config_overrides_observer_name" not in existing_idx:
        op.create_index(
            "ix_observer_config_overrides_observer_name",
            "observer_config_overrides",
            ["observer_name"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "observer_config_overrides" not in tables:
        return
    if "ix_observer_config_overrides_observer_name" in _indexes_for(inspector, "observer_config_overrides"):
        op.drop_index(
            "ix_observer_config_overrides_observer_name",
            table_name="observer_config_overrides",
        )
    op.drop_table("observer_config_overrides")
