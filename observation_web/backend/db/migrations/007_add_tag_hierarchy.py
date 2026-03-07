"""Migration 007: Add tag hierarchy (parent_id, level) for two-level tags."""

version = 7


def upgrade(conn):
    from .utils import add_column_if_not_exists
    from sqlalchemy import text

    add_column_if_not_exists(conn, "tags", "parent_id", "INTEGER", default="NULL")
    add_column_if_not_exists(conn, "tags", "level", "INTEGER", default="1")
    # Existing tags become level 2 (array type), parent_id stays NULL
    conn.execute(text("UPDATE tags SET level = 2 WHERE level IS NULL OR level = 1"))
