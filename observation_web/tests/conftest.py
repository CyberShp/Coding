"""Shared fixtures for observation_web tests."""
import sys
import os
import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.database import init_db, create_tables, get_db, Base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """Create a fresh in-memory database for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Import ALL models so Base.metadata is fully populated before create_all
    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def app_client():
    """Create test client for API testing with a fresh in-memory database."""
    import backend.db.database as db_mod
    from httpx import AsyncClient, ASGITransport
    from backend.main import create_app

    # Override engine to use in-memory DB so we always have the latest schema
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the module-level globals used by the rest of the application
    old_engine = db_mod._async_engine
    old_session = db_mod.AsyncSessionLocal
    db_mod._async_engine = engine
    db_mod.AsyncSessionLocal = session_factory

    # Import ALL models so Base.metadata is fully populated, then create tables
    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Teardown
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    db_mod._async_engine = old_engine
    db_mod.AsyncSessionLocal = old_session


@pytest_asyncio.fixture
async def app_client_with_db():
    """App client + DB session sharing the same in-memory DB for direct data injection."""
    import backend.db.database as db_mod
    from httpx import AsyncClient, ASGITransport
    from backend.main import create_app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    old_engine = db_mod._async_engine
    old_session = db_mod.AsyncSessionLocal
    db_mod._async_engine = engine
    db_mod.AsyncSessionLocal = session_factory

    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)

    async with session_factory() as session:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    db_mod._async_engine = old_engine
    db_mod.AsyncSessionLocal = old_session


# Helpers for tests that need to inject data (bypass non-existent /register, /ingest schema)
async def create_test_array(db: AsyncSession, array_id: str, host: str = "192.168.1.1", name: str = None):
    """Insert a test array directly into the database."""
    from backend.models.array import ArrayModel
    arr = ArrayModel(
        array_id=array_id,
        name=name or array_id,
        host=host,
        port=22,
        username="root",
        key_path="",
        folder="",
    )
    db.add(arr)
    await db.flush()
    return arr


async def inject_test_alert(db: AsyncSession, array_id: str, observer_name: str, level: str, message: str, details: dict = None, timestamp=None):
    """Insert a test alert directly into the database."""
    import json
    from datetime import datetime, timedelta
    from backend.models.alert import AlertModel
    ts = timestamp if timestamp is not None else datetime.now()
    alert = AlertModel(
        array_id=array_id,
        observer_name=observer_name,
        level=level,
        message=message,
        details=json.dumps(details or {}),
        timestamp=ts,
    )
    db.add(alert)
    await db.flush()
    return alert
