"""Migration 005: Add observer_configs table for built-in observer overrides."""

version = 5


def upgrade(conn):
    from .utils import create_table_if_not_exists

    create_table_if_not_exists(
        conn,
        "observer_configs",
        "id INTEGER PRIMARY KEY, "
        "observer_name VARCHAR(64) NOT NULL UNIQUE, "
        "enabled BOOLEAN DEFAULT 1, "
        "interval INTEGER, "
        "params_json TEXT DEFAULT '{}', "
        "updated_by VARCHAR(64) DEFAULT '', "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    )
