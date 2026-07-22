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
    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal, user_account  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# Cached PBKDF2 hash so we only pay the 100k-iteration cost once per test run
_TEST_USER_PASSWORD = "pytest-password"
_test_password_hash_cache = {}


async def seed_test_user(session_factory, nickname="pytest_user", is_admin=True):
    """Insert a user account directly and return (user, token).

    Bypasses the /auth/register endpoint so tests don't pay the PBKDF2 cost
    for every fixture instantiation (hash is computed once and reused).
    """
    from backend.models.user_account import UserAccountModel, hash_password
    from backend.api.user_auth import _create_user_token

    if "hash" not in _test_password_hash_cache:
        _test_password_hash_cache["hash"] = hash_password(_TEST_USER_PASSWORD)

    async with session_factory() as session:
        user = UserAccountModel(
            nickname=nickname,
            password_hash=_test_password_hash_cache["hash"],
            is_admin=is_admin,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user, _create_user_token(user).token


import contextlib


@contextlib.asynccontextmanager
async def _app_client_ctx(with_auth: bool = True):
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
    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal, user_account  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        if with_auth:
            # Seed a logged-in user so legacy tests exercising write endpoints
            # keep passing under the require_user gate.
            _, token = await seed_test_user(session_factory)
            client.headers["Authorization"] = f"Bearer {token}"
        yield client

    # Teardown
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    db_mod._async_engine = old_engine
    db_mod.AsyncSessionLocal = old_session


@pytest_asyncio.fixture
async def app_client():
    """API test client carrying a default logged-in test user token."""
    async with _app_client_ctx(with_auth=True) as client:
        yield client


@pytest_asyncio.fixture
async def anonymous_client():
    """API test client without any auth token (for 401 gate tests)."""
    async with _app_client_ctx(with_auth=False) as client:
        yield client


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

    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference, array_lock, alert_rule, audit_log, issue, monitor_template, observer_config, ai_interpretation, card_inventory, alerts_v2, expected_window, observer_snapshot, agent_heartbeat, card_presence, viewer_profile, system_config, enrollment, baseline, causal, user_account  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)

    _, token = await seed_test_user(session_factory)

    async with session_factory() as session:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.headers["Authorization"] = f"Bearer {token}"
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
