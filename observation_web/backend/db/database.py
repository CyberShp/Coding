"""
Database configuration and session management.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from typing import AsyncGenerator

from ..config import get_config

Base = declarative_base()

# Async engine for SQLite
_async_engine = None
AsyncSessionLocal = None


def get_database_url() -> str:
    """Get database URL"""
    config = get_config()
    return f"sqlite+aiosqlite:///{config.database.path}"


def init_db():
    """Initialize database"""
    global _async_engine, AsyncSessionLocal
    
    config = get_config()
    database_url = get_database_url()
    
    _async_engine = create_async_engine(
        database_url,
        echo=config.database.echo,
    )
    
    AsyncSessionLocal = sessionmaker(
        _async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_tables():
    """Create all tables"""
    from ..models import array, alert, query  # Import models to register them
    
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
