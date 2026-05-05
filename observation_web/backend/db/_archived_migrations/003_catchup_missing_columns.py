"""Migration 003: Catch up missing columns across 8 tables (21 columns)."""

version = 3


def upgrade(conn):
    from .utils import add_column_if_not_exists, table_exists

    # alerts 表
    if table_exists(conn, "alerts"):
        add_column_if_not_exists(conn, "alerts", "task_id", "INTEGER")
        add_column_if_not_exists(conn, "alerts", "is_expected", "INTEGER", default=0)
        add_column_if_not_exists(conn, "alerts", "matched_rule_id", "INTEGER")
        # Backfill NULLs for pre-existing rows (SQLite ADD COLUMN DEFAULT only affects new rows)
        from sqlalchemy import text
        conn.execute(text("UPDATE alerts SET is_expected = 0 WHERE is_expected IS NULL"))

    # alert_acknowledgements 表
    if table_exists(conn, "alert_acknowledgements"):
        add_column_if_not_exists(conn, "alert_acknowledgements", "ack_type", "VARCHAR(32)", default="'dismiss'")
        add_column_if_not_exists(conn, "alert_acknowledgements", "ack_expires_at", "DATETIME")
        add_column_if_not_exists(conn, "alert_acknowledgements", "note", "TEXT", default="''")

    # port_traffic 表
    if table_exists(conn, "port_traffic"):
        add_column_if_not_exists(conn, "port_traffic", "mode", "VARCHAR(32)", default="''")
        add_column_if_not_exists(conn, "port_traffic", "protocol", "VARCHAR(32)", default="''")

    # snapshots 表
    if table_exists(conn, "snapshots"):
        add_column_if_not_exists(conn, "snapshots", "task_id", "INTEGER")

    # array_locks 表
    if table_exists(conn, "array_locks"):
        add_column_if_not_exists(conn, "array_locks", "locked_by_nickname", "VARCHAR(64)", default="''")

    # alert_expectation_rules 表
    if table_exists(conn, "alert_expectation_rules"):
        add_column_if_not_exists(conn, "alert_expectation_rules", "is_enabled", "BOOLEAN", default=1)
        add_column_if_not_exists(conn, "alert_expectation_rules", "priority", "INTEGER", default=100)

    # audit_logs 表
    if table_exists(conn, "audit_logs"):
        add_column_if_not_exists(conn, "audit_logs", "result", "VARCHAR(16)", default="'success'")

    # issues 表
    if table_exists(conn, "issues"):
        add_column_if_not_exists(conn, "issues", "resolved_by_ip", "VARCHAR(64)")
        add_column_if_not_exists(conn, "issues", "resolved_by_nickname", "VARCHAR(64)")
        add_column_if_not_exists(conn, "issues", "resolution_note", "TEXT", default="''")
        add_column_if_not_exists(conn, "issues", "updated_at", "DATETIME")

    # query_templates 表
    if table_exists(conn, "query_templates"):
        add_column_if_not_exists(conn, "query_templates", "auto_monitor", "BOOLEAN", default=0)
        add_column_if_not_exists(conn, "query_templates", "monitor_interval", "INTEGER", default=300)
        add_column_if_not_exists(conn, "query_templates", "monitor_arrays", "TEXT", default="'[]'")
        add_column_if_not_exists(conn, "query_templates", "alert_on_mismatch", "BOOLEAN", default=0)
