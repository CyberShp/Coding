"""Migration 009: Add the per-array card inventory table."""

version = 9


def upgrade(conn):
    from .utils import create_table_if_not_exists
    from sqlalchemy import text

    create_table_if_not_exists(
        conn,
        "card_inventory",
        """
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
        """,
    )
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(card_inventory)"))}
    for column in ("array_id", "board_id", "model"):
        if column in columns:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_card_inventory_{column} "
                f"ON card_inventory({column})"
            ))
