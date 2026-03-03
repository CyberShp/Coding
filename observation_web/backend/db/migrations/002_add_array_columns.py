"""Migration 002: Add tag_id, saved_password, version columns to arrays."""

from sqlalchemy import text

version = 2


def upgrade(conn):
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='arrays'")
    )
    if not result.fetchone():
        return
    result = conn.execute(text("PRAGMA table_info(arrays)"))
    columns = [row[1] for row in result.fetchall()]
    if "tag_id" not in columns:
        conn.execute(
            text(
                "ALTER TABLE arrays ADD COLUMN tag_id INTEGER "
                "REFERENCES tags(id) ON DELETE SET NULL"
            )
        )
    if "saved_password" not in columns:
        conn.execute(text("ALTER TABLE arrays ADD COLUMN saved_password TEXT DEFAULT ''"))
    if "version" not in columns:
        conn.execute(text("ALTER TABLE arrays ADD COLUMN version INTEGER DEFAULT 1"))
