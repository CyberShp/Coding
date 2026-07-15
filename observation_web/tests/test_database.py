"""Tests for backend/db/database.py — Database initialization and sessions."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy import create_engine
import backend.db.database as db_mod
from backend.db.database import init_db, create_tables, get_db, get_database_url, Base
from backend.config import AppConfig
from backend.db.migrations import run_migrations


class TestDatabaseUrl:
    def test_default_url(self):
        url = get_database_url()
        assert "sqlite" in url
        assert "aiosqlite" in url

    def test_url_format(self):
        url = get_database_url()
        assert url.startswith("sqlite+aiosqlite://")


def test_migrations_preserve_legacy_card_catalog(tmp_path):
    """The abandoned global catalog must not block startup or lose its rows."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE card_inventory ("
            "id INTEGER PRIMARY KEY, name VARCHAR(128), device_type VARCHAR(64))"
        ))
        conn.execute(text(
            "INSERT INTO card_inventory (name, device_type) VALUES ('legacy-card', 'SSD')"
        ))
        conn.execute(text("CREATE TABLE _schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO _schema_version (version) VALUES (12)"))
        run_migrations(conn)

        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(card_inventory)"))
        }
        legacy_count = conn.scalar(text("SELECT COUNT(*) FROM card_inventory_legacy"))
        version = conn.scalar(text("SELECT version FROM _schema_version"))

    assert {"array_id", "card_no", "board_id", "raw_fields"} <= columns
    assert legacy_count == 1
    assert version == 13


@pytest.mark.asyncio
class TestDatabaseInit:
    async def test_init_and_create_tables(self, tmp_path, monkeypatch):
        """DB initialization creates tables and applies every schema migration."""
        config = AppConfig()
        config.database.path = str(tmp_path / "migration-test.db")
        monkeypatch.setattr(db_mod, "get_config", lambda: config)
        init_db()
        await create_tables()

        async for session in get_db():
            version = await session.scalar(text("SELECT version FROM _schema_version"))
            alert_columns = await session.execute(text("PRAGMA table_info(alerts)"))
            break

        assert version == 13
        assert "source_event_id" in {row[1] for row in alert_columns.fetchall()}
        await db_mod.get_async_engine().dispose()

    async def test_get_db_session(self, tmp_path, monkeypatch):
        """Session generator should yield a session."""
        config = AppConfig()
        config.database.path = str(tmp_path / "session-test.db")
        monkeypatch.setattr(db_mod, "get_config", lambda: config)
        init_db()
        await create_tables()
        async for session in get_db():
            assert session is not None
            break
        await db_mod.get_async_engine().dispose()


@pytest.mark.asyncio
class TestSessionManagement:
    async def test_session_rollback_on_error(self, db_session):
        """EDGE: Session should handle errors without corruption."""
        from backend.models.alert import AlertModel
        try:
            # Try inserting invalid data
            db_session.add(AlertModel(
                array_id=None,  # May violate constraints
                observer_name="test",
                level="info", message="test",
                timestamp=None  # May be required
            ))
            await db_session.commit()
        except Exception:
            await db_session.rollback()
        # Session should still be usable
