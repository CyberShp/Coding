"""add users and user_teams tables for multi-user Phase 1

Creates the ``users`` table (nickname + password accounts, is_admin flag)
and the ``user_teams`` table (self-selected L1-tag team membership).

The migration is fault-tolerant/idempotent: table and index creation are
guarded by existence checks so it is safe to run against databases that may
already carry the tables (e.g. created by create_all on a fresh start).

Revision ID: d5e8a7c3f912
Revises: c3f5a9d21b47
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e8a7c3f912"
down_revision: Union[str, None] = "c3f5a9d21b47"
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

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("nickname", sa.String(length=64), nullable=False),
            sa.Column("password_hash", sa.String(length=128), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
        )

    existing = _indexes_for(inspector, "users")
    if "ix_users_nickname" not in existing:
        op.create_index("ix_users_nickname", "users", ["nickname"], unique=True)

    if "user_teams" not in tables:
        op.create_table(
            "user_teams",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("tag_id", sa.Integer(), nullable=False),
        )

    existing = _indexes_for(inspector, "user_teams")
    if "ix_user_teams_user_id" not in existing:
        op.create_index("ix_user_teams_user_id", "user_teams", ["user_id"])
    if "ix_user_teams_tag_id" not in existing:
        op.create_index("ix_user_teams_tag_id", "user_teams", ["tag_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "user_teams" in tables:
        op.drop_table("user_teams")
    if "users" in tables:
        op.drop_table("users")
