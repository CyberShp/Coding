"""
Migration utility functions for schema changes.

Use these in migration scripts to safely add/rename columns
and check column existence. Supports SQLite.
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in the table. SQLite-compatible."""
    try:
        result = conn.execute(text(f"PRAGMA table_info({table})"))
        rows = result.fetchall()
        for row in rows:
            if row[1] == column:  # row[1] is column name in pragma output
                return True
        return False
    except Exception as e:
        logger.warning("column_exists failed for %s.%s: %s", table, column, e)
        return False


def add_column_if_not_exists(conn, table: str, column: str, col_type: str, default=None):
    """
    Add a column to a table if it does not exist.
    SQLite does not support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
    so we check first.
    """
    if column_exists(conn, table, column):
        logger.debug("Column %s.%s already exists, skipping", table, column)
        return
    default_clause = f" DEFAULT {default}" if default is not None else ""
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"))
    logger.info("Added column %s.%s", table, column)


def rename_column_if_exists(conn, table: str, old_name: str, new_name: str):
    """
    Rename a column if it exists. SQLite 3.25.0+ supports ALTER TABLE RENAME COLUMN.
    For older SQLite, this would require table recreation - not implemented.
    """
    if not column_exists(conn, table, old_name):
        logger.debug("Column %s.%s does not exist, skipping rename", table, old_name)
        return
    if column_exists(conn, table, new_name):
        logger.debug("Column %s.%s already exists, skipping rename", table, new_name)
        return
    conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}"))
    logger.info("Renamed column %s.%s -> %s", table, old_name, new_name)


def table_exists(conn, table: str) -> bool:
    """Check if a table exists. SQLite-compatible."""
    try:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
        return result.fetchone() is not None
    except Exception as e:
        logger.warning("table_exists failed for %s: %s", table, e)
        return False


def create_table_if_not_exists(conn, table: str, columns_sql: str):
    """
    Create a table if it does not exist.
    columns_sql: full column definitions, e.g. "id INTEGER PRIMARY KEY, name TEXT"
    """
    if table_exists(conn, table):
        logger.debug("Table %s already exists, skipping", table)
        return
    conn.execute(text(f"CREATE TABLE {table} ({columns_sql})"))
    logger.info("Created table %s", table)
