"""
Database configuration and session management.
"""

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from typing import AsyncGenerator

from ..config import get_config


class Base(DeclarativeBase):
    pass

# Async engine for SQLite
_async_engine = None
AsyncSessionLocal = None


def get_database_url() -> str:
    """Get database URL with absolute path"""
    config = get_config()
    db_path = config.database.path
    
    # If path is relative, make it relative to the config directory
    if not os.path.isabs(db_path):
        config_dir = Path(__file__).parent.parent.parent  # observation_web directory
        db_path = str(config_dir / db_path)
    
    return f"sqlite+aiosqlite:///{db_path}"


def init_db():
    """Initialize database with optimized settings for multi-user access"""
    global _async_engine, AsyncSessionLocal
    
    config = get_config()
    database_url = get_database_url()
    
    # Connection pool settings for concurrent access
    _async_engine = create_async_engine(
        database_url,
        echo=config.database.echo,
        pool_size=10,  # Number of connections to keep open
        max_overflow=20,  # Additional connections when pool is exhausted
        pool_timeout=30,  # Seconds to wait for connection
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_pre_ping=True,  # Verify connections before use
    )

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


async def create_tables():
    """Create all tables and run migrations"""
    from ..models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, array_lock, alert_rule, audit_log, issue  # Import models to register them
    from .migrations import run_migrations

    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_migrations)


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
