"""Add Ethernet topology inventory and snapshots.

Revision ID: c9a12e4d7b60
Revises: b8e2f4a16c30
"""
from alembic import op
import sqlalchemy as sa

revision = "c9a12e4d7b60"
down_revision = "b8e2f4a16c30"
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "topology_cables" not in tables:
        op.create_table(
            "topology_cables",
            sa.Column("cable_id", sa.String(80), primary_key=True),
            sa.Column("source", sa.String(80), nullable=False),
            sa.Column("source_port", sa.String(128), nullable=False),
            sa.Column("target", sa.String(80), nullable=False),
            sa.Column("target_port", sa.String(128), nullable=False),
            sa.Column("confirmed_by", sa.String(128), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        )
    if "topology_switches" not in tables:
        op.create_table(
            "topology_switches",
            sa.Column("device_id", sa.String(80), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("host", sa.String(256), unique=True, nullable=False),
            sa.Column("port", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(64), nullable=False),
            sa.Column("saved_password", sa.String(512), nullable=False),
            sa.Column("key_path", sa.String(512), nullable=False),
        )
    if "topology_snapshots" not in tables:
        op.create_table(
            "topology_snapshots",
            sa.Column("device_id", sa.String(80), primary_key=True),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("collected_at", sa.DateTime()),
            sa.Column("attempted_at", sa.DateTime()),
            sa.Column("last_error", sa.Text(), nullable=False),
        )


def downgrade():
    op.drop_table("topology_cables")
    op.drop_table("topology_snapshots")
    op.drop_table("topology_switches")
