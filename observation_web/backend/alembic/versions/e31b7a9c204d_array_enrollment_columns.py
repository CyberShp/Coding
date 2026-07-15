"""catch up array enrollment and typed-tag columns used by the current ORM

Revision ID: e31b7a9c204d
Revises: f208c0b5e711
Create Date: 2026-07-16 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e31b7a9c204d"
down_revision: Union[str, None] = "f208c0b5e711"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ARRAY_COLUMNS = (
    sa.Column("display_name", sa.String(128), nullable=True, server_default=""),
    sa.Column("mgmt_ip", sa.String(256), nullable=True, server_default=""),
    sa.Column("site", sa.String(128), nullable=True, server_default=""),
    sa.Column("env_type", sa.String(64), nullable=True, server_default=""),
    sa.Column("owner_team", sa.String(128), nullable=True, server_default=""),
    sa.Column("serial", sa.String(128), nullable=True, server_default=""),
    sa.Column("cluster_id", sa.String(64), nullable=True, server_default=""),
    sa.Column("enrollment_status", sa.String(32), nullable=True, server_default="draft"),
    sa.Column("connection_mode", sa.String(32), nullable=True, server_default="ssh_only"),
    sa.Column("agent_registered_at", sa.DateTime(), nullable=True),
    sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
    sa.Column("enrolled_by", sa.String(128), nullable=True, server_default=""),
    sa.Column("enrolled_at", sa.DateTime(), nullable=True),
    sa.Column("last_error", sa.Text(), nullable=True, server_default=""),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "arrays" in tables:
        existing = {item["name"] for item in inspector.get_columns("arrays")}
        missing = [column for column in ARRAY_COLUMNS if column.name not in existing]
        if missing:
            with op.batch_alter_table("arrays") as batch_op:
                for column in missing:
                    batch_op.add_column(column)
    if "tags" in tables:
        tag_columns = {item["name"] for item in inspector.get_columns("tags")}
        if "tag_type" not in tag_columns:
            with op.batch_alter_table("tags") as batch_op:
                batch_op.add_column(
                    sa.Column("tag_type", sa.String(64), nullable=True, server_default="general")
                )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "arrays" in tables:
        existing = {item["name"] for item in inspector.get_columns("arrays")}
        with op.batch_alter_table("arrays") as batch_op:
            for column in reversed(ARRAY_COLUMNS):
                if column.name in existing:
                    batch_op.drop_column(column.name)
    if "tags" in tables:
        tag_columns = {item["name"] for item in inspector.get_columns("tags")}
        if "tag_type" in tag_columns:
            with op.batch_alter_table("tags") as batch_op:
                batch_op.drop_column("tag_type")
