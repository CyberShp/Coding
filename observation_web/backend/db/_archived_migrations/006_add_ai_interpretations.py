"""Migration 006: Add ai_interpretations table for cached AI alert interpretations."""

version = 6


def upgrade(conn):
    from .utils import create_table_if_not_exists

    create_table_if_not_exists(
        conn,
        "ai_interpretations",
        "id INTEGER PRIMARY KEY, "
        "alert_id INTEGER NOT NULL UNIQUE, "
        "interpretation TEXT NOT NULL, "
        "model_name VARCHAR(64) DEFAULT '', "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    )
