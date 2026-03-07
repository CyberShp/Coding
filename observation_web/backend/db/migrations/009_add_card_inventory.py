"""Migration 009: Add card_inventory table for global card catalog."""

version = 9


def upgrade(conn):
    from .utils import create_table_if_not_exists
    from sqlalchemy import text

    create_table_if_not_exists(
        conn,
        "card_inventory",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(128) NOT NULL,
        device_type VARCHAR(64) NOT NULL,
        model VARCHAR(128) DEFAULT '',
        description TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        """,
    )
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_card_inventory_name ON card_inventory(name)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_card_inventory_device_type ON card_inventory(device_type)"
    ))
