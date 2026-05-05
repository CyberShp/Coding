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

    def _build_pre_alembic_db(self, db_path: str) -> None:
        """Create a pre-Alembic database missing all historical ADD COLUMN columns.

        Includes the tables that archived migrations 001-011 operated on,
        but only with the original columns each table had before those
        migrations ran.
        """
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            # user_sessions — missing previous_ips (001)
            conn.execute(sa.text("""
                CREATE TABLE user_sessions (
                    id INTEGER PRIMARY KEY,
                    ip VARCHAR(64) NOT NULL,
                    nickname VARCHAR(64) DEFAULT '',
                    first_seen DATETIME, last_seen DATETIME,
                    is_active BOOLEAN DEFAULT 1
                )
            """))
            # monitor_templates — missing consecutive_threshold (_apply_column_migrations)
            conn.execute(sa.text("""
                CREATE TABLE monitor_templates (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    description TEXT DEFAULT '',
                    category VARCHAR(32) DEFAULT 'custom',
                    command TEXT NOT NULL,
                    command_type VARCHAR(16) DEFAULT 'shell',
                    interval INTEGER DEFAULT 60, timeout INTEGER DEFAULT 30,
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
                    created_at DATETIME, updated_at DATETIME
                )
            """))
            # arrays — missing tag_id, saved_password, version (002)
            conn.execute(sa.text("""
                CREATE TABLE arrays (
                    id INTEGER PRIMARY KEY,
                    array_id VARCHAR(64) NOT NULL UNIQUE,
                    name VARCHAR(128) NOT NULL,
                    host VARCHAR(256) NOT NULL UNIQUE,
                    port INTEGER DEFAULT 22,
                    username VARCHAR(64) DEFAULT 'root',
                    key_path VARCHAR(512) DEFAULT '',
                    folder VARCHAR(128) DEFAULT ''
                )
            """))
            # alerts — missing task_id, is_expected, matched_rule_id (003)
            conn.execute(sa.text("""
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY,
                    array_id VARCHAR(64) NOT NULL,
                    observer_name VARCHAR(64) NOT NULL,
                    level VARCHAR(16) NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT DEFAULT '{}',
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME
                )
            """))
            # tags — missing parent_id, level (007)
            conn.execute(sa.text("""
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(64) NOT NULL UNIQUE,
                    color VARCHAR(32) DEFAULT '#409eff',
                    description TEXT DEFAULT '',
                    created_at DATETIME, updated_at DATETIME
                )
            """))
        engine.dispose()

    def test_catchup_adds_missing_columns_to_pre_alembic_db(self, tmp_path):
        """
        A pre-Alembic database missing historical ADD COLUMN columns must
        have all of them present after upgrade head.

        Verifies the columns specifically called out in gpt52's P1/P2 reviews:
          - user_sessions.previous_ips (001)
          - monitor_templates.consecutive_threshold (_apply_column_migrations)
          - arrays.tag_id / version / saved_password (002)
          - alerts.task_id / is_expected (003)
          - tags.parent_id / level (007)
        """
        db_path = str(tmp_path / "pre_alembic.db")
        self._build_pre_alembic_db(db_path)

        self._run_upgrade_head(db_path)

        verify_engine = sa.create_engine(f"sqlite:///{db_path}")
        inspector = sa.inspect(verify_engine)

        def cols(table):
            return {c["name"] for c in inspector.get_columns(table)}

        # 001
        assert "previous_ips" in cols("user_sessions"), \
            "previous_ips must be added to user_sessions"

        # _apply_column_migrations
        assert "consecutive_threshold" in cols("monitor_templates"), \
            "consecutive_threshold must be added to monitor_templates"

        # 002
        arr_cols = cols("arrays")
        assert "tag_id" in arr_cols, "tag_id must be added to arrays"
        assert "saved_password" in arr_cols, "saved_password must be added to arrays"
        assert "version" in arr_cols, "version must be added to arrays"

        # 003
        al_cols = cols("alerts")
        assert "task_id" in al_cols, "task_id must be added to alerts"
        assert "is_expected" in al_cols, "is_expected must be added to alerts"

        # 007
        tag_cols = cols("tags")
        assert "parent_id" in tag_cols, "parent_id must be added to tags"
        assert "level" in tag_cols, "level must be added to tags"

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
