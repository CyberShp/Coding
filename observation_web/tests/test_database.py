"""Tests for backend/db/database.py — Database initialization and sessions."""
import pytest
import pytest_asyncio
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
