"""Migration 008: Add user_preferences table for personal view settings."""

version = 8


def upgrade(conn):
    from .utils import create_table_if_not_exists
    from sqlalchemy import text

    create_table_if_not_exists(
        conn,
        "user_preferences",
        "ip VARCHAR(64) PRIMARY KEY, default_tag_id INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    )
