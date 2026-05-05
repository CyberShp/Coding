"""catchup: add historical columns missing from pre-Alembic schemas

Revision ID: c7e9d2b4f81a
Revises: a18c393c631a
Create Date: 2026-05-06 10:00:00.000000

These two columns were introduced by legacy migration scripts that no longer
exist (schema_migrate.py / _archived_migrations/).  Any database that was
created before Alembic was adopted may be missing them.  We add them here
with existence checks so the migration is idempotent on both old and new
schemas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e9d2b4f81a'
down_revision: Union[str, None] = 'a18c393c631a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    # user_sessions.previous_ips — JSON array of historical IPs after IP claim
    # Added in _archived_migrations/001_add_previous_ips.py; may be absent on
    # databases that were created before that migration ran.
    if not _column_exists('user_sessions', 'previous_ips'):
        with op.batch_alter_table('user_sessions') as batch_op:
            batch_op.add_column(
                sa.Column('previous_ips', sa.Text(), nullable=True, server_default='[]')
            )

    # monitor_templates.consecutive_threshold — consecutive matches required
    # before an alert fires.  Added in the old _apply_column_migrations()
    # helper that was removed when Alembic was introduced.
    if not _column_exists('monitor_templates', 'consecutive_threshold'):
        with op.batch_alter_table('monitor_templates') as batch_op:
            batch_op.add_column(
                sa.Column('consecutive_threshold', sa.Integer(), nullable=True, server_default='1')
            )


def downgrade() -> None:
    # These columns existed in production before Alembic was introduced.
    # Dropping them on downgrade would lose real data, so downgrade is a no-op.
    pass
