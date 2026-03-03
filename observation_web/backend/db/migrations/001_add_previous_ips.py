"""Migration 001: Add previous_ips column to user_sessions."""

from sqlalchemy import text

version = 1


def upgrade(conn):
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")
    )
    if not result.fetchone():
        return
    result = conn.execute(text("PRAGMA table_info(user_sessions)"))
    columns = [row[1] for row in result.fetchall()]
    if "previous_ips" not in columns:
        conn.execute(text("ALTER TABLE user_sessions ADD COLUMN previous_ips TEXT DEFAULT '[]'"))
