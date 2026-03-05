"""Migration 004: Add monitor_templates table."""

version = 4


def upgrade(conn):
    from .utils import create_table_if_not_exists

    create_table_if_not_exists(
        conn,
        "monitor_templates",
        "id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, description TEXT DEFAULT '', "
        "category VARCHAR(32) DEFAULT 'custom', command TEXT NOT NULL, command_type VARCHAR(16) DEFAULT 'shell', "
        "interval INTEGER DEFAULT 60, timeout INTEGER DEFAULT 30, match_type VARCHAR(16) DEFAULT 'regex', "
        "match_expression TEXT NOT NULL, match_condition VARCHAR(16) DEFAULT 'found', match_threshold TEXT, "
        "alert_level VARCHAR(16) DEFAULT 'warning', alert_message_template TEXT DEFAULT '', cooldown INTEGER DEFAULT 300, "
        "is_enabled BOOLEAN DEFAULT 1, is_builtin BOOLEAN DEFAULT 0, created_by VARCHAR(64) DEFAULT '', "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    )
