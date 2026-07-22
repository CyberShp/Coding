"""
Database configuration and session management.
"""

import logging
import os
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from typing import AsyncGenerator

from ..config import get_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass

# Async engine for SQLite
_async_engine = None
AsyncSessionLocal = None


def get_async_engine():
    """Return the async engine (for fallback table creation)."""
    return _async_engine


def get_database_url() -> str:
    """Get database URL.

    If ``config.database.url`` is set (e.g. postgresql+asyncpg://…) it wins and
    switches the engine off SQLite. Otherwise fall back to the SQLite path.
    An ``OBSERVATION_DB_URL`` env var overrides both (handy for staging/prod).
    """
    env_url = os.environ.get("OBSERVATION_DB_URL")
    if env_url:
        return env_url

    config = get_config()
    if getattr(config.database, "url", ""):
        return config.database.url

    db_path = config.database.path
    # If path is relative, make it relative to the config directory
    if not os.path.isabs(db_path):
        config_dir = Path(__file__).parent.parent.parent  # observation_web directory
        db_path = str(config_dir / db_path)

    return f"sqlite+aiosqlite:///{db_path}"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def init_db():
    """Initialize database with optimized settings for multi-user access"""
    global _async_engine, AsyncSessionLocal
    
    config = get_config()
    database_url = get_database_url()
    
    # Connection pool settings for concurrent access
    # SQLite serialises all writes regardless of pool size, so a large pool
    # only adds lock contention (SQLITE_BUSY) without improving write throughput.
    # Keep the pool modest; reads still scale via WAL.  (A true fix for heavy
    # concurrent writes is Postgres — tracked as a known scaling limit.)
    _async_engine = create_async_engine(
        database_url,
        echo=config.database.echo,
        pool_size=5,       # Connections kept open
        max_overflow=10,   # Extra connections under burst (15 max total)
        pool_timeout=30,   # Seconds to wait for a connection
        pool_recycle=3600, # Recycle connections after 1 hour
        pool_pre_ping=True, # Verify connections before use
    )

    # SQLite-only pragmas — skipped entirely on Postgres/other backends.
    if _is_sqlite(database_url):
        @event.listens_for(_async_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            """Configure SQLite pragmas for optimal performance"""
            cursor = dbapi_conn.cursor()
            # WAL mode for better concurrent read/write
            cursor.execute("PRAGMA journal_mode=WAL")
            # Increased busy timeout for multi-user access
            cursor.execute("PRAGMA busy_timeout=10000")
            # Synchronous mode - NORMAL is faster than FULL, still safe with WAL
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Cache size in KB (negative = KB, positive = pages)
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            # Memory-mapped I/O for faster reads
            cursor.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            # Temp storage in memory
            cursor.execute("PRAGMA temp_store=MEMORY")
            # Enable foreign key constraints
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    AsyncSessionLocal = sessionmaker(
        _async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def _get_alembic_config():
    """Build Alembic Config pointing to our backend/alembic directory."""
    from alembic.config import Config as AlembicConfig

    project_root = Path(__file__).parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    return cfg


_BASELINE_REVISION = "a18c393c631a"


def _reconcile_orphan_version(cfg):
    """Reset databases stamped with a revision no longer in the migration graph.

    Historical databases may carry an ``alembic_version`` left behind by the
    old self-rolled migration systems (schema_migrate.py / _archived_migrations),
    e.g. ``e31b7a9c204d``.  ``upgrade head`` on such a DB raises
    ``Can't locate revision`` and the whole service fails to start.

    Since the catch-up migration (c7e9d2b4f81a) is fully idempotent — every
    ADD COLUMN is guarded by a column-existence check — we can safely re-stamp
    the baseline and let ``upgrade head`` re-run the catch-up, which fills only
    the columns that are genuinely missing.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text as _text

    # This heals a SQLite-only legacy residue; on Postgres/other backends the
    # orphan-revision situation doesn't apply and the sync driver differs.
    if not _is_sqlite(get_database_url()):
        return

    known = {sc.revision for sc in ScriptDirectory.from_config(cfg).walk_revisions()}

    db_url = get_database_url().replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            has_table = conn.execute(_text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='alembic_version'"
            )).fetchone()
            if has_table is None:
                return  # no version table yet; upgrade will establish it
            current = conn.execute(
                _text("SELECT version_num FROM alembic_version")
            ).scalar()
            if not current or current in known:
                return
            logger.warning(
                "alembic_version=%s is not in the migration graph (legacy residue); "
                "resetting to baseline %s so the idempotent catch-up migration "
                "restores the schema on upgrade head",
                current, _BASELINE_REVISION,
            )
            # Overwrite directly via SQL: alembic's own stamp/upgrade would first
            # try to resolve the orphan revision and crash with "Can't locate revision".
            conn.execute(
                _text("UPDATE alembic_version SET version_num = :v"),
                {"v": _BASELINE_REVISION},
            )
    finally:
        engine.dispose()


def _run_alembic_upgrade():
    """Run alembic upgrade head (synchronous — called via run_in_executor)."""
    from alembic import command
    try:
        cfg = _get_alembic_config()
        # Heal databases pinned to a revision that no longer exists before
        # attempting the upgrade, otherwise upgrade head crashes on startup.
        _reconcile_orphan_version(cfg)
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as e:
        logger.error("Alembic migration failed: %s", e)
        raise


def _stamp_head_if_needed():
    """Safety net: stamp baseline revision when alembic_version is absent.

    upgrade head (called before this function in create_tables) normally
    handles all migration tracking.  This function covers the rare edge case
    where a pre-Alembic database somehow exits upgrade without alembic_version
    being created.

    We stamp the *baseline* revision (not head) so that the catch-up
    migration (c7e9d2b4f81a) will run on the next startup and add any
    columns that were missing from the old schema.  Stamping head directly
    would skip that migration, leaving previous_ips / consecutive_threshold
    absent.
    """
    from alembic import command
    from sqlalchemy import create_engine, text as _text

    # SQLite-only safety net (pre-Alembic residue + sqlite sync driver).
    if not _is_sqlite(get_database_url()):
        return

    db_url = get_database_url().replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                _text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
            )
            if result.fetchone() is not None:
                return  # upgrade head already set the version; nothing to do

            logger.info(
                "No alembic_version after upgrade; stamping baseline (%s) "
                "so catch-up migration runs on next start",
                _BASELINE_REVISION,
            )
            cfg = _get_alembic_config()
            command.stamp(cfg, _BASELINE_REVISION)
    finally:
        engine.dispose()


async def create_tables():
    """Create tables (create_all) and apply Alembic migrations."""
    import asyncio
    from ..models import (  # noqa: F401
        array, alert, query, lifecycle, scheduler, traffic,
        task_session, snapshot, tag, user_session, user_preference,
        array_lock, alert_rule, audit_log, issue, monitor_template,
        observer_config, ai_interpretation, card_inventory, alerts_v2,
        expected_window, observer_snapshot, agent_heartbeat, card_presence,
        viewer_profile, system_config, enrollment, baseline, causal,
        metric_sample, user_account,
    )

    # Step 1: create_all for new databases (idempotent on existing ones)
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Step 2: apply any pending Alembic migrations (sync, via thread)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_alembic_upgrade)

    # Step 3: stamp head for databases that pre-date Alembic
    await loop.run_in_executor(None, _stamp_head_if_needed)

    # Step 4: startup diagnostic — verify all expected tables exist
    async with _async_engine.begin() as conn:
        def _check_tables(sync_conn):
            result = sync_conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            existing = {row[0] for row in result.fetchall()}
            expected = set(Base.metadata.tables.keys())
            missing = expected - existing
            if missing:
                logger.error("MISSING TABLES after create_all: %s", missing)
            else:
                logger.info("All %d tables verified", len(expected))

        await conn.run_sync(_check_tables)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session"""
    if AsyncSessionLocal is None:
        init_db()
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
