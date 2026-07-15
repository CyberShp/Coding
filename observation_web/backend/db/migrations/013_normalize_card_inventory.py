"""Normalize card_inventory after its early global-catalog prototype."""

from sqlalchemy import text

from .utils import add_column_if_not_exists, table_exists

version = 13


_CURRENT_TABLE_SQL = """
    CREATE TABLE card_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        array_id VARCHAR(64) NOT NULL,
        card_no VARCHAR(32) DEFAULT '',
        board_id VARCHAR(64) DEFAULT '',
        health_state VARCHAR(32) DEFAULT '',
        running_state VARCHAR(32) DEFAULT '',
        model VARCHAR(256) DEFAULT '',
        raw_fields TEXT DEFAULT '{}',
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_card_array_cardno UNIQUE (array_id, card_no)
    )
"""


def _next_legacy_name(conn):
    base = "card_inventory_legacy"
    name = base
    suffix = 1
    while table_exists(conn, name):
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def upgrade(conn):
    if not table_exists(conn, "card_inventory"):
        conn.execute(text(_CURRENT_TABLE_SQL))
    else:
        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(card_inventory)"))
        }
        # Version 009 briefly used this name for a manually maintained global
        # catalog. Preserve that data, then restore the runtime table shape.
        if "array_id" not in columns and {"name", "device_type"} & columns:
            legacy_name = _next_legacy_name(conn)
            conn.execute(text(f"ALTER TABLE card_inventory RENAME TO {legacy_name}"))
            conn.execute(text(_CURRENT_TABLE_SQL))
        else:
            add_column_if_not_exists(conn, "card_inventory", "array_id", "VARCHAR(64)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "card_no", "VARCHAR(32)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "board_id", "VARCHAR(64)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "health_state", "VARCHAR(32)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "running_state", "VARCHAR(32)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "model", "VARCHAR(256)", default="''")
            add_column_if_not_exists(conn, "card_inventory", "raw_fields", "TEXT", default="'{}'")
            add_column_if_not_exists(conn, "card_inventory", "last_updated", "DATETIME")

    for column in ("array_id", "board_id", "model"):
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_card_inventory_{column} "
            f"ON card_inventory({column})"
        ))
