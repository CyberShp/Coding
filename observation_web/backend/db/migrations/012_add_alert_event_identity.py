"""Add stable source event identity for idempotent alert ingestion."""

from sqlalchemy import text

from .utils import add_column_if_not_exists

version = 12


def upgrade(conn):
    add_column_if_not_exists(conn, "alerts", "source_event_id", "VARCHAR(128)")
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_array_source_event "
        "ON alerts (array_id, source_event_id)"
    ))
