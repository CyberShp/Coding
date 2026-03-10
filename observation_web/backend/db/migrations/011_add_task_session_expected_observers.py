"""Add expected_observers column to task_sessions table."""

version = 11


def upgrade(conn):
    from .utils import add_column_if_not_exists

    add_column_if_not_exists(
        conn,
        "task_sessions",
        "expected_observers",
        "TEXT",
        default="'[]'",
    )
