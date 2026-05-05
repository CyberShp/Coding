"""Tests for backend/db/database.py — Database initialization and sessions."""
import os
import pytest
import pytest_asyncio
import sqlalchemy as sa
from pathlib import Path
from backend.db.database import init_db, create_tables, get_db, get_database_url, Base


class TestDatabaseUrl:
    def test_default_url(self):
        url = get_database_url()
        assert "sqlite" in url
        assert "aiosqlite" in url

    def test_url_format(self):
        url = get_database_url()
        assert url.startswith("sqlite+aiosqlite://")


@pytest.mark.asyncio
class TestDatabaseInit:
    async def test_init_and_create_tables(self):
        """DB initialization should not crash."""
        init_db()
        await create_tables()

    async def test_get_db_session(self):
        """Session generator should yield a session."""
        init_db()
        await create_tables()
        async for session in get_db():
            assert session is not None
            break


class TestAlembicCatchupMigration:
    """Regression: catch-up migration adds historical columns to pre-Alembic DBs."""

    def _run_upgrade_head(self, db_path: str) -> None:
        """Run alembic upgrade head against *db_path*.

        env.py resolves the DB URL via get_config(), which is a global
        singleton.  We patch it directly so Alembic operates on our temp file
        rather than the real database from config.json.
        """
        from alembic.config import Config as AlembicConfig
        from alembic import command
        import backend.config as config_mod
        from backend.config import AppConfig, DatabaseConfig

        project_root = Path(__file__).parent.parent
        cfg = AlembicConfig(str(project_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(project_root / "backend" / "alembic"))

        # Replace the global singleton so env.py._get_sync_database_url sees our path
        mock_app_cfg = AppConfig()
        mock_app_cfg.database = DatabaseConfig(path=db_path)
        old_config = config_mod._config
        config_mod._config = mock_app_cfg
        try:
            command.upgrade(cfg, "head")
        finally:
            config_mod._config = old_config

    def test_catchup_adds_missing_columns_to_pre_alembic_db(self, tmp_path):
        """
        A pre-Alembic database that is missing previous_ips and
        consecutive_threshold must have both columns after upgrade head.

        Red scenario: DB schema created BEFORE those columns existed
        (no previous_ips in user_sessions, no consecutive_threshold in
        monitor_templates, no alembic_version table).
        """
        db_path = str(tmp_path / "pre_alembic.db")

        # Build a minimal pre-Alembic schema without the historical columns
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(sa.text("""
                CREATE TABLE user_sessions (
                    id INTEGER PRIMARY KEY,
                    ip VARCHAR(64) NOT NULL,
                    nickname VARCHAR(64) DEFAULT '',
                    first_seen DATETIME,
                    last_seen DATETIME,
                    is_active BOOLEAN DEFAULT 1
                )
            """))
            conn.execute(sa.text("""
                CREATE TABLE monitor_templates (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    description TEXT DEFAULT '',
                    category VARCHAR(32) DEFAULT 'custom',
                    command TEXT NOT NULL,
                    command_type VARCHAR(16) DEFAULT 'shell',
                    interval INTEGER DEFAULT 60,
                    timeout INTEGER DEFAULT 30,
                    match_type VARCHAR(16) DEFAULT 'regex',
                    match_expression TEXT NOT NULL,
                    match_condition VARCHAR(16) DEFAULT 'found',
                    match_threshold TEXT,
                    alert_level VARCHAR(16) DEFAULT 'warning',
                    alert_message_template TEXT DEFAULT '',
                    cooldown INTEGER DEFAULT 300,
                    is_enabled BOOLEAN DEFAULT 1,
                    is_builtin BOOLEAN DEFAULT 0,
                    created_by VARCHAR(64) DEFAULT '',
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
        engine.dispose()

        self._run_upgrade_head(db_path)

        # Verify columns were added by the catch-up migration
        verify_engine = sa.create_engine(f"sqlite:///{db_path}")
        inspector = sa.inspect(verify_engine)

        us_cols = {col["name"] for col in inspector.get_columns("user_sessions")}
        assert "previous_ips" in us_cols, (
            "catch-up migration must add previous_ips to user_sessions"
        )

        mt_cols = {col["name"] for col in inspector.get_columns("monitor_templates")}
        assert "consecutive_threshold" in mt_cols, (
            "catch-up migration must add consecutive_threshold to monitor_templates"
        )

        verify_engine.dispose()

    def test_catchup_is_idempotent_on_full_schema(self, tmp_path):
        """
        upgrade head must not raise when both columns already exist
        (idempotency: fresh DB created via create_all has all columns).
        """
        db_path = str(tmp_path / "full_schema.db")

        # Build schema with all columns already present
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(sa.text("""
                CREATE TABLE user_sessions (
                    id INTEGER PRIMARY KEY,
                    ip VARCHAR(64) NOT NULL,
                    previous_ips TEXT DEFAULT '[]',
                    nickname VARCHAR(64) DEFAULT '',
                    first_seen DATETIME,
                    last_seen DATETIME,
                    is_active BOOLEAN DEFAULT 1
                )
            """))
            conn.execute(sa.text("""
                CREATE TABLE monitor_templates (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    consecutive_threshold INTEGER DEFAULT 1,
                    description TEXT DEFAULT '',
                    category VARCHAR(32) DEFAULT 'custom',
                    command TEXT NOT NULL,
                    command_type VARCHAR(16) DEFAULT 'shell',
                    interval INTEGER DEFAULT 60,
                    timeout INTEGER DEFAULT 30,
                    match_type VARCHAR(16) DEFAULT 'regex',
                    match_expression TEXT NOT NULL,
                    match_condition VARCHAR(16) DEFAULT 'found',
                    match_threshold TEXT,
                    alert_level VARCHAR(16) DEFAULT 'warning',
                    alert_message_template TEXT DEFAULT '',
                    cooldown INTEGER DEFAULT 300,
                    is_enabled BOOLEAN DEFAULT 1,
                    is_builtin BOOLEAN DEFAULT 0,
                    created_by VARCHAR(64) DEFAULT '',
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
        engine.dispose()

        # Must not raise even though columns already exist
        self._run_upgrade_head(db_path)


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
