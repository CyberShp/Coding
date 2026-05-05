"""catchup: add historical columns missing from pre-Alembic schemas

Revision ID: c7e9d2b4f81a
Revises: a18c393c631a
Create Date: 2026-05-06 10:00:00.000000

These columns were introduced by legacy migration scripts that no longer
exist (schema_migrate.py / _archived_migrations/001-011).  Any database
that was created before Alembic was adopted may be missing some or all of
them.  We add each with an existence check so the migration is idempotent
on databases that already have the full schema.

Coverage (all ADD COLUMN operations from archived migrations that are still
referenced by current ORM models):

  001  user_sessions.previous_ips
  002  arrays.tag_id / saved_password / version
  003  alerts.(task_id, is_expected, matched_rule_id)
       alert_acknowledgements.(ack_type, ack_expires_at, note)
       port_traffic.(mode, protocol)
       snapshots.task_id
       array_locks.locked_by_nickname
       alert_expectation_rules.(is_enabled, priority)
       audit_logs.result
       issues.(resolved_by_ip, resolved_by_nickname, resolution_note, updated_at)
       query_templates.(auto_monitor, monitor_interval, monitor_arrays, alert_on_mismatch)
  007  tags.(parent_id, level)
  010  user_preferences.dashboard_l1_tag_id
  011  task_sessions.expected_observers
  _apply_column_migrations  monitor_templates.consecutive_threshold

Migrations 004-006, 008-009 were CREATE TABLE operations; create_all
handles those, so they need no catch-up here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e9d2b4f81a'
down_revision: Union[str, None] = 'a18c393c631a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def col_exists(table: str, col: str) -> bool:
        """Return True if the column already exists OR the table does not exist.

        A missing table means create_all already created it with the current
        (complete) schema, so no catch-up column is needed.
        """
        if table not in existing_tables:
            return True
        return col in {c['name'] for c in inspector.get_columns(table)}

    # ── 001 ─ user_sessions ──────────────────────────────────────────────────
    us_missing = not col_exists('user_sessions', 'previous_ips')
    if us_missing:
        with op.batch_alter_table('user_sessions') as batch_op:
            batch_op.add_column(
                sa.Column('previous_ips', sa.Text(), nullable=True,
                          server_default=sa.text("'[]'"))
            )

    # ── 002 ─ arrays ─────────────────────────────────────────────────────────
    arr_missing = {
        'tag_id':         not col_exists('arrays', 'tag_id'),
        'saved_password': not col_exists('arrays', 'saved_password'),
        'version':        not col_exists('arrays', 'version'),
    }
    if any(arr_missing.values()):
        with op.batch_alter_table('arrays') as batch_op:
            if arr_missing['tag_id']:
                batch_op.add_column(
                    sa.Column('tag_id', sa.Integer(), nullable=True)
                )
            if arr_missing['saved_password']:
                batch_op.add_column(
                    sa.Column('saved_password', sa.Text(), nullable=True,
                              server_default=sa.text("''"))
                )
            if arr_missing['version']:
                batch_op.add_column(
                    sa.Column('version', sa.Integer(), nullable=True,
                              server_default=sa.text('1'))
                )

    # ── 003 ─ alerts ─────────────────────────────────────────────────────────
    al_missing = {
        'task_id':        not col_exists('alerts', 'task_id'),
        'is_expected':    not col_exists('alerts', 'is_expected'),
        'matched_rule_id': not col_exists('alerts', 'matched_rule_id'),
    }
    if any(al_missing.values()):
        with op.batch_alter_table('alerts') as batch_op:
            if al_missing['task_id']:
                batch_op.add_column(
                    sa.Column('task_id', sa.Integer(), nullable=True)
                )
            if al_missing['is_expected']:
                batch_op.add_column(
                    sa.Column('is_expected', sa.Integer(), nullable=True,
                              server_default=sa.text('0'))
                )
            if al_missing['matched_rule_id']:
                batch_op.add_column(
                    sa.Column('matched_rule_id', sa.Integer(), nullable=True)
                )
    # Backfill: existing rows must have is_expected=0, not NULL, so that API
    # filtering (is_expected == 0) works correctly on old data.
    if al_missing.get('is_expected') and 'alerts' in existing_tables:
        op.execute(sa.text(
            "UPDATE alerts SET is_expected = 0 WHERE is_expected IS NULL"
        ))

    # ── 003 ─ alert_acknowledgements ─────────────────────────────────────────
    ack_missing = {
        'ack_type':      not col_exists('alert_acknowledgements', 'ack_type'),
        'ack_expires_at': not col_exists('alert_acknowledgements', 'ack_expires_at'),
        'note':          not col_exists('alert_acknowledgements', 'note'),
    }
    if any(ack_missing.values()):
        with op.batch_alter_table('alert_acknowledgements') as batch_op:
            if ack_missing['ack_type']:
                batch_op.add_column(
                    sa.Column('ack_type', sa.String(32), nullable=True,
                              server_default=sa.text("'dismiss'"))
                )
            if ack_missing['ack_expires_at']:
                batch_op.add_column(
                    sa.Column('ack_expires_at', sa.DateTime(), nullable=True)
                )
            if ack_missing['note']:
                batch_op.add_column(
                    sa.Column('note', sa.Text(), nullable=True,
                              server_default=sa.text("''"))
                )

    # ── 003 ─ port_traffic ───────────────────────────────────────────────────
    pt_missing = {
        'mode':     not col_exists('port_traffic', 'mode'),
        'protocol': not col_exists('port_traffic', 'protocol'),
    }
    if any(pt_missing.values()):
        with op.batch_alter_table('port_traffic') as batch_op:
            if pt_missing['mode']:
                batch_op.add_column(
                    sa.Column('mode', sa.String(32), nullable=True,
                              server_default=sa.text("'auto'"))
                )
            if pt_missing['protocol']:
                batch_op.add_column(
                    sa.Column('protocol', sa.String(32), nullable=True,
                              server_default=sa.text("'ethernet'"))
                )

    # ── 003 ─ snapshots ──────────────────────────────────────────────────────
    if not col_exists('snapshots', 'task_id'):
        with op.batch_alter_table('snapshots') as batch_op:
            batch_op.add_column(
                sa.Column('task_id', sa.Integer(), nullable=True)
            )

    # ── 003 ─ array_locks ────────────────────────────────────────────────────
    if not col_exists('array_locks', 'locked_by_nickname'):
        with op.batch_alter_table('array_locks') as batch_op:
            batch_op.add_column(
                sa.Column('locked_by_nickname', sa.String(64), nullable=True)
            )

    # ── 003 ─ alert_expectation_rules ────────────────────────────────────────
    aer_missing = {
        'is_enabled': not col_exists('alert_expectation_rules', 'is_enabled'),
        'priority':   not col_exists('alert_expectation_rules', 'priority'),
    }
    if any(aer_missing.values()):
        with op.batch_alter_table('alert_expectation_rules') as batch_op:
            if aer_missing['is_enabled']:
                batch_op.add_column(
                    sa.Column('is_enabled', sa.Boolean(), nullable=True,
                              server_default=sa.text('1'))
                )
            if aer_missing['priority']:
                batch_op.add_column(
                    sa.Column('priority', sa.Integer(), nullable=True,
                              server_default=sa.text('100'))
                )

    # ── 003 ─ audit_logs ─────────────────────────────────────────────────────
    if not col_exists('audit_logs', 'result'):
        with op.batch_alter_table('audit_logs') as batch_op:
            batch_op.add_column(
                sa.Column('result', sa.String(16), nullable=True,
                          server_default=sa.text("'success'"))
            )

    # ── 003 ─ issues ─────────────────────────────────────────────────────────
    iss_missing = {
        'resolved_by_ip':       not col_exists('issues', 'resolved_by_ip'),
        'resolved_by_nickname': not col_exists('issues', 'resolved_by_nickname'),
        'resolution_note':      not col_exists('issues', 'resolution_note'),
        'updated_at':           not col_exists('issues', 'updated_at'),
    }
    if any(iss_missing.values()):
        with op.batch_alter_table('issues') as batch_op:
            if iss_missing['resolved_by_ip']:
                batch_op.add_column(
                    sa.Column('resolved_by_ip', sa.String(64), nullable=True)
                )
            if iss_missing['resolved_by_nickname']:
                batch_op.add_column(
                    sa.Column('resolved_by_nickname', sa.String(64), nullable=True)
                )
            if iss_missing['resolution_note']:
                batch_op.add_column(
                    sa.Column('resolution_note', sa.Text(), nullable=True,
                              server_default=sa.text("''"))
                )
            if iss_missing['updated_at']:
                batch_op.add_column(
                    sa.Column('updated_at', sa.DateTime(), nullable=True)
                )

    # ── 003 ─ query_templates ────────────────────────────────────────────────
    qt_missing = {
        'auto_monitor':      not col_exists('query_templates', 'auto_monitor'),
        'monitor_interval':  not col_exists('query_templates', 'monitor_interval'),
        'monitor_arrays':    not col_exists('query_templates', 'monitor_arrays'),
        'alert_on_mismatch': not col_exists('query_templates', 'alert_on_mismatch'),
    }
    if any(qt_missing.values()):
        with op.batch_alter_table('query_templates') as batch_op:
            if qt_missing['auto_monitor']:
                batch_op.add_column(
                    sa.Column('auto_monitor', sa.Boolean(), nullable=True,
                              server_default=sa.text('0'))
                )
            if qt_missing['monitor_interval']:
                batch_op.add_column(
                    sa.Column('monitor_interval', sa.Integer(), nullable=True,
                              server_default=sa.text('300'))
                )
            if qt_missing['monitor_arrays']:
                batch_op.add_column(
                    sa.Column('monitor_arrays', sa.Text(), nullable=True,
                              server_default=sa.text("'[]'"))
                )
            if qt_missing['alert_on_mismatch']:
                batch_op.add_column(
                    sa.Column('alert_on_mismatch', sa.Boolean(), nullable=True,
                              server_default=sa.text('1'))
                )

    # ── _apply_column_migrations ─ monitor_templates ─────────────────────────
    if not col_exists('monitor_templates', 'consecutive_threshold'):
        with op.batch_alter_table('monitor_templates') as batch_op:
            batch_op.add_column(
                sa.Column('consecutive_threshold', sa.Integer(), nullable=True,
                          server_default=sa.text('1'))
            )

    # ── 007 ─ tags ───────────────────────────────────────────────────────────
    tags_missing = {
        'parent_id': not col_exists('tags', 'parent_id'),
        'level':     not col_exists('tags', 'level'),
    }
    if any(tags_missing.values()):
        with op.batch_alter_table('tags') as batch_op:
            if tags_missing['parent_id']:
                batch_op.add_column(
                    sa.Column('parent_id', sa.Integer(), nullable=True)
                )
            if tags_missing['level']:
                batch_op.add_column(
                    sa.Column('level', sa.Integer(), nullable=True,
                              server_default=sa.text('1'))
                )
    # Backfill: tags that existed before hierarchy was introduced were all
    # flat "array type" tags.  Migration 007 set them to level=2 explicitly:
    #   "Existing tags become level 2 (array type), parent_id stays NULL"
    # We must match BOTH NULL and 1: batch_alter_table fills existing rows
    # with server_default=1 during table recreation, so level IS NULL alone
    # would miss every row.  Only run when level column was absent, so we
    # know all matching rows are pre-hierarchy.
    if tags_missing.get('level') and 'tags' in existing_tables:
        op.execute(sa.text(
            "UPDATE tags SET level = 2 WHERE level IS NULL OR level = 1"
        ))

    # ── 010 ─ user_preferences ───────────────────────────────────────────────
    if not col_exists('user_preferences', 'dashboard_l1_tag_id'):
        with op.batch_alter_table('user_preferences') as batch_op:
            batch_op.add_column(
                sa.Column('dashboard_l1_tag_id', sa.Integer(), nullable=True)
            )

    # ── 011 ─ task_sessions ──────────────────────────────────────────────────
    if not col_exists('task_sessions', 'expected_observers'):
        with op.batch_alter_table('task_sessions') as batch_op:
            batch_op.add_column(
                sa.Column('expected_observers', sa.Text(), nullable=True,
                          server_default=sa.text("'[]'"))
            )


def downgrade() -> None:
    # These columns existed in production before Alembic was introduced.
    # Dropping them on downgrade would lose real data, so downgrade is a no-op.
    pass
